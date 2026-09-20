"""Isolated mock HTTP+WS backend for Playwright UI tests.

Labeled E2E_MOCK. Does not call switchbay.daemon.run, does not touch
the live vault, does not read workspaces.json. Serves frontend/dist
and a deterministic /api + /ws surface.
"""

from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any

from aiohttp import WSMsgType, web

WS_A = "/tmp/switchbay-e2e-mock-ws"
WS_B = "/tmp/switchbay-e2e-mock-ws-b"

STATE: dict[str, Any] = {
    "workspace": WS_A,
    "policies": {WS_A: False, WS_B: True},
    "admin_allows": True,
    "fail_save": False,
    "clients": set(),
    "desk_max_live_workers": 8,
    "comms": [
        {
            "key": "gmail:acct:thread-e2e",
            "provider": "gmail",
            "account_id": "acct",
            "stable_id": "thread-e2e",
            "kind": "email_thread",
            "status": "pending",
            "subject": "Fixture thread",
            "sender": "fixture@example.invalid",
            "deep_link": "https://example.invalid/mail",
            "approved_workspaces": [],
            "suggested_workspaces": [WS_A],
            "content_capability": "ok",
        },
        {
            "key": "gmail:acct:thread-e2e-b",
            "provider": "gmail",
            "account_id": "acct",
            "stable_id": "thread-e2e-b",
            "kind": "email_thread",
            "status": "pending",
            "subject": "Other workspace thread",
            "sender": "other@example.invalid",
            "deep_link": "https://example.invalid/mail-b",
            "approved_workspaces": [],
            "suggested_workspaces": [WS_B],
            "content_capability": "ok",
        },
        {
            "key": "msgraph:acct:team-channel",
            "provider": "msgraph",
            "account_id": "acct",
            "stable_id": "team/t1/channel/c1",
            "kind": "channel",
            "status": "pending",
            "subject": "Fixture Teams channel",
            "sender": "",
            "deep_link": "https://example.invalid/teams",
            "approved_workspaces": [],
            "suggested_workspaces": [WS_A],
            "content_capability": "fail_closed",
            "content_capability_reason": (
                "Teams channel messages have no documented metadata-only "
                "projection; listing is supported, content fetch is refuse-closed. "
                "Approval does not retrieve Teams message bodies."
            ),
        },
    ],
}


def _custom(payload: dict[str, Any]) -> dict[str, Any]:
    return {"type": "CUSTOM", "name": payload.get("type"), "value": payload}


def _policy(workspace: str | None = None) -> dict[str, Any]:
    ws = workspace or STATE["workspace"]
    requested = bool(STATE["policies"].get(ws, False))
    admin = bool(STATE["admin_allows"])
    return {
        "enabled": bool(requested and admin),
        "admin_allows": admin,
        "requested": requested,
        "workspace": ws,
    }


def _hello() -> dict[str, Any]:
    ws = STATE["workspace"]
    return {
        "type": "hello",
        "workspace": ws,
        "default_file": None,
        "mode": {
            "name": "default",
            "tabs": [
                {"id": "wiki", "title": "Wiki", "kind": "wiki", "source": "core"},
                {"id": "agents", "title": "Agents", "kind": "agents", "source": "system"},
                {"id": "comms", "title": "Comms", "kind": "comms", "source": "user"},
            ],
        },
        "selection": None,
        "workspaces": {
            "paths": [WS_A, WS_B],
            "active": ws,
        },
        "thread_id": "th-e2e",
        "web_policy": _policy(ws),
    }


async def _broadcast(payload: dict[str, Any]) -> None:
    dead = []
    inner = payload if isinstance(payload, dict) else {}
    raw = json.dumps(_custom(inner) if inner.get("type") != "CUSTOM" else inner)
    for ws in list(STATE["clients"]):
        try:
            await ws.send_str(raw)
        except Exception:  # noqa: BLE001
            dead.append(ws)
    for ws in dead:
        STATE["clients"].discard(ws)


async def handle_health(_request: web.Request) -> web.Response:
    return web.json_response({
        "ok": True,
        "boot_id": "e2e-mock",
        "pid": 0,
        "started_at": 0,
        "frontend_mtime": 0,
        "workspace": STATE["workspace"],
        "service_managed": False,
        "repo_root": "",
        "policy": {"profile": "open", "source": "mock"},
        "e2e_mock": True,
    })


def _requested_workspace(request: web.Request, body: dict[str, Any] | None = None) -> str:
    if isinstance(body, dict):
        raw = str(body.get("workspace") or "").strip()
        if raw:
            return raw
    q = str(request.rel_url.query.get("workspace") or "").strip()
    if q:
        return q
    hdr = (
        request.headers.get("X-Switchbay-Workspace")
        or request.headers.get("X-Workspace")
        or ""
    ).strip()
    if hdr:
        return hdr
    return str(STATE["workspace"])


async def handle_web_policy_get(request: web.Request) -> web.Response:
    ws = _requested_workspace(request)
    return web.json_response(_policy(ws))


async def handle_web_policy_post(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}
    ws = _requested_workspace(request, body if isinstance(body, dict) else None)
    if STATE["fail_save"] or request.headers.get("X-E2E-Fail") == "1":
        return web.json_response(
            {"error": "save failed", **_policy(ws)},
            status=500,
        )
    if not isinstance(body, dict) or "enabled" not in body:
        return web.json_response({"error": "enabled required"}, status=400)
    STATE["policies"][ws] = bool(body.get("enabled"))
    view = _policy(ws)
    await _broadcast({"type": "web_policy", **view})
    return web.json_response({"ok": True, **view})


def _comms_visible(item: dict[str, Any], ws: str) -> bool:
    if not ws:
        return True
    suggested = list(item.get("suggested_workspaces") or [])
    approved = list(item.get("approved_workspaces") or [])
    if ws in suggested or ws in approved:
        return True
    status = str(item.get("status") or "")
    if status in ("pending", "blocked", "revoked") and not suggested and not approved:
        return True
    return False


async def handle_comms_get(request: web.Request) -> web.Response:
    ws = _requested_workspace(request)
    items = [i for i in STATE["comms"] if _comms_visible(i, ws)]
    return web.json_response({
        "items": items,
        "pending": sum(1 for i in items if i.get("status") == "pending"),
        "workspace": ws,
        "workspaces": [
            {"path": WS_A, "name": "ws-a"},
            {"path": WS_B, "name": "ws-b"},
        ],
    })


async def handle_comms_post(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}
    key = str((body or {}).get("key") or "")
    action = str((body or {}).get("action") or "")
    for item in STATE["comms"]:
        if item.get("key") == key:
            if action == "approve":
                item["status"] = "approved"
                ws = str((body or {}).get("workspace") or STATE["workspace"])
                item["approved_workspaces"] = [ws]
                if item.get("content_capability") == "fail_closed":
                    item["ingest_state"] = "unsupported"
                    item["ingest_error"] = (
                        "This source can be listed, but message content cannot be retrieved."
                    )
                else:
                    item["ingest_state"] = "ingested"
                    item["ingest_error"] = ""
            elif action == "reject":
                item["status"] = "rejected"
            elif action == "revoke":
                item["status"] = "revoked"
            await _broadcast({"type": "comms.review", "key": key, "action": action})
            return web.json_response({
                "ok": True,
                "item": item,
                "ingest_state": item.get("ingest_state") or "",
                "ingest_error": item.get("ingest_error") or "",
            })
    return web.json_response({"error": "unknown"}, status=404)


async def handle_comms_open(_request: web.Request) -> web.Response:
    await _broadcast({"type": "open_comms"})
    return web.json_response({"ok": True})


async def handle_settings_get(_request: web.Request) -> web.Response:
    return web.json_response({
        "rail_history_local": True,
        "rail_history_path": "/tmp",
        "workspace_synced": None,
        "desk_max_live_workers": STATE["desk_max_live_workers"],
        "requested": STATE["desk_max_live_workers"],
        "min": 4,
        "default": 8,
        "hard_max": 8,
        "admin_ceiling": None,
        "chief_counted": True,
        "note": "Total live seats per desk, including the chief-of-staff.",
    })


async def handle_settings_post(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}
    if "desk_max_live_workers" in (body or {}):
        try:
            n = int(body["desk_max_live_workers"])
        except (TypeError, ValueError):
            n = 8
        STATE["desk_max_live_workers"] = max(4, min(8, n))
    return await handle_settings_get(request)


async def handle_workspaces(_request: web.Request) -> web.Response:
    return web.json_response({
        "paths": [WS_A, WS_B],
        "active": STATE["workspace"],
    })


async def handle_workspaces_switch(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}
    path = str((body or {}).get("path") or WS_A)
    STATE["workspace"] = path
    STATE["policies"].setdefault(path, path == WS_B)
    await _broadcast(_hello())
    return web.json_response({"ok": True, "active": path})


async def handle_mode(_request: web.Request) -> web.Response:
    return web.json_response(_hello()["mode"])


async def handle_threads(_request: web.Request) -> web.Response:
    return web.json_response({
        "threads": [{
            "thread_id": "th-e2e",
            "title": "Chat",
            "kind": "structured-agent",
            "project": None,
            "created_at": 0,
            "updated_at": 0,
            "chat_count": 0,
            "last_summary": "",
            "running": 0,
        }],
        "focused": "th-e2e",
    })


def _empty_graph() -> dict[str, Any]:
    return {
        "workspace": STATE["workspace"],
        "generated_at": "0",
        "palette": {},
        "nodes": [],
        "edges": [],
        "pages": {},
    }


async def handle_graph(_request: web.Request) -> web.Response:
    return web.json_response(_empty_graph())


async def handle_json(request: web.Request) -> web.Response:
    path = request.path
    if path.startswith("/api/graph"):
        return web.json_response(_empty_graph())
    if path.startswith("/api/llm/reasoning"):
        return web.json_response({
            "provider": "",
            "model": None,
            "options": [],
            "selected": None,
        })
    if path.startswith("/api/workspaces"):
        return web.json_response({
            "home": STATE["workspace"],
            "expanded": STATE["workspace"],
            "exists": True,
            "candidates": [],
            "active": STATE["workspace"],
            "ok": True,
        })
    if path.startswith("/api/curator-profile"):
        return web.json_response({"profile": "", "text": ""})
    if path.startswith("/api/walkthrough"):
        return web.json_response({"done": True})
    if path.startswith("/api/localllm/harness"):
        return web.json_response({
            "text": "", "lines": 0, "refine_lines": 0, "path": "",
        })
    if path.startswith("/api/localllm"):
        return web.json_response({
            "plan": {"ok": False, "ram_gb": 0},
            "config": {}, "install": None,
            "candidates": [], "installed": [], "servers": [],
            "backends": {},
        })
    if path.startswith("/api/settings"):
        return web.json_response({"orchestration_preference": 0.5})
    if path.startswith("/api/pasteboard"):
        return web.json_response({"slots": []})
    if path.startswith("/api/action-buttons"):
        return web.json_response({"buttons": []})
    if path.startswith("/api/permission"):
        return web.json_response({
            "pending": [], "muted_origins": [], "patterns": [],
        })
    if path.startswith("/api/packs"):
        return web.json_response({"packs": [], "registry": []})
    if path.startswith("/api/mcp-servers"):
        return web.json_response({"servers": []})
    if path.startswith("/api/user-tabs"):
        return web.json_response({"tabs": []})
    if path.startswith("/api/watch-folders"):
        return web.json_response({"folders": [], "pending": []})
    if path.startswith("/api/streams"):
        return web.json_response({"streams": []})
    if path.startswith("/api/orchestration"):
        return web.json_response({"runs": [], "policy": {}, "interrupted": []})
    if path.startswith("/api/llm"):
        return web.json_response({
            "providers": [],
            "keychain_available": False,
            "keychain_backend": "none",
            "default_provider": "",
            "default_model": "",
        })
    if path.startswith("/api/verbs"):
        return web.json_response({"verbs": []})
    if path.startswith("/api/projects"):
        return web.json_response({"projects": []})
    if path.startswith("/api/tree"):
        return web.json_response({"files": []})
    if path.startswith("/api/sources"):
        return web.json_response({
            "sources": [], "internal_pages": 0, "pages_scanned": 0,
        })
    if path.startswith("/api/file-routes"):
        return web.json_response({"routes": []})
    if path.startswith("/api/threads"):
        return await handle_threads(request)
    if path.startswith("/api/rail/events"):
        return web.json_response({"events": [], "has_more": False})
    if path.startswith("/api/runs"):
        return web.json_response({"runs": []})
    if path.startswith("/api/permission/pending"):
        return web.json_response({"pending": [], "muted_origins": []})
    if path.startswith("/api/proposals"):
        return web.json_response({"proposals": []})
    return web.json_response({})


async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    STATE["clients"].add(ws)
    await ws.send_str(json.dumps(_custom(_hello())))
    try:
        async for msg in ws:
            if msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                break
    finally:
        STATE["clients"].discard(ws)
    return ws


async def handle_fail_save(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}
    STATE["fail_save"] = bool((body or {}).get("fail"))
    return web.json_response({"ok": True, "fail_save": STATE["fail_save"]})


async def handle_push(request: web.Request) -> web.Response:
    body = await request.json()
    if isinstance(body, dict) and body.get("type") == "web_policy":
        ws = str(body.get("workspace") or STATE["workspace"])
        if "enabled" in body:
            STATE["policies"][ws] = bool(body.get("enabled"))
        if "admin_allows" in body:
            STATE["admin_allows"] = bool(body.get("admin_allows"))
    await _broadcast(body if isinstance(body, dict) else {})
    return web.json_response({"ok": True})


def build_app(dist: pathlib.Path) -> web.Application:
    app = web.Application()
    app["dist"] = dist

    async def handle_index(_request: web.Request) -> web.StreamResponse:
        index = dist / "index.html"
        if not index.is_file():
            return web.Response(text="frontend dist missing", status=500)
        return web.FileResponse(index)

    app.router.add_get("/api/health", handle_health)
    app.router.add_get("/api/comms/review", handle_comms_get)
    app.router.add_post("/api/comms/review", handle_comms_post)
    app.router.add_post("/api/comms/review/open", handle_comms_open)
    app.router.add_get("/api/settings", handle_settings_get)
    app.router.add_post("/api/settings", handle_settings_post)
    app.router.add_get("/api/web-policy", handle_web_policy_get)
    app.router.add_post("/api/web-policy", handle_web_policy_post)
    app.router.add_get("/api/workspaces", handle_workspaces)
    app.router.add_post("/api/workspaces/switch", handle_workspaces_switch)
    app.router.add_get("/api/mode", handle_mode)
    app.router.add_get("/api/threads", handle_threads)
    app.router.add_get("/api/graph/data", handle_graph)
    app.router.add_post("/api/e2e/fail-save", handle_fail_save)
    app.router.add_post("/api/e2e/push", handle_push)
    app.router.add_get("/ws", handle_ws)
    app.router.add_route("GET", "/api/{tail:.*}", handle_json)
    app.router.add_route("POST", "/api/{tail:.*}", handle_json)
    app.router.add_get("/", handle_index)
    if dist.is_dir():
        app.router.add_static("/", dist, show_index=False)
    return app


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=41765)
    p.add_argument("--dist", required=True)
    args = p.parse_args()
    web.run_app(build_app(pathlib.Path(args.dist)), host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
