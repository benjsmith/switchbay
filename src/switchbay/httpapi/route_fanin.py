"""Saved-route fan-out matching.

Split out of switchbay.daemon so this concept has its own module.
The daemon re-exports every name; tests that monkeypatch
switchbay.daemon still apply, because patched helpers are read
back through _daemon_ns at call time.

Run: python -m switchbay serve --workspace PATH
"""
from __future__ import annotations

from pathlib import Path
import asyncio
import logging
from aiohttp import web
from switchbay import llmgateway
from switchbay import modestore
from switchbay import protocol
from switchbay import skillkit

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

async def _route_pick_n(app: web.Application, text: str) -> int:
    """Let a cheap model decide how many sub-tasks a `/route` task should
    split into (2–6). Falls back to 3 on any failure — a sensible middle
    for an unknown task. Uses the ladder's trivial/normal worker rung so
    the pick is cheap and stays off the picker model."""
    workspace: Path = app["workspace"]
    pid, model = modestore.resolve_for_difficulty(workspace, "normal")
    if not pid:
        pid = _daemon_ns._resolve_default_provider()
        model = _daemon_ns._effective_model(pid)
    try:
        provider = llmgateway.get(pid)
        if not provider.has_key():
            return 3
        out = await _daemon_ns._oneshot_json(
            provider, model,
            "How many independent parallel sub-tasks should this work be "
            "split into? Consider its breadth. Reply STRICT JSON "
            '{\"n\": <integer 2-6>}.\n\nTASK:\n' + text[:2000],
            workspace, max_tokens=64)
    except Exception:  # noqa: BLE001
        return 3
    try:
        n = int((out or {}).get("n"))
    except (TypeError, ValueError):
        return 3
    return max(2, min(6, n))

def _route_worker_provider(workspace: Path):
    """(provider, model) for the cheap route classifier/N-pick — the
    ladder's normal (worker) rung, else the picker/default."""
    pid, model = modestore.resolve_for_difficulty(workspace, "normal")
    if not pid:
        pid = _daemon_ns._resolve_default_provider()
        model = _daemon_ns._effective_model(pid)
    try:
        prov = llmgateway.get(pid)
    except llmgateway.ProviderError:
        return None, None
    if not prov.has_key():
        return None, None
    return prov, model

async def _route_match(app: web.Application, desc: str):
    """Match a /route description to ONE of the user's OWN skills
    (workspace + personal), or None. Built-ins are excluded by decision
    — they fire through normal chat, not /route. Returns
    `(skill, is_route, tasks)` on a confident match."""
    workspace: Path = app["workspace"]
    own = [s for s in skillkit.list_skills(workspace)
           if s.source in ("workspace", "user")]
    if not own:
        return None
    provider, model = _route_worker_provider(workspace)
    if provider is None:
        return None
    catalog = "\n".join(
        f"- {s.name}: {s.when_to_use or s.description}" for s in own)
    prompt = (
        "Match the user's request to ONE of their saved skills, or none. "
        "Only pick a skill if it CLEARLY fits.\n\n"
        f"SKILLS:\n{catalog}\n\nREQUEST: {desc}\n\n"
        'Reply STRICT JSON {\"skill\": \"<name or empty>\", '
        '\"confidence\": <0.0-1.0>}.')
    try:
        out = await _daemon_ns._oneshot_json(provider, model, prompt, workspace, max_tokens=128)
    except Exception:  # noqa: BLE001
        log.exception("route match failed")
        return None
    name = str((out or {}).get("skill") or "").strip()
    try:
        conf = float((out or {}).get("confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    if not name or conf < 0.6:
        return None
    sk = skillkit.get_skill(workspace, name)
    if sk is None or sk.source not in ("workspace", "user"):
        return None
    return sk, skillkit.is_route_skill(sk), skillkit.parse_route_tasks(sk)

async def _route_save(
    app: web.Application, ws: web.WebSocketResponse, name: str,
) -> None:
    """`/route save <name>` — crystallise the last /route (in this thread)
    into a named, reusable route-skill via skillkit."""
    workspace: Path = app["workspace"]
    thread_id = app.get("thread_id")
    last = (app.get("last_route") or {}).get(thread_id)
    if not last or not last.get("tasks"):
        await ws.send_json(protocol.notice(
            "nothing to save — run `/route <task>` first, then "
            "`/route save <name>`.", kind="slash"))
        return
    if not name.strip():
        await ws.send_json(protocol.notice(
            "usage: /route save <name>", kind="slash"))
        return
    task_desc = str(last["description"]).strip()
    description = f"Use when the user asks to {task_desc[:180]}"
    body = skillkit.route_body(last["tasks"])
    try:
        sk = await asyncio.to_thread(
            skillkit.create_skill, workspace, "workspace", name,
            description, body, {"kind": skillkit.ROUTE_KIND})
    except skillkit.SkillError as e:
        await ws.send_json(protocol.notice(f"couldn't save: {e}", kind="slash"))
        return
    await ws.send_json(protocol.notice(
        f"✓ saved route-skill '{sk.name}' ({len(last['tasks'])} sub-tasks). "
        "`/route` a similar task to replay it.", kind="slash"))

async def _dispatch_route(
    app: web.Application, ws: web.WebSocketResponse, raw: str,
) -> None:
    """`/route` — on-the-fly ladder routing.

    · `/route save <name>`  → crystallise the last route as a route-skill.
    · `/route --split <task>` → force a fresh planner split (skip matching).
    · `/route <task>`        → match the task to one of YOUR skills first;
        a matched route-skill replays its saved split, a matched regular
        skill is invoked (loaded + run), otherwise plan a fresh split.
    """
    stripped = raw.strip()
    low = stripped.lower()
    if low == "save" or low.startswith("save "):
        await _route_save(app, ws, stripped[4:].strip())
        return

    force_split = False
    if low.startswith("--split"):
        force_split = True
        desc = stripped[len("--split"):].strip()
    else:
        desc = stripped
    if not desc:
        await ws.send_json(protocol.notice(
            "usage: /route <describe the task> · /route --split <task> · "
            "/route save <name>", kind="slash"))
        return

    if not force_split:
        matched = await _route_match(app, desc)
        if matched is not None:
            sk, is_route, tasks = matched
            if is_route and tasks:
                await ws.send_json(protocol.notice(
                    f"matched your route-skill '{sk.name}' — replaying its "
                    f"{len(tasks)} sub-tasks (`/route --split` to re-plan)…",
                    kind="chat"))
                await _daemon_ns._dispatch_fanout(
                    app, ws, desc, len(tasks),
                    preplanned_tasks=tasks, is_route=True)
                return
            # Regular skill → load + run it (single agent).
            await ws.send_json(protocol.notice(
                f"matched your '{sk.name}' skill — running it "
                "(`/route --split` to route fresh instead)…", kind="chat"))
            prompt = (f"Load the '{sk.name}' skill and use it to handle this "
                      f"request:\n\n{desc}")
            t = asyncio.create_task(_daemon_ns._dispatch_chat(app, ws, prompt))
            t.add_done_callback(_daemon_ns._make_dispatch_error_surface(app, ws))
            return

    n = await _route_pick_n(app, desc)
    await ws.send_json(protocol.notice(
        f"routing this task into {n} parallel sub-tasks across the ladder…",
        kind="chat"))
    await _daemon_ns._dispatch_fanout(app, ws, desc, n, is_route=True)
