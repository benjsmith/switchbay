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
near expiry) and talk OpenAI-shaped chat completions or the Responses API to
api.githubcopilot.com. The model catalog's ``supported_endpoints``
picks the path; a 400 ``unsupported_api_for_model`` retries the
other.

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
from .openai_compat import (
    messages_to_openai,
    messages_to_responses,
    parse_responses_sse,
    parse_sse,
    tools_to_openai,
    tools_to_responses,
)
from .. import secrets

log = logging.getLogger("switchbay.llm.copilot")

ID = "github_copilot"
LABEL = "GitHub Copilot"
DEFAULT_MODEL = "gpt-5.4"
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


_ENTERPRISE_SLUG_RE = re.compile(
    r"(?:^|/)enterprises/([A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)",
    re.I,
)
_SSO_SLUG_KEY = f"{ID}_sso_slug"


def parse_github_host_input(raw: str | None) -> tuple[str, str | None]:
    """Parse a host field value into (host, enterprise_slug|None).

    Accepts bare hosts (`acme.ghe.com`), URLs, and EMU SSO URLs like
    `https://github.com/enterprises/<slug>/sso`. Strips leading `www.`.
    EMU accounts live on github.com — only the SSO door differs, so a
    github.com enterprises URL keeps host=github.com and returns the slug.
    """
    h = (raw or "").strip()
    if not h:
        return DEFAULT_HOST, None
    h = re.sub(r"^https?://", "", h, flags=re.I).strip("/")
    h = re.sub(r"^www\.", "", h, flags=re.I)
    slug_m = _ENTERPRISE_SLUG_RE.search(h)
    slug = slug_m.group(1) if slug_m else None
    host_part = h.split("/", 1)[0].lower() or DEFAULT_HOST
    if host_part in ("github.com", "www.github.com"):
        return DEFAULT_HOST, slug
    return host_part, slug


def _normalize_host(host: str | None) -> str:
    """Accept 'acme.ghe.com', 'https://acme.ghe.com/', 'github.com'."""
    return parse_github_host_input(host)[0]


def _is_dotcom(host: str) -> bool:
    return _normalize_host(host) == DEFAULT_HOST


def get_host() -> str:
    """The GitHub host this install signs in against."""
    from .. import admin_policy
    if admin_policy.copilot_lock_host():
        return _normalize_host(admin_policy.copilot_host())
    return _normalize_host(secrets.get(_HOST_KEY) or admin_policy.copilot_host() or DEFAULT_HOST)


def get_sso_slug() -> str | None:
    val = secrets.get(_SSO_SLUG_KEY)
    return str(val) if val else None


def set_host(host: str | None, *, sso_slug: str | None = None) -> str:
    """Persist host (+ optional EMU enterprise slug for SSO hints)."""
    h, parsed_slug = parse_github_host_input(host)
    slug = sso_slug if sso_slug is not None else parsed_slug
    if h == DEFAULT_HOST:
        secrets.delete_key(_HOST_KEY)
    else:
        secrets.set_key(_HOST_KEY, h)
    if slug and h == DEFAULT_HOST:
        secrets.set_key(_SSO_SLUG_KEY, slug)
    else:
        secrets.delete_key(_SSO_SLUG_KEY)
    _bearer_cache.clear()
    _model_endpoints.clear()
    _learned_kind.clear()
    return h


def _sso_uri(host: str, slug: str | None = None) -> str:
    if _is_dotcom(host):
        s = slug or get_sso_slug()
        if s:
            return f"https://github.com/enterprises/{s}/sso"
        return "https://github.com/enterprises/<your-enterprise>/sso"
    return f"https://{host}/login"


def _endpoints(host: str | None = None, *, sso_slug: str | None = None) -> dict[str, str]:
    """OAuth + API endpoints for a GitHub host.

    github.com keeps its well-known hostnames. GHE.com and GHES put the
    REST API under `api.<host>` and `<host>/api/v3` respectively, and
    serve Copilot from `api.<host>`-style subdomains.
    """
    h, parsed = parse_github_host_input(host or get_host())
    slug = sso_slug if sso_slug is not None else (parsed or get_sso_slug())
    if _is_dotcom(h):
        return {
            "host": h,
            "device_code": _DEVICE_CODE_URL,
            "access_token": _ACCESS_TOKEN_URL,
            "copilot_token": _COPILOT_TOKEN_URL,
            "api_base": _API_BASE,
            "sso_hint": _sso_uri(h, slug),
            "sso_uri": _sso_uri(h, slug) if slug else "",
            "enterprise_slug": slug or "",
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
            "sso_uri": f"https://{h}/login",
            "enterprise_slug": "",
        }
    # GitHub Enterprise Server.
    return {
        "host": h,
        "device_code": f"https://{h}/login/device/code",
        "access_token": f"https://{h}/login/oauth/access_token",
        "copilot_token": f"https://{h}/api/v3/copilot_internal/v2/token",
        "api_base": f"https://{h}/api/v3/copilot",
        "sso_hint": f"https://{h}/login",
        "sso_uri": f"https://{h}/login",
        "enterprise_slug": "",
    }


# Copilot's HTTP API is an IDE product surface. Enterprise and newer
# models reject requests that omit IDE auth headers or that look like
# an old vscode-chat client. These versions track current VS Code
# Copilot Chat (in-tree extension 0.65, engines ^1.137). We still
# identify as vscode-chat because that is the integration id the API
# accepts; User-Agent matches the plugin, not a custom product name.
_EDITOR_VERSION = "vscode/1.137.0"
_PLUGIN_VERSION = "copilot-chat/0.65.0"


def _editor_headers(*, agent: bool | None = None) -> dict[str, str]:
    """IDE identity (+ optional turn intent).

    ``agent=True`` for tool-using turns (rail / curate). ``agent=False``
    for a plain chat completion. ``None`` for token/catalog fetches
    that are not a conversation turn.
    """
    plugin_rev = _PLUGIN_VERSION.split("/", 1)[-1]
    headers = {
        "Editor-Version": _EDITOR_VERSION,
        "Editor-Plugin-Version": _PLUGIN_VERSION,
        "Copilot-Integration-Id": "vscode-chat",
        "User-Agent": f"GitHubCopilotChat/{plugin_rev}",
    }
    if agent is True:
        headers["Openai-Intent"] = "conversation-agent"
        headers["X-Initiator"] = "agent"
    elif agent is False:
        headers["Openai-Intent"] = "conversation-edits"
        headers["X-Initiator"] = "user"
    return headers

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
    # Cold-cache fallback for the picker and Auto diversity when
    # GET /models has not been fetched yet. Live catalog is
    # authoritative (plan- and policy-dependent). Ids match
    # api.githubcopilot.com as of 2026-08 (docs.github.com Copilot
    # supported models). gpt-4o / o3-mini are retired on this surface.
    "model_suggestions": [
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5.5",
        "claude-sonnet-4.6",
        "claude-sonnet-5",
        "claude-opus-5",
        "claude-haiku-4.5",
        "gemini-3.1-pro-preview",
        "gemini-3.5-flash",
        "grok-4.6",
    ],
    "capabilities": {
        "chat": True,
        "streaming": True,
        "tools": True,
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

    `host` targets an enterprise deployment or an EMU SSO URL
    (`github.com/enterprises/<slug>`); omitted means github.com.
    The resolved host rides back in the result so the poller and the
    bearer exchange stay on the same deployment.
    """
    h, slug = parse_github_host_input(host)
    eps = _endpoints(h, sso_slug=slug)
    # Remember slug for later retries / status while still on github.com.
    if slug and h == DEFAULT_HOST:
        secrets.set_key(_SSO_SLUG_KEY, slug)
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
    body["sso_uri"] = eps.get("sso_uri") or ""
    body["enterprise_slug"] = eps.get("enterprise_slug") or ""
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
                set_host(
                    eps["host"],
                    sso_slug=get_sso_slug() or device.get("enterprise_slug") or None,
                )
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
    secrets.delete_key(_SSO_SLUG_KEY)
    _bearer_cache.clear()
    _model_endpoints.clear()
    _learned_kind.clear()


# ── Copilot bearer exchange (short-lived; cached) ──────────────────

_bearer_cache: dict = {}
# Last GET /models endpoint sets, plus kinds learned from a 400 that
# said the other path is required. Survives until sign-out / host change.
_model_endpoints: dict[str, frozenset[str]] = {}
_learned_kind: dict[str, str] = {}


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
                **_editor_headers(),
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


def _is_gpt5_family(model: str) -> bool:
    m = (model or "").lower()
    return m.startswith(("gpt-5", "o1", "o3", "o4"))


def _endpoint_list(item: dict) -> list[str]:
    """Copilot puts ``supported_endpoints`` on the row, sometimes nested
    under ``capabilities``. Paths may be ``/chat/completions``,
    ``/responses``, or both."""
    caps = item.get("capabilities") if isinstance(item.get("capabilities"), dict) else {}
    raw = (
        item.get("supported_endpoints")
        or caps.get("supported_endpoints")
        or caps.get("endpoints")
        or []
    )
    if not isinstance(raw, list):
        return []
    return [str(e) for e in raw if e]


def _has_chat_completions(endpoints: list[str] | frozenset[str]) -> bool:
    return any("chat/completions" in e.lower() for e in endpoints)


def _has_responses(endpoints: list[str] | frozenset[str]) -> bool:
    return any("responses" in e.lower() for e in endpoints)


def _is_picker_model(item: dict) -> bool:
    """True if this /models row should appear in our chat picker.

    VS Code lists anything with ``model_picker_enabled``. We include
    chat/completions *and* responses-only chat rows so newer Copilot
    models (Codex / GPT-5.x that refuse chat/completions) are
    selectable. Tool-less and non-chat rows still 400 on the rail.
    """
    caps = item.get("capabilities") if isinstance(item.get("capabilities"), dict) else {}
    ctype = str(caps.get("type") or "chat").lower()
    if ctype != "chat":
        return False
    if item.get("model_picker_enabled") is False:
        return False
    if caps.get("model_picker_enabled") is False:
        return False
    endpoints = _endpoint_list(item)
    if endpoints and not (
        _has_chat_completions(endpoints) or _has_responses(endpoints)
    ):
        return False
    supports = caps.get("supports") if isinstance(caps.get("supports"), dict) else {}
    if supports.get("tool_calls") is False:
        return False
    return True


def _supports_chat_completions(item: dict) -> bool:
    """True if this row can be POSTed to ``/chat/completions``."""
    if not _is_picker_model(item):
        return False
    endpoints = _endpoint_list(item)
    if endpoints and not _has_chat_completions(endpoints):
        return False
    return True


def _ingest_catalog(items: list) -> list[str]:
    """Remember per-model endpoints and return picker ids."""
    new_eps: dict[str, frozenset[str]] = {}
    out: list[str] = []
    for it in items:
        if not isinstance(it, dict) or not it.get("id"):
            continue
        mid = str(it["id"])
        eps = _endpoint_list(it)
        if eps:
            new_eps[mid] = frozenset(e.lower() for e in eps)
        if _is_picker_model(it):
            out.append(mid)
    _model_endpoints.clear()
    _model_endpoints.update(new_eps)
    return sorted(set(out))


def _preferred_kind(model: str) -> str:
    """``chat`` or ``responses``. Prefer chat when the catalog lists it."""
    learned = _learned_kind.get(model)
    if learned in ("chat", "responses"):
        return learned
    eps = _model_endpoints.get(model)
    if not eps:
        return "chat"
    if _has_chat_completions(eps):
        return "chat"
    if _has_responses(eps):
        return "responses"
    return "chat"


def _endpoint_order(model: str) -> tuple[str, str]:
    first = _preferred_kind(model)
    second = "chat" if first == "responses" else "responses"
    return first, second


def _learn_kind(model: str, kind: str) -> None:
    if kind in ("chat", "responses"):
        _learned_kind[model] = kind


def _is_wrong_endpoint_error(text: str) -> bool:
    low = (text or "").lower()
    if "unsupported_api_for_model" in low:
        return True
    if "not accessible via the /chat/completions" in low:
        return True
    if "not accessible via the /responses" in low:
        return True
    if "does not support" in low and "/chat/completions" in low:
        return True
    if "does not support" in low and "/responses" in low:
        return True
    if "use the responses api" in low:
        return True
    return False


def _build_chat_body(req: base.ChatRequest, model: str) -> dict:
    tools = tools_to_openai(req.tools)
    body: dict = {
        "model": model,
        "messages": messages_to_openai(req.messages, req.system),
        "stream": True,
    }
    if tools:
        body["tools"] = tools
    # GPT-5 / o-series reject temperature and want max_completion_tokens.
    if req.temperature is not None and not _is_gpt5_family(model):
        body["temperature"] = req.temperature
    if req.max_tokens:
        if _is_gpt5_family(model):
            body["max_completion_tokens"] = req.max_tokens
        else:
            body["max_tokens"] = req.max_tokens
    return body


def _build_responses_body(req: base.ChatRequest, model: str) -> dict:
    instructions, input_items = messages_to_responses(req.messages, req.system)
    tools = tools_to_responses(req.tools)
    body: dict = {
        "model": model,
        "input": input_items,
        "stream": True,
        "store": False,
    }
    if instructions:
        body["instructions"] = instructions
    if tools:
        body["tools"] = tools
    if req.temperature is not None and not _is_gpt5_family(model):
        body["temperature"] = req.temperature
    if req.max_tokens:
        body["max_output_tokens"] = req.max_tokens
    return body


async def chat_stream(req: base.ChatRequest) -> AsyncIterator[base.ChunkEvent]:
    bearer = await _bearer()
    model = req.model or DEFAULT_MODEL
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {bearer}",
        **_editor_headers(agent=bool(req.tools)),
    }
    timeout = aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT_S)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            kinds = _endpoint_order(model)
            last_err: base.ProviderError | None = None
            for i, kind in enumerate(kinds):
                path = "/responses" if kind == "responses" else "/chat/completions"
                body = (
                    _build_responses_body(req, model)
                    if kind == "responses"
                    else _build_chat_body(req, model)
                )
                async with session.post(
                    f"{_endpoints()['api_base']}{path}",
                    headers=headers, json=body,
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        err = _http_error(resp.status, text)
                        if i == 0 and _is_wrong_endpoint_error(text):
                            other = kinds[1]
                            _learn_kind(model, other)
                            log.info(
                                "Copilot %s rejected %s; retrying %s",
                                model, path, other,
                            )
                            last_err = err
                            continue
                        raise err
                    parser = parse_responses_sse if kind == "responses" else parse_sse
                    async for chunk in parser(resp.content):
                        yield chunk
                    return
            if last_err is not None:
                raise last_err
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
                headers={"Authorization": f"Bearer {bearer}", **_editor_headers()},
            ) as resp:
                if resp.status != 200:
                    return []
                body = await resp.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError):
        return []
    items = body.get("data") if isinstance(body, dict) else None
    if not isinstance(items, list):
        return []
    return _ingest_catalog(items)


async def validate_key(*, workspace: str | None = None) -> bool:
    """The Settings Test button: a successful bearer exchange proves
    both the sign-in and the Copilot subscription."""
    del workspace
    await _bearer()
    return True
