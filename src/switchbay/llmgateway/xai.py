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
        "tools": False,           # tool-use plumbing lands later (matches openai)
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


def _to_openai_messages(messages: list[dict], system: str | None) -> list[dict]:
    out: list[dict] = []
    if system:
        out.append({"role": "system", "content": system})
    for m in messages:
        role = m.get("role") or "user"
        content = m.get("content")
        if isinstance(content, (str, list)):
            out.append({"role": role, "content": content})
        else:
            out.append({"role": role, "content": str(content or "")})
    return out


async def chat_stream(req: base.ChatRequest) -> AsyncIterator[base.ChunkEvent]:
    """Stream a chat completion. Yields TextChunks then a final DoneChunk."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_api_key()}",
    }
    body: dict = {
        "model": req.model or DEFAULT_MODEL,
        "messages": _to_openai_messages(req.messages, req.system),
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if req.temperature is not None:
        body["temperature"] = req.temperature
    if req.max_tokens:
        body["max_tokens"] = req.max_tokens

    timeout = aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT_S)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(API_URL, headers=headers, json=body) as resp:
                if resp.status != 200:
                    raise _http_error(resp.status, await resp.text())
                async for chunk in _parse_sse(resp.content):
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


async def _parse_sse(content) -> AsyncIterator[base.ChunkEvent]:
    input_tokens: int | None = None
    output_tokens: int | None = None
    stop_reason: str | None = None
    async for raw in content:
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line.startswith("data: "):
            continue
        payload = line[6:]
        if not payload:
            continue
        if payload == "[DONE]":
            break
        try:
            evt = json.loads(payload)
        except json.JSONDecodeError:
            continue
        for choice in evt.get("choices") or []:
            delta = choice.get("delta") or {}
            text = delta.get("content")
            if isinstance(text, str) and text:
                yield base.TextChunk(text=text)
            # Grok reasoning models surface chain-of-thought here.
            rzn = delta.get("reasoning_content")
            if isinstance(rzn, str) and rzn:
                yield base.ReasoningChunk(text=rzn)
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
