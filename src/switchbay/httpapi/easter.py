"""Mars Hopper and thrusters easter-egg routes.

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
from aiohttp import web
from switchbay import protocol
from switchbay import tabstore

from switchbay.httpapi._ns import _daemon_ns

# ── Easter egg: Mars Hopper (Settings → "fire thrusters?") ──────────
# First-party static game under static/mars-hopper/. Served from the
# daemon (not an external GitHub Pages URL) so a compromised upstream
# cannot become an attack vector against Switch Bay users.


def _mars_hopper_dir() -> Path:
    return Path(_daemon_ns.__file__).resolve().parents[2] / "static" / "mars-hopper"

async def handle_mars_hopper_asset(request: web.Request) -> web.Response:
    """Serve a allowlisted Mars Hopper asset. Path param empty → index."""
    name = (request.match_info.get("name") or "").strip().lstrip("/")
    rel = _daemon_ns._MARS_HOPPER_FILES.get(name)
    if rel is None:
        return web.json_response({"error": "not found"}, status=404)
    path = _mars_hopper_dir() / rel
    # Containment: resolved path must stay under the hopper dir.
    try:
        path.resolve().relative_to(_mars_hopper_dir().resolve())
    except ValueError:
        return web.json_response({"error": "not found"}, status=404)
    try:
        data = await asyncio.to_thread(path.read_bytes)
    except OSError:
        return web.json_response({"error": "mars hopper not bundled"}, status=404)
    ct = _daemon_ns._MARS_HOPPER_CT.get(rel, "application/octet-stream")
    kwargs: dict[str, Any] = {
        "body": data,
        "content_type": ct,
        "headers": {
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-cache",
        },
    }
    if ct.startswith("text/") or "javascript" in ct:
        kwargs["charset"] = "utf-8"
    return web.Response(**kwargs)

async def handle_thrusters_get(request: web.Request) -> web.Response:
    """Whether the Hopper easter-egg tab is currently armed."""
    workspace: Path = request.app["workspace"]
    armed = await asyncio.to_thread(tabstore.thrusters_tab_present, workspace)
    return web.json_response({"armed": armed})

async def handle_thrusters_post(request: web.Request) -> web.Response:
    """Arm or cut thrusters — open/close the temporary Hopper tab.
    Body: `{armed: bool}`."""
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        body = {}
    want = bool(body.get("armed"))
    if want:
        # Game assets must exist or the tab is a blank frame.
        if not (_mars_hopper_dir() / "index.html").is_file():
            return web.json_response(
                {"error": "mars hopper assets not bundled"}, status=404)
        await asyncio.to_thread(tabstore.add_thrusters_tab, workspace)
        await _daemon_ns._broadcast(request.app, _daemon_ns._hello_payload(request.app))
        await _daemon_ns._broadcast(
            request.app, protocol.custom({"type": "open_thrusters"}))
        return web.json_response({"ok": True, "armed": True})
    removed = await asyncio.to_thread(tabstore.remove_thrusters_tab, workspace)
    if removed:
        await _daemon_ns._broadcast(request.app, _daemon_ns._hello_payload(request.app))
        await _daemon_ns._broadcast(request.app, protocol.nav("graph", {}, "Graph"))
    return web.json_response({"ok": True, "armed": False, "removed": removed})

async def handle_thrusters_close(request: web.Request) -> web.Response:
    """Hopper tab ✕ — same as cutting thrusters."""
    workspace: Path = request.app["workspace"]
    removed = await asyncio.to_thread(tabstore.remove_thrusters_tab, workspace)
    if removed:
        await _daemon_ns._broadcast(request.app, _daemon_ns._hello_payload(request.app))
        await _daemon_ns._broadcast(request.app, protocol.nav("graph", {}, "Graph"))
    return web.json_response({"ok": True, "removed": removed})
