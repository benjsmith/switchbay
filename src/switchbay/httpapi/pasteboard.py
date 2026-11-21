"""Rail pasteboard slots.

Split out of switchbay.daemon so this concept has its own module.
The daemon re-exports every name; tests that monkeypatch
switchbay.daemon still apply, because patched helpers are read
back through _daemon_ns at call time.

Run: python -m switchbay serve --workspace PATH
"""
from __future__ import annotations

from pathlib import Path
import json
from aiohttp import web
from switchbay import pasteboard

async def handle_pasteboard_list(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    return web.json_response({"slots": pasteboard.list_slots(workspace)})

async def handle_pasteboard_get(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    sid = request.query.get("id", "").strip()
    if not sid:
        return web.json_response({"error": "id required"}, status=400)
    slot = pasteboard.get_slot(workspace, sid)
    if slot is None:
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response({"slot": slot})

async def handle_pasteboard_add(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    kind = str(body.get("kind") or "text")
    content = body.get("content")
    image_b64 = body.get("image_b64")
    try:
        slot = pasteboard.add_slot(
            workspace,
            content=content if isinstance(content, str) else None,
            image_b64=image_b64 if isinstance(image_b64, str) else None,
            kind=kind,
        )
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({"slot": slot})

async def handle_pasteboard_image(request: web.Request) -> web.StreamResponse:
    """Stream the PNG bytes for an image slot. Used by the pasteboard
    popover to render thumbnails inline."""
    workspace: Path = request.app["workspace"]
    sid = request.query.get("id", "").strip()
    if not sid:
        return web.json_response({"error": "id required"}, status=400)
    payload = pasteboard.image_bytes(workspace, sid)
    if payload is None:
        return web.json_response({"error": "not found"}, status=404)
    return web.Response(body=payload, content_type="image/png")

async def handle_pasteboard_delete(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    sid = request.query.get("id", "").strip()
    if not sid:
        return web.json_response({"error": "id required"}, status=400)
    return web.json_response({"ok": pasteboard.remove_slot(workspace, sid)})

async def handle_pasteboard_clear(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    return web.json_response({"removed": pasteboard.clear(workspace)})
