"""Open/switch workspace and database introspect routes.

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
import os
import sqlite3
from aiohttp import web
from switchbay import app_settings
from switchbay import cebridge
from switchbay import dbintrospect
from switchbay import share
from switchbay import workspaces

from switchbay.httpapi._ns import _daemon_ns

async def handle_workspaces_get(request: web.Request) -> web.Response:
    return web.json_response({
        **workspaces.load(),
        "archived": workspaces.load_archived(),
    })

async def handle_workspaces_add(request: web.Request) -> web.Response:
    """Register a directory as a workspace, optionally running CE setup.sh.

    Body: {path, init?: bool}. If `init` is true (or the directory has no
    `wiki/` yet) we run CE's setup.sh against it before registering.
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    raw = str(body.get("path", "")).strip()
    if not raw:
        return web.json_response({"error": "missing path"}, status=400)
    if share.looks_like_repo_ref(raw):
        # D3 install path: a GitHub URL / owner-repo shorthand clones
        # into the workspaces home, then registers like any folder.
        dest = app_settings.workspaces_home_path() / share.repo_dir_name(raw)
        try:
            await share.clone(raw, dest)
        except share.ShareError as e:
            return web.json_response({"error": str(e)}, status=400)
        _daemon_ns._log_event(
            request.app, "exec", f"workspace cloned: {raw} → {dest}",
            source="share", actor="user",
            payload={"ref": raw, "dest": str(dest)},
        )
        raw = str(dest)
    path = Path(raw).expanduser()
    if not path.is_absolute():
        return web.json_response({"error": "path must be absolute"}, status=400)
    if not path.is_dir():
        return web.json_response({"error": "path is not a directory"}, status=400)
    if not workspaces.is_within_home(path):
        return web.json_response(
            {"error": f"workspaces must live inside {workspaces.home_label()}"},
            status=400,
        )
    if not os.access(path, os.W_OK):
        return web.json_response(
            {"error": "path is not writable by the current user"}, status=400
        )
    from switchbay.federation.boundary import TrustBoundaryError, require
    try:
        require(path)
    except TrustBoundaryError as exc:
        return web.json_response({"error": str(exc)}, status=400)

    needs_init = bool(body.get("init")) or not (path / "wiki").is_dir()
    if needs_init:
        ok, output = await cebridge.setup(path)
        if not ok:
            return web.json_response(
                {"error": "setup.sh failed", "detail": output}, status=500
            )

    await _daemon_ns._activate(request.app, path)
    return web.json_response({"ok": True, "workspaces": workspaces.load()})

async def handle_workspaces_switch(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    raw = str(body.get("path", "")).strip()
    path = Path(raw).expanduser()
    if not path.is_absolute() or not path.is_dir():
        return web.json_response({"error": "invalid workspace path"}, status=400)
    if not workspaces.is_within_home(path):
        return web.json_response(
            {"error": f"workspaces must live inside {workspaces.home_label()}"},
            status=400,
        )
    if not os.access(path, os.W_OK):
        return web.json_response(
            {"error": "path is not writable by the current user"}, status=400
        )
    from switchbay.federation.boundary import TrustBoundaryError, require
    try:
        require(path)
    except TrustBoundaryError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    await _daemon_ns._activate(request.app, path)
    return web.json_response({"ok": True, "workspaces": workspaces.load()})

async def handle_db_introspect(request: web.Request) -> web.Response:
    """List tables/views in a workspace SQLite file. Used by the Table
    tab when DuckDB-WASM's sqlite extension can't ATTACH the file
    cleanly (vec0 / fts5 / similar)."""
    workspace: Path = request.app["workspace"]
    rel = request.query.get("path", "")
    target = _daemon_ns._safe_resolve(workspace, rel)
    if target is None or not target.is_file():
        return web.json_response({"error": "not found"}, status=404)
    try:
        # sqlite open + schema query — off-thread so the Table tab's
        # introspect can't block the loop (sqlite I/O + iCloud reads).
        result = await asyncio.to_thread(dbintrospect.introspect, target)
        return web.json_response(result)
    except (sqlite3.DatabaseError, sqlite3.OperationalError, OSError) as e:
        return web.json_response({"error": str(e)}, status=400)

async def handle_db_query(request: web.Request) -> web.Response:
    """Run a read-only SQL query against a workspace SQLite file via the
    daemon's stock `sqlite3` (no extension loading required). The
    fallback path for DBs that DuckDB-WASM can't query."""
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    rel = str(body.get("path", ""))
    sql = str(body.get("sql", "")).strip()
    if not sql:
        return web.json_response({"error": "sql required"}, status=400)
    target = _daemon_ns._safe_resolve(workspace, rel)
    if target is None or not target.is_file():
        return web.json_response({"error": "not found"}, status=404)
    try:
        result = await asyncio.to_thread(dbintrospect.run_query, target, sql)
        # Compact summary for the rail log: first ~80 chars of the SQL
        # plus the row count so recall_rail surfaces meaningful hits.
        snippet = sql[:80].replace("\n", " ")
        n = len(result.get("rows") or [])
        _daemon_ns._log_event(
            request.app, "sql",
            f"{rel}: {snippet} → {n} row{'s' if n != 1 else ''}",
            source="duckdb", actor="user",
            payload={"path": rel, "sql": sql, "rows": n},
        )
        return web.json_response(result)
    except (sqlite3.DatabaseError, sqlite3.OperationalError, OSError) as e:
        return web.json_response({"error": str(e)}, status=400)
