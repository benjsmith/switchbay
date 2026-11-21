"""Workspace activation and one-time migrations.

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
import logging
from aiohttp import web
from switchbay import app_settings
from switchbay import ce_viewer_supervisor
from switchbay import conversations
from switchbay import curation_history
from switchbay import html_decks
from switchbay import proposals
from switchbay import protocol
from switchbay import sketches
from switchbay import statedir
from switchbay import tabstore
from switchbay import workspaces

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

async def _activate(app: web.Application, new_path: Path) -> None:
    """Switch the active workspace, invalidate caches, broadcast a fresh hello."""
    app["workspace"] = new_path
    # Keep the rail-history DB at the location the current setting
    # implies (roam-by-default in the workspace vs machine-local).
    # Off-thread + best-effort: the source file may live on a slow
    # cloud-sync service, and a relocation must never wedge the switch.
    asyncio.create_task(_ensure_rail_history_location(new_path))
    # Don't clear the per-workspace cache — switching back to an
    # earlier workspace should be instant. The legacy `graph_data`
    # alias gets re-pointed to whatever we have for the new
    # workspace (or None for first-visit).
    cache: dict[str, dict] = app.setdefault("graph_data_per_ws", {})
    app["graph_data"] = cache.get(str(new_path.resolve()))
    # Reset the FOREGROUND thread id — a new workspace is a new rail
    # context. Restore the destination workspace's most-recent thread
    # *before* hello so clients don't sit with focusedThread=null and
    # adopt a background RUN_STARTED from the workspace we just left.
    #
    # Do NOT wipe `llm_sessions`: provider resume handles are keyed by
    # thread_id (not provider), so a backgrounded run in the workspace
    # we're leaving keeps its session and stays steerable from the
    # (cross-workspace) Agent Dashboard. The foreground rail won't
    # mis-resume because thread_id is the destination's thread.
    app["thread_id"] = None
    app["thread_kind"] = None
    dest_tid = await asyncio.to_thread(conversations.active_thread_id, new_path)
    if dest_tid:
        app["thread_id"] = dest_tid
        dest_kind = await asyncio.to_thread(conversations.thread_kind, new_path, dest_tid)
        app["thread_kind"] = dest_kind or "structured-agent"
    workspaces.register(new_path, set_active=True)
    try:
        from switchbay import workspace_plan
        workspace_plan.ensure(new_path)
    except Exception:  # noqa: BLE001
        log.exception("workspace plan seed failed")
    try:
        from switchbay import skillkit
        skillkit.mirror_into_workspace(new_path)
    except Exception:  # noqa: BLE001
        log.exception("skill mirror seed failed")
    # First event of the new workspace's first thread. Lazily
    # creates the thread row in the new workspace's DB.
    _daemon_ns._log_event(
        app, "workspace_switch", f"opened {new_path}",
        source="system", actor="system",
        payload={"path": str(new_path)},
    )
    # Pre-warm the curation-history cache so the opening graph
    # animation starts paint-on-first-render instead of waiting
    # for a cold git-log walk after the user lands on the Graph
    # tab. Best-effort — failure just means the first hit pays
    # the build cost the way it did before.
    asyncio.create_task(_warm_curation_history(new_path))
    try:
        if await asyncio.to_thread(proposals.has_proposed, new_path):
            await asyncio.to_thread(tabstore.add_report_tab, new_path)
    except Exception:  # noqa: BLE001
        log.exception("reviews tab restore on workspace switch failed")
    # One-shot figures-convention migration (2026-07-05): legacy
    # workspace-root `figures/` moves into `wiki/figures/_assets/`
    # with wiki refs rewritten, so CE/CM tooling resolves assets
    # natively. Idempotent no-op once done; off-loop and best-effort.
    asyncio.create_task(_migrate_figures(app, new_path))
    asyncio.create_task(_migrate_legacy_decks(app, new_path))
    # Keep proxied Graph CE (:8766) on the active tip — best-effort, off-thread.
    async def _kick_ce_viewer() -> None:
        try:
            out = await asyncio.to_thread(ce_viewer_supervisor.start, new_path)
            log.info("CE viewer retarget on workspace switch: %s", out)
        except Exception:  # noqa: BLE001
            log.exception("CE viewer retarget on workspace switch failed")
    asyncio.create_task(_kick_ce_viewer())
    await _daemon_ns._broadcast(app, _daemon_ns._hello_payload(app))

async def _migrate_figures(app: web.Application, workspace: Path) -> None:
    try:
        res = await asyncio.to_thread(sketches.migrate_root_figures, workspace)
    except Exception:  # noqa: BLE001
        log.exception("figures migration failed for %s", workspace)
        return
    if not res:
        return
    _daemon_ns._log_event(
        app, "file_edit_internal",
        f"figures migrated to wiki/figures/_assets "
        f"({res['moved']} files, {res['pages_rewritten']} pages rewritten)",
        source="system", actor="system",
        payload={"workspace": str(workspace), **res},
    )
    await _daemon_ns._broadcast(app, protocol.files_changed())

async def _migrate_legacy_decks(app: web.Application, workspace: Path) -> None:
    """Move stale workspace ``decks/`` into ``slideshows/`` and drop the
    empty legacy root so the file browser no longer shows both."""
    try:
        res = await asyncio.to_thread(html_decks.migrate_legacy_decks, workspace)
    except Exception:  # noqa: BLE001
        log.exception("legacy decks/ migration failed for %s", workspace)
        return
    if not res:
        return
    _daemon_ns._log_event(
        app, "file_edit_internal",
        f"legacy decks/ → slideshows/ "
        f"(moved={res.get('moved')}, dupes={res.get('removed_dupes')}, "
        f"root_removed={res.get('removed_root')})",
        source="system", actor="system",
        payload={"workspace": str(workspace), **res},
    )
    await _daemon_ns._broadcast(app, protocol.files_changed())

async def _ensure_rail_history_location(workspace: Path) -> None:
    try:
        moved = await asyncio.to_thread(
            statedir.migrate_conversations_db,
            workspace,
            local=app_settings.get_rail_history_local(),
        )
        if moved:
            log.info("relocated rail-history DB for %s", workspace)
    except Exception:  # noqa: BLE001
        log.exception("rail-history relocation failed for %s", workspace)

async def _warm_curation_history(workspace: Path) -> None:
    try:
        await curation_history.read_or_build(workspace)
    except Exception:  # noqa: BLE001
        log.exception("curation-history pre-warm failed for %s", workspace)

def _desk_live_view(workspace: Path | None = None) -> dict[str, Any]:
    from switchbay.agents.desk_admission import public_view
    return public_view(workspace)
