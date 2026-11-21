"""In-memory run bookkeeping and cancel/steer routes.

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
import uuid
from aiohttp import web
from switchbay import conversations
from switchbay import terminals

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

def _remember_run_workspace(app: web.Application, run_id: str, workspace: Path) -> None:
    """Record which workspace a run belongs to, in a small capped map
    that — unlike `app["runs"]` — survives the run completing. The
    Agent Dashboard is cross-workspace: it must resolve a run's
    transcript against that run's OWN workspace DB, even from another
    focused workspace and even for a run that just finished. Keyed by
    run_id (not provider/conversation) so two runs never collide."""
    m: dict[str, str] = app.setdefault("run_ws", {})
    m[run_id] = str(workspace)
    # Bound it: drop oldest insertions past the cap (dict preserves
    # insertion order). Recently-finished runs stay resolvable.
    overflow = len(m) - 256
    if overflow > 0:
        for k in list(m)[:overflow]:
            m.pop(k, None)

def _run_workspace(app: web.Application, run_id: str) -> Path | None:
    """Resolve a run's workspace from the capped run→ws map (live or
    recently-finished). None if unknown (very old / never-registered)."""
    raw = (app.get("run_ws") or {}).get(run_id)
    return Path(raw) if raw else None

def _workspace_key(path: Path | str) -> str:
    try:
        return str(Path(path).expanduser().resolve())
    except OSError:
        return str(path).rstrip("/")

def _is_focused_workspace(app: web.Application, workspace: Path | str) -> bool:
    """True when `workspace` is the daemon's currently focused vault."""
    cur = app.get("workspace")
    if cur is None:
        return False
    return _workspace_key(workspace) == _workspace_key(cur)

def _remember_run_thread(app: web.Application, run_id: str, thread_id: str) -> None:
    """run→thread twin of `_remember_run_workspace`: keeps a finished
    run steerable/continuable — the dashboard can resolve its thread
    and dispatch a follow-up via `thread_id_override` after the
    `app["runs"]` entry is gone. (The DB also persists run_id on every
    event, so this map is a fast path, not the source of truth.)"""
    m: dict[str, str] = app.setdefault("run_thread", {})
    m[run_id] = thread_id
    overflow = len(m) - 256
    if overflow > 0:
        for k in list(m)[:overflow]:
            m.pop(k, None)

def _remember_run_palette(
    app: web.Application,
    run_id: str,
    command: str | None,
    template: str | None,
) -> None:
    """Keep the command desk on a finished run so a steer stays on it."""
    if not command:
        return
    m: dict[str, dict[str, str | None]] = app.setdefault("run_palette", {})
    m[run_id] = {"command": command, "template": template}
    overflow = len(m) - 256
    if overflow > 0:
        for k in list(m)[:overflow]:
            m.pop(k, None)

def _run_palette(
    app: web.Application, run_id: str,
) -> tuple[str | None, str | None]:
    rec = (app.get("run_palette") or {}).get(run_id)
    if not isinstance(rec, dict):
        return None, None
    cmd = rec.get("command")
    tmpl = rec.get("template")
    return (
        str(cmd) if cmd else None,
        str(tmpl) if tmpl else None,
    )

async def handle_runs_active(request: web.Request) -> web.Response:
    """Snapshot of currently-running rail dispatches. The Agent
    Dashboard polls this every couple of seconds — the registry is in
    process memory so the read is cheap, no DB hit."""
    _daemon_ns._refresh_pty_statuses(request.app)
    runs: dict[str, dict[str, Any]] = request.app.get("runs") or {}
    out = []
    for r in runs.values():
        # `task` is an asyncio.Task — not JSON-serialisable. Strip it.
        out.append({k: v for k, v in r.items() if k != "task"})
    out.sort(key=lambda r: r.get("started_at") or 0, reverse=True)
    return web.json_response({"runs": out})

async def handle_run_background(request: web.Request) -> web.Response:
    """Mark a run as backgrounded — UX hint that the user can close
    the rail / tab without losing it. The run keeps executing as
    before (asyncio task is already independent of the WS), this
    just flags the registry so the dashboard surfaces it
    differently."""
    runs: dict[str, dict[str, Any]] = request.app.get("runs") or {}
    run_id = request.match_info.get("run_id", "").strip()
    rec = runs.get(run_id)
    if rec is None:
        return web.json_response({"ok": True, "note": "already finished"})
    rec["is_background"] = True
    return web.json_response({"ok": True})

async def handle_run_steer(request: web.Request) -> web.Response:
    """Dispatch a follow-up user turn INTO a run's thread — the
    cross-workspace steer seam's first caller. Works for live and
    recently-finished runs: the run's workspace + thread resolve via
    the capped `run_ws`/`run_thread` maps, with the DB (events carry
    run_id) as fallback. The dispatch is headless (`ws=None`); output
    streams to that thread's transcript only, and the per-thread
    reject-busy guard turns a steer at a still-streaming run into a
    broadcast notice instead of a corrupted session."""
    run_id = request.match_info.get("run_id", "").strip()
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    text = str(body.get("text") or "").strip()
    if not text:
        return web.json_response({"error": "text required"}, status=400)
    app = request.app
    ws_path = _run_workspace(app, run_id)
    if ws_path is None:
        return web.json_response(
            {"error": "unknown run (too old — not in the run map)"}, status=404,
        )
    thread_id = (app.get("run_thread") or {}).get(run_id)
    if not thread_id:
        evs = await asyncio.to_thread(
            conversations.list_events, ws_path, run_id=run_id, limit=1,
        )
        thread_id = evs[0]["thread_id"] if evs else None
    if not thread_id:
        return web.json_response(
            {"error": "run has no thread on record"}, status=404,
        )
    new_run = f"run-{uuid.uuid4().hex[:8]}"
    steer_cmd, steer_tmpl = _run_palette(app, run_id)
    task = asyncio.create_task(_daemon_ns._dispatch_chat(
        app, None, text,
        input_excerpt=f"[steer] {text[:100]}",
        run_id=new_run,
        workspace_override=ws_path,
        thread_id_override=thread_id,
        command=steer_cmd,
        command_template=steer_tmpl,
    ))
    task.add_done_callback(_daemon_ns._make_dispatch_error_surface(app, new_run))
    return web.json_response({
        "ok": True,
        "run_id": new_run,
        "thread_id": thread_id,
        "workspace": str(ws_path),
    })

async def handle_run_cancel(request: web.Request) -> web.Response:
    """Cancel a run by id. The asyncio.Task gets `.cancel()`'d; the
    dispatch's CancelledError handler broadcasts a RUN_ERROR and
    the finally block deregisters from `runs`. Returns ok=true even
    when the run had already ended (idempotent from the UI's view)."""
    runs: dict[str, dict[str, Any]] = request.app.get("runs") or {}
    run_id = request.match_info.get("run_id", "").strip()
    rec = runs.get(run_id)
    if rec is None:
        return web.json_response({"ok": True, "note": "already finished"})
    rec["user_cancel"] = True
    parent_id = rec.get("parent_run_id")
    if parent_id and runs.get(parent_id):
        runs[parent_id]["user_cancel"] = True
    ws_raw = rec.get("workspace")
    if ws_raw:
        from switchbay import kernel as sbk
        try:
            sbk.quiet_run(Path(ws_raw), run_id)
            if parent_id:
                sbk.quiet_run(Path(ws_raw), str(parent_id))
        except Exception:  # noqa: BLE001
            log.exception("desk quiet on cancel failed")
    task = rec.get("task")
    if task is not None:
        try:
            task.cancel()
        except Exception:  # noqa: BLE001
            pass
    # PTY-thread runs have no asyncio task — kill the shell instead;
    # its on_exit callback closes the AG-UI run + registry entry.
    sid = rec.get("pty_session")
    if sid:
        s = (request.app.get("terminals") or {}).get(sid)
        if s is not None:
            terminals.kill(s)
    return web.json_response({"ok": True})

def _cancel_ce_runs(
    app: web.Application, action: str | tuple[str, ...] = "curate",
    *, workspace: Path | None = None, settle: str = "quiet",
) -> int:
    """Cancel background jobs for one desk/command in one workspace.

    Matches ``command`` or an excerpt prefix ``[action ·``, never a
    substring like ``code`` inside ``Codex`` or an unrelated chat.
    Sets ``user_cancel`` so orchestration records cancelled (not
    interrupted). The desk itself is quieted or dismissed by the
    caller — Stop does not tear the chief down.
    """
    needles = (
        {action.lower()}
        if isinstance(action, str)
        else {a.lower() for a in action}
    )
    runs: dict[str, dict[str, Any]] = app.get("runs") or {}
    want_ws = str(workspace.resolve()) if workspace is not None else None
    matched: set[str] = set()
    for rec in list(runs.values()):
        if want_ws:
            rec_ws = str(rec.get("workspace") or "")
            if rec_ws:
                try:
                    rec_ws = str(Path(rec_ws).resolve())
                except OSError:
                    pass
                if rec_ws != want_ws:
                    continue
        cmd = str(rec.get("command") or "").lower()
        excerpt = str(rec.get("input_excerpt") or "").lower()
        if cmd not in needles and not any(
            excerpt.startswith(f"[{n} ·") for n in needles
        ):
            continue
        rid = str(rec.get("run_id") or "")
        if rid:
            matched.add(rid)
        parent = rec.get("parent_run_id")
        if parent:
            matched.add(str(parent))
    if not matched:
        return 0
    for rec in list(runs.values()):
        rid = str(rec.get("run_id") or "")
        parent = str(rec.get("parent_run_id") or "")
        if rid in matched or parent in matched:
            if rid:
                matched.add(rid)
            if parent:
                matched.add(parent)
    if workspace is not None:
        if settle == "cancelled":
            _mark_orchestrations_cancelled(workspace, matched)
        else:
            _mark_orchestrations_quiet(workspace, matched)
    return _daemon_ns._cancel_run_ids(app, matched, dismiss=(settle == "cancelled"))

def _mark_orchestrations_cancelled(workspace: Path, ids: set[str]) -> None:
    """Write cancelled checkpoints immediately so Stop cannot auto-resume."""
    from switchbay.agents import orchestration as orch
    for oid in ids:
        if not oid:
            continue
        try:
            cp = orch.load_checkpoint(workspace, oid)
        except Exception:  # noqa: BLE001
            continue
        if not cp or not isinstance(cp.get("status"), dict):
            continue
        st = cp["status"]
        if str(st.get("phase") or "") in ("completed", "cancelled"):
            continue
        try:
            orch.persist_checkpoint(
                workspace, oid,
                phase="cancelled",
                completed=st.get("completed") or [],
                failed=st.get("failed") or [],
                expansions=int(st.get("expansions") or 0),
                results=cp.get("results") or {},
                elapsed_s=float(st.get("elapsed_s") or 0),
                thread_id=st.get("thread_id"),
            )
        except Exception:  # noqa: BLE001
            log.exception("cancel checkpoint %s failed", oid)

def _mark_orchestrations_quiet(workspace: Path, ids: set[str]) -> None:
    """Freeze a DAG on Stop so boot does not auto-resume, but Start can."""
    from switchbay.agents import orchestration as orch
    for oid in ids:
        if not oid:
            continue
        try:
            cp = orch.load_checkpoint(workspace, oid)
        except Exception:  # noqa: BLE001
            continue
        if not cp or not isinstance(cp.get("status"), dict):
            continue
        st = cp["status"]
        if str(st.get("phase") or "") in ("completed", "cancelled"):
            continue
        try:
            orch.persist_checkpoint(
                workspace, oid,
                phase="quiet",
                completed=st.get("completed") or [],
                failed=st.get("failed") or [],
                expansions=int(st.get("expansions") or 0),
                results=cp.get("results") or {},
                elapsed_s=float(st.get("elapsed_s") or 0),
                thread_id=st.get("thread_id"),
            )
        except Exception:  # noqa: BLE001
            log.exception("quiet checkpoint %s failed", oid)
