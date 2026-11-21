"""RFC 7662 token introspection.

The alternative to local JWT validation. The authorisation server says
whether the token is active. An inactive token, or a transport error,
is a refusal.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

from .jwt_jwks import TokenError


def introspect(url: str, token: str, *, client_id: str = "switchbay") -> dict:
    body = urllib.parse.urlencode({
        "token": token,
        "token_type_hint": "access_token",
        "client_id": client_id,
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise TokenError(f"introspection failed: {exc}") from exc
    if not isinstance(data, dict):
        raise TokenError("introspection response was not an object")
    if data.get("active") is not True:
        raise TokenError("token is not active")
    return data
