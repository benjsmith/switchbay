"""Skill CRUD, ladder, micro-model, and MCP server routes.

Split out of switchbay.daemon so this concept has its own module.
The daemon re-exports every name; tests that monkeypatch
switchbay.daemon still apply, because patched helpers are read
back through _daemon_ns at call time.

Run: python -m switchbay serve --workspace PATH
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import asyncio
import json
import logging
from aiohttp import web
from switchbay import app_settings
from switchbay import conversations
from switchbay import llmgateway
from switchbay import localllm
from switchbay import mcpstore
from switchbay import micro_edits
from switchbay import modestore
from switchbay import protocol
from switchbay import selection
from switchbay import share
from switchbay import skillkit
from switchbay.agents import rail_default

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

async def handle_skills_list(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    skills = []
    for s in skillkit.list_skills(workspace):
        row = skillkit.to_summary(s)
        row["writable"] = skillkit.is_writable_skill(workspace, s)
        # A cheap health badge so a broken trigger is visible before the
        # user wonders why the skill never fired.
        row["health"] = skillkit.worst_level(skillkit.diagnose(workspace, s))
        skills.append(row)
    return web.json_response({"skills": skills})

async def handle_skill_explain(request: web.Request) -> web.Response:
    """"Why won't my skill fire?" — deterministic diagnostics always,
    plus (when the caller supplies an example `request`) one cheap model
    call: would an agent load this skill for that request, and if the
    trigger is weak, a stronger 'Use when …' description.

    Body: {name, request?}. The model half runs on the micro-edit /
    trivial rung so the explainer stays cheap."""
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}
    name = str(body.get("name") or "").strip()
    example = str(body.get("request") or "").strip()
    sk = skillkit.get_skill(workspace, name)
    if sk is None:
        return web.json_response({"error": "not found"}, status=404)

    diags = skillkit.diagnose(workspace, sk)
    result: dict[str, Any] = {
        "skill": skillkit.to_summary(sk),
        "diagnostics": diags,
        "health": skillkit.worst_level(diags),
        "match": None,
        "suggestion": None,
    }
    if not example:
        return web.json_response(result)

    # Model half: a single cheap call — this is a quick "would it match"
    # judgment, not curation, so prefer a fast worker model. Order:
    # the ladder's normal (worker) rung → the micro-edit fast model →
    # the picker/default. Keeps the "Test" button snappy instead of
    # spinning up the picker's flagship model.
    pid, model = modestore.resolve_for_difficulty(workspace, "normal")
    if not pid:
        rung = micro_edits.effective_rung(workspace, None)
        pid, model = micro_edits.micro_model_for_rung(workspace, rung)
    if not pid:
        pid = _daemon_ns._resolve_default_provider()
        model = _daemon_ns._effective_model(pid)
    try:
        provider = llmgateway.get(pid)
    except llmgateway.ProviderError:
        provider = None
    if provider is None or not provider.has_key():
        result["match"] = {"error": "no model available to judge the match"}
        return web.json_response(result)

    prompt = (
        "You decide whether an AI agent would load a SKILL for a user "
        "request. A skill loads when the request matches its trigger.\n\n"
        f"SKILL name: {sk.name}\n"
        f"SKILL trigger/description: {sk.description or '(none)'}\n\n"
        f"USER REQUEST: {example}\n\n"
        "Reply with STRICT JSON only: "
        '{\"would_fire\": true|false, \"reason\": \"one sentence\", '
        '\"better_description\": \"a stronger description starting with '
        "'Use when …' — ONLY if the current one is weak, else empty\"}"
    )
    try:
        out = await _daemon_ns._oneshot_json(provider, model, prompt, workspace)
    except Exception:  # noqa: BLE001
        log.exception("skill explain model call failed")
        out = None
    if isinstance(out, dict):
        result["match"] = {
            "would_fire": bool(out.get("would_fire")),
            "reason": str(out.get("reason") or ""),
            "model": f"{pid} · {model}",
        }
        better = str(out.get("better_description") or "").strip()
        if better and better != (sk.description or "").strip():
            result["suggestion"] = {"description": better}
    else:
        result["match"] = {"error": "model reply was not parseable JSON"}
    return web.json_response(result)

async def handle_skill_get(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    name = request.query.get("name", "").strip()
    if not name:
        return web.json_response({"error": "name required"}, status=400)
    sk = skillkit.get_skill(workspace, name)
    if sk is None:
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response({"skill": skillkit.to_full(sk)})

async def handle_skill_create(request: web.Request) -> web.Response:
    """Author a new skill. Body: {scope, name, description, body}.
    scope ∈ {workspace, user}. Local-first: nothing fetched from the web."""
    workspace: Path = request.app["workspace"]
    try:
        b = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    try:
        sk = await asyncio.to_thread(
            skillkit.create_skill, workspace,
            str(b.get("scope") or "workspace"),
            str(b.get("name") or ""), str(b.get("description") or ""),
            str(b.get("body") or ""),
        )
    except skillkit.SkillError as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({"skill": skillkit.to_full(sk)})

async def handle_skill_update(request: web.Request) -> web.Response:
    """Rewrite a writable skill. Body: {name, description, body}."""
    workspace: Path = request.app["workspace"]
    try:
        b = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    try:
        sk = await asyncio.to_thread(
            skillkit.update_skill, workspace,
            str(b.get("name") or ""), str(b.get("description") or ""),
            str(b.get("body") or ""),
        )
    except skillkit.SkillError as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({"skill": skillkit.to_full(sk)})

async def handle_skill_delete(request: web.Request) -> web.Response:
    """Delete a writable skill. Body: {name}."""
    workspace: Path = request.app["workspace"]
    try:
        b = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    try:
        await asyncio.to_thread(skillkit.delete_skill, workspace, str(b.get("name") or ""))
    except skillkit.SkillError as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({"ok": True})

async def handle_skill_promote(request: web.Request) -> web.Response:
    """Promote a workspace-private skill to the personal (user-global)
    scope so it's available in every workspace. Body: {name}."""
    workspace: Path = request.app["workspace"]
    try:
        b = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    try:
        sk = await asyncio.to_thread(skillkit.promote_skill, workspace, str(b.get("name") or ""))
    except skillkit.SkillError as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({"skill": skillkit.to_full(sk)})

async def handle_skill_publish(request: web.Request) -> web.Response:
    """Publish a user-owned skill to GitHub (its own repo, `claude-skill`
    topic) so others can `npx skills add <owner>/<name>`. Body:
    {name, private?}. Only writable (user/workspace) skills; scans for
    obvious secrets first."""
    workspace: Path = request.app["workspace"]
    try:
        b = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    name = str(b.get("name") or "").strip()
    private = bool(b.get("private", True))
    sk = skillkit.find_writable(workspace, name)
    if sk is None:
        return web.json_response(
            {"error": "only your own (workspace/personal) skills can be published"},
            status=400)
    skill_dir = Path(sk.path).parent
    # Secret scan the skill dir — publishing is outward-facing.
    hits = await asyncio.to_thread(_scan_dir_secrets, skill_dir)
    if hits:
        return web.json_response(
            {"error": f"possible secret in {hits[0]} — remove it before publishing"},
            status=400)
    try:
        url = await share.publish_skill(skill_dir, name=sk.name, private=private)
    except share.ShareError as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({"ok": True, "url": url})

def _scan_dir_secrets(d: Path) -> list[str]:
    """Cheap secret scan over a skill dir — reuses share's per-file
    scanner. Returns a list of "rel: reason" hits (empty = clean)."""
    hits: list[dict[str, Any]] = []
    for fp in d.rglob("*"):
        if fp.is_file() and fp.stat().st_size < 512 * 1024:
            try:
                share._scan_secrets(fp, str(fp.relative_to(d)), fp.stat().st_size, hits)
            except Exception:  # noqa: BLE001
                pass
    return [f"{h.get('path')}: {h.get('kind', 'secret')}" for h in hits]

async def handle_skill_open_in_editor(request: web.Request) -> web.Response:
    """Open a WORKSPACE-scoped skill's SKILL.md in the Editor tab. User-
    global (personal) skills live outside the workspace, so the editor —
    which is workspace-relative — can't open them; those use the inline
    editor. Body: {name}."""
    workspace: Path = request.app["workspace"]
    try:
        b = await request.json()
    except json.JSONDecodeError:
        b = {}
    sk = skillkit.find_writable(workspace, str(b.get("name") or ""))
    if sk is None:
        return web.json_response({"error": "not an editable skill"}, status=400)
    md = Path(sk.path).resolve()
    try:
        rel = md.relative_to(workspace.resolve())
    except ValueError:
        return web.json_response(
            {"error": "this skill lives outside the workspace — use the inline editor"},
            status=400)
    sel = {"kind": "file", "path": str(rel), "title": f"{sk.name}/SKILL.md"}
    await asyncio.to_thread(selection.save, workspace, sel)
    await _daemon_ns._broadcast(request.app, protocol.selection_state(sel))
    await _daemon_ns._broadcast(request.app, protocol.nav("markdown", {"selection": sel}, "Editor"))
    return web.json_response({"ok": True, "path": str(rel)})

async def handle_skill_from_thread(request: web.Request) -> web.Response:
    """"Save this thread as a skill" — draft a SKILL.md from a thread's
    transcript via a background agent.

    Body: {thread_id?, name?}. Gathers the thread's user/assistant turns,
    then dispatches a headless agent instructed to distill the workflow
    and author it with the `save_skill` tool. Returns immediately; the
    Skills panel refreshes when the run finishes."""
    workspace: Path = request.app["workspace"]
    try:
        b = await request.json()
    except json.JSONDecodeError:
        b = {}
    tid = str(b.get("thread_id") or "") or await _daemon_ns._focused_thread_id(request.app)
    if not tid:
        return web.json_response({"error": "no thread to save"}, status=400)
    turns = await asyncio.to_thread(conversations.working_set, workspace, tid, limit=40)
    if not turns:
        return web.json_response({"error": "thread has no conversation yet"}, status=400)
    name_hint = str(b.get("name") or "").strip()
    transcript = "\n\n".join(
        f"{t['role'].upper()}: {t['content']}" for t in turns if t.get("content"))
    # Cap the transcript so a very long thread doesn't blow the prompt.
    transcript = transcript[:12000]
    prompt = (
        "Distill the following conversation into a REUSABLE skill so the "
        "user can invoke this workflow again later. Write a concise "
        "SKILL.md: a short kebab-case name, a one-paragraph description "
        "that STARTS with a 'Use when …' trigger clause (so it fires "
        "automatically), and a body of clear numbered steps / rules the "
        "agent should follow. Then call the `save_skill` tool with "
        "scope='workspace' to save it privately to this workspace. Do NOT "
        "include anything workspace-specific or secret.\n"
        + (f"\nSuggested name: {name_hint}\n" if name_hint else "")
        + "\n--- CONVERSATION ---\n" + transcript
    )
    task = asyncio.create_task(_daemon_ns._dispatch_chat(
        request.app, None, prompt,
        input_excerpt=f"[save thread as skill] {name_hint or tid}",
    ))
    task.add_done_callback(_daemon_ns._make_dispatch_error_surface(request.app, None))
    return web.json_response({"ok": True, "drafting": True})

async def handle_ladder_get(request: web.Request) -> web.Response:
    """Ladder state for the Settings editor: the GLOBAL defaults, this
    workspace's per-rung overrides, and the merged effective ladder.
    `ladder` stays = effective for older clients."""
    workspace: Path = request.app["workspace"]
    pid = _daemon_ns._resolve_default_provider()
    try:
        picker_label = llmgateway.get(pid).LABEL
    except llmgateway.ProviderError:
        picker_label = pid
    return web.json_response({
        "global": modestore.global_ladder(),
        "workspace": modestore.get_ladder(workspace),
        "effective": modestore.effective_ladder(workspace),
        "ladder": modestore.effective_ladder(workspace),
        "workspace_name": workspace.name,
        "difficulties": list(modestore.DIFFICULTIES),
        # The picker selection the `hard` (orchestrator) rung follows
        # when unset — lets the Settings editor grey it out honestly.
        "picker": {
            "provider": pid,
            "provider_label": picker_label,
            "model": _daemon_ns._effective_model(pid),
        },
    })

async def handle_micro_model_get(request: web.Request) -> web.Response:
    """Micro-edit fast-model state for the Settings editor. The base
    tier is `trivial` (the default effective rung); we surface it at
    both scopes so the editor can show "follows picker" when unset."""
    workspace: Path = request.app["workspace"]
    g_pid, g_model, g_effort = None, None, None
    grow = (app_settings.load().get("micro_edits") or {})
    if isinstance(grow, dict):
        m = grow.get("models")
        if isinstance(m, dict) and isinstance(m.get("trivial"), dict):
            g_pid = m["trivial"].get("provider")
            g_model = m["trivial"].get("model")
            g_effort = m["trivial"].get("effort")
    rung = micro_edits.effective_rung(workspace, None)
    e_pid, e_model = micro_edits.micro_model_for_rung(workspace, rung)
    return web.json_response({
        "global": {"provider": g_pid, "model": g_model, "effort": g_effort},
        "effective": {"provider": e_pid, "model": e_model, "rung": rung},
    })

def _resolve_ce_override(
    provider: str, model: str,
) -> tuple[str | None, str | None, str | None]:
    """Validate a per-run CE-action orchestrator override.

    Returns `(provider_id, model, error)`. A non-None `error` is a 400
    reason. An empty `provider` yields `(None, None, None)` — the caller
    then falls back to the normal `_ce_action_provider` routing. A named
    provider MUST be known, keyed, and execute-capable: curation needs a
    shell, so a propose-only provider is rejected rather than silently
    degraded (the whole point of the capability gate)."""
    if not provider:
        return None, None, None
    if provider not in llmgateway.PROVIDERS:
        return None, None, f"unknown provider: {provider}"
    prov = llmgateway.get(provider)
    if not prov.has_key():
        return None, None, f"{prov.LABEL} has no key/binary configured"
    if not llmgateway.can_curate(provider):
        return None, None, (
            f"{prov.LABEL} cannot run CE scripts (no tools, no shell). "
            "Pick Copilot / a local model (ce_run tools) or a CLI agent."
        )
    return provider, (model or _daemon_ns._effective_model(provider)), None

async def handle_mcp_servers_list(request: web.Request) -> web.Response:
    return web.json_response({"servers": mcpstore.load()})

async def handle_mcp_servers_add(request: web.Request) -> web.Response:
    """Verify (a real MCP `initialize` handshake) then persist a new
    user MCP server. Rollback (400) if it doesn't launch/respond."""
    blocked = _daemon_ns._policy_block("user_mcp_servers")
    if blocked:
        return blocked
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    try:
        ws = request.app.get("workspace")
        if ws and not body.get("allowed_workspaces"):
            body["allowed_workspaces"] = [str(Path(ws).resolve())]
        s = await mcpstore.add(body)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({"server": s, "servers": mcpstore.load()})

async def handle_mcp_servers_delete(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    ok = await asyncio.to_thread(mcpstore.remove, str(body.get("name") or ""))
    return web.json_response({"ok": ok, "servers": mcpstore.load()})

async def handle_mcp_servers_toggle(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    ok = await asyncio.to_thread(
        mcpstore.set_enabled, str(body.get("name") or ""), bool(body.get("enabled")))
    return web.json_response({"ok": ok, "servers": mcpstore.load()})

async def handle_ce_action_run(request: web.Request) -> web.Response:
    """Kick off a CE action (curate / ingest / add-source / viewer) in a
    BACKGROUND thread, optionally on an explicit orchestrator model.

    This is the per-run override the picker exposes: "run a curate now on
    grok-4.5 in the background, but keep the rail on my picker model". It
    runs headless (`ws=None` → its own new thread) so the focused rail
    thread is untouched; the Agent Dashboard tracks it and the rail
    surfaces its run events.

    Body: `{action, args?, provider?, model?}`. When `provider` is given
    it MUST be execute-capable (curation needs a shell) — a propose-only
    provider can't orchestrate a curate, so we reject rather than
    silently degrade. When omitted, routing falls to the same default as
    the `/curate` slash (`_ce_action_provider` → hard rung → picker)."""
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)

    action = str(body.get("action") or "curate").strip().lower()
    args = str(body.get("args") or "").strip()
    if action in ("curate", "curator"):
        cverb = _daemon_ns._desk_slash_verb(args)
        cspec = _daemon_ns._desk_spec("curate") or {
            "desk_id": "curate", "cancel": ("curate",), "slash": "curate",
        }
        if cverb == "quiet":
            n = _daemon_ns._quiet_desk(request.app, cspec, request.app["workspace"])
            return web.json_response({"ok": True, "cancelled": n, "action": "stop"})
        if cverb == "dismiss":
            n = _daemon_ns._dismiss_desk(request.app, cspec, request.app["workspace"])
            return web.json_response({"ok": True, "cancelled": n, "action": "dismiss"})
    provider = str(body.get("provider") or "").strip()
    model = str(body.get("model") or "").strip()

    # Explicit override must be a known, keyed, execute-capable provider.
    pid, cp_model, err = _resolve_ce_override(provider, model)
    if err:
        return web.json_response({"error": err}, status=400)
    if not provider:
        pid, cp_model = _daemon_ns._ce_action_provider(workspace)

    effective_pid = pid or _daemon_ns._resolve_default_provider()
    is_local = _daemon_ns._provider_is_local(effective_pid)
    is_curate = action in ("curate", "curator")
    label = pid or _daemon_ns._resolve_default_provider()
    try:
        plabel = llmgateway.get(label).LABEL
    except llmgateway.ProviderError:
        plabel = label
    run_model = cp_model or _daemon_ns._effective_model(label)
    if is_curate:
        raw_pref = body.get("preference")
        try:
            pref = float(raw_pref) if raw_pref is not None else None
        except (TypeError, ValueError):
            pref = None
        cspec = _daemon_ns._desk_spec("curate") or {
            "desk_id": "curate", "cancel": ("curate",), "slash": "curate",
            "command": "curate", "task_kind": "curation", "staff": _daemon_ns._CURATE_STAFF,
        }
        _daemon_ns._launch_desk(
            request.app, cspec, prompt=args, workspace=workspace,
            preference=pref,
            provider_override=pid, model_override=cp_model,
            lock_provider=bool(provider),
        )
        return web.json_response({
            "ok": True, "action": action,
            "provider": label, "provider_label": plabel, "model": run_model,
            "background": True,
            "orchestrated": not _daemon_ns._curate_constrained(local=is_local, text=args),
        })

    _lrung = None
    if is_local:
        _lcfg = await asyncio.to_thread(localllm.load_config)
        _lrung = rail_default.resolve_local_rung(
            localllm.ram_gb(),
            model_hint=rail_default.model_hint_from_cfg(_lcfg),
        )
    ce_prompt = _daemon_ns._ce_action_prompt(
        action, args, local=is_local, local_rung=_lrung,
    )
    if ce_prompt is None:
        return web.json_response(
            {"error": f"not a CE action: {action}"}, status=400)
    excerpt = f"[{action} · background · {plabel} · {run_model}] {args}".strip()
    task = asyncio.create_task(_daemon_ns._dispatch_chat(
        request.app, None, ce_prompt,
        provider_override=pid, model_override=cp_model,
        input_excerpt=excerpt,
        command=action if is_local else None,
    ))
    task.add_done_callback(_daemon_ns._make_dispatch_error_surface(request.app, None))
    return web.json_response({
        "ok": True, "action": action,
        "provider": label, "provider_label": plabel, "model": run_model,
        "background": True, "orchestrated": False,
    })

async def handle_micro_model_post(request: web.Request) -> web.Response:
    """Set (or clear) the micro-edit fast model at the `trivial` tier.
    Body: {provider, model} — empty/absent provider clears it (→ follow
    the picker)."""
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    provider = str(body.get("provider") or "").strip()
    model = str(body.get("model") or "").strip()
    effort = str(body.get("effort") or "").strip()
    if provider and provider not in llmgateway.PROVIDERS:
        return web.json_response({"error": f"unknown provider: {provider}"}, status=400)
    await asyncio.to_thread(
        micro_edits.set_micro_model, "global", workspace, "trivial",
        provider or None, model or None, effort or None,
    )
    return await handle_micro_model_get(request)

async def handle_ladder_post(request: web.Request) -> web.Response:
    """Upsert the model ladder. Body shape:
        {"ladder": {"trivial": {provider, model}, "normal": …, "hard": …}}
    Sanitisation drops any rung that isn't `{provider: str, model: str}`-
    shaped; supplying an empty `ladder` clears the field."""
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    raw = body.get("ladder")
    if not isinstance(raw, dict):
        return web.json_response({"error": "ladder must be an object"}, status=400)
    scope = str(body.get("scope") or "workspace")
    if scope == "global":
        saved = await asyncio.to_thread(modestore.set_global_ladder, raw)
    else:
        saved = await asyncio.to_thread(modestore.set_ladder, workspace, raw)
    return web.json_response({
        "scope": scope,
        "saved": saved,
        "global": modestore.global_ladder(),
        "workspace": modestore.get_ladder(workspace),
        "effective": modestore.effective_ladder(workspace),
    })
