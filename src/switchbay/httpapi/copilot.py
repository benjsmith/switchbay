"""GitHub Copilot device-login routes.

Split out of switchbay.daemon so this concept has its own module.
The daemon re-exports every name; tests that monkeypatch
switchbay.daemon still apply, because patched helpers are read
back through _daemon_ns at call time.

Run: python -m switchbay serve --workspace PATH
"""
from __future__ import annotations

import asyncio
import json
import logging
from aiohttp import web
from switchbay import llmgateway
from switchbay import protocol

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

async def handle_copilot_login(request: web.Request) -> web.Response:
    """Start the GitHub device-flow sign-in (Copilot provider).

    Body (optional): {host} — a GitHub Enterprise Server or ghe.com
    hostname. Omitted means github.com. Returns {user_code,
    verification_uri, host, sso_hint}; a background task polls until the
    user authorizes in their browser. Status via
    GET /api/copilot/login/status.
    """
    from switchbay.llmgateway import github_copilot
    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}
    host = str((body or {}).get("host") or "").strip() or None
    cur = request.app.get("copilot_login")
    if isinstance(cur, dict) and cur.get("state") == "pending":
        return web.json_response({
            "ok": True,
            "user_code": cur.get("user_code"),
            "verification_uri": cur.get("verification_uri"),
            "host": cur.get("host"),
            "sso_hint": cur.get("sso_hint"),
            "sso_uri": cur.get("sso_uri") or "",
            "enterprise_slug": cur.get("enterprise_slug") or "",
        })
    try:
        device = await github_copilot.device_code(host)
    except llmgateway.ProviderError as e:
        return web.json_response({"error": str(e)}, status=502)
    rec = {
        "state": "pending",
        "user_code": device.get("user_code"),
        "verification_uri": device.get("verification_uri"),
        "host": device.get("host"),
        "sso_hint": device.get("sso_hint"),
        "sso_uri": device.get("sso_uri") or "",
        "enterprise_slug": device.get("enterprise_slug") or "",
        "error": None,
        "task": None,
    }
    request.app["copilot_login"] = rec

    async def _poll() -> None:
        try:
            await github_copilot.poll_for_token(device)
            if request.app.get("copilot_login") is not rec:
                return  # cancelled
            rec["state"] = "done"
            await _daemon_ns._broadcast(request.app, protocol.notice(
                "GitHub Copilot signed in — pick it in the rail's provider menu.",
                kind="chat",
            ))
        except asyncio.CancelledError:
            rec.update(state="cancelled", error="sign-in cancelled")
            raise
        except llmgateway.ProviderError as e:
            if request.app.get("copilot_login") is rec:
                rec.update(state="error", error=str(e))
        except Exception as e:  # noqa: BLE001
            log.exception("copilot login poll crashed")
            if request.app.get("copilot_login") is rec:
                rec.update(state="error", error=str(e))

    rec["task"] = asyncio.create_task(_poll())
    return web.json_response({
        "ok": True,
        "user_code": rec["user_code"],
        "verification_uri": rec["verification_uri"],
        "host": rec["host"],
        "sso_hint": rec["sso_hint"],
        "sso_uri": rec["sso_uri"],
        "enterprise_slug": rec["enterprise_slug"],
    })

async def handle_copilot_login_status(request: web.Request) -> web.Response:
    from switchbay.llmgateway import github_copilot
    rec = request.app.get("copilot_login")
    # Never ship the live Task over JSON.
    login = None
    if isinstance(rec, dict):
        login = {k: v for k, v in rec.items() if k != "task"}
    return web.json_response({
        "authed": github_copilot.has_key(),
        "host": github_copilot.get_host(),
        "default_host": github_copilot.DEFAULT_HOST,
        "login": login,
    })

async def handle_copilot_login_cancel(request: web.Request) -> web.Response:
    """Abort a pending device-flow poll so the user can retry immediately
    (otherwise a wedged pending record blocks for ~15 minutes)."""
    rec = request.app.pop("copilot_login", None)
    if isinstance(rec, dict):
        task = rec.get("task")
        if isinstance(task, asyncio.Task) and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        rec["state"] = "cancelled"
    return web.json_response({"ok": True})

async def handle_copilot_logout(request: web.Request) -> web.Response:
    from switchbay.llmgateway import github_copilot
    await asyncio.to_thread(github_copilot.sign_out)
    rec = request.app.pop("copilot_login", None)
    if isinstance(rec, dict):
        task = rec.get("task")
        if isinstance(task, asyncio.Task) and not task.done():
            task.cancel()
    return web.json_response({"ok": True})
