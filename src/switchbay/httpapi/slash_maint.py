"""Maintenance slash commands (rescan, setup, clear).

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
from switchbay import cebridge
from switchbay import conversations
from switchbay import protocol
from switchbay import tabstore

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

async def _handle_rescan(
    app: web.Application, ws: web.WebSocketResponse,
) -> None:
    """Cold-rebuild the workspace's wiki cache. Drops switchbay's
    in-memory `graph_data_per_ws` entry for the active workspace,
    deletes the on-disk `data.json` so the next read can't fall
    back to a stale copy, runs `viewer.sh build` fresh, and
    broadcasts `files_changed` so every connected client refetches
    /api/tree + /api/graph/data.

    Use when the BROWSER sidebar shows artefacts that didn't clear
    after a workspace switch — stale Kuzu nodes from a previous
    session, deleted pages still listed, etc."""
    workspace: Path = app["workspace"]
    ws_key = str(workspace.resolve())
    cache: dict[str, dict] = app.setdefault("graph_data_per_ws", {})
    cache.pop(ws_key, None)
    if app.get("graph_data") is not None:
        app["graph_data"] = None
    # Wipe the on-disk data.json so read_cached can't serve a stale
    # copy on next request. cebridge.output_dir is `<wiki>/.cache/...`
    # in CE's convention.
    try:
        from switchbay import cebridge as _cebridge
        out = _cebridge.output_dir(workspace)
        data_json = out / "data.json"
        if data_json.is_file():
            data_json.unlink()
    except Exception:  # noqa: BLE001
        log.exception("rescan: failed to clear on-disk data.json")
    await ws.send_json(protocol.notice(
        "rescan: rebuilding workspace cache (fresh viewer.sh build)…",
        kind="chat",
    ))
    fresh = await cebridge.build(workspace)
    if fresh is None:
        await ws.send_json(protocol.notice(
            "rescan: viewer.sh build failed (no wiki/ in workspace?)",
            kind="chat",
        ))
        return
    _daemon_ns._put_graph_cache(app, ws_key, fresh)
    await _daemon_ns._broadcast(app, protocol.files_changed())
    await ws.send_json(protocol.notice(
        f"rescan: rebuilt — {len(fresh.get('pages') or {})} pages, "
        f"{len(fresh.get('edges') or [])} edges.",
        kind="chat",
    ))

async def _handle_setup_wiki(
    app: web.Application, ws: web.WebSocketResponse,
) -> None:
    """Initialise a curiosity-engine wiki in the active workspace,
    server-side. Backs the no-wiki "Set up wiki + run curator" rail
    action. Runs CE's `setup.sh` via cebridge (the rail agent can't —
    it's sandboxed shell-less, and setup.sh is interactive), rebuilds
    the viewer, then dispatches the curator agent to ingest any raw
    sources in `vault/` (which the agent CAN do via the CE skill)."""
    workspace: Path = app["workspace"]
    await _daemon_ns._broadcast(app, protocol.notice(
        "Setting up a curiosity-engine wiki (running setup.sh)…", kind="chat",
    ))
    ok, output = await cebridge.setup(workspace)
    if not ok:
        await _daemon_ns._broadcast(app, protocol.notice(
            f"Wiki setup failed: {output[-400:]}", kind="error",
        ))
        return
    # Build the viewer + broadcast files_changed so clients refetch the
    # graph and the no-wiki empty state clears.
    await _handle_rescan(app, ws)
    # If there are raw sources to ingest, kick the curator (agent work,
    # not shell work — the agent can drive the CE skill here).
    vault = workspace / "vault"
    has_sources = vault.is_dir() and any(p.is_file() for p in vault.rglob("*"))
    if has_sources:
        prompt = (
            "A curiosity-engine wiki was just initialised in this "
            "workspace. Ingest the raw sources under `vault/` into "
            "interlinked `wiki/` pages (sources, concepts, entities), "
            "then run a curator pass to build out the graph. Load the "
            "curiosity-engine skill first if you haven't."
        )
        t = asyncio.create_task(_daemon_ns._dispatch_chat(
            app, ws, prompt, command="curate",
        ))
        t.add_done_callback(_daemon_ns._make_dispatch_error_surface(app, ws))
    else:
        await _daemon_ns._broadcast(app, protocol.notice(
            "Wiki ready. Add sources to vault/ and run /curate to build "
            "the graph.", kind="chat",
        ))

async def _handle_clear_rail(
    app: web.Application, ws: web.WebSocketResponse,
) -> None:
    """Truncate the rail's persisted history for the active workspace.
    Drops every events + threads row in
    `<ws>/.workbench/state/conversations.db`, resets the in-memory
    thread pointer, and broadcasts `rail_cleared` so connected
    frontends drop their transcripts in lock-step."""
    workspace: Path = app["workspace"]
    try:
        result = conversations.clear_all(workspace)
    except Exception as e:  # noqa: BLE001
        log.exception("clear-rail-history: clear_all failed")
        await ws.send_json(protocol.notice(
            f"clear-rail-history: failed — {e}", kind="chat",
        ))
        return
    # Drop in-memory state so the next user turn starts a fresh
    # thread row.
    app["thread_id"] = None
    app["thread_kind"] = None
    app["llm_sessions"] = {}
    # Every thread is gone — unscope thread-scoped tabs so they revert
    # to workspace-wide instead of hiding forever behind dead ids, and
    # drop terminal tabs (their payload thread ids can never attach).
    stripped = await asyncio.to_thread(tabstore.strip_thread_scopes, workspace)
    dropped = await asyncio.to_thread(tabstore.remove_terminal_tabs, workspace)
    if stripped or dropped:
        await _daemon_ns._broadcast(app, _daemon_ns._hello_payload(app))
    await _daemon_ns._broadcast(app, protocol.rail_cleared())
    await ws.send_json(protocol.notice(
        f"rail history cleared — removed {result['events']} events "
        f"across {result['threads']} threads.",
        kind="chat",
    ))
