"""OpenAI Chat Completions provider — async streaming via SSE.

BYOK pattern. The Codex CLI subscription path is a separate provider
(see `openai_codex.py` once that lands) — same vendor, different auth
and transport, so they live as siblings rather than mode-flags on one
provider.
"""

from __future__ import annotations

import json
import logging
import os
from typing import AsyncIterator

import aiohttp

from .. import secrets
from . import base

log = logging.getLogger("switchbay.llm.openai")

ID = "openai"
LABEL = "OpenAI"
API_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-4.1"
DEFAULT_TIMEOUT_S = 300.0

PROVIDER = {
    "id": ID,
    "label": LABEL,
    "category": "byok",
    "default_model": DEFAULT_MODEL,
    "key_placeholder": "sk-…",
    "key_help_url": "https://platform.openai.com/api-keys",
    "model_suggestions": [
        "gpt-5",
        "gpt-4.1",
        "gpt-4o",
        "gpt-4o-mini",
        "o3",
        "o3-mini",
    ],
    "capabilities": {
        "chat": True,
        "streaming": True,
        "tools": False,           # tool-use plumbing lands later
        # Execution surface — see base.CAPABILITY_NOTES.
        # HTTP: switchbay tool registry only (propose_*/create_report).
        "shell": False,
        "file_write": False,
        "key_validation": True,
        # Media: Settings → Media generation (see media_settings.CATALOG).
        "image": True,
        "video": True,            # Sora when the account has access
        "voice": True,            # TTS + Realtime
    },
}


def has_key() -> bool:
    return secrets.has(ID) or bool(os.environ.get("OPENAI_API_KEY"))


def _api_key() -> str:
    key = secrets.get(ID) or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise base.ProviderError(
            "OpenAI API key required. Set it in Settings.",
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
    except (ValueError, TypeError):
        pass
    return base.ProviderError(
        f"OpenAI: {msg}",
        code=code,
        status=status,
        retryable=code in ("rate-limit", "server", "timeout"),
    )


# ── Reasoning effort ────────────────────────────────────────────────
# `reasoning_effort` is accepted by the reasoning families (o-series,
# gpt-5) and rejected by the plain chat models, so the option list is
# gated on the model id (see base.REASONING_NOTES).

_REASONING_PREFIXES = ("o1", "o3", "o4", "gpt-5")


def _is_reasoning_model(model: str) -> bool:
    m = (model or "").lower().lstrip()
    return any(m.startswith(p) for p in _REASONING_PREFIXES)


def reasoning_options(model: str | None = None) -> list[dict]:
    if not _is_reasoning_model(model or DEFAULT_MODEL or ""):
        return []
    return [
        base.reasoning_option(
            "minimal", "Minimal", "barely thinks — cheapest and fastest"),
        base.reasoning_option("low", "Low", "light reasoning for small edits"),
        base.reasoning_option("medium", "Medium", "the API default"),
        base.reasoning_option("high", "High", "slowest, for hard problems"),
    ]


def _to_openai_messages(
    messages: list[dict], system: str | None,
) -> list[dict]:
    """Translate the canonical {role, content} list into OpenAI's
    chat-completions schema. System prompt slots in as a leading
    `system` message (Anthropic uses a top-level `system` field; we
    centralise on the canonical shape and translate per-provider)."""
    out: list[dict] = []
    if system:
        out.append({"role": "system", "content": system})
    for m in messages:
        role = m.get("role") or "user"
        content = m.get("content")
        # Daemon stores plain strings for chat events; passing through.
        if isinstance(content, str):
            out.append({"role": role, "content": content})
        elif isinstance(content, list):
            # Caller passed pre-shaped blocks (e.g. multi-modal). Send
            # them as-is; OpenAI accepts content arrays for vision.
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
        # `max_completion_tokens` is the newer field; older models still
        # accept `max_tokens`. OpenAI silently ignores either when the
        # other is set, so passing the new one is safe across the board.
        body["max_completion_tokens"] = req.max_tokens
    effort = base.coerce_effort(
        req.reasoning_effort, reasoning_options(req.model or DEFAULT_MODEL))
    if effort:
        body["reasoning_effort"] = effort

    timeout = aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT_S)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(API_URL, headers=headers, json=body) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise _http_error(resp.status, text)
                async for chunk in _parse_sse(resp.content):
                    yield chunk
    except aiohttp.ClientConnectionError as e:
        raise base.ProviderError(
            "Could not reach api.openai.com",
            code="network", retryable=True, cause=e,
        ) from e
    except TimeoutError as e:
        raise base.ProviderError(
            f"Request timed out after {int(DEFAULT_TIMEOUT_S)}s",
            code="timeout", retryable=True, cause=e,
        ) from e


async def _parse_sse(content) -> AsyncIterator[base.ChunkEvent]:
    """Parse OpenAI's SSE stream. Each `data: {…}` line is a delta
    with `choices[0].delta.content` text fragments. The terminal
    `data: [DONE]` ends the stream; the preceding chunk usually
    carries `usage` and `choices[0].finish_reason`."""
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
        choices = evt.get("choices") or []
        for choice in choices:
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
    """Query GET /v1/models for the keys the user can actually use.
    Filters to chat-capable model ids — drops embedding/whisper/dall-e
    families and old completion-only models. Cached daily by
    model_cache so this doesn't hit the API on every providers fetch."""
    if not has_key():
        return []
    headers = {"Authorization": f"Bearer {_api_key()}"}
    timeout = aiohttp.ClientTimeout(total=10.0)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                "https://api.openai.com/v1/models", headers=headers,
            ) as resp:
                if resp.status != 200:
                    return []
                body = await resp.json()
    except (aiohttp.ClientConnectionError, TimeoutError, ValueError):
        return []
    items = body.get("data") if isinstance(body, dict) else None
    if not isinstance(items, list):
        return []
    raw: list[str] = []
    for it in items:
        if isinstance(it, dict) and isinstance(it.get("id"), str):
            raw.append(it["id"])
    # OpenAI's /v1/models returns hundreds of ids including embeddings,
    # whisper, dall-e, deprecated dated snapshots, and base completion
    # models. Filter to the chat-completion families our PROVIDER
    # actually targets. Keep root names (e.g. "gpt-4o") plus their
    # date-suffixed snapshots so users can pin to a specific revision.
    keep_prefixes = ("gpt-", "o1", "o3", "o4")
    drop_substrings = (
        "embedding", "whisper", "tts", "dall-e", "moderation",
        "audio", "instruct", "babbage", "davinci", "search", "realtime",
    )
    chat = []
    for mid in raw:
        low = mid.lower()
        if not any(low.startswith(p) for p in keep_prefixes):
            continue
        if any(s in low for s in drop_substrings):
            continue
        chat.append(mid)
    # Most useful ordering: shorter (canonical) names first, dated
    # snapshots after.
    chat.sort(key=lambda m: (len(m), m))
    return chat


async def validate_key(*, workspace: str | None = None) -> bool:
    """Cheap ping: ask for max_completion_tokens=1 and read the first
    chunk. Used by Settings → Test."""
    del workspace
    req = base.ChatRequest(
        messages=[{"role": "user", "content": "ping"}],
        max_tokens=1,
    )
    async for _ in chat_stream(req):
        return True
    return True
