"""Built frontend files, power assertion, and boot workspace.

Split out of switchbay.daemon so this concept has its own module.
The daemon re-exports every name; tests that monkeypatch
switchbay.daemon still apply, because patched helpers are read
back through _daemon_ns at call time.

Run: python -m switchbay serve --workspace PATH
"""
from __future__ import annotations

from pathlib import Path
import asyncio
import logging
import mimetypes
import os
import subprocess
import sys
from aiohttp import web
from switchbay import admin_policy
from switchbay import statedir

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

def _sync_power_assertion(app: web.Application) -> None:
    """Hold a macOS `caffeinate -i` idle-sleep assertion while any run
    is active; release it when idle. Keeps a long curate alive when the
    Mac would otherwise idle-sleep (lid OPEN). No-op off macOS. Called
    on a 5 s timer from build_app's _power_loop."""
    if sys.platform != "darwin":
        return
    active = bool(app.get("runs"))
    proc = app.get("_caffeinate")
    alive = proc is not None and proc.poll() is None
    if active and not alive:
        try:
            app["_caffeinate"] = subprocess.Popen(
                ["caffeinate", "-i"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            log.info("power: holding idle-sleep assertion (run active)")
        except (OSError, ValueError):
            pass
    elif not active and alive:
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
        app["_caffeinate"] = None
        log.info("power: released idle-sleep assertion (idle)")

def _frontend_dist() -> Path:
    """Where the built frontend lives. Override with
    SWITCHBAY_FRONTEND_DIST; otherwise repo-relative (src/switchbay/
    daemon.py → repo/frontend/dist). Run `make build-frontend` to fill it."""
    override = os.environ.get("SWITCHBAY_FRONTEND_DIST")
    if override:
        return Path(override).expanduser()
    return Path(_daemon_ns.__file__).resolve().parents[2] / "frontend" / "dist"

async def _serve_static(path: Path) -> web.Response:
    """Serve a static file by reading bytes into a Response (off-thread)
    rather than `web.FileResponse`. FileResponse's `loop.sendfile`
    fallback intermittently threw `OSError [Errno 11] Resource deadlock
    avoided` on `file.readinto` under concurrent asset loads on macOS;
    a plain read sidesteps it. Fine for a single-user localhost app.

    Cache policy matters here: the SPA shell (index.html) must NOT be
    cached, or the browser/PWA keeps loading an old shell that points at
    a stale JS bundle (so a rebuilt frontend never takes effect until the
    cache expires). Vite's hashed `/assets/*` filenames change on every
    build, so those are safe to cache immutably; everything else
    revalidates."""
    data = await asyncio.to_thread(path.read_bytes)
    ctype, _ = mimetypes.guess_type(str(path))
    resp = web.Response(body=data, content_type=ctype or "application/octet-stream")
    name = path.name.lower()
    if name.endswith(".html"):
        resp.headers["Cache-Control"] = "no-store, must-revalidate"
    elif path.parent.name == "assets":
        # Content-hashed filenames → safe to cache forever.
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    else:
        # manifest, icons, favicon — let the browser revalidate.
        resp.headers["Cache-Control"] = "no-cache"
    return resp

def _frontend_missing_response() -> web.Response:
    """PWA-safe 503: a mid-restart navigation used to land on a bare
    `frontend not built` text page with no JS, so the dock window
    never recovered. This shell polls /api/health and reloads once
    frontend/dist/index.html is there."""
    return web.Response(
        text=_daemon_ns._FRONTEND_MISSING_HTML,
        status=503,
        content_type="text/html",
        headers={"Cache-Control": "no-store, must-revalidate"},
    )

async def handle_spa(request: web.Request) -> web.StreamResponse:
    """Static file server for the built frontend, with SPA fallback to
    index.html. Registered last as a catch-all GET, so the specific
    /api and /ws routes always win. In dev you use vite (:5173) instead
    and this just serves whatever was last built (or 503s)."""
    dist: Path = request.app["frontend_dist"]
    if not dist.is_dir():
        return _frontend_missing_response()
    rel = request.match_info.get("tail", "").lstrip("/")
    # Never serve the SPA for API/WS paths — an unregistered /api GET
    # must 404 (so clients that probe GET-then-POST fall back correctly),
    # not silently receive index.html.
    if (
        rel == "api" or rel.startswith("api/")
        or rel == "ws" or rel.startswith("ws/")
        or rel == "embed" or rel.startswith("embed/")
    ):
        return web.Response(status=404)
    if rel:
        candidate = (dist / rel).resolve()
        try:
            candidate.relative_to(dist.resolve())
        except ValueError:
            return web.Response(status=404)  # path traversal
        if candidate.is_file():
            return await _serve_static(candidate)
        # Missing FILE request → 404, never the SPA shell. A request for
        # a concrete asset (anything under /assets/, or whose last path
        # segment has an extension: *.js, *.css, *.wasm, …) that fell
        # through means the file is gone — usually a hashed chunk from a
        # bundle that was rebuilt under a long-open session. Returning
        # index.html here makes that chunk load as text/html and blows up
        # the dynamic import ("'text/html' is not a valid JavaScript MIME
        # type"). A clean 404 lets the client's preload-error guard
        # reload into the fresh bundle instead. SPA fallback stays only
        # for route-like paths (no extension) below.
        last = rel.rsplit("/", 1)[-1]
        if rel.startswith("assets/") or "." in last:
            return web.Response(status=404)
    index = dist / "index.html"
    if index.is_file():
        return await _serve_static(index)
    return _frontend_missing_response()

def _is_install_tree_workspace(ws: Path) -> bool:
    root = admin_policy.install_root()
    try:
        r = ws.resolve()
    except OSError:
        r = ws
    if root:
        try:
            if r == Path(root).resolve():
                return True
        except OSError:
            pass
    low = str(r).lower()
    if "program files" in low:
        return True
    if "/library/application support/switchbay" in low:
        return True
    return False

def _boot_workspace_under_home() -> Path | None:
    raw = admin_policy.workspaces_home_policy()
    base = Path(os.path.expandvars(os.path.expanduser(raw))) if raw else (Path.home() / "SwitchBay")
    if admin_policy.profile() == "enterprise" and not admin_policy.allow_synced_workspaces():
        hint = statedir.sync_service_hint(base)
        if hint:
            print(f"refusing cloud-synced workspace home ({hint}); set paths.allow_synced_workspaces")
            return None
    dest = base / "workspace"
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"could not create workspace {dest}: {e}")
        return None
    return dest
