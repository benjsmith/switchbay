"""Deterministic capture and micro-edit slash commands.

Split out of switchbay.daemon so this concept has its own module.
The daemon re-exports every name; tests that monkeypatch
switchbay.daemon still apply, because patched helpers are read
back through _daemon_ns at call time.

Run: python -m switchbay serve --workspace PATH
"""
from __future__ import annotations

from pathlib import Path
import asyncio
import json
import logging
from aiohttp import web
from switchbay import capture
from switchbay import conversations
from switchbay import micro_edits
from switchbay import modestore
from switchbay import projects
from switchbay import protocol

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

# ── Capture verbs: /note /todo /decision /project (D7 + D8) ────────


def _known_projects(workspace: Path) -> dict[str, str]:
    """lower-name → canonical-name map of live registry projects.
    Sync (registry read) — call via to_thread."""
    reg = projects.load_registry(workspace)
    return {
        name.lower(): name
        for name, entry in (reg.get("projects") or {}).items()
        if not (entry or {}).get("deleted_at")
    }

async def _focused_thread_id(app: web.Application) -> str | None:
    tid = app.get("thread_id")
    if tid:
        return tid
    return await asyncio.to_thread(
        conversations.active_thread_id, app["workspace"],
    )

async def _capture_project_for(
    app: web.Application, text: str,
) -> tuple[str, str | None]:
    """Resolve which project a capture belongs to (D8): an inline
    `#<name>` token naming a REGISTERED project wins (and is stripped
    from the text); otherwise the focused thread's binding; otherwise
    None (workspace-level capture)."""
    workspace: Path = app["workspace"]
    known = await asyncio.to_thread(_known_projects, workspace)
    text, inline = capture.strip_project_token(text, list(known.values()))
    if inline:
        return text, inline
    tid = await _focused_thread_id(app)
    if tid:
        proj = await asyncio.to_thread(
            conversations.thread_project, workspace, tid,
        )
        if proj:
            return text, proj
    return text, None

async def _handle_capture_slash(
    app: web.Application, ws: web.WebSocketResponse, verb: str, args: str,
) -> None:
    """`/note` `/todo` `/decision` — deterministic instant capture
    (D7). NO LLM turn in this path — a meeting can't wait 10 s per
    item. Writes CE-native staging shapes (capture.py); the curator's
    existing sweeps classify/wikilink/dedupe asynchronously. No viewer
    rebuild either — staging pages join the graph when curation files
    them."""
    if not args.strip():
        await ws.send_json(protocol.notice(
            f"usage: /{verb} <text>"
            + ("  (topic: <name> … routes to a topic file)" if verb == "note" else ""),
            kind="slash",
        ))
        return
    workspace: Path = app["workspace"]
    text, project = await _capture_project_for(app, args)
    try:
        result = await asyncio.to_thread(
            _daemon_ns._CAPTURE_WRITERS[verb], workspace, text, project,
        )
    except Exception as e:  # noqa: BLE001
        log.exception("capture failed: /%s", verb)
        await ws.send_json(protocol.notice(f"/{verb} failed: {e}", kind="slash"))
        return
    where = result["path"]
    suffix = f" · [[{project}]]" if project else ""
    _daemon_ns._log_event(
        app, "capture", f"{verb} → {where}{suffix}",
        source="rail", actor="user",
        payload={"verb": verb, **result},
    )
    await ws.send_json(protocol.notice(
        f"✓ {verb} captured → {where}{suffix}", kind="slash",
    ))
    await _daemon_ns._broadcast(app, protocol.files_changed())

async def _handle_micro_edits_slash(
    app: web.Application, ws: web.WebSocketResponse, args: str,
) -> None:
    """`/micro-edits` — show or set which ladder rung micro-edits use."""
    workspace: Path = app["workspace"]
    tid = await _focused_thread_id(app)
    action, payload = micro_edits.parse_slash_args(args)
    if action == "reset_feedback":
        await asyncio.to_thread(micro_edits.reset_feedback, workspace)
        await ws.send_json(protocol.notice(
            "Micro-edit feedback card will show again after the next micro-edit.",
            kind="slash",
        ))
        return
    if action == "clear":
        # Clear the micro-edit model at global + workspace scope so
        # micro-edits follow the picker again.
        await asyncio.to_thread(micro_edits.clear_micro_models, "global", workspace)
        await asyncio.to_thread(micro_edits.clear_micro_models, "workspace", workspace)
        await ws.send_json(protocol.notice(
            "✓ micro-edits now follow the picker (no separate fast model).\n"
            + micro_edits.status_text(workspace, tid),
            kind="slash",
        ))
        return
    if action == "set" and isinstance(payload, dict):
        scope = str(payload.get("scope") or "workspace")
        rung = str(payload.get("rung") or "trivial")
        if scope not in ("thread", "workspace", "global") or rung not in micro_edits.RUNGS:
            await ws.send_json(protocol.notice(
                "usage: /micro-edits [trivial|normal|hard] "
                "· /micro-edits global|workspace|thread <rung> "
                "· /micro-edits reset-feedback",
                kind="slash",
            ))
            return
        if scope == "thread" and not tid:
            await ws.send_json(protocol.notice(
                "no focused thread — send a message first, or use workspace/global scope.",
                kind="slash",
            ))
            return
        try:
            await asyncio.to_thread(
                micro_edits.set_rung, scope, workspace, tid, rung,  # type: ignore[arg-type]
            )
        except ValueError as e:
            await ws.send_json(protocol.notice(str(e), kind="slash"))
            return
        await ws.send_json(protocol.notice(
            f"✓ micro-edits rung = {rung} ({scope})\n"
            + micro_edits.status_text(workspace, tid),
            kind="slash",
        ))
        return
    await ws.send_json(protocol.notice(
        micro_edits.status_text(workspace, tid), kind="slash",
    ))

async def handle_micro_edits_feedback(request: web.Request) -> web.Response:
    """POST /api/micro-edits/feedback — Keep / Increase & redo / dismiss."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    fid = str(body.get("id") or "").strip()
    action = str(body.get("action") or "").strip().lower()
    scope = str(body.get("scope") or "workspace").strip().lower()
    if scope not in ("thread", "workspace", "global"):
        return web.json_response({"error": "invalid scope"}, status=400)
    if action not in ("keep", "increase", "dismiss"):
        return web.json_response({"error": "invalid action"}, status=400)
    pending = micro_edits.get_pending_feedback(fid)
    if not pending:
        return web.json_response({"error": "unknown or expired feedback id"}, status=404)
    workspace = Path(str(pending["workspace"]))
    tid = str(pending.get("thread_id") or "")
    rung_used = str(pending.get("rung_used") or "trivial")
    if rung_used not in micro_edits.RUNGS:
        rung_used = "trivial"

    if action == "dismiss":
        await asyncio.to_thread(
            micro_edits.mark_feedback_shown, scope, workspace, tid or None,  # type: ignore[arg-type]
        )
        micro_edits.pop_pending_feedback(fid)
        return web.json_response({"ok": True, "action": "dismiss"})

    if action == "keep":
        await asyncio.to_thread(
            micro_edits.set_rung, scope, workspace, tid or None,  # type: ignore[arg-type]
            rung_used, mark_feedback=True,
        )
        micro_edits.pop_pending_feedback(fid)
        return web.json_response({
            "ok": True, "action": "keep", "rung": rung_used, "scope": scope,
        })

    # increase & redo — bump to the next micro-edit tier and re-run.
    new_rung = micro_edits.next_rung(rung_used)  # type: ignore[arg-type]
    await asyncio.to_thread(
        micro_edits.set_rung, scope, workspace, tid or None,  # type: ignore[arg-type]
        new_rung, mark_feedback=True,
    )
    original = str(pending.get("original_text") or "").strip()
    micro_edits.pop_pending_feedback(fid)
    redo_run: str | None = None
    if original:
        # Resolve the micro-edit's OWN model map for the new tier
        # (decoupled from the CE ladder). An unset tier → run on the
        # picker/default, which is the natural "stronger" target when
        # escalating away from a fast model.
        pid, model = micro_edits.micro_model_for_rung(workspace, new_rung)
        where = f"{pid} · {model}" if pid else "the picker"
        t = asyncio.create_task(_daemon_ns._dispatch_chat(
            request.app, None, original,
            workspace_override=workspace,
            thread_id_override=tid or None,
            provider_override=pid,          # None → picker/default
            model_override=model,
            input_excerpt=f"[micro-edit redo · {new_rung}] {original[:80]}",
        ))
        t.add_done_callback(
            _daemon_ns._make_dispatch_error_surface(request.app, None))
        await _daemon_ns._broadcast(request.app, protocol.notice(
            f"micro-edit · increased to {new_rung} ({where}) · redoing…",
            kind="chat",
        ))
        redo_run = "started"
    return web.json_response({
        "ok": True, "action": "increase", "rung": new_rung, "scope": scope,
        "redo": redo_run,
    })

async def handle_micro_edits_status(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    tid = request.app.get("thread_id")
    rung = micro_edits.effective_rung(
        workspace, tid if isinstance(tid, str) else None)
    return web.json_response({
        "rung": rung,
        "feedback_shown": micro_edits.feedback_shown(
            workspace, tid if isinstance(tid, str) else None),
        "ladder": modestore.effective_ladder(workspace),
        "text": micro_edits.status_text(
            workspace, tid if isinstance(tid, str) else None),
    })

async def _handle_project_slash(
    app: web.Application, ws: web.WebSocketResponse, args: str,
) -> None:
    """`/project <name>` — bind the focused thread to a project (D8);
    captures in the thread inherit it. `/project` shows the binding;
    `/project none` unbinds. Names must exist in CE's project registry
    (the ThreadBar picker offers the same set)."""
    workspace: Path = app["workspace"]
    tid = await _focused_thread_id(app)
    if not tid:
        await ws.send_json(protocol.notice(
            "no focused thread to bind — send a message first.", kind="slash",
        ))
        return
    known = await asyncio.to_thread(_known_projects, workspace)
    arg = args.strip()
    if not arg:
        current = await asyncio.to_thread(
            conversations.thread_project, workspace, tid,
        )
        names = ", ".join(sorted(known.values())) or "(none registered)"
        await ws.send_json(protocol.notice(
            f"thread project: {current or '(none)'}\n"
            f"registered projects: {names}\n"
            "usage: /project <name> · /project none",
            kind="slash",
        ))
        return
    if arg.lower() in ("none", "clear", "off"):
        await asyncio.to_thread(conversations.set_project, workspace, tid, None)
        _daemon_ns._log_event(
            app, "slash", "/project none — thread unbound",
            source="rail", actor="user",
            payload={"thread_id": tid, "project": None},
        )
        await _daemon_ns._broadcast(app, protocol.thread_project_changed(tid, None))
        await ws.send_json(protocol.notice(
            "✓ thread unbound — captures land at workspace level",
            kind="slash",
        ))
        return
    name = known.get(arg.lower())
    if name is None:
        names = ", ".join(sorted(known.values())) or (
            "(none — create one via CE's projects.py, or skip binding: "
            "single-topic workspaces capture at workspace level)"
        )
        await ws.send_json(protocol.notice(
            f"unknown project {arg!r}. Registered: {names}", kind="slash",
        ))
        return
    ok = await asyncio.to_thread(
        conversations.set_project, workspace, tid, name,
    )
    if not ok:
        await ws.send_json(protocol.notice(
            "could not bind — thread not found.", kind="slash",
        ))
        return
    _daemon_ns._log_event(
        app, "slash", f"/project {name} — thread bound",
        source="rail", actor="user",
        payload={"thread_id": tid, "project": name},
    )
    await _daemon_ns._broadcast(app, protocol.thread_project_changed(tid, name))
    await ws.send_json(protocol.notice(
        f"✓ thread bound to [[{name}]] — /note /todo /decision here "
        f"inherit it (inline #<project> overrides per item)",
        kind="slash",
    ))
