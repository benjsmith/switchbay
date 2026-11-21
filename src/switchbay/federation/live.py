"""Client for a ce-graph/1 server (HTTP mirror, bearer token)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import oauth
from .citations import cache_page
from .mounts import Mount

_TIMEOUT = 4


class GraphError(RuntimeError):
    pass


def _origin(url: str) -> str:
    if url.endswith("/mcp"):
        return url[: -len("/mcp")]
    return url.rstrip("/")


def _request(mount: Mount, op: str, payload: dict | None, token: str) -> dict:
    url = _origin(mount.url) + "/ce-graph/1/" + op
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method="GET" if data is None else "POST")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise GraphError(f"HTTP {exc.code}: {detail[:300]}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GraphError(str(exc)) from exc
    if not isinstance(body, dict):
        raise GraphError("response was not a JSON object")
    return body


def token_for(workspace: Path, mount: Mount) -> str:
    if mount.auth == "anonymous":
        return ""
    existing = oauth.load_token(mount.id)
    token = existing or oauth.obtain(mount.url, mount.id)
    _check_token(mount, token)
    return token


def _check_token(mount: Mount, token: str) -> None:
    """JWT on every non-dev connection. Introspection when configured."""
    if mount.auth in ("anonymous", "dev"):
        return
    mode = (mount.token_check or "jwt").strip().lower()
    if mode == "introspection":
        from .introspect import introspect
        url = mount.introspection_url or str(_discovered(mount).get("introspection_endpoint") or "")
        if not url:
            raise GraphError("introspection endpoint is not configured")
        try:
            introspect(url, token)
        except Exception as exc:
            raise GraphError(str(exc)) from exc
        return
    from .jwt_jwks import JWKSCache, TokenError, validate
    if token.count(".") != 2:
        raise GraphError("remote graph token is not a JWT")
    meta = {} if mount.jwks_url and mount.issuer else _discovered(mount)
    jwks_url = mount.jwks_url or str(meta.get("jwks_uri") or "")
    issuer = mount.issuer or str(meta.get("issuer") or "")
    audience = mount.audience or str(meta.get("resource") or mount.url)
    if not jwks_url or not issuer:
        raise GraphError("jwt issuer and jwks url are required")
    cache = JWKSCache(jwks_url)
    try:
        validate(token, cache=cache, issuer=issuer, audience=audience)
    except TokenError as exc:
        raise GraphError(str(exc)) from exc


def _discovered(mount: Mount) -> dict:
    try:
        return oauth.discover(mount.url)
    except Exception:
        return {}


def info(workspace: Path, mount: Mount) -> dict:
    return _request(mount, "info", None, token_for(workspace, mount))


def search(workspace: Path, mount: Mount, query: str, limit: int) -> list[dict]:
    body = _request(mount, "search", {"query": query, "k": limit}, token_for(workspace, mount))
    return list(body.get("results") or [])


def read_page(workspace: Path, mount: Mount, path: str, rev: str = "") -> dict:
    payload: dict[str, Any] = {"path": path}
    if rev:
        payload["rev"] = rev
    page = _request(mount, "page", payload, token_for(workspace, mount))
    if page.get("error"):
        raise GraphError(str(page["error"]))
    cache_page(workspace, mount.id, str(page.get("rev") or ""), str(page.get("path") or path), page)
    return page


def neighbors(workspace: Path, mount: Mount, path: str, hops: int) -> dict:
    return _request(
        mount, "neighbors",
        {"page": path, "hops": hops, "direction": "both"},
        token_for(workspace, mount),
    )


def path_between(workspace: Path, mount: Mount, start: str, end: str) -> dict:
    return _request(
        mount, "path",
        {"from": start, "to": end, "max_hops": 6},
        token_for(workspace, mount),
    )


def propose(workspace: Path, mount: Mount, change: dict) -> dict:
    return _request(mount, "propose", change, token_for(workspace, mount))
