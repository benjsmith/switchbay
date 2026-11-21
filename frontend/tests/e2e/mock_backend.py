"""Isolated mock HTTP+WS backend for Playwright UI tests.

Labeled E2E_MOCK. Does not call switchbay.daemon.run, does not touch
the live vault, does not read workspaces.json. Serves frontend/dist
and a deterministic /api + /ws surface.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import time
from typing import Any

from aiohttp import WSMsgType, web

WS_A = "/tmp/switchbay-e2e-mock-ws"
WS_B = "/tmp/switchbay-e2e-mock-ws-b"
GALLERY_WS = pathlib.Path("/tmp/switchbay-e2e-plots-ws")

STATE: dict[str, Any] = {
    "workspace": WS_A,
    "policies": {WS_A: False, WS_B: True},
    "admin_allows": True,
    "fail_save": False,
    "clients": set(),
    "desk_max_live_workers": 8,
    # Curiosity Engine embed fixture: "absent" (no CE install) or "stub"
    # (a tiny fake CEEmbed under /embed/ce). graph_tab adds a Graph tab
    # to the mode so the shell's hide-without-CE rule can be observed.
    "ce": "absent",
    "graph_tab": False,
    "show_reviews": False,
    "session_label": "public",
    "exclusion_rules": [],
    "class_items": [],
    "public_rules": [],
    "presidio_enabled": True,
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


def _tabs() -> list[dict[str, Any]]:
    if STATE.get("gallery"):
        return [
            {"id": "plot", "title": "Plot", "kind": "vega", "source": "core"},
            {"id": "library", "title": "Library", "kind": "library", "source": "core"},
        ]
    tabs = [
        {"id": "wiki", "title": "Wiki", "kind": "wiki", "source": "core"},
        {"id": "agents", "title": "Agents", "kind": "agents", "source": "system"},
        {"id": "comms", "title": "Comms", "kind": "comms", "source": "user"},
    ]
    if STATE["graph_tab"]:
        tabs.append({"id": "graph", "title": "Graph", "kind": "graph", "source": "core"})
    if STATE.get("show_reviews"):
        tabs.append({"id": "reviews", "title": "Reviews", "kind": "report", "source": "core"})
    return tabs


def _hello() -> dict[str, Any]:
    ws = STATE["workspace"]
    return {
        "type": "hello",
        "workspace": ws,
        "default_file": None,
        "mode": {
            "name": "default",
            "tabs": _tabs(),
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
        "gallery": bool(STATE.get("gallery")),
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
        "proxied_skill_embeds": False,
        "ce_graph": {
            "installed": STATE["ce"] == "stub",
            "has_wiki": STATE["ce"] == "stub",
        },
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


async def handle_ce_mode(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}
    mode = str((body or {}).get("mode") or "absent")
    STATE["ce"] = mode if mode in ("absent", "stub") else "absent"
    STATE["graph_tab"] = bool((body or {}).get("graph_tab"))
    return web.json_response({"ok": True, "ce": STATE["ce"], "graph_tab": STATE["graph_tab"]})


# A stand-in for CE's embed.js: enough of CEEmbed.create for Switch Bay's
# dual-mount session (sidebar shell + canvas shell are Switch Bay markup).
_CE_EMBED_STUB = """
(function () {
  window.CEEmbed = {
    create: function (opts) {
      return fetch(opts.dataUrl).then(function (r) { return r.json(); }).then(function (data) {
        var live = false;
        return {
          getData: function () { return data; },
          mountSidebar: function (el) {
            var list = el.querySelector('#sidebar-list');
            if (list) list.innerHTML = '<div class="sidebar-row" data-id="p1">Page one</div>';
          },
          mountCanvas: function () { live = true; },
          unmountCanvas: function (o) { if (o && o.destroy) live = false; },
          isCanvasLive: function () { return live; },
          revalidate: function () {},
          destroy: function () { live = false; },
        };
      });
    },
  };
})();
"""


async def handle_ce_static(request: web.Request) -> web.Response:
    if STATE["ce"] != "stub":
        return web.Response(status=502, text="CE viewer not running")
    name = request.match_info.get("name", "")
    if name.endswith(".css"):
        return web.Response(text="/* stub */", content_type="text/css")
    body = _CE_EMBED_STUB if name == "embed.js" else "/* stub */"
    return web.Response(text=body, content_type="application/javascript")


async def handle_ce_data(_request: web.Request) -> web.Response:
    if STATE["ce"] != "stub":
        return web.Response(status=502, text="CE viewer not running")
    return web.json_response({
        "workspace": STATE["workspace"],
        "palette": {},
        "nodes": [{"id": "p1", "path": "wiki/concepts/p1.md", "title": "Page one", "type": "concept"}],
        "edges": [],
        "pages": {"p1": {"id": "p1", "path": "wiki/concepts/p1.md", "title": "Page one",
                         "type": "concept", "body_html": "<p>one</p>"}},
    })


async def handle_session_label(request: web.Request) -> web.Response:
    if request.method == "GET":
        return web.json_response({"label": STATE.get("session_label") or "public", "session": "e2e"})
    return web.json_response({"ok": True, "after": "public"})


async def handle_exclusion(request: web.Request) -> web.Response:
    if request.method == "PUT":
        body = await request.json()
        rules = body.get("rules") if isinstance(body, dict) else []
        cleaned = []
        for index, row in enumerate(rules or []):
            if not isinstance(row, dict) or not str(row.get("description") or "").strip():
                continue
            cleaned.append({
                "id": str(row.get("id") or f"r{index}"),
                "description": str(row["description"]),
                "decision": str(row.get("decision") or "ask"),
            })
        STATE["exclusion_rules"] = cleaned
    return web.json_response({"rules": STATE.get("exclusion_rules") or []})


async def handle_class_queue(_request: web.Request) -> web.Response:
    return web.json_response({"items": STATE.get("class_items") or [], "mandatory": False})


async def handle_class_decide(request: web.Request) -> web.Response:
    body = await request.json()
    item_id = str(body.get("id") or "")
    label = str(body.get("label") or "")
    STATE["class_items"] = [
        row for row in (STATE.get("class_items") or []) if row.get("id") != item_id
    ]
    return web.json_response({"ok": True, "item": {"id": item_id, "classification": label}})


async def handle_public_write(request: web.Request) -> web.Response:
    if request.method == "GET":
        return web.json_response({
            "presidio_installed": False,
            "presidio_enabled": STATE.get("presidio_enabled", True),
            "user_may_toggle": True,
            "guidance": "Presidio is off in this workspace, so public writes are not scanned for personal data.",
            "rules": STATE.get("public_rules") or [],
        })
    body = await request.json()
    if request.path.endswith("/presidio"):
        STATE["presidio_enabled"] = bool(body.get("enabled", True))
        return web.json_response({"ok": True, "enabled": STATE["presidio_enabled"], "guidance": "Presidio is off in this workspace, so public writes are not scanned for personal data."})
    if request.path.endswith("/confirm"):
        if body.get("choice") == "always":
            STATE.setdefault("public_rules", []).append({
                "id": "allow-1",
                "description": "Public write without Presidio",
                "decision": "allow",
                "scope": "global",
            })
        return web.json_response({"ok": body.get("choice") != "cancel"})
    if request.path.endswith("/scope"):
        for row in STATE.get("public_rules") or []:
            if row.get("id") == body.get("id"):
                row["scope"] = body.get("scope")
        return web.json_response({"ok": True})
    return web.json_response({"ok": True})


async def handle_e2e_seed(request: web.Request) -> web.Response:
    body = await request.json()
    if isinstance(body, dict):
        for key in ("session_label", "show_reviews", "class_items", "exclusion_rules", "presidio_enabled"):
            if key in body:
                STATE[key] = body[key]
    return web.json_response({"ok": True, "e2e_mock": True})


def _gallery_ws() -> pathlib.Path:
    return pathlib.Path(STATE.get("gallery_ws") or GALLERY_WS)


def _init_gallery() -> None:
    """Real plot + extracted-figure workspace for the plots e2e."""
    from PIL import Image, ImageDraw

    from switchbay import plots

    ws = GALLERY_WS
    if ws.exists():
        shutil.rmtree(ws)
    assets = ws / "wiki" / "figures" / "_assets"
    assets.mkdir(parents=True)
    pages = ws / "wiki" / "figures"

    def _write_figure(
        stem: str,
        title: str,
        caption: str,
        axes: tuple[str, str],
        legend: tuple[str, ...],
        draw_image,
    ) -> None:
        image = Image.new("RGB", (800, 480), "#fbfcfe")
        draw = ImageDraw.Draw(image)
        draw.text((56, 20), title, fill="#1a1d22")
        draw_image(draw)
        image.save(assets / f"{stem}.png", format="PNG")
        axis_lines = "\n".join(f'  - "{label}"' for label in axes)
        legend_lines = "\n".join(f'  - "{label}"' for label in legend)
        (pages / f"{stem}.md").write_text(
            "---\n"
            f'title: "{title}"\n'
            "type: figure\n"
            "origin: extracted\n"
            f"asset: {stem}.png\n"
            "sources: [source-doc]\n"
            "axis_titles:\n"
            f"{axis_lines}\n"
            "legend:\n"
            f"{legend_lines}\n"
            "---\n\n"
            f"![[figures/_assets/{stem}.png]]\n\n"
            f"*{caption}*\n",
            encoding="utf-8",
        )

    def _glucose_bars(draw: ImageDraw.ImageDraw) -> None:
        draw.rectangle((48, 64, 752, 430), outline="#d5d9e0")
        for i, height in enumerate((120, 180, 150, 220, 160)):
            x = 90 + i * 70
            draw.rectangle((x, 400 - height, x + 40, 400), fill="#e17c05")

    def _floor_plan(draw: ImageDraw.ImageDraw) -> None:
        draw.rectangle((80, 70, 720, 420), outline="#1d6996", width=3)
        draw.line((400, 70, 400, 420), fill="#1d6996", width=2)
        draw.line((80, 250, 720, 250), fill="#1d6996", width=2)
        draw.ellipse((180, 140, 210, 170), fill="#cc503e")
        draw.ellipse((520, 300, 550, 330), fill="#0f8554")

    _write_figure(
        "glucose",
        "Glucose curve",
        "Plasma glucose after the meal.",
        ("Time", "Concentration"),
        ("control", "treated"),
        _glucose_bars,
    )
    _write_figure(
        "site-plan",
        "Site plan",
        "Camera positions on the floor.",
        ("East-west", "North-south"),
        ("Lobby", "Loading dock"),
        _floor_plan,
    )
    plots.save_plot(
        ws,
        name="Revenue by region",
        spec={
            "title": "Revenue by region",
            "description": "Quarterly revenue split by region.",
            "mark": "bar",
            "data": {"values": [
                {"quarter": "Q1", "region": "North", "revenue": 10},
                {"quarter": "Q1", "region": "South", "revenue": 7},
                {"quarter": "Q2", "region": "North", "revenue": 12},
                {"quarter": "Q2", "region": "South", "revenue": 9},
            ]},
            "encoding": {
                "x": {"field": "quarter", "type": "ordinal", "title": "Quarter"},
                "y": {"field": "revenue", "type": "quantitative", "axis": {"title": "Revenue"}},
                "color": {"field": "region", "type": "nominal", "legend": {"title": "Region"}},
            },
        },
        sources=["vault/sales.csv"],
    )
    # On disk without a figure page, so opening the Plot tab backfills it.
    cohort = {
        "id": "cohort-retention",
        "name": "Cohort retention",
        "spec": {
            "title": "Cohort retention",
            "description": "Share of each cohort still active.",
            "mark": "line",
            "data": {"values": [
                {"week": 1, "cohort": "Jan", "share": 0.8},
                {"week": 4, "cohort": "Jan", "share": 0.55},
                {"week": 1, "cohort": "Feb", "share": 0.78},
                {"week": 4, "cohort": "Feb", "share": 0.5},
            ]},
            "encoding": {
                "x": {"field": "week", "type": "quantitative", "title": "Weeks since signup"},
                "y": {"field": "share", "type": "quantitative", "title": "Share still active"},
                "color": {"field": "cohort", "type": "nominal", "legend": {"title": "Cohort"}},
            },
        },
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    plot_dir = ws / ".workbench" / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)
    (plot_dir / "cohort-retention.json").write_text(json.dumps(cohort), encoding="utf-8")
    STATE["gallery"] = True
    STATE["gallery_ws"] = str(ws)
    STATE["workspace"] = str(ws)


def _ensure_gallery() -> None:
    if os.environ.get("E2E_GALLERY") != "1":
        return
    if STATE.get("gallery"):
        return
    _init_gallery()


async def handle_gallery_plots(_request: web.Request) -> web.Response:
    if not STATE.get("gallery"):
        return web.json_response({"plots": [], "extracted": []})
    from switchbay import plot_gallery
    ws = _gallery_ws()
    plot_gallery.backfill_figure_docs(ws)
    return web.json_response(plot_gallery.gallery(ws))


async def handle_gallery_plot(request: web.Request) -> web.Response:
    if not STATE.get("gallery"):
        return web.json_response({"error": "not found"}, status=404)
    from switchbay import plots
    plot_id = request.query.get("id", "").strip()
    try:
        rec = plots.get_plot(_gallery_ws(), plot_id)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    if rec is None:
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response({"plot": rec})


async def handle_gallery_figure(request: web.Request) -> web.Response:
    if not STATE.get("gallery"):
        return web.json_response({"error": "not found"}, status=404)
    from switchbay import plot_gallery
    plot_id = request.query.get("id", "").strip()
    doc = plot_gallery.figure_doc_for_plot(_gallery_ws(), plot_id)
    if doc is None:
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response(doc)


async def handle_gallery_thumb(request: web.Request) -> web.Response:
    if not STATE.get("gallery"):
        return web.json_response({"error": "not found"}, status=404)
    from switchbay import plot_gallery
    plot_id = request.match_info.get("plot_id", "").strip()
    png = plot_gallery.thumbnail_bytes(_gallery_ws(), plot_id)
    if not png:
        return web.json_response({"error": "not found"}, status=404)
    return web.Response(body=png, content_type="image/png")


async def handle_gallery_library(request: web.Request) -> web.Response:
    if not STATE.get("gallery"):
        return web.json_response({})
    from switchbay import library
    if request.path.endswith("/search"):
        q = str(request.query.get("q") or "")
        return web.json_response({"q": q, "hits": library.search(_gallery_ws(), q)})
    return web.json_response(library.list_all(_gallery_ws()))


async def handle_gallery_figures(request: web.Request) -> web.Response:
    if not STATE.get("gallery"):
        return web.json_response({"error": "not found"}, status=404)
    rel = request.match_info.get("path", "").strip()
    ws = _gallery_ws()
    roots = [
        (ws / "wiki" / "figures" / "_assets").resolve(),
        (ws / "figures").resolve(),
        (ws / "wiki" / "figures").resolve(),
    ]
    for root in roots:
        if not root.is_dir():
            continue
        candidate = (root / rel).resolve()
        if root not in candidate.parents and candidate != root:
            continue
        if candidate.is_file():
            return web.FileResponse(candidate)
    return web.json_response({"error": "not found"}, status=404)


def build_app(dist: pathlib.Path) -> web.Application:
    _ensure_gallery()
    app = web.Application()
    app["dist"] = dist

    async def handle_index(_request: web.Request) -> web.StreamResponse:
        index = dist / "index.html"
        if not index.is_file():
            return web.Response(text="frontend dist missing", status=500)
        return web.FileResponse(index)

    app.router.add_get("/api/health", handle_health)
    app.router.add_post("/api/e2e/seed", handle_e2e_seed)
    app.router.add_get("/api/session/label", handle_session_label)
    app.router.add_get("/api/exclusion-rules", handle_exclusion)
    app.router.add_put("/api/exclusion-rules", handle_exclusion)
    app.router.add_get("/api/classification/queue", handle_class_queue)
    app.router.add_post("/api/classification/decide", handle_class_decide)
    app.router.add_get("/api/public-write", handle_public_write)
    app.router.add_post("/api/public-write/presidio", handle_public_write)
    app.router.add_post("/api/public-write/confirm", handle_public_write)
    app.router.add_post("/api/public-write/scope", handle_public_write)
    app.router.add_get("/api/plots", handle_gallery_plots)
    app.router.add_get("/api/plots/{plot_id}/thumb", handle_gallery_thumb)
    app.router.add_get("/api/plot/figure", handle_gallery_figure)
    app.router.add_get("/api/plot", handle_gallery_plot)
    app.router.add_get("/api/library/search", handle_gallery_library)
    app.router.add_get("/api/library", handle_gallery_library)
    app.router.add_get("/figures/{path:.*}", handle_gallery_figures)
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
    app.router.add_post("/api/e2e/ce", handle_ce_mode)
    app.router.add_get("/embed/ce/data.json", handle_ce_data)
    app.router.add_get("/embed/ce/static/{name:.*}", handle_ce_static)
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
