"""xAI (Grok) provider — OpenAI-compatible Chat Completions over SSE.

BYOK pattern (sibling of `openai.py`). xAI's API is OpenAI-compatible,
so this is the same SSE transport pointed at `https://api.x.ai/v1`.
The subscription "Grok Build" CLI path is a separate provider
(`grok_build.py`) — same vendor, different auth + transport — mirroring
how anthropic/claude_code and openai/openai_codex live as siblings.
"""

from __future__ import annotations

import json
import logging
import os
from typing import AsyncIterator

import aiohttp

from .. import secrets
from . import base
from .openai_compat import messages_to_openai, parse_sse, tools_to_openai

log = logging.getLogger("switchbay.llm.xai")

ID = "xai"
LABEL = "xAI Grok"
API_URL = "https://api.x.ai/v1/chat/completions"
MODELS_URL = "https://api.x.ai/v1/models"
DEFAULT_MODEL = "grok-4.5"
DEFAULT_TIMEOUT_S = 300.0

PROVIDER = {
    "id": ID,
    "label": LABEL,
    "category": "byok",
    "default_model": DEFAULT_MODEL,
    "key_placeholder": "xai-…",
    "key_help_url": "https://console.x.ai",
    # Live ids as of 2026-07 (validated against /v1/models). The
    # provider also fetches the live list via list_models(), so this
    # only seeds the picker before the first fetch.
    "model_suggestions": [
        "grok-4.5",
        "grok-4.3",
        "grok-build-0.1",
        "grok-4.20-0309-reasoning",
        "grok-4.20-0309-non-reasoning",
    ],
    "capabilities": {
        "chat": True,
        "streaming": True,
        "tools": True,
        # Execution surface — see base.CAPABILITY_NOTES.
        # HTTP: switchbay tool registry only (propose_*/create_report).
        "shell": False,
        "file_write": False,
        "key_validation": True,
        # Media: Settings → Media generation (see media_settings.CATALOG).
        "image": True,
        "video": True,
        "voice": True,
    },
}


def has_key() -> bool:
    return secrets.has(ID) or bool(os.environ.get("XAI_API_KEY"))


def _api_key() -> str:
    key = secrets.get(ID) or os.environ.get("XAI_API_KEY")
    if not key:
        raise base.ProviderError(
            "xAI API key required. Set it in Settings.",
            code="missing-key",
        )
    return key


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
            err = data.get("error") or {}
            if isinstance(err, dict) and err.get("message"):
                msg = err["message"]
            elif isinstance(data.get("error"), str):
                msg = data["error"]
    except (ValueError, TypeError):
        pass
    return base.ProviderError(
        f"xAI: {msg}",
        code=code,
        status=status,
        retryable=code in ("rate-limit", "server", "timeout"),
    )


# ── Reasoning effort ────────────────────────────────────────────────
# xAI takes an OpenAI-shaped `reasoning_effort` enum. Non-reasoning
# models reject it outright, so the option list is gated on the model
# id rather than advertised provider-wide (see base.REASONING_NOTES).

_NON_REASONING_HINTS = ("non-reasoning", "grok-build")


def reasoning_options(model: str | None = None) -> list[dict]:
    m = (model or DEFAULT_MODEL or "").lower()
    if any(h in m for h in _NON_REASONING_HINTS):
        return []
    return [
        base.reasoning_option(
            "low", "Low", "fast and much cheaper — good for edits and chores"),
        base.reasoning_option(
            "high", "High", "slower, for planning and hard problems"),
    ]


async def chat_stream(req: base.ChatRequest) -> AsyncIterator[base.ChunkEvent]:
    """Stream a chat completion. Yields TextChunks / ToolUseChunks / DoneChunk."""
    model = req.model or DEFAULT_MODEL
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_api_key()}",
    }
    body: dict = {
        "model": model,
        "messages": messages_to_openai(req.messages, req.system),
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    tools = tools_to_openai(req.tools)
    if tools:
        body["tools"] = tools
    # Only send temperature when this model takes no reasoning_effort
    # (non-reasoning family) — reasoning models often reject it.
    if req.temperature is not None and not reasoning_options(model):
        body["temperature"] = req.temperature
    if req.max_tokens:
        body["max_tokens"] = req.max_tokens
    effort = base.coerce_effort(
        req.reasoning_effort, reasoning_options(model))
    if effort:
        body["reasoning_effort"] = effort

    timeout = aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT_S)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(API_URL, headers=headers, json=body) as resp:
                if resp.status != 200:
                    raise _http_error(resp.status, await resp.text())
                async for chunk in parse_sse(resp.content):
                    yield chunk
    except aiohttp.ClientConnectionError as e:
        raise base.ProviderError(
            "Could not reach api.x.ai",
            code="network", retryable=True, cause=e,
        ) from e
    except TimeoutError as e:
        raise base.ProviderError(
            f"Request timed out after {int(DEFAULT_TIMEOUT_S)}s",
            code="timeout", retryable=True, cause=e,
        ) from e


async def list_models() -> list[str]:
    """GET /v1/models (OpenAI-compatible). Cached daily by model_cache."""
    if not has_key():
        return []
    headers = {"Authorization": f"Bearer {_api_key()}"}
    timeout = aiohttp.ClientTimeout(total=10.0)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(MODELS_URL, headers=headers) as resp:
                if resp.status != 200:
                    return []
                body = await resp.json()
    except (aiohttp.ClientConnectionError, TimeoutError, ValueError):
        return []
    items = body.get("data") if isinstance(body, dict) else None
    if not isinstance(items, list):
        return []
    # Keep grok chat/coding models; drop image/video generators
    # (grok-imagine-*) which aren't chat-completion models.
    drop = ("imagine", "image", "video")
    out = [it["id"] for it in items
           if isinstance(it, dict) and isinstance(it.get("id"), str)
           and it["id"].lower().startswith("grok")
           and not any(d in it["id"].lower() for d in drop)]
    out.sort(key=lambda m: (len(m), m))
    return out


async def validate_key(*, workspace: str | None = None) -> bool:
    del workspace
    req = base.ChatRequest(messages=[{"role": "user", "content": "ping"}], max_tokens=1)
    async for _ in chat_stream(req):
        return True
    return True
