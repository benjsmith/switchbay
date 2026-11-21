"""Quit, restart, and update routes.

Split out of switchbay.daemon so this concept has its own module.
The daemon re-exports every name; tests that monkeypatch
switchbay.daemon still apply, because patched helpers are read
back through _daemon_ns at call time.

Run: python -m switchbay serve --workspace PATH
"""
from __future__ import annotations

from typing import Any
import asyncio
import logging
import os
import signal
from aiohttp import web
from switchbay import protocol
from switchbay import service
from switchbay import updater

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

# ── Daemon shutdown (user-requested stop) ────────────────────────────
# Stopping from inside the app (Settings → Quit, or `/quit`) reuses the
# exact path `make stop` takes: a clean self-SIGTERM. aiohttp turns
# SIGTERM into a graceful shutdown (on_cleanup kills terminal shells +
# cancels in-flight runs), the process exits 0, and because the launchd
# agent is KeepAlive={SuccessfulExit:false} a clean exit stays down — it
# only relaunches on a *crash*. No launchctl call from the app needed.


def _schedule_daemon_exit(app: web.Application, *, delay: float = 0.4) -> None:
    """Fire a self-SIGTERM after a short delay so the HTTP reply / the
    shutdown broadcast flush first. Idempotent: a second call (button +
    a racing /quit) is a no-op."""
    if app.get("_quitting"):
        return
    app["_quitting"] = True
    loop = asyncio.get_running_loop()
    loop.call_later(delay, lambda: os.kill(os.getpid(), signal.SIGTERM))
    log.info("shutdown requested — SIGTERM self in %.1fs", delay)

async def _initiate_shutdown(app: web.Application, *, reason: str) -> None:
    """Tell every open window we're stopping (so they show a 'stopped'
    overlay instead of reconnect-looping), then schedule the clean exit."""
    try:
        await _daemon_ns._broadcast(app, protocol.daemon_shutdown(reason))
    except Exception:  # noqa: BLE001 — never let a broadcast error block the stop
        log.exception("shutdown broadcast failed")
    _daemon_ns._schedule_daemon_exit(app)

async def handle_quit(request: web.Request) -> web.Response:
    """POST /api/quit — stop Switch Bay on user request (the Settings
    'Quit Switch Bay' button). Ends the daemon for *all* workspaces and
    threads. The calling client shows its own overlay; we also broadcast
    so any other open window does too."""
    await _daemon_ns._initiate_shutdown(request.app, reason="user")
    return web.json_response({"ok": True})

async def _handle_quit_slash(
    app: web.Application, ws: web.WebSocketResponse, args: str,
) -> None:
    if args.strip().lower() not in _daemon_ns._QUIT_CONFIRM:
        await ws.send_json(protocol.notice(
            "This stops Switch Bay for **all** workspaces and ends any "
            "agents still running. Nothing you've saved is lost. Restart "
            "later with `make restart`, or it starts again next time you "
            "log in.\n\nType `/quit confirm` to stop now.",
            kind="slash",
        ))
        return
    await ws.send_json(protocol.notice("Stopping Switch Bay…", kind="slash"))
    await _daemon_ns._initiate_shutdown(app, reason="slash")

# ── Daemon restart (user-requested) ──────────────────────────────────
# Settings → Restart and `/start`. The managed launchd/systemd job is
# bounced via `service restart`. A foreground `serve` re-execs itself
# after releasing the port. The PWA's boot_id watcher reloads either way.

def _restart_this_daemon(app: web.Application) -> None:
    """Restart whichever process is serving :8765.

    The installed launchd/systemd job uses ``service restart``. A
    foreground ``serve`` (Settings from a PWA talking to `make
    dev-daemon` / a manual `python -m switchbay serve`) re-execs itself
    after a short delay so it does not spawn a rival on the same port.
    """
    if app.get("service_managed"):
        service.spawn_restart()
        return
    service.spawn_self_reexec()
    _daemon_ns._schedule_daemon_exit(app)

async def handle_restart(request: web.Request) -> web.Response:
    """POST /api/restart — Settings → Restart. Restarts the process
    that is actually serving this PWA (managed service or foreground)."""
    try:
        _restart_this_daemon(request.app)
    except Exception as e:  # noqa: BLE001
        log.exception("restart failed")
        return web.json_response(
            {"ok": False, "error": f"could not start restart: {e}"}, status=500,
        )
    log.info("restart requested via /api/restart")
    return web.json_response({"ok": True})

async def handle_versions(request: web.Request) -> web.Response:
    """GET /api/versions — running Switch Bay / curiosity-engine /
    curiosity-merge versions for the Help panel.

    Local metadata first (git tag / the skill's own CHANGELOG). A skill
    that carries neither — curiosity-engine keeps its changelog at the
    repo root, outside the installed tree — is identified by matching
    its SKILL.md bytes against recent releases, memoized per install.
    Offline that lookup is skipped and Help says "installed" rather
    than printing a version nobody verified.
    """
    def _components() -> list[dict[str, Any]]:
        return updater.resolve_unknown_versions(updater.installed_components())

    try:
        components = await asyncio.to_thread(_components)
    except Exception as e:  # noqa: BLE001
        log.exception("versions lookup failed")
        return web.json_response(
            {
                "ok": False,
                "error": f"versions lookup failed: {e}",
                "components": [],
            },
            status=500,
        )
    return web.json_response({"ok": True, "components": components})

async def handle_update_check(request: web.Request) -> web.Response:
    """GET /api/update/check — compare running versions to GitHub latest
    releases (Switch Bay, curiosity-engine, curiosity-merge). Read-only."""
    blocked = _daemon_ns._policy_block("in_app_update")
    if blocked:
        return blocked
    try:
        body = await asyncio.to_thread(updater.check)
    except Exception as e:  # noqa: BLE001
        log.exception("update check failed")
        return web.json_response(
            {"ok": False, "error": f"update check failed: {e}"}, status=500,
        )
    return web.json_response(body)

async def handle_update(request: web.Request) -> web.Response:
    """POST /api/update — check GitHub, apply any older components, then
    restart this daemon so the PWA reloads."""
    blocked = _daemon_ns._policy_block("in_app_update")
    if blocked:
        return blocked
    try:
        body = await asyncio.to_thread(updater.apply)
    except Exception as e:  # noqa: BLE001
        log.exception("update apply failed")
        return web.json_response(
            {"ok": False, "error": f"update failed: {e}", "updated": False},
            status=500,
        )
    if not body.get("updated"):
        body.setdefault("restarted", False)
        return web.json_response(body)
    try:
        _restart_this_daemon(request.app)
    except Exception as e:  # noqa: BLE001
        log.exception("spawn_restart after update failed")
        body["restarted"] = False
        body["restart_error"] = f"could not start restart: {e}"
        return web.json_response(body, status=500)
    body["restarted"] = True
    log.info("restart requested via /api/update")
    return web.json_response(body)

async def _handle_start_slash(
    app: web.Application, ws: web.WebSocketResponse,
) -> None:
    await ws.send_json(protocol.notice(
        "Restarting Switch Bay… the app reconnects on its own once it's "
        "back up.",
        kind="slash",
    ))
    try:
        _restart_this_daemon(app)
    except Exception as e:  # noqa: BLE001
        log.exception("spawn_restart failed")
        await ws.send_json(protocol.notice(
            f"restart failed to launch — {e}", kind="slash",
        ))
