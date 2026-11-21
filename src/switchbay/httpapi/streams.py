"""Comms-stream account routes and the poll loop.

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
from aiohttp import web
from switchbay import streams
from switchbay import workspaces

from switchbay.httpapi._ns import _daemon_ns

def _stream_port() -> int:
    try:
        return int(os.environ.get("CSWY_DAEMON_PORT") or "8765")
    except ValueError:
        return 8765

async def handle_streams_list(request: web.Request) -> web.Response:
    accounts = await asyncio.to_thread(streams.list_accounts)
    out = []
    for a in accounts:
        pending = await asyncio.to_thread(streams.pending_events, a["id"])
        row = {k: v for k, v in a.items() if k != "client_id"}
        row["client_id_tail"] = a["client_id"][-6:] if a.get("client_id") else ""
        row["status"] = streams.account_status(a)
        row["pending"] = len(pending)
        # Effective allowlist (migrates legacy workspace+route_to).
        row["workspaces"] = streams.allowed_workspaces(a)
        out.append(row)
    return web.json_response({
        "accounts": out,
        "providers": {
            k: {"label": v["label"], "needs_secret": v["needs_secret"],
                "auth": v.get("auth", "oauth"),
                "fields": v.get("fields", []),
                "setup_help": v["setup_help"]}
            for k, v in streams.PROVIDERS.items()
        },
        "redirect_uri": streams.redirect_uri(_stream_port()),
        # Registered workspaces for the routing pickers (default
        # workspace + smart-routing allowlist).
        "workspaces": [
            {"path": p, "name": Path(p).name}
            for p in (workspaces.load().get("paths") or [])
        ],
    })

async def handle_streams_routing(request: web.Request) -> web.Response:
    """Routing settings, allowlist-only form: the set of workspaces
    ALLOWED to ingest from this stream (no privileged/default — the
    allowlist is the whole routing authority and the consent
    boundary) plus the gate mode (`smart` matrix gate | `fanout` no
    gate). Registered workspaces only."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    refs = body.get("workspaces")
    if refs is None:
        refs = body.get("route_to")  # legacy clients
    allow: list[str] = []
    for ref in refs or []:
        ws = _daemon_ns._a2a_resolve_workspace(request.app, str(ref))
        if ws is None:
            return web.json_response(
                {"error": f"workspace not in the registry: {ref}"}, status=400,
            )
        if str(ws) not in allow:
            allow.append(str(ws))
    mode = str(body.get("routing") or "")
    if not mode:
        mode = "smart" if body.get("triage") else "fanout"  # legacy
    if mode == "default":
        mode = "fanout"  # legacy: one-target no-gate ≡ fanout
    if mode not in ("smart", "fanout"):
        return web.json_response(
            {"error": "routing must be smart | fanout"}, status=400,
        )
    acct = await asyncio.to_thread(
        streams.update_account, request.match_info["account_id"],
        routing=mode, workspaces=allow, triage=(mode == "smart"),
    )
    if acct is None:
        return web.json_response({"error": "no such account"}, status=404)
    return web.json_response({
        "ok": True, "routing": mode, "workspaces": allow,
    })

async def handle_streams_add(request: web.Request) -> web.Response:
    blocked = _daemon_ns._policy_block("comms_streams")
    if blocked:
        return blocked
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    try:
        acct = await asyncio.to_thread(
            streams.add_account,
            provider=str(body.get("provider") or ""),
            label=str(body.get("label") or ""),
            client_id=str(body.get("client_id") or ""),
            client_secret=str(body.get("client_secret") or "") or None,
            tenant=str(body.get("tenant") or "") or None,
            host=str(body.get("host") or "") or None,
            username=str(body.get("username") or "") or None,
            password=str(body.get("password") or "") or None,
            fields=body.get("fields") if isinstance(body.get("fields"), dict) else None,
            workspace=str(request.app["workspace"]),
        )
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    # Password accounts verify NOW so a typo'd credential fails loudly
    # at add time, not at the first silent poll. Roll back on failure.
    try:
        identity = await asyncio.to_thread(streams.verify_password_account, acct)
    except ValueError as e:
        await asyncio.to_thread(streams.remove_account, acct["id"])
        return web.json_response({"error": str(e)}, status=400)
    if streams.PROVIDERS[acct["provider"]].get("auth") == "password":
        await asyncio.to_thread(
            streams.update_account, acct["id"],
            verified=True, identity=identity or acct.get("identity"),
        )
    return web.json_response({"ok": True, "id": acct["id"]})

async def handle_streams_remove(request: web.Request) -> web.Response:
    aid = request.match_info["account_id"]
    ok = await asyncio.to_thread(streams.remove_account, aid)
    return web.json_response({"ok": ok}, status=200 if ok else 404)

async def handle_streams_login(request: web.Request) -> web.Response:
    acct = await asyncio.to_thread(streams.get_account, request.match_info["account_id"])
    if acct is None:
        return web.json_response({"error": "no such account"}, status=404)
    if streams.PROVIDERS.get(acct["provider"], {}).get("auth") == "password":
        return web.json_response(
            {"error": "password account — no browser login needed"}, status=400,
        )
    try:
        url = streams.build_auth_url(acct, _stream_port())
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({"auth_url": url})

async def handle_streams_oauth_callback(request: web.Request) -> web.Response:
    """Loopback redirect target. The browser lands here after consent;
    we exchange the code and show a tiny close-me page."""
    err = request.query.get("error")
    state = request.query.get("state", "")
    code = request.query.get("code", "")
    def _page(msg: str, ok: bool) -> web.Response:
        return web.Response(
            content_type="text/html",
            text=(
                "<!doctype html><meta charset='utf-8'>"
                "<body style='font-family:system-ui;display:grid;"
                "place-items:center;height:90vh'><div style='text-align:center'>"
                f"<h2>{'✓' if ok else '✕'} {msg}</h2>"
                "<p>You can close this tab and return to switchbay.</p>"
                "</div></body>"
            ),
        )
    if err:
        return _page(f"login refused: {err}", False)
    if not state or not code:
        return _page("missing state/code in callback", False)
    try:
        acct = await streams.complete_auth(state, code, _stream_port())
    except ValueError as e:
        return _page(str(e), False)
    return _page(f"{acct['label']} connected as {acct.get('identity') or '…'}", True)

async def handle_streams_poll(request: web.Request) -> web.Response:
    blocked = _daemon_ns._policy_block("comms_streams")
    if blocked:
        return blocked
    acct = await asyncio.to_thread(streams.get_account, request.match_info["account_id"])
    if acct is None:
        return web.json_response({"error": "no such account"}, status=404)
    try:
        new = await streams.poll_account(acct)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    except Exception as e:  # noqa: BLE001 — network/provider soup
        return web.json_response({"error": f"poll failed: {e}"}, status=502)
    pending = await asyncio.to_thread(streams.pending_events, acct["id"])
    return web.json_response({"ok": True, "new": new, "pending": len(pending)})

async def handle_streams_auto(request: web.Request) -> web.Response:
    """Cadence only: poll/ingest already-approved threads. Never auto-approves."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    acct = await asyncio.to_thread(
        streams.update_account, request.match_info["account_id"],
        auto_curate=bool(body.get("auto_curate")),
    )
    if acct is None:
        return web.json_response({"error": "no such account"}, status=404)
    return web.json_response({
        "ok": True,
        "auto_curate": bool(acct.get("auto_curate")),
        "note": "cadence for approved threads only; does not approve sources",
    })
