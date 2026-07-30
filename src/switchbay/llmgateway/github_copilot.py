"""GitHub Copilot provider — subscription auth via browser login.

Auth is the VS-Code-style flow the user ratified (2026-07-05): the
GitHub **device flow** — daemon requests a device/user code, the user
opens github.com/login/device in their browser (enterprise SSO
happens there, on GitHub's own pages), and the daemon polls for the
OAuth grant. We use the standard Copilot editor-integration client id
(the one the official editor plugins ship; no secret involved —
device flow is public-client by design). The long-lived OAuth token
lands in the secrets backend; per-request we exchange it for the
short-lived Copilot bearer (`copilot_internal/v2/token`, cached until
near expiry) and talk OpenAI-shaped chat completions to
api.githubcopilot.com.

Requires an active Copilot subscription on the signed-in account
(individual / business / enterprise); the token exchange fails with a
clear message otherwise.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import AsyncIterator

import aiohttp

from . import base
from .. import secrets

log = logging.getLogger("switchbay.llm.copilot")

ID = "github_copilot"
LABEL = "GitHub Copilot"
DEFAULT_MODEL = "gpt-4o"
DEFAULT_TIMEOUT_S = 300.0

# The public client id GitHub's official Copilot editor plugins use
# for the device flow. Public by design (device flow has no secret).
CLIENT_ID = "Iv1.b507a08c87ecfe98"

_DEVICE_CODE_URL = "https://github.com/login/device/code"
_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
_COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
_API_BASE = "https://api.githubcopilot.com"

# ── Enterprise hosts ────────────────────────────────────────────────
# The device flow above is hardcoded to github.com, which is wrong for
# two populations:
#
#  * **GitHub Enterprise Cloud with data residency** (`<slug>.ghe.com`)
#    and **GitHub Enterprise Server** — these are separate deployments
#    with their own OAuth endpoints. Sending a github.com device code
#    there can't work.
#  * **Enterprise Managed Users (EMU)** on github.com — the account is
#    provisioned by the customer's IdP, so the generic github.com
#    sign-in page (password / Google) is not their login path. They have
#    to authenticate through their enterprise's SSO URL first; the
#    device flow then binds to the already-authenticated session. This
#    is the case that looks like "the login screen has no SSO option" —
#    the flow is fine, but it points at the wrong front door.
#
# The host is stored next to the token because the Copilot bearer
# exchange and the API base have to keep agreeing with whatever host
# minted the OAuth token.

DEFAULT_HOST = "github.com"
_HOST_KEY = f"{ID}_host"


def _normalize_host(host: str | None) -> str:
    """Accept 'acme.ghe.com', 'https://acme.ghe.com/', 'github.com'."""
    h = (host or "").strip()
    if not h:
        return DEFAULT_HOST
    h = re.sub(r"^https?://", "", h).strip("/")
    return h.split("/", 1)[0].lower() or DEFAULT_HOST


def _is_dotcom(host: str) -> bool:
    return _normalize_host(host) == DEFAULT_HOST


def get_host() -> str:
    """The GitHub host this install signs in against."""
    return _normalize_host(secrets.get(_HOST_KEY) or DEFAULT_HOST)


def set_host(host: str | None) -> str:
    h = _normalize_host(host)
    if h == DEFAULT_HOST:
        secrets.delete_key(_HOST_KEY)
    else:
        secrets.set_key(_HOST_KEY, h)
    _bearer_cache.clear()
    return h


def _endpoints(host: str | None = None) -> dict[str, str]:
    """OAuth + API endpoints for a GitHub host.

    github.com keeps its well-known hostnames. GHE.com and GHES put the
    REST API under `api.<host>` and `<host>/api/v3` respectively, and
    serve Copilot from `api.<host>`-style subdomains.
    """
    h = _normalize_host(host or get_host())
    if _is_dotcom(h):
        return {
            "host": h,
            "device_code": _DEVICE_CODE_URL,
            "access_token": _ACCESS_TOKEN_URL,
            "copilot_token": _COPILOT_TOKEN_URL,
            "api_base": _API_BASE,
            "sso_hint": "https://github.com/enterprises/<your-enterprise>/sso",
        }
    if h.endswith(".ghe.com"):
        # Enterprise Cloud with data residency.
        return {
            "host": h,
            "device_code": f"https://{h}/login/device/code",
            "access_token": f"https://{h}/login/oauth/access_token",
            "copilot_token": f"https://api.{h}/copilot_internal/v2/token",
            "api_base": f"https://api.copilot.{h}",
            "sso_hint": f"https://{h}/login",
        }
    # GitHub Enterprise Server.
    return {
        "host": h,
        "device_code": f"https://{h}/login/device/code",
        "access_token": f"https://{h}/login/oauth/access_token",
        "copilot_token": f"https://{h}/api/v3/copilot_internal/v2/token",
        "api_base": f"https://{h}/api/v3/copilot",
        "sso_hint": f"https://{h}/login",
    }


_EDITOR_HEADERS = {
    "Editor-Version": "vscode/1.99.0",
    "Editor-Plugin-Version": "copilot-chat/0.26.0",
    "Copilot-Integration-Id": "vscode-chat",
    "User-Agent": "switchbay",
}

PROVIDER = {
    "id": ID,
    "label": LABEL,
    "category": "subscription",
    "default_model": DEFAULT_MODEL,
    "auth_help": (
        "Sign in with GitHub (browser login). Needs an active Copilot "
        "subscription. Enterprise-managed (EMU) accounts must sign in to "
        "their enterprise SSO first — the generic GitHub login page "
        "won't list your provider. GitHub Enterprise Server / ghe.com: "
        "set the host in the sign-in panel."
    ),
    "auth_flow": "github_device",  # Settings renders the sign-in button
    "model_suggestions": [
        "gpt-4o",
        "gpt-4o-mini",
        "o3-mini",
        "claude-sonnet-4",
    ],
    "capabilities": {
        "chat": True,
        "streaming": True,
        "tools": False,
        # Execution surface — see base.CAPABILITY_NOTES.
        # HTTP: switchbay tool registry only.
        "shell": False,
        "file_write": False,
        "key_validation": True,
    },
}


def has_key() -> bool:
    return secrets.has(ID)


# ── Device-flow login (driven by the daemon's /api/copilot/login) ──


async def device_code(host: str | None = None) -> dict:
    """Step 1: get {device_code, user_code, verification_uri,
    interval, expires_in}.

    `host` targets an enterprise deployment; omitted means github.com.
    The resolved host rides back in the result so the poller and the
    bearer exchange stay on the same deployment.
    """
    eps = _endpoints(host)
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.post(
            eps["device_code"],
            headers={"Accept": "application/json"},
            data={"client_id": CLIENT_ID, "scope": "read:user"},
        ) as resp:
            body = await resp.json(content_type=None)
    if resp.status != 200 or "device_code" not in body:
        raise base.ProviderError(
            f"{eps['host']} device-code request failed: {body}",
            code="http", status=resp.status,
        )
    body = dict(body)
    body["host"] = eps["host"]
    body["sso_hint"] = eps["sso_hint"]
    return body


async def poll_for_token(device: dict) -> None:
    """Step 2: poll until the user authorizes in the browser, then
    persist the OAuth token. Raises ProviderError on denial/expiry."""
    eps = _endpoints(device.get("host"))
    interval = max(int(device.get("interval") or 5), 5)
    deadline = time.time() + min(int(device.get("expires_in") or 900), 900)
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        while time.time() < deadline:
            await asyncio.sleep(interval)
            async with s.post(
                eps["access_token"],
                headers={"Accept": "application/json"},
                data={
                    "client_id": CLIENT_ID,
                    "device_code": device["device_code"],
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
            ) as resp:
                body = await resp.json(content_type=None)
            err = body.get("error")
            if err == "authorization_pending":
                continue
            if err == "slow_down":
                interval += 5
                continue
            if err:
                raise base.ProviderError(
                    _auth_error_help(err, eps), code="auth",
                )
            token = body.get("access_token")
            if token:
                secrets.set_key(ID, token)
                set_host(eps["host"])
                _bearer_cache.clear()
                return
    raise base.ProviderError(
        f"{eps['host']} sign-in timed out — the code expired before it "
        "was entered. Start the sign-in again.",
        code="auth",
    )


def _auth_error_help(err: str, eps: dict[str, str]) -> str:
    """Turn GitHub's terse device-flow errors into something actionable.

    `access_denied` on an enterprise-managed account usually means the
    user authorized as the wrong identity — the generic sign-in page
    doesn't offer their IdP, so they land as a personal account with no
    Copilot seat. Say so, rather than "sign-in failed".
    """
    if err in ("access_denied", "unauthorized_client", "incorrect_client_credentials"):
        return (
            f"{eps['host']} sign-in was denied ({err}). If your account is "
            "managed by an organisation (Enterprise Managed User), sign in "
            f"to your enterprise first at {eps['sso_hint']} — the generic "
            "GitHub login page won't offer your SSO provider — then start "
            "the sign-in again. Otherwise check the account has an active "
            "Copilot subscription."
        )
    if err == "expired_token":
        return f"{eps['host']} sign-in expired before the code was entered — try again."
    return f"{eps['host']} sign-in failed: {err}"


def sign_out() -> None:
    secrets.delete_key(ID)
    secrets.delete_key(_HOST_KEY)
    _bearer_cache.clear()


# ── Copilot bearer exchange (short-lived; cached) ──────────────────

_bearer_cache: dict = {}


async def _bearer() -> str:
    now = time.time()
    if _bearer_cache.get("token") and _bearer_cache.get("exp", 0) - 60 > now:
        return _bearer_cache["token"]
    oauth = secrets.get(ID)
    if not oauth:
        raise base.ProviderError(
            "GitHub Copilot isn't signed in — use the Sign in button "
            "in Settings.",
            code="auth",
        )
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.get(
            _endpoints()["copilot_token"],
            headers={
                "Authorization": f"token {oauth}",
                "Accept": "application/json",
                **_EDITOR_HEADERS,
            },
        ) as resp:
            body = await resp.json(content_type=None)
            status = resp.status
    if status == 401:
        raise base.ProviderError(
            "GitHub token was revoked — sign in again in Settings.",
            code="auth",
        )
    if status == 403 or not body.get("token"):
        raise base.ProviderError(
            "This GitHub account has no active Copilot subscription "
            "(or your organization hasn't enabled it).",
            code="auth", status=status,
        )
    _bearer_cache["token"] = body["token"]
    _bearer_cache["exp"] = float(body.get("expires_at") or (now + 600))
    return body["token"]


def _http_error(status: int, text: str) -> base.ProviderError:
    code: base.ErrorCode = (
        "auth" if status in (401, 403) else
        "model-not-found" if status == 404 else
        "rate-limit" if status == 429 else
        "server" if status >= 500 else
        "http"
    )
    msg = (text or "").strip()[:400] or f"HTTP {status}"
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict) and err.get("message"):
                msg = str(err["message"])
    except (ValueError, TypeError):
        pass
    return base.ProviderError(
        f"Copilot: {msg}", code=code, status=status,
        retryable=code in ("server", "rate-limit"),
    )


def _to_openai_messages(messages: list[dict], system: str | None) -> list[dict]:
    out: list[dict] = []
    if system:
        out.append({"role": "system", "content": system})
    for m in messages:
        role = m.get("role") or "user"
        content = m.get("content")
        out.append({
            "role": role,
            "content": content if isinstance(content, (str, list)) else str(content or ""),
        })
    return out


async def chat_stream(req: base.ChatRequest) -> AsyncIterator[base.ChunkEvent]:
    bearer = await _bearer()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {bearer}",
        **_EDITOR_HEADERS,
    }
    body: dict = {
        "model": req.model or DEFAULT_MODEL,
        "messages": _to_openai_messages(req.messages, req.system),
        "stream": True,
    }
    if req.temperature is not None:
        body["temperature"] = req.temperature
    if req.max_tokens:
        body["max_tokens"] = req.max_tokens

    timeout = aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT_S)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{_endpoints()['api_base']}/chat/completions", headers=headers, json=body,
            ) as resp:
                if resp.status != 200:
                    raise _http_error(resp.status, await resp.text())
                async for chunk in _parse_sse(resp.content):
                    yield chunk
    except aiohttp.ClientConnectionError as e:
        raise base.ProviderError(
            "Could not reach api.githubcopilot.com",
            code="network", retryable=True, cause=e,
        ) from e
    except TimeoutError as e:
        raise base.ProviderError(
            f"Copilot request timed out after {int(DEFAULT_TIMEOUT_S)}s",
            code="timeout", retryable=True, cause=e,
        ) from e


async def _parse_sse(content) -> AsyncIterator[base.ChunkEvent]:
    """Copilot speaks the OpenAI SSE dialect."""
    input_tokens: int | None = None
    output_tokens: int | None = None
    stop_reason: str | None = None
    async for raw in content:
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line.startswith("data: "):
            continue
        payload = line[6:]
        if not payload or payload == "[DONE]":
            if payload == "[DONE]":
                break
            continue
        try:
            evt = json.loads(payload)
        except json.JSONDecodeError:
            continue
        for choice in evt.get("choices") or []:
            delta = choice.get("delta") or {}
            text = delta.get("content")
            if isinstance(text, str) and text:
                yield base.TextChunk(text=text)
            fr = choice.get("finish_reason")
            if isinstance(fr, str):
                stop_reason = fr
        usage = evt.get("usage") or {}
        if "prompt_tokens" in usage:
            input_tokens = usage["prompt_tokens"]
        if "completion_tokens" in usage:
            output_tokens = usage["completion_tokens"]
    yield base.DoneChunk(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        stop_reason=stop_reason,
    )


async def list_models() -> list[str]:
    """Models the subscription can use — GET /models. Empty on any
    failure so the UI falls back to suggestions."""
    try:
        bearer = await _bearer()
    except base.ProviderError:
        return []
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.get(
                f"{_endpoints()['api_base']}/models",
                headers={"Authorization": f"Bearer {bearer}", **_EDITOR_HEADERS},
            ) as resp:
                if resp.status != 200:
                    return []
                body = await resp.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError):
        return []
    items = body.get("data") if isinstance(body, dict) else None
    if not isinstance(items, list):
        return []
    out = []
    for it in items:
        if isinstance(it, dict) and it.get("id"):
            caps = it.get("capabilities") or {}
            if isinstance(caps, dict) and caps.get("type") not in (None, "chat"):
                continue
            out.append(str(it["id"]))
    return sorted(set(out))


async def validate_key(*, workspace: str | None = None) -> bool:
    """The Settings Test button: a successful bearer exchange proves
    both the sign-in and the Copilot subscription."""
    del workspace
    await _bearer()
    return True
