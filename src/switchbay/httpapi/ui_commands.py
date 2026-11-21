"""Shared UI acknowledgements and table/CSV commands.

Split out of switchbay.daemon so this concept has its own module.
The daemon re-exports every name; tests that monkeypatch
switchbay.daemon still apply, because patched helpers are read
back through _daemon_ns at call time.

Run: python -m switchbay serve --workspace PATH
"""
from __future__ import annotations

import asyncio
import json
import uuid
from aiohttp import web
from switchbay import protocol
from switchbay import sheet_focus
from switchbay import ui_focus

from switchbay.httpapi._ns import _daemon_ns

async def handle_ui_focus_get(request: web.Request) -> web.Response:
    """Live focus for a tab surface: table | plot | sketch (sheet uses
    /api/sheet/focus). Query: ?surface=table"""
    ws = _daemon_ns._workspace_from_request(request)
    if isinstance(ws, web.Response):
        return ws
    surface = str(request.rel_url.query.get("surface") or "").strip()
    if not surface:
        return web.json_response({"error": "`surface` query required"}, status=400)
    if surface == "sheet":
        focus = await asyncio.to_thread(sheet_focus.load, ws)
    else:
        try:
            focus = await asyncio.to_thread(ui_focus.load, ws, surface)
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
    return web.json_response({
        "surface": surface, "focus": focus, "workspace": str(ws),
    })

async def handle_ui_focus_post(request: web.Request) -> web.Response:
    """Frontend publishes live focus for table | plot | sketch."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "body must be an object"}, status=400)
    ws = _daemon_ns._workspace_from_request(request, body)
    if isinstance(ws, web.Response):
        return ws
    surface = str(body.get("surface") or "").strip()
    if not surface:
        return web.json_response({"error": "`surface` is required"}, status=400)
    if surface == "sheet":
        # Accept sheet via this endpoint too; normalise through sheet_focus.
        saved = await asyncio.to_thread(sheet_focus.save, ws, body)
        return web.json_response({
            "ok": True, "surface": surface, "focus": saved, "workspace": str(ws),
        })
    try:
        saved = await asyncio.to_thread(ui_focus.save, ws, surface, body)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({
        "ok": True, "surface": surface, "focus": saved, "workspace": str(ws),
    })

async def handle_table_command(request: web.Request) -> web.Response:
    """Agent → Table tab. Same pipe as rail `!sql`.

    Body: {op: "run_sql", sql: "SELECT …", wait_ack?: true}
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "body must be an object"}, status=400)
    ws = _daemon_ns._workspace_from_request(request, body)
    if isinstance(ws, web.Response):
        return ws
    op = str(body.get("op") or "").strip()
    if op != "run_sql":
        return web.json_response(
            {"error": f"unknown op {op!r}; expected run_sql"}, status=400)
    sql = str(body.get("sql") or body.get("query") or "").strip()
    if not sql:
        return web.json_response({"error": "`sql` is required"}, status=400)
    wait_ack = bool(body.get("wait_ack"))
    command_id = uuid.uuid4().hex if wait_ack else None
    fut = _daemon_ns._register_ui_ack(request.app, command_id) if command_id else None
    await _daemon_ns._broadcast(request.app, protocol.custom({
        "type": "sql.run",
        "query": sql,
        "command_id": command_id,
        "workspace": str(ws),
    }))
    # Optimistic focus so table_context sees the new query immediately.
    prev = await asyncio.to_thread(ui_focus.load, ws, "table") or {}
    prev.update({"sql": sql, "query": sql})
    await asyncio.to_thread(ui_focus.save, ws, "table", prev)
    if not wait_ack or fut is None or command_id is None:
        return web.json_response({
            "ok": True,
            "op": "run_sql",
            "sql": sql,
            "workspace": str(ws),
            "note": (
                "SQL dispatched to the Table tab (same path as !sql). "
                "The editor is filled and the query runs."
            ),
        })
    ack = await _daemon_ns._wait_ui_ack(request.app, command_id, fut)
    if ack.get("timeout") or not ack.get("ok"):
        return web.json_response({
            "ok": False,
            "error": ack.get("error") or "Table SQL run failed",
            "command_id": command_id,
            "sql": sql,
            "workspace": str(ws),
        }, status=504 if ack.get("timeout") else 422)
    return web.json_response({
        "ok": True,
        "op": "run_sql",
        "sql": sql,
        "applied": True,
        "command_id": command_id,
        "workspace": str(ws),
        "result": ack.get("result"),
        "note": "SQL ran in the Table tab.",
    })
