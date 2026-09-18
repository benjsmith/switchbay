"""Same-origin reverse proxy for CE + okstratr (Phase 4a).

Charter locked decision #1: Switchbay reverse-proxies loopback skill
daemons under ``/embed/ce/`` and ``/embed/okstratr/`` so in-app panels
can load first-party routes (no cross-origin iframes).

Upstream targets are **loopback-only** (127.0.0.1 / ::1). Non-loopback
upstream configuration is rejected. Proxied requests carry hosted-shell
headers so CE/okstratr can enter hosted mode:

  X-CE-Host: switchbay
  X-Okstratr-Host: switchbay
"""

from __future__ import annotations

import ipaddress
import logging
import os
from typing import Mapping
from urllib.parse import urlsplit, urlunsplit

from aiohttp import ClientSession, ClientTimeout, web

log = logging.getLogger("switchbay.embed_proxy")

# Public path prefixes (no trailing slash).
PREFIX_CE = "/embed/ce"
PREFIX_OKSTRATR = "/embed/okstratr"

HOST_HEADER_CE = "X-CE-Host"
HOST_HEADER_OKSTRATR = "X-Okstratr-Host"
HOSTED_SHELL = "switchbay"

# Charter defaults: CE :8766, okstratr :8767.
_DEFAULT_CE = "http://127.0.0.1:8766"
_DEFAULT_OKSTRATR = "http://127.0.0.1:8767"

_HOP_BY_HOP = frozenset({
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
})


class UpstreamNotLoopback(ValueError):
    """Raised when an embed upstream is not a loopback address."""


def _env_upstream(name: str, default: str) -> str:
    raw = (os.environ.get(name) or "").strip()
    return raw or default


def ce_upstream() -> str:
    return _normalize_base(_env_upstream("SWITCHBAY_CE_UPSTREAM", _DEFAULT_CE))


def okstratr_upstream() -> str:
    return _normalize_base(
        _env_upstream("SWITCHBAY_OKSTRATR_UPSTREAM", _DEFAULT_OKSTRATR)
    )


def _normalize_base(url: str) -> str:
    u = url.rstrip("/")
    if "://" not in u:
        u = "http://" + u
    return u


def is_loopback_host(host: str) -> bool:
    """True iff *host* (no port) is a loopback literal."""
    h = (host or "").strip().lower()
    if h in ("localhost", "127.0.0.1", "::1"):
        return True
    # Bracketed IPv6 from urlsplit netloc
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def assert_loopback_upstream(url: str) -> str:
    """Validate upstream URL is http(s) to a loopback host. Return normalized base."""
    base = _normalize_base(url)
    parts = urlsplit(base)
    if parts.scheme not in ("http", "https"):
        raise UpstreamNotLoopback(f"embed upstream scheme must be http(s): {url!r}")
    host = parts.hostname or ""
    if not is_loopback_host(host):
        raise UpstreamNotLoopback(
            f"embed upstream must be loopback-only (got host {host!r} from {url!r})"
        )
    # Rebuild without path/query/fragment so join is predictable
    netloc = parts.netloc
    return urlunsplit((parts.scheme, netloc, "", "", "")).rstrip("/")


def embed_targets() -> dict[str, dict[str, str]]:
    """Prefix → {upstream, host_header, host_value} (validated loopback)."""
    return {
        PREFIX_CE: {
            "upstream": assert_loopback_upstream(ce_upstream()),
            "host_header": HOST_HEADER_CE,
            "host_value": HOSTED_SHELL,
        },
        PREFIX_OKSTRATR: {
            "upstream": assert_loopback_upstream(okstratr_upstream()),
            "host_header": HOST_HEADER_OKSTRATR,
            "host_value": HOSTED_SHELL,
        },
    }


def match_embed_prefix(path: str) -> tuple[str, str] | None:
    """Return ``(prefix, rest)`` if *path* is under an embed prefix.

    *rest* is the upstream path including a leading ``/`` (or ``/`` when
    the request targeted the prefix alone).
    """
    p = path or "/"
    for prefix in (PREFIX_CE, PREFIX_OKSTRATR):
        if p == prefix or p == prefix + "/":
            return prefix, "/"
        if p.startswith(prefix + "/"):
            rest = p[len(prefix) :]
            return prefix, rest if rest else "/"
    return None


def build_upstream_url(prefix: str, rest: str, query: str = "") -> str:
    """Compose absolute upstream URL for a matched embed request."""
    targets = embed_targets()
    if prefix not in targets:
        raise KeyError(prefix)
    base = targets[prefix]["upstream"]
    path = rest if rest.startswith("/") else "/" + rest
    q = f"?{query}" if query else ""
    return f"{base}{path}{q}"


def filter_request_headers(
    headers: Mapping[str, str],
    *,
    host_header: str,
    host_value: str,
) -> dict[str, str]:
    """Copy inbound headers minus hop-by-hop; inject hosted-shell header."""
    out: dict[str, str] = {}
    for k, v in headers.items():
        if k.lower() in _HOP_BY_HOP:
            continue
        # Drop client-supplied hosted-shell headers; we set them.
        if k.lower() in (HOST_HEADER_CE.lower(), HOST_HEADER_OKSTRATR.lower()):
            continue
        out[k] = v
    out[host_header] = host_value
    return out


def filter_response_headers(headers: Mapping[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in headers.items():
        if k.lower() in _HOP_BY_HOP:
            continue
        out[k] = v
    return out


async def _proxy_http(request: web.Request) -> web.StreamResponse:
    matched = match_embed_prefix(request.path)
    if not matched:
        return web.Response(status=404, text="not an embed path")
    prefix, rest = matched
    try:
        targets = embed_targets()
    except UpstreamNotLoopback as e:
        log.error("embed upstream rejected: %s", e)
        return web.json_response({"error": str(e)}, status=502)

    meta = targets[prefix]
    upstream_url = build_upstream_url(prefix, rest, request.query_string)
    # Defense in depth: re-check the concrete URL we are about to hit.
    try:
        assert_loopback_upstream(
            urlunsplit(urlsplit(upstream_url)[:2] + ("", "", ""))
        )
    except UpstreamNotLoopback as e:
        return web.json_response({"error": str(e)}, status=502)

    req_headers = filter_request_headers(
        request.headers,
        host_header=meta["host_header"],
        host_value=meta["host_value"],
    )
    body = await request.read()
    timeout = ClientTimeout(total=120, connect=5, sock_connect=5)

    session: ClientSession | None = request.app.get("embed_http")
    owns_session = False
    if session is None or session.closed:
        session = ClientSession(timeout=timeout)
        owns_session = True

    try:
        async with session.request(
            request.method,
            upstream_url,
            headers=req_headers,
            data=body if body else None,
            allow_redirects=False,
        ) as upstream:
            resp_headers = filter_response_headers(upstream.headers)
            payload = await upstream.read()
            return web.Response(
                status=upstream.status,
                body=payload,
                headers=resp_headers,
            )
    except OSError as e:
        log.warning("embed upstream unreachable %s: %s", upstream_url, e)
        return web.json_response(
            {
                "error": "embed upstream unreachable",
                "upstream": meta["upstream"],
                "prefix": prefix,
                "detail": str(e),
            },
            status=502,
        )
    except Exception as e:  # noqa: BLE001
        log.exception("embed proxy failed for %s", upstream_url)
        return web.json_response(
            {"error": "embed proxy failed", "detail": str(e)},
            status=502,
        )
    finally:
        if owns_session and session is not None:
            await session.close()


async def handle_embed(request: web.Request) -> web.StreamResponse:
    """HTTP reverse-proxy handler for ``/embed/ce/*`` and ``/embed/okstratr/*``."""
    if request.method == "OPTIONS":
        # Let upstream decide CORS; we still inject host headers via proxy.
        return await _proxy_http(request)
    return await _proxy_http(request)


def register_routes(app: web.Application) -> None:
    """Mount embed proxy routes (call before the SPA catch-all)."""
    # Bare prefix + wildcard. Methods mirror what skill UIs typically need.
    paths = (
        PREFIX_CE,
        PREFIX_CE + "/",
        PREFIX_CE + "/{tail:.*}",
        PREFIX_OKSTRATR,
        PREFIX_OKSTRATR + "/",
        PREFIX_OKSTRATR + "/{tail:.*}",
    )
    methods = ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD")
    for path in paths:
        for method in methods:
            app.router.add_route(method, path, handle_embed)

    async def _open_session(application: web.Application) -> None:
        application["embed_http"] = ClientSession(
            timeout=ClientTimeout(total=120, connect=5, sock_connect=5),
        )

    async def _close_session(application: web.Application) -> None:
        sess = application.get("embed_http")
        if sess is not None and not sess.closed:
            await sess.close()

    app.on_startup.append(_open_session)
    app.on_cleanup.append(_close_session)


# ── allowlist helpers (unit-tested) ─────────────────────────────────────

def allowed_upstream_bases() -> frozenset[str]:
    """Current configured (validated) upstream bases."""
    t = embed_targets()
    return frozenset(v["upstream"] for v in t.values())


def upstream_allowed(url: str) -> bool:
    """True if *url* targets a configured loopback embed upstream."""
    try:
        parts = urlsplit(url)
        base = assert_loopback_upstream(
            urlunsplit((parts.scheme, parts.netloc, "", "", ""))
        )
    except UpstreamNotLoopback:
        return False
    return base in allowed_upstream_bases()
