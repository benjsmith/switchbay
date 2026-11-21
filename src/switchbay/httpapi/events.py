"""Rail event log, broadcast, and post-write graph refresh.

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
import functools
import logging
from aiohttp import web
from switchbay import cebridge
from switchbay import conversations
from switchbay import file_state
from switchbay import ingest_run_drain
from switchbay import pack_run_drain
from switchbay import protocol
from switchbay import wiki_sync

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

async def _broadcast(app: web.Application, message: dict) -> None:
    """Send a message to every connected WS client, dropping dead ones."""
    dead = []
    for ws in app["ws_clients"]:
        try:
            await ws.send_json(message)
        except (ConnectionResetError, ConnectionAbortedError, RuntimeError):
            dead.append(ws)
    for ws in dead:
        app["ws_clients"].discard(ws)

# ── Rail-log write-serializer ────────────────────────────────────────
# Every rail-log write (`conversations.append_event`) used to open
# sqlite and INSERT on the event loop. On a cloud-sync-evicted
# conversations.db that sqlite open can block for tens of seconds. We
# funnel all writes through a single FIFO worker that runs each insert
# off the loop via `to_thread`. One consumer ⇒ writes stay ordered and
# never contend with each other; reads (working_set / list_events) are
# offloaded separately and `PRAGMA busy_timeout` covers the overlap.


async def _conv_write_worker(app: web.Application) -> None:
    q: asyncio.Queue = app["conv_writes"]
    while True:
        thunk, fut = await q.get()
        try:
            res = await asyncio.to_thread(thunk)
            if fut is not None and not fut.done():
                fut.set_result(res)
        except Exception as e:  # noqa: BLE001
            if fut is not None and not fut.done():
                fut.set_exception(e)
            else:
                log.exception("rail append (queued) failed")
        finally:
            q.task_done()

def _submit_conv_write(app: web.Application, fn: Any) -> None:
    """Enqueue an arbitrary conversations-write thunk onto the single
    FIFO write-serializer (runs off the loop via to_thread). Falls back
    to a direct (blocking) call if the queue isn't up yet (build_app
    before the loop, or tests). The single consumer means thunks that
    create-then-cache a conversation id serialise correctly — the first
    creates it, the rest reuse the cached id."""
    q: asyncio.Queue | None = app.get("conv_writes")
    if q is None:
        try:
            fn()
        except Exception:  # noqa: BLE001
            log.exception("rail write (inline fallback) failed")
        return
    q.put_nowait((fn, None))

def _append_event(app: web.Application, *args: Any, **kwargs: Any) -> None:
    """Fire-and-forget rail-log append, serialized off the event loop."""
    _submit_conv_write(app, functools.partial(conversations.append_event, *args, **kwargs))

async def _append_event_wait(app: web.Application, *args: Any, **kwargs: Any) -> Any:
    """Append and await completion — for the one path that reads the
    event back immediately (a user turn feeding `working_set`)."""
    thunk = functools.partial(conversations.append_event, *args, **kwargs)
    q: asyncio.Queue | None = app.get("conv_writes")
    if q is None:
        return await asyncio.to_thread(thunk)
    fut = asyncio.get_running_loop().create_future()
    q.put_nowait((thunk, fut))
    return await fut

def _log_event(
    app: web.Application,
    kind: str,
    summary: str,
    *,
    source: str = "system",
    actor: str | None = None,
    payload: Any = None,
    ref_id: str | None = None,
) -> None:
    """Append to the rail log. Best-effort — never raises into the
    caller, since logging shouldn't break a workspace op. The entire
    write — conversation-create included — runs off the event loop in
    the write-serializer worker, so no sqlite ever touches the loop."""
    try:
        ws = app.get("workspace")
        if not ws:
            return

        def _write() -> None:
            # Resolve/create the thread INSIDE the worker so the
            # sqlite writes stay off the loop. The single-consumer
            # queue serialises this: the first call resolves + caches
            # the id, the rest reuse it. System breadcrumbs GLUE to the
            # most-recent thread rather than minting one — untitled
            # system-only threads were flooding the switcher (45 in a
            # real DB). Only user dispatch paths create fresh threads.
            tid = app.get("thread_id")
            if not tid:
                tid = conversations.active_thread_id(ws) or conversations.new_thread(ws)
                app["thread_id"] = tid
            conversations.append_event(
                ws, tid, kind, summary,
                source=source, actor=actor, payload=payload, ref_id=ref_id,
            )

        _submit_conv_write(app, _write)
    except Exception:  # noqa: BLE001
        log.exception("failed to append rail event kind=%s", kind)

def _log_user_turn(app: web.Application, workspace: Path, text: str) -> None:
    """Record the user's prose as a `user` rail event before the rail
    dispatches it (rule / intent / fan-out paths). Thread-create
    included, off the loop via the write-serializer — preserves rail
    order (enqueued before any follow-up _log_event for the same turn)."""
    def _write() -> None:
        tid = app.get("thread_id")
        if not tid:
            # Unfocused: continue the most-recent thread (matches what
            # the rail shows after auto-focus) instead of minting an
            # orphan. /llm-reset paths reach _dispatch_* which DO mint.
            tid = conversations.active_thread_id(workspace) or conversations.new_thread(workspace)
            app["thread_id"] = tid
        conversations.append_event(workspace, tid, "user", text)
    _submit_conv_write(app, _write)

def _schedule_after_wiki_write(
    app: web.Application, workspace: Path, rel: str | None = None,
) -> None:
    """Coalesce graph rebuilds during a curate wave (2s after last write)."""
    prev = app.get("_after_wiki_write_task")
    if isinstance(prev, asyncio.Task) and not prev.done():
        prev.cancel()

    async def _go() -> None:
        try:
            await asyncio.sleep(2.0)
        except asyncio.CancelledError:
            return
        await _after_wiki_write(app, workspace, rel)

    app["_after_wiki_write_task"] = asyncio.create_task(_go())

async def _after_wiki_write(
    app: web.Application, workspace: Path, rel: str | None = None,
) -> None:
    """Wire [[wikilinks]], refresh CE index, rebuild kuzu + viewer."""
    rel_s = str(rel or "")
    if rel_s.startswith("wiki/"):
        try:
            await asyncio.to_thread(wiki_sync.after_wiki_write, workspace, rel)
        except Exception:  # noqa: BLE001
            log.exception("wiki_sync.after_wiki_write failed for %s", rel)
        await _rebuild_graph_async(app)
        return
    try:
        await _daemon_ns._broadcast(app, protocol.files_changed())
    except Exception:  # noqa: BLE001
        log.exception("files_changed after non-wiki write failed")

async def _rebuild_graph_async(app: web.Application) -> None:
    """Rebuild kuzu, then the viewer bundle, then broadcast.

    `viewer.sh build` only *reads* `.curator/graph.kuzu`. Without a
    ``graph.py rebuild`` first, new pages land as isolated nodes (or
    stay missing from the wiki browser until a curate wave).
    """
    try:
        ws = app.get("workspace")
        if not ws:
            return
        try:
            await cebridge.ensure_venv(ws)
            await cebridge.graph_rebuild(ws)
        except Exception:  # noqa: BLE001
            log.exception("kuzu graph rebuild failed (continuing with viewer)")
        data = await cebridge.build(ws)
        if data is None:
            data = await asyncio.to_thread(cebridge.read_cached, ws)
        if data is not None:
            await asyncio.to_thread(wiki_sync.inject_on_disk_pages, ws, data)
            _daemon_ns._put_graph_cache(app, str(ws.resolve()), data)
            await _daemon_ns._broadcast(app, protocol.files_changed())
    except Exception:  # noqa: BLE001
        log.exception("graph rebuild after agent edit failed")

def _broadcast_files_changed_soon(app: web.Application) -> None:
    """Schedule a `files_changed` WS broadcast on the running event
    loop. Safe to call from sync code paths — fires once the loop
    yields. Cheap; the frontend dedupes via render."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # not inside an event loop (test context, etc.)
    loop.create_task(_daemon_ns._broadcast(app, protocol.files_changed()))
    # Opportunistic pack-run drain when workspace files change (CE may
    # have just written ``.workbench/pack-runs/*.json``). No-op if the
    # dir is absent; dedupes via ``pack_run_inflight``.
    try:
        ws = app.get("workspace")
        if ws and pack_run_drain.runs_dir(Path(ws)).is_dir():
            pack_run_drain.kick_drain(app)
        if ws and ingest_run_drain.runs_dir(Path(ws)).is_dir():
            ingest_run_drain.kick_drain(app)
    except Exception:  # noqa: BLE001
        pass

def _check_external_edit(app: web.Application, rel: str) -> None:
    """Schedule lazy external-edit detection for `rel` without blocking
    the caller. Called from every read path that touches a single file
    (page get, raw fetch, db introspect, …).

    The detection itself (`file_state.check_external`) does a stat, an
    indexed sqlite lookup in conversations.db, and — if the stat drifted
    — a full-file sha256. On a large or cloud-sync-evicted file/DB that
    would block the event loop, so we run it on a thread and only touch
    the loop again to emit the rail event. Fire-and-forget + best-effort;
    failures never affect the read that triggered it."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # not inside an event loop (test context, etc.)
    loop.create_task(_check_external_edit_async(app, rel))

async def _check_external_edit_async(app: web.Application, rel: str) -> None:
    try:
        ws = app.get("workspace")
        if not ws:
            return
        change = await asyncio.to_thread(file_state.check_external, ws, rel)
        if not change:
            return
        old_n = change.get("old_size") or 0
        new_n = change.get("new_size") or 0
        delta = new_n - old_n
        sign = "+" if delta >= 0 else ""
        _daemon_ns._log_event(
            app, "file_edit_external",
            f"external edit: {rel} ({sign}{delta} bytes, {old_n} → {new_n})",
            source="filesystem", actor="external",
            payload={"path": rel, **change},
        )
        _daemon_ns._broadcast_files_changed_soon(app)
    except Exception:  # noqa: BLE001
        log.exception("file_state check failed for %s", rel)
