"""Loopback origin checks and workspace path containment.

Split out of switchbay.daemon so this concept has its own module.
The daemon re-exports every name; tests that monkeypatch
switchbay.daemon still apply, because patched helpers are read
back through _daemon_ns at call time.

Run: python -m switchbay serve --workspace PATH
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import logging
from aiohttp import web

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

def _within(root: Path, candidate: Path) -> bool:
    """True iff resolved `candidate` is inside (or equal to) resolved
    `root`. The single containment predicate for the several handlers
    that resolve a path themselves then need the guard (figures, pack
    files, sketch raster, CSV dir, external-edit) — replaces the
    hand-rolled `root not in c.parents and c != root` copies."""
    try:
        root = root.resolve()
        candidate = candidate.resolve()
    except (OSError, ValueError):
        return False
    return candidate == root or root in candidate.parents

def _safe_resolve(workspace: Path, rel: str) -> Path | None:
    try:
        target = (workspace / rel).resolve()
    except (OSError, ValueError):
        return None
    return target if _within(workspace, target) else None

def _hostname_of(value: str) -> str:
    """Strip scheme + port from an Origin/Host header, returning the
    bare hostname (lowercased). '' for the null/empty/opaque origin."""
    v = (value or "").strip().lower()
    if not v or v == "null":
        return ""
    # Drop scheme (http://, https://, ws://, wss://).
    if "://" in v:
        v = v.split("://", 1)[1]
    # Drop any path/query.
    v = v.split("/", 1)[0]
    # IPv6 literal in brackets: keep the brackets so it matches the set.
    if v.startswith("["):
        end = v.find("]")
        if end != -1:
            return v[: end + 1]
    # Strip :port.
    if ":" in v:
        v = v.rsplit(":", 1)[0]
    return v

def _origin_host_allowed(request: web.Request) -> bool:
    origin = request.headers.get("Origin")
    if origin is not None and _hostname_of(origin) not in _daemon_ns._LOOPBACK_HOSTS:
        return False
    # Host header is effectively always present (HTTP/1.1 requires it).
    # A missing Host is not a browser request; allow it (curl -0 etc.).
    host = request.headers.get("Host")
    if host is not None and _hostname_of(host) not in _daemon_ns._LOOPBACK_HOSTS:
        return False
    return True

def _untrusted_html_response(html: str) -> web.Response:
    """Serve model/agent-authored HTML with a locked-down CSP so that,
    even if it's opened directly at the daemon origin (not just inside
    the Report tab's sandboxed iframe), its scripts get an opaque origin
    and cannot reach `/api/*`. `sandbox` without `allow-same-origin`
    forces the null origin; `default-src 'none'` blocks network egress.
    `allow-scripts` keeps interactive reports working."""
    return web.Response(
        text=html,
        content_type="text/html",
        headers={
            "Content-Security-Policy": (
                "sandbox allow-scripts; default-src 'none'; "
                "img-src data: blob:; style-src 'unsafe-inline'; "
                "font-src data:"
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )

@web.middleware
async def _origin_guard(request: web.Request, handler: Any) -> web.StreamResponse:
    if not _origin_host_allowed(request):
        log.warning(
            "rejected cross-origin request: origin=%r host=%r path=%s",
            request.headers.get("Origin"), request.headers.get("Host"),
            request.path,
        )
        return web.json_response(
            {"error": "cross-origin request refused"}, status=403,
        )
    return await handler(request)
