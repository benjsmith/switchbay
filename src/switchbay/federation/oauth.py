"""OAuth 2.1 authorisation-code with PKCE (S256).

Tokens are stored in the keychain when it is available, otherwise in a
machine-local file that is not the mount config. The mount file never
contains a token. A loopback graph server that auto-approves is enough
for the client: it reads the redirect without a browser. An
organisation identity provider that returns a login page needs a
browser, and this function says so instead of embedding a token.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .. import secrets as keychain
from .. import statedir

_TIMEOUT = 4


def _s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object from {url}")
    return data


def discover(resource_url: str) -> dict:
    """Protected-resource metadata, then the authorisation server."""
    origin = resource_url.split("/mcp")[0].rstrip("/")
    resource = _get_json(origin + "/.well-known/oauth-protected-resource")
    issuers = resource.get("authorization_servers") or [origin]
    meta = _get_json(str(issuers[0]).rstrip("/") + "/.well-known/oauth-authorization-server")
    meta["resource"] = resource.get("resource") or resource_url
    return meta


def _token_path(mount_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in mount_id)
    return statedir.state_root() / "graph-tokens" / f"{safe}.json"


def load_token(mount_id: str) -> str:
    stored = keychain.get(f"graph-mount:{mount_id}")
    if stored:
        return stored
    path = _token_path(mount_id)
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(data.get("access_token") or "")


def store_token(mount_id: str, token: str) -> None:
    if keychain.available() and keychain.set_key(f"graph-mount:{mount_id}", token):
        return
    path = _token_path(mount_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"access_token": token}) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ARG002
        return None


def obtain(resource_url: str, mount_id: str, *, client_id: str = "switchbay") -> str:
    """Run PKCE against the resource's authorisation server. Returns the access token."""
    meta = discover(resource_url)
    verifier = secrets.token_urlsafe(48)
    challenge = _s256(verifier)
    state = secrets.token_urlsafe(12)
    redirect = "http://127.0.0.1:9/switchbay-oauth"
    query = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "scope": "ce-graph.read ce-graph.propose",
    })
    auth_url = meta["authorization_endpoint"] + "?" + query
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        opener.open(auth_url, timeout=_TIMEOUT)
        raise ValueError(
            "the identity provider did not redirect; organisation sign-in "
            "needs a browser and is not completed here"
        )
    except urllib.error.HTTPError as exc:
        if exc.code not in (302, 303, 307):
            raise ValueError(f"authorization failed: HTTP {exc.code}") from exc
        location = exc.headers.get("Location") or ""
    parsed = urllib.parse.urlparse(location)
    params = urllib.parse.parse_qs(parsed.query)
    if params.get("state", [""])[0] != state:
        raise ValueError("authorization state did not match")
    if "error" in params:
        raise ValueError(str(params["error"][0]))
    code = params.get("code", [""])[0]
    if not code:
        raise ValueError("authorization redirect had no code")
    body = json.dumps({
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": redirect,
        "client_id": client_id,
    }).encode("utf-8")
    req = urllib.request.Request(
        meta["token_endpoint"], data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        token = json.loads(resp.read().decode("utf-8"))
    access = str(token.get("access_token") or "")
    if not access:
        raise ValueError("token response had no access_token")
    store_token(mount_id, access)
    return access
