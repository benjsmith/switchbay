"""Rail threads, focus, archive, and terminal tab routes.

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
from aiohttp import web
from switchbay import conversations
from switchbay import llmgateway
from switchbay import protocol
from switchbay import tabstore
from switchbay import terminals

from switchbay.httpapi._ns import _daemon_ns

def _refresh_pty_statuses(app: web.Application) -> None:
    """Re-derive each live PTY run's status from its session: `running`
    while something is actually happening, `idle` when the shell sits
    at its prompt / a TUI waits for input (terminals.is_idle). Dormant
    shells must not count as running work anywhere — dashboard counts,
    the top-bar tasks button, the thread bar dot — so every reader of
    run statuses calls this first. Cheap: one tcgetpgrp per live pty."""
    sessions = app.get("terminals") or {}
    for rec in (app.get("runs") or {}).values():
        sid = rec.get("pty_session")
        if not sid:
            continue
        s = sessions.get(sid)
        if s is None or s.exited:
            rec["status"] = "idle"  # on_exit pops the rec momentarily
        else:
            rec["status"] = "idle" if terminals.is_idle(s) else "running"

def _threads_running(app: web.Application) -> dict[str, int]:
    """Per-thread count of currently-streaming runs, from the live-runs
    registry. Lingering finished workers (status done/error, kept a few
    seconds for the dashboard poll) don't count, and neither do dormant
    shells (status idle)."""
    _refresh_pty_statuses(app)
    running: dict[str, int] = {}
    for rec in (app.get("runs") or {}).values():
        tid = rec.get("thread_id")
        if tid and rec.get("status") in _daemon_ns._ORCH_BUSY_STATUSES:
            running[tid] = running.get(tid, 0) + 1
    return running

async def handle_threads_list(request: web.Request) -> web.Response:
    """Threads of the focused workspace for the rail switcher, plus
    which one is focused and how many runs stream on each."""
    workspace: Path = request.app["workspace"]
    threads = await asyncio.to_thread(conversations.list_threads, workspace)
    running = _threads_running(request.app)
    sessions = request.app.get("terminals") or {}
    thread_pty: dict[str, str] = request.app.get("thread_pty") or {}
    for t in threads:
        t["running"] = running.get(t["thread_id"], 0)
        if t["kind"] == "interactive-pty":
            sid = thread_pty.get(t["thread_id"])
            s = sessions.get(sid) if sid else None
            t["pty_live"] = bool(s is not None and not s.exited)
    return web.json_response({
        "threads": threads,
        "focused": request.app.get("thread_id"),
    })

async def handle_thread_new(request: web.Request) -> web.Response:
    """Create + focus a fresh thread (rail "+ New thread"). The next
    rail turn runs in it; the old thread keeps its provider session
    (keyed by thread_id) and stays continuable from the switcher."""
    workspace: Path = request.app["workspace"]
    title: str | None = None
    kind = "structured-agent"
    try:
        body = await request.json()
        title = str(body.get("title") or "").strip() or None
        if str(body.get("kind") or "") == "interactive-pty":
            kind = "interactive-pty"
    except Exception:  # noqa: BLE001 — empty/absent body is fine
        pass
    if not title:
        # Placeholders so the switcher never shows an anonymous row:
        # shells are "shell"; chat threads get a numbered "New thread
        # N" that the excerpt backfill / auto-titler replace on the
        # first user turn.
        if kind == "interactive-pty":
            title = "shell"
        else:
            title = await asyncio.to_thread(
                conversations.next_new_thread_title, workspace,
            )
    tid = await asyncio.to_thread(conversations.new_thread, workspace, title, kind)
    request.app["thread_id"] = tid
    request.app["thread_kind"] = kind
    await _daemon_ns._broadcast(request.app, protocol.thread_focused(
        tid, kind, workspace=str(workspace),
    ))
    return web.json_response({"ok": True, "thread_id": tid, "kind": kind})

async def handle_thread_focus(request: web.Request) -> web.Response:
    """Switch the daemon's focused thread. Sessions are per-thread, so
    focusing back onto an old thread resumes its provider session on
    the next turn — no state is torn down here."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    tid = str(body.get("thread_id") or "").strip()
    if not tid:
        return web.json_response({"error": "thread_id required"}, status=400)
    workspace: Path = request.app["workspace"]
    kind = await asyncio.to_thread(conversations.thread_kind, workspace, tid)
    if kind is None:
        return web.json_response(
            {"error": "no such thread in this workspace"}, status=404,
        )
    request.app["thread_id"] = tid
    request.app["thread_kind"] = kind
    await _daemon_ns._broadcast(request.app, protocol.thread_focused(
        tid, kind, workspace=str(workspace),
    ))
    return web.json_response({"ok": True, "thread_id": tid, "kind": kind})

async def handle_llm_test(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    pid = str(body.get("provider", llmgateway.default_provider_id()))
    workspace: Path = request.app["workspace"]
    try:
        provider = llmgateway.get(pid)
        await provider.validate_key(workspace=str(workspace))
    except llmgateway.ProviderError as e:
        return web.json_response({"ok": False, "code": e.code, "message": str(e)}, status=400)
    return web.json_response({"ok": True})

async def _kill_thread_pty(app: web.Application, thread_id: str) -> None:
    """Terminate the live shell attached to a pty thread, if any.
    Shared by archive + purge — a hidden/removed thread must not leave
    an orphaned session behind."""
    sid = (app.get("thread_pty") or {}).get(thread_id)
    if not sid:
        return
    s = (app.get("terminals") or {}).get(sid)
    if s is not None and not s.exited:
        terminals.kill(s)

async def handle_thread_archive(request: web.Request) -> web.Response:
    """Soft-delete a thread: hide it from the switcher, keep its
    events in the log (searchable via recall_rail — rail philosophy).
    Kills an attached live shell, drops the provider resume handle,
    and moves focus to the most recent surviving thread."""
    workspace: Path = request.app["workspace"]
    tid = request.match_info.get("thread_id", "").strip()
    if not tid:
        return web.json_response({"error": "thread_id required"}, status=400)
    ok = await asyncio.to_thread(conversations.archive_thread, workspace, tid)
    if not ok:
        return web.json_response({"error": "no such thread"}, status=404)
    await _kill_thread_pty(request.app, tid)
    (request.app.get("llm_sessions") or {}).pop(tid, None)
    # An archived pty thread's popped-out terminal tab would orphan
    # (its attach can never succeed again) — remove it with the thread.
    orphaned = await asyncio.to_thread(
        tabstore.remove_terminal_tabs, workspace, thread_id=tid,
    )
    if orphaned:
        await _daemon_ns._broadcast(request.app, _daemon_ns._hello_payload(request.app))
    refocused: str | None = None
    if request.app.get("thread_id") == tid:
        remaining = await asyncio.to_thread(conversations.list_threads, workspace)
        request.app["thread_id"] = remaining[0]["thread_id"] if remaining else None
        request.app["thread_kind"] = remaining[0]["kind"] if remaining else None
        refocused = request.app["thread_id"]
        if refocused:
            await _daemon_ns._broadcast(request.app, protocol.thread_focused(
                refocused, request.app["thread_kind"] or "structured-agent",
                workspace=str(workspace),
            ))
    await _daemon_ns._broadcast(request.app, protocol.custom({
        "type": "thread.archived", "thread_id": tid,
    }))
    return web.json_response({"ok": True, "focused": refocused})

async def handle_thread_project(request: web.Request) -> web.Response:
    """Bind / unbind a thread's project (D8) — the ThreadBar picker
    chip's endpoint. Body: {"project": "<name>" | null}. Names must
    exist (non-archived) in CE's project registry; null unbinds."""
    workspace: Path = request.app["workspace"]
    tid = request.match_info.get("thread_id", "").strip()
    if not tid:
        return web.json_response({"error": "thread_id required"}, status=400)
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    raw = body.get("project")
    project: str | None = None
    if raw is not None:
        known = await asyncio.to_thread(_daemon_ns._known_projects, workspace)
        project = known.get(str(raw).strip().lower())
        if project is None:
            return web.json_response(
                {"error": f"unknown project {raw!r}"}, status=400,
            )
    ok = await asyncio.to_thread(
        conversations.set_project, workspace, tid, project,
    )
    if not ok:
        return web.json_response({"error": "no such thread"}, status=404)
    await _daemon_ns._broadcast(
        request.app, protocol.thread_project_changed(tid, project),
    )
    return web.json_response({"ok": True, "thread_id": tid, "project": project})
