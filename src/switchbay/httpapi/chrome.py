"""User tabs, action buttons, and project summary routes.

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
from switchbay import action_buttons
from switchbay import projects
from switchbay import protocol
from switchbay import tabstore

from switchbay.httpapi._ns import _daemon_ns

async def handle_user_tabs_list(request: web.Request) -> web.Response:
    """List user-source tabs (anything in mode.json that isn't a
    core default and isn't pack-contributed). Frontend Settings
    renders an ACTIVE / INACTIVE pill per row, mirroring packs."""
    workspace: Path = request.app["workspace"]
    return web.json_response({"tabs": tabstore.list_user_tabs(workspace)})

async def handle_user_tabs_toggle(request: web.Request) -> web.Response:
    """Soft enable/disable one user tab. Body: `{id, enabled}`."""
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    tid = str(body.get("id") or "").strip()
    enabled = bool(body.get("enabled"))
    if not tid:
        return web.json_response({"error": "id required"}, status=400)
    tabstore.set_enabled(workspace, tid, enabled)
    await _daemon_ns._broadcast(request.app, protocol.files_changed())
    return web.json_response({"ok": True})

async def handle_action_buttons_list(request: web.Request) -> web.Response:
    return web.json_response({"buttons": action_buttons.load()})

async def handle_action_buttons_add(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    try:
        rec = action_buttons.add(
            str(body.get("label") or ""),
            str(body.get("command") or ""),
        )
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({"button": rec, "buttons": action_buttons.load()})

async def handle_action_buttons_delete(request: web.Request) -> web.Response:
    bid = request.query.get("id", "").strip()
    if not bid:
        return web.json_response({"error": "id required"}, status=400)
    ok = action_buttons.remove(bid)
    return web.json_response({"ok": ok, "buttons": action_buttons.load()})

async def handle_projects_list(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    # _index_pages rglob's the wiki reading frontmatter — off-thread.
    listed = await asyncio.to_thread(projects.list_projects, workspace)
    return web.json_response(listed)

async def handle_projects_detail(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    name = request.match_info.get("name", "").strip()
    if not name:
        return web.json_response({"error": "name required"}, status=400)
    detail = await asyncio.to_thread(projects.project_detail, workspace, name)
    if detail is None:
        return web.json_response(
            {"error": f"unknown project: {name}"}, status=404
        )
    return web.json_response(detail)
