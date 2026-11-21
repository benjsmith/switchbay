"""Graph JSON cache, curation history, and the hello payload.

Split out of switchbay.daemon so this concept has its own module.
The daemon re-exports every name; tests that monkeypatch
switchbay.daemon still apply, because patched helpers are read
back through _daemon_ns at call time.

Run: python -m switchbay serve --workspace PATH
"""
from __future__ import annotations

from pathlib import Path
import asyncio
from aiohttp import web
from switchbay import cebridge
from switchbay import curation_history
from switchbay import protocol
from switchbay import wiki_sync
from switchbay import workspaces

from switchbay.httpapi._ns import _daemon_ns

async def handle_curation_history(request: web.Request) -> web.Response:
    """Return the replayable curation timeline for the opening graph
    animation. Cached under <ws>/.workbench/curation-history.json;
    rebuilds in-line when the cache is missing. Cheap on the hot
    path (cache hit is a single file read)."""
    qpath = request.query.get("workspace", "").strip()
    if qpath:
        target = Path(qpath).expanduser().resolve()
        if not target.is_dir() or not workspaces.is_within_home(target):
            return web.json_response({"error": "invalid workspace"}, status=400)
        ws = target
    else:
        ws = request.app["workspace"]
    data = await curation_history.read_or_build(ws)
    if data is None:
        return web.json_response(
            {"duration": 15.0, "events": [], "source": "missing"},
        )
    return web.json_response(data)

def _put_graph_cache(app: web.Application, ws_key: str, data: dict) -> None:
    """Store a slimmed graph bundle and drop old workspaces.

    Full page HTML does not belong here (use /api/page). Unbounded
    per-workspace copies of data.json were a plausible path to
    multi-GB RSS on a long-lived daemon.
    """
    wiki_sync.slim_graph_payload(data)
    cache: dict[str, dict] = app.setdefault("graph_data_per_ws", {})
    cache.pop(ws_key, None)
    cache[ws_key] = data
    overflow = len(cache) - _daemon_ns._GRAPH_WS_CAP
    if overflow > 0:
        for k in list(cache)[:overflow]:
            cache.pop(k, None)
    if str(app.get("workspace") and Path(app["workspace"]).resolve()) == ws_key:
        app["graph_data"] = data

async def handle_graph_data(request: web.Request) -> web.Response:
    """Return the workspace's data.json — stale-while-revalidate.

    Order of preference (fastest to slowest):
      1. In-memory cache from a previous build / read in this
         daemon process (`app["graph_data_per_ws"]`).
      2. On-disk data.json from a *previous* viewer.sh build —
         possibly stale, but loads in milliseconds (json only —
         no wiki FS walks on the request path).
      3. Synchronous viewer.sh build — only when neither cache hit.

    Disk-truth enrichment (resync types / inject decks / inject
    on-disk pages) and the heavier kuzu+viewer rebuild both run
    in background tasks. Progress is broadcast as ``graph_progress``;
    when enrich finishes the cache is updated and ``files_changed``
    tells the frontend to re-fetch. Large vaults (tens of thousands
    of pages) must never wedge the PWA on first paint.
    """
    # Optional `?workspace=<abs-path>` arg lets the client warm
    # another workspace's cache without changing app["workspace"].
    # The WorkspaceSwitcher's hover-prefetch uses this so a click
    # finds the data already hot.
    qpath = request.query.get("workspace", "").strip()
    if qpath:
        target = Path(qpath).expanduser().resolve()
        if not target.is_dir() or not workspaces.is_within_home(target):
            return web.json_response({"error": "invalid workspace"}, status=400)
        workspace: Path = target
    else:
        workspace = request.app["workspace"]
    ws_key = str(workspace.resolve())
    cache: dict[str, dict] = request.app.setdefault("graph_data_per_ws", {})
    cached = cache.get(ws_key)
    enriched: set[str] = request.app.setdefault("graph_enriched_ws", set())
    served_from_disk = False
    if cached is None:
        # Hot path: json.load only. enrich=False — FS walks are minutes
        # on a 29k-page vault and must not block the response.
        await _daemon_ns._broadcast(request.app, protocol.graph_progress(
            "cache", "Loading graph from cache…", workspace=ws_key,
        ))
        cached = await asyncio.to_thread(
            cebridge.read_cached, workspace, enrich=False,
        )
        if cached is not None:
            _put_graph_cache(request.app, ws_key, cached)
            enriched.discard(ws_key)  # needs background enrich
            served_from_disk = True
    if cached is None:
        # First time we've ever seen this workspace, no on-disk
        # build either — synchronous build is unavoidable.
        await _daemon_ns._broadcast(request.app, protocol.graph_progress(
            "build", "Building graph (viewer.sh)…", workspace=ws_key,
        ))
        cached = await cebridge.build(workspace)
        if cached is None:
            await _daemon_ns._broadcast(request.app, protocol.graph_progress(
                "ready", "Graph unavailable", workspace=ws_key, done=True,
            ))
            return web.json_response(
                {"error": "no wiki/ in workspace, or viewer.sh build failed"},
                status=404,
            )
        _put_graph_cache(request.app, ws_key, cached)
        enriched.add(ws_key)  # build() already ran enrich_from_disk
        await _daemon_ns._broadcast(request.app, protocol.graph_progress(
            "ready", "Graph ready", workspace=ws_key, done=True,
        ))
    else:
        # Serve immediately. Enrich at most once per cold disk load
        # (deduped); full rebuild only when we just hydrated from disk.
        if ws_key not in enriched:
            asyncio.create_task(_daemon_ns._enrich_graph_cache(request.app, ws_key))
        if served_from_disk:
            # Stale-while-revalidate: also kick the heavier rebuild so
            # kuzu edges catch up eventually. Enrich finishes first
            # and paints a fresher node set; rebuild may take longer.
            asyncio.create_task(_daemon_ns._refresh_graph_cache(request.app, ws_key))
    cached = request.app.get("graph_data_per_ws", {}).get(ws_key) or cached
    return web.json_response(cached)

async def handle_graph_rebuild(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    data = await cebridge.build(workspace)
    if data is None:
        return web.json_response(
            {"error": "viewer.sh build failed"}, status=500
        )
    _put_graph_cache(request.app, str(workspace.resolve()), data)
    _daemon_ns._log_event(
        request.app, "curation",
        f"manual graph rebuild (pages={len(data.get('pages') or {})})",
        source="cebridge", actor="user",
        payload={"trigger": "manual"},
    )
    return web.json_response(data)
