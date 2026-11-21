"""Wiki page and filesystem stat/delete/duplicate/reveal routes.

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
from switchbay import cebridge
from switchbay import file_state
from switchbay import fileops
from switchbay import protocol
from switchbay import selection
from switchbay import statedir
from switchbay import wiki_sync
from switchbay import workspaces

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

def _resolve_wiki_md(workspace: Path, rel: str) -> Path | None:
    """Resolve `rel` under `<workspace>/wiki/` and require .md.

    Accepts either form:
      - workspace-relative: `wiki/concepts/foo.md`
      - wiki-relative (as CE's data.json reports it): `concepts/foo.md`

    Returns None on absolute paths, traversal escape, or non-.md path.
    Switch Bay allows editing of any .md page in wiki/; CE only
    allowed notes/* and todos/*.
    """
    if not rel or rel.startswith("/") or not rel.endswith(".md"):
        return None
    parts = Path(rel).parts
    if not parts or parts[0] != "wiki":
        rel = f"wiki/{rel}"
    target = _daemon_ns._safe_resolve(workspace, rel)
    if target is None:
        return None
    wiki = workspace / "wiki"
    try:
        target.relative_to(wiki)
    except ValueError:
        return None
    return target

async def handle_page_get(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    rel = request.query.get("path", "")
    target = _resolve_wiki_md(workspace, rel)
    if target is None:
        return web.json_response({"error": "invalid path"}, status=400)
    if not target.is_file():
        return web.json_response({"error": "not found"}, status=404)
    # Cloud-sync placeholder — hydrate off-thread + tell the frontend to
    # show an honest "syncing" state rather than blocking on the read.
    if statedir.is_dataless(target):
        async def _pull() -> None:
            try:
                await asyncio.to_thread(target.read_bytes)
            except Exception:  # noqa: BLE001
                log.exception("hydration read failed for %s", target)
        asyncio.create_task(_pull())
        return web.json_response(
            {"path": rel, "syncing": True,
             "service": statedir.sync_service_hint(workspace)},
            status=202,
        )
    if target.stat().st_size > _daemon_ns.MAX_FILE_BYTES:
        return web.json_response({"error": "file too large"}, status=413)
    try:
        content = await asyncio.to_thread(target.read_text, encoding="utf-8")
    except UnicodeDecodeError:
        return web.json_response({"error": "binary file"}, status=415)
    # rel may be wiki/-prefixed or wiki-relative; normalise to the
    # workspace-relative form that file_state stores.
    norm_rel = rel if rel.startswith("wiki/") else f"wiki/{rel}"
    _daemon_ns._check_external_edit(request.app, norm_rel)
    return web.json_response({"path": rel, "content": content})

async def handle_fs_stat(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    rel = request.query.get("path", "")
    try:
        return web.json_response(fileops.stat(workspace, rel))
    except fileops.FileOpError as e:
        return web.json_response({"error": str(e)}, status=400)

async def handle_fs_delete(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    rel = str(body.get("path", ""))
    try:
        # Off-thread: trash goes through a subprocess (`trash`/`gio`)
        # and a possible cross-volume move — never on the loop.
        trashed_to = await asyncio.to_thread(fileops.delete, workspace, rel)
        await asyncio.to_thread(file_state.delete_record, workspace, rel)
        if rel.startswith("wiki/"):
            # Wiki browser reads the in-memory graph bundle, not the
            # FS. Prune the gone page before files_changed so the
            # refetch does not wait on kuzu/viewer.sh.
            ws_key = str(workspace.resolve())
            cached = (request.app.get("graph_data_per_ws") or {}).get(ws_key)
            if isinstance(cached, dict):
                await asyncio.to_thread(
                    wiki_sync.inject_on_disk_pages, workspace, cached,
                )
            asyncio.create_task(_refresh_graph_cache(request.app, ws_key))
        _daemon_ns._log_event(
            request.app, "file_delete", f"deleted {rel} → {trashed_to}",
            source="fileops", actor="user",
            payload={"path": rel, "trashed_to": trashed_to},
        )
        await _daemon_ns._broadcast(request.app, protocol.files_changed())
        return web.json_response({"ok": True, "trashed_to": trashed_to})
    except fileops.FileOpError as e:
        return web.json_response({"error": str(e)}, status=400)

async def handle_fs_duplicate(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    src = str(body.get("path", ""))
    try:
        new_rel = fileops.duplicate(workspace, src)
        file_state.record_internal_write(workspace, new_rel, owner="fileops")
        _daemon_ns._log_event(
            request.app, "file_edit_internal", f"duplicated {src} → {new_rel}",
            source="fileops", actor="user",
            payload={"src": src, "dst": new_rel},
        )
        await _daemon_ns._broadcast(request.app, protocol.files_changed())
        return web.json_response({"ok": True, "path": new_rel})
    except fileops.FileOpError as e:
        return web.json_response({"error": str(e)}, status=400)

async def handle_fs_reveal(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    try:
        await fileops.reveal(workspace, str(body.get("path", "")))
        return web.json_response({"ok": True})
    except fileops.FileOpError as e:
        return web.json_response({"error": str(e)}, status=400)

async def handle_fs_open_external(request: web.Request) -> web.Response:
    """Hand the file off to the OS default app. Used by the file
    browser's right-click "Open" item for vault sources the user
    wants in Preview / Word / their image viewer rather than in a
    switchbay tab."""
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    try:
        await fileops.open_external(workspace, str(body.get("path", "")))
        return web.json_response({"ok": True})
    except fileops.FileOpError as e:
        return web.json_response({"error": str(e)}, status=400)

# ── Workspace registry ───────────────────────────────────────────────


def _hello_payload(app: web.Application) -> dict:
    workspace: Path = app["workspace"]
    from switchbay import web_policy as web_policy_mod
    return protocol.hello(
        workspace=str(workspace),
        default_file=_daemon_ns._pick_default_file(workspace),
        mode=_daemon_ns._compose_mode(workspace),
        selection=selection.load(workspace),
        workspaces=workspaces.load(),
        thread_id=app.get("thread_id"),
        web_policy=web_policy_mod.public_view(workspace),
    )

async def _enrich_graph_cache(app: web.Application, ws_key: str) -> None:
    """Background filesystem-truth enrich of an already-served graph.

    Runs inject_deck / inject_on_disk_pages off the request path
    with ``graph_progress`` stages so the UI never whites out on a
    large vault. Deduped per workspace via
    ``app["graph_enrich_inflight"]``.
    """
    from pathlib import Path as _Path
    inflight: set[str] = app.setdefault("graph_enrich_inflight", set())
    if ws_key in inflight:
        return
    inflight.add(ws_key)
    workspace = _Path(ws_key)
    try:
        # Fresh json-only load so we don't deepcopy a multi-10MB
        # in-memory bundle (BioCure ~51MB) and so the served snapshot
        # stays untouched until we swap the cache at the end.
        data = await asyncio.to_thread(
            cebridge.read_cached, workspace, enrich=False,
        )
        if data is None:
            await _daemon_ns._broadcast(app, protocol.graph_progress(
                "ready", "Graph ready", workspace=ws_key, done=True,
            ))
            return

        await _daemon_ns._broadcast(app, protocol.graph_progress(
            "decks", "Refreshing deck nodes…", workspace=ws_key,
        ))
        decks_n = await asyncio.to_thread(
            cebridge.inject_deck_nodes, workspace, data,
        )
        await _daemon_ns._broadcast(app, protocol.graph_progress(
            "decks",
            f"Refreshing deck nodes… ({int(decks_n or 0)} added)",
            workspace=ws_key, current=int(decks_n or 0),
        ))

        await _daemon_ns._broadcast(app, protocol.graph_progress(
            "pages", "Refreshing links…", workspace=ws_key,
        ))
        pages_n = await asyncio.to_thread(
            wiki_sync.inject_on_disk_pages, workspace, data,
        )
        await _daemon_ns._broadcast(app, protocol.graph_progress(
            "pages",
            f"Refreshing links… ({int(pages_n or 0)} updates)",
            workspace=ws_key, current=int(pages_n or 0),
        ))

        _daemon_ns._put_graph_cache(app, ws_key, data)
        app.setdefault("graph_enriched_ws", set()).add(ws_key)
        await _daemon_ns._broadcast(app, protocol.graph_progress(
            "ready", "Graph ready", workspace=ws_key, done=True,
        ))
        # Only bump files_changed when something actually moved —
        # otherwise every prefetch would remount the graph.
        if int(decks_n or 0) or int(pages_n or 0):
            await _daemon_ns._broadcast(app, protocol.files_changed())
    except Exception:  # noqa: BLE001
        log.exception("background graph enrich failed for %s", ws_key)
        try:
            await _daemon_ns._broadcast(app, protocol.graph_progress(
                "ready", "Graph sync failed (showing cache)",
                workspace=ws_key, done=True,
            ))
        except Exception:  # noqa: BLE001
            pass
    finally:
        inflight.discard(ws_key)

async def _refresh_graph_cache(app: web.Application, ws_key: str) -> None:
    """Background rebuild of the per-workspace graph cache. Fires
    after a stale-while-revalidate hit on /api/graph/data so the
    next fetch returns the fresh data.json. Broadcasts a
    `files_changed` so any connected client re-fetches.

    Deduped per workspace. This is the heavy path (venv + kuzu +
    viewer.sh); prefer ``_enrich_graph_cache`` for fast FS truth.
    """
    from pathlib import Path as _Path
    inflight: set[str] = app.setdefault("graph_rebuild_inflight", set())
    if ws_key in inflight:
        return
    inflight.add(ws_key)
    workspace = _Path(ws_key)
    try:
        try:
            await cebridge.ensure_venv(workspace)
            await cebridge.graph_rebuild(workspace)
        except Exception:  # noqa: BLE001
            log.exception("background kuzu rebuild failed for %s", ws_key)
        fresh = await cebridge.build(workspace)
        if fresh is None:
            return
        _daemon_ns._put_graph_cache(app, ws_key, fresh)
        app.setdefault("graph_enriched_ws", set()).add(ws_key)
        await _daemon_ns._broadcast(app, protocol.files_changed())
        await _daemon_ns._broadcast(app, protocol.graph_progress(
            "ready", "Graph ready", workspace=ws_key, done=True,
        ))
    finally:
        inflight.discard(ws_key)
