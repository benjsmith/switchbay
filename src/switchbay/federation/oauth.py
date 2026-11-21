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


def _params_from_redirect(location: str, state: str) -> dict:
    parsed = urllib.parse.urlparse(location)
    params = urllib.parse.parse_qs(parsed.query)
    if params.get("state", [""])[0] != state:
        raise ValueError("authorization state did not match")
    if "error" in params:
        raise ValueError(str(params["error"][0]))
    return params


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


class _Callback:
    """Loopback redirect target for the system browser."""

    def __init__(self) -> None:
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        self._box: dict[str, str] = {}
        self._ready = threading.Event()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                return

            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path != "/switchbay-oauth":
                    self.send_response(404)
                    self.end_headers()
                    return
                owner._box["query"] = parsed.query
                owner._ready.set()
                body = b"Switch Bay signed in. You can close this window."
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def wait(self, timeout: float) -> str:
        if not self._ready.wait(timeout):
            raise ValueError("timed out waiting for the browser sign-in")
        return self._box.get("query") or ""

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def obtain(
    resource_url: str, mount_id: str, *, client_id: str = "switchbay",
    open_browser=None,
) -> str:
    """Run PKCE against the resource's authorisation server.

    An immediate redirect is enough. A login page is opened in the
    system browser, and the loopback redirect delivers the code.
    ``open_browser`` replaces that launch in tests.
    """
    meta = discover(resource_url)
    verifier = secrets.token_urlsafe(48)
    challenge = _s256(verifier)
    state = secrets.token_urlsafe(12)
    callback = _Callback()
    try:
        redirect = f"http://127.0.0.1:{callback.port}/switchbay-oauth"
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
        location = ""
        try:
            opener.open(auth_url, timeout=_TIMEOUT)
            needs_browser = True
        except urllib.error.HTTPError as exc:
            if exc.code in (302, 303, 307):
                location = exc.headers.get("Location") or ""
                needs_browser = False
            elif exc.code == 200:
                needs_browser = True
            else:
                raise ValueError(f"authorization failed: HTTP {exc.code}") from exc
        if needs_browser:
            launch = open_browser
            if launch is None:
                import webbrowser
                launch = webbrowser.open
            launch(auth_url)
            location = redirect + "?" + callback.wait(120)
        params = _params_from_redirect(location, state)
        code = params.get("code", [""])[0]
        if not code:
            raise ValueError("authorization redirect had no code")
    finally:
        callback.close()
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
