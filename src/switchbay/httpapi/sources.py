"""Vault source list, reveal, open, and hydrate routes.

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
import os
import sys
from aiohttp import web
from switchbay import sources
from switchbay import statedir

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

async def handle_sources_list(request: web.Request) -> web.Response:
    """The Browser column's Sources view (D1): every EXTERNAL
    `extracted_from` provenance path across the wiki, with the pages
    each one backs. In-workspace provenance folds into the vault view
    (only its count is returned, for the honest empty state)."""
    workspace: Path = request.app["workspace"]
    data = await asyncio.to_thread(sources.scan, workspace)
    # Remember what the scan saw — the allowlist for reveal/open on
    # external paths below (keyed by workspace so switches don't leak).
    request.app["sources_known"] = {
        "workspace": str(workspace),
        "paths": sources.known_paths(data),
    }
    return web.json_response(data)

async def _sources_validated_path(request: web.Request) -> Path | None:
    """Resolve + validate the {path} body of a sources reveal/open
    call. External paths are only ever touched when the CURRENT scan
    lists them as provenance — re-scanning when the cache is cold/
    stale — so these endpoints can't be aimed at arbitrary files."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return None
    raw = str(body.get("path") or "").strip()
    if not raw:
        return None
    workspace: Path = request.app["workspace"]
    cache = request.app.get("sources_known")
    if not cache or cache.get("workspace") != str(workspace):
        data = await asyncio.to_thread(sources.scan, workspace)
        cache = {
            "workspace": str(workspace),
            "paths": sources.known_paths(data),
        }
        request.app["sources_known"] = cache
    # Accept both the scan's resolved form and the raw frontmatter
    # form (`~/x.pdf`, symlinked ancestors) — the chip sends whatever
    # the page recorded.
    q = Path(os.path.expanduser(raw))
    if not q.is_absolute():
        return None  # in-workspace paths use the workspace-scoped fs endpoints
    try:
        q = q.resolve()
    except OSError:
        pass
    if str(q) not in cache["paths"]:
        return None
    return q

async def handle_sources_reveal(request: web.Request) -> web.Response:
    """Reveal an external source file in the OS file manager."""
    target = await _sources_validated_path(request)
    if target is None:
        return web.json_response(
            {"error": "not a known source path"}, status=400,
        )
    if sys.platform == "darwin":
        argv = ["open", "-R", str(target)]
    elif sys.platform == "win32":
        argv = ["explorer", "/select,", str(target)]
    else:
        argv = ["xdg-open", str(target.parent)]
    proc = await asyncio.create_subprocess_exec(*argv)
    await proc.wait()
    return web.json_response({"ok": True})

async def handle_sources_open(request: web.Request) -> web.Response:
    """Open an external source file with the OS default app — the
    provenance chip's "open original"."""
    target = await _sources_validated_path(request)
    if target is None:
        return web.json_response(
            {"error": "not a known source path"}, status=400,
        )
    if sys.platform == "darwin":
        argv = ["open", str(target)]
    elif sys.platform == "win32":
        argv = ["cmd", "/c", "start", "", str(target)]
    else:
        argv = ["xdg-open", str(target)]
    proc = await asyncio.create_subprocess_exec(*argv)
    await proc.wait()
    return web.json_response({"ok": True})

async def handle_fs_hydrate(request: web.Request) -> web.Response:
    """Kick off a background hydration of a cloud-sync placeholder so a
    subsequent read is warm. Returns immediately — the actual download
    runs off-thread. Body: {path} (workspace-relative)."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    workspace: Path = request.app["workspace"]
    rel = str(body.get("path", "")).strip()
    target = _daemon_ns._safe_resolve(workspace, rel)
    if target is None or not target.exists():
        return web.json_response({"error": "no such path"}, status=404)
    dataless = statedir.is_dataless(target)
    if dataless:
        # Reading the bytes is what forces the sync service to hydrate.
        # Fire-and-forget on a thread so this request doesn't block.
        async def _pull() -> None:
            try:
                await asyncio.to_thread(target.read_bytes)
            except Exception:  # noqa: BLE001
                log.exception("hydration read failed for %s", target)
        asyncio.create_task(_pull())
    return web.json_response({"syncing": dataless})
