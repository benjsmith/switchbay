"""Sheet documents, focus, and sheet commands.

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
import json
import uuid
from aiohttp import web
from switchbay import protocol
from switchbay import sheet_focus
from switchbay import sheets
from switchbay import workspaces

from switchbay.httpapi._ns import _daemon_ns

_MISSING = object()

def _workspace_from_request(
    request: web.Request,
    body: dict[str, Any] | None = None,
) -> Path | web.Response:
    """Resolve workspace for live-tab HTTP.

    Order: JSON body ``workspace`` → query ``workspace`` → header
    ``X-Switchbay-Workspace`` → daemon active workspace.
    Returns a Path, or a ready-made error Response.
    """
    candidates: list[str] = []
    if isinstance(body, dict):
        w = body.get("workspace")
        if w is not None and str(w).strip():
            candidates.append(str(w).strip())
    q = str(request.rel_url.query.get("workspace") or "").strip()
    if q:
        candidates.append(q)
    hdr = (
        request.headers.get("X-Switchbay-Workspace")
        or request.headers.get("X-Workspace")
        or ""
    ).strip()
    if hdr:
        candidates.append(hdr)
    default: Path = request.app["workspace"]
    if not candidates:
        return default
    try:
        return workspaces.resolve_path(candidates[0], default=default)
    except workspaces.OutsideHomeError as e:
        return web.json_response({"error": str(e)}, status=400)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)

async def handle_sheet_get(request: web.Request) -> web.Response:
    ws = _workspace_from_request(request)
    if isinstance(ws, web.Response):
        return ws
    # Off-thread: a large Univer workbook JSON parse (multi-MB) must not
    # block the event loop.
    snap = await asyncio.to_thread(sheets.load, ws)
    return web.json_response({"snapshot": snap})

async def handle_sheet_post(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "body must be an object"}, status=400)
    ws = _workspace_from_request(request, body)
    if isinstance(ws, web.Response):
        return ws
    snap = body.get("snapshot")
    if not isinstance(snap, dict):
        return web.json_response({"error": "snapshot must be an object"}, status=400)
    # Off-thread: serializing + writing a large workbook can be slow.
    await asyncio.to_thread(sheets.save, ws, snap)
    return web.json_response({"ok": True, "workspace": str(ws)})

async def handle_sheet_focus_get(request: web.Request) -> web.Response:
    """Live Sheet tab focus + value preview (published by SheetTab)."""
    ws = _workspace_from_request(request)
    if isinstance(ws, web.Response):
        return ws
    focus = await asyncio.to_thread(sheet_focus.load, ws)
    return web.json_response({"focus": focus, "workspace": str(ws)})

async def handle_sheet_focus_post(request: web.Request) -> web.Response:
    """Frontend publishes active cell + compact preview for the agent."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "body must be an object"}, status=400)
    ws = _workspace_from_request(request, body)
    if isinstance(ws, web.Response):
        return ws
    saved = await asyncio.to_thread(sheet_focus.save, ws, body)
    return web.json_response({"ok": True, "focus": saved, "workspace": str(ws)})

def _ui_ack_futures(app: web.Application) -> dict[str, asyncio.Future]:
    """Pending agent wait_ack futures keyed by command_id (all surfaces)."""
    return app.setdefault("ui_cmd_acks", {})

def _register_ui_ack(app: web.Application, command_id: str) -> asyncio.Future:
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    _ui_ack_futures(app)[command_id] = fut
    return fut

async def _wait_ui_ack(
    app: web.Application,
    command_id: str,
    fut: asyncio.Future,
    *,
    timeout: float = _MISSING,
) -> dict[str, Any]:
    if timeout is _MISSING:
        timeout = _daemon_ns._UI_ACK_TIMEOUT_S
    try:
        return await asyncio.wait_for(fut, timeout=timeout)
    except asyncio.TimeoutError:
        _ui_ack_futures(app).pop(command_id, None)
        return {
            "ok": False,
            "error": (
                f"UI did not confirm within {int(timeout)}s — open the "
                "target tab and retry"
            ),
            "timeout": True,
        }

async def handle_ui_command_ack(request: web.Request) -> web.Response:
    """Browser reports live-tab command result (sheet/table/plot/sketch).

    Body: {command_id, ok, error?, label?, durable?, surface?, …}
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "body must be an object"}, status=400)
    cid = str(body.get("command_id") or "").strip()
    if not cid:
        return web.json_response({"error": "command_id required"}, status=400)
    futs = _ui_ack_futures(request.app)
    fut = futs.pop(cid, None)
    if fut is None or fut.done():
        return web.json_response({"ok": True, "late": True})
    fut.set_result({
        "ok": bool(body.get("ok")),
        "error": body.get("error"),
        "label": body.get("label"),
        "durable": bool(body.get("durable")),
        "writes": body.get("writes"),
        "applied": body.get("applied"),
        "surface": body.get("surface"),
        "result": body.get("result"),
    })
    return web.json_response({"ok": True})

async def handle_sheet_command_ack(request: web.Request) -> web.Response:
    """Alias of /api/ui/command-ack (kept for existing Sheet clients)."""
    return await handle_ui_command_ack(request)

async def handle_sheet_command(request: web.Request) -> web.Response:
    """Agent tools drive Sheet UI via the same pipe as rail `!fn`.

    Body shapes:
      {op: "select", range: "H18"|"C2:H2"}
      {op: "set_formula", formula: "=AVERAGE(C2:C17)", cell?: "C18"}
      {op: "set_formula", writes: [{cell, formula}, …], wait_ack?: true}
      {op: "set_values", values: [[headers…], [row…], …], origin?: str}

    When ``wait_ack`` is true (agent tools), the response blocks until
    the Sheet tab ACKs apply + durable save, or times out — never a
    silent false-success.
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "body must be an object"}, status=400)
    ws = _workspace_from_request(request, body)
    if isinstance(ws, web.Response):
        return ws
    op = str(body.get("op") or "").strip()
    wait_ack = bool(body.get("wait_ack"))

    if op == "select":
        rng = str(body.get("range") or "").strip().upper()
        if not rng:
            return web.json_response({"error": "`range` is required"}, status=400)
        try:
            sheet_focus.parse_a1_range(rng)
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        await _daemon_ns._broadcast(request.app, protocol.custom({
            "type": "sheet.select",
            "range": rng,
            "workspace": str(ws),
        }))
        # Optimistic focus update so the next sheet_context sees the target
        # even before the browser re-publishes.
        prev = await asyncio.to_thread(sheet_focus.load, ws) or {}
        cell = rng.split(":")[0]
        prev.update({"a1": cell, "range": rng})
        await asyncio.to_thread(sheet_focus.save, ws, prev)
        return web.json_response({
            "ok": True, "op": "select", "range": rng, "workspace": str(ws),
        })

    if op == "set_formula":
        writes_raw = body.get("writes")
        if writes_raw is None:
            formula = str(body.get("formula") or "").strip()
            cell = str(body.get("cell") or "").strip().upper()
            if not formula:
                return web.json_response(
                    {"error": "`formula` or `writes` is required"}, status=400)
            if not cell:
                focus = await asyncio.to_thread(sheet_focus.load, ws)
                cell = str((focus or {}).get("a1") or "").strip().upper()
            if not cell:
                return web.json_response({
                    "error": (
                        "no target cell — pass `cell` or click a sheet "
                        "cell so focus is published"
                    ),
                }, status=400)
            writes_raw = [{"cell": cell, "formula": formula}]
        try:
            writes = sheet_focus.validate_writes(writes_raw)
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)

        command_id = uuid.uuid4().hex
        fut: asyncio.Future | None = None
        if wait_ack:
            fut = _register_ui_ack(request.app, command_id)

        await _daemon_ns._broadcast(request.app, protocol.custom({
            "type": "formula.run",
            "writes": writes,
            "command_id": command_id if wait_ack else None,
            "workspace": str(ws),
        }))
        # Optimistic focus (browser will re-publish after apply).
        last = writes[-1]["cell"]
        prev = await asyncio.to_thread(sheet_focus.load, ws) or {}
        prev.update({"a1": last, "range": last})
        await asyncio.to_thread(sheet_focus.save, ws, prev)

        if not wait_ack or fut is None:
            return web.json_response({
                "ok": True,
                "op": "set_formula",
                "writes": writes,
                "workspace": str(ws),
                "note": (
                    "Formulas dispatched to the Sheet tab (same path as !fn)."
                ),
            })

        ack = await _wait_ui_ack(request.app, command_id, fut)
        if ack.get("timeout"):
            return web.json_response({
                "ok": False,
                "error": (
                    f"Sheet tab did not confirm apply within "
                    f"{int(_daemon_ns._UI_ACK_TIMEOUT_S)}s — open the Sheet tab "
                    "and retry, or pass an explicit cell="
                ),
                "command_id": command_id,
                "writes": writes,
                "workspace": str(ws),
            }, status=504)

        if not ack.get("ok"):
            return web.json_response({
                "ok": False,
                "error": ack.get("error") or "Sheet apply failed",
                "command_id": command_id,
                "writes": writes,
                "workspace": str(ws),
            }, status=422)

        durable = bool(ack.get("durable"))
        return web.json_response({
            "ok": True,
            "op": "set_formula",
            "writes": writes,
            "applied": True,
            "durable": durable,
            "command_id": command_id,
            "workspace": str(ws),
            "label": ack.get("label"),
            "note": (
                f"Formulas applied in Sheet"
                + (f" ({ack.get('label')})" if ack.get("label") else "")
                + (" and workbook saved." if durable
                   else " but durable snapshot save did not confirm.")
            ),
        })

    if op == "set_values":
        raw_vals = body.get("values")
        if not isinstance(raw_vals, list) or not raw_vals:
            return web.json_response(
                {"error": "`values` must be a non-empty 2D array"}, status=400)
        values: list[list[Any]] = []
        for row in raw_vals[:1000]:
            if not isinstance(row, list):
                row = [row]
            clipped: list[Any] = []
            for cell in row[:20]:
                if cell is None or isinstance(cell, (str, int, float, bool)):
                    clipped.append(cell)
                else:
                    clipped.append(str(cell))
            values.append(clipped)
        origin = str(body.get("origin") or "agent").strip() or "agent"
        command_id = uuid.uuid4().hex
        fut: asyncio.Future | None = None
        if wait_ack:
            fut = _register_ui_ack(request.app, command_id)
        await _daemon_ns._broadcast(request.app, protocol.custom({
            "type": "sheet.values",
            "values": values,
            "origin": origin,
            "command_id": command_id if wait_ack else None,
            "workspace": str(ws),
        }))
        if not wait_ack or fut is None:
            return web.json_response({
                "ok": True, "op": "set_values",
                "rows": len(values), "origin": origin, "workspace": str(ws),
            })
        ack = await _wait_ui_ack(request.app, command_id, fut)
        if ack.get("timeout"):
            return web.json_response({
                "ok": False,
                "error": (
                    f"Sheet tab did not confirm the grid within "
                    f"{int(_daemon_ns._UI_ACK_TIMEOUT_S)}s — open the Sheet tab and retry"
                ),
                "command_id": command_id,
                "workspace": str(ws),
            }, status=504)
        if not ack.get("ok"):
            return web.json_response({
                "ok": False,
                "error": ack.get("error") or "Sheet apply failed",
                "command_id": command_id,
                "workspace": str(ws),
            }, status=422)
        await _daemon_ns._broadcast(request.app, protocol.notice(
            f"Opened Sheet · {origin}", kind="chat"))
        await _daemon_ns._broadcast(request.app, protocol.artifact(
            "univer", f"sheet · {origin}"))
        return web.json_response({
            "ok": True, "op": "set_values",
            "applied": True, "durable": bool(ack.get("durable")),
            "command_id": command_id, "origin": origin,
            "rows": len(values), "workspace": str(ws),
            "label": ack.get("label"),
        })

    return web.json_response(
        {"error": f"unknown op {op!r}; expected select|set_formula|set_values"},
        status=400,
    )
