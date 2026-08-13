"""Meta Model API — OpenAI-compatible Chat Completions over SSE.

BYOK sibling of `openai.py` / `xai.py`, pointed at `https://api.meta.ai/v1`.
The subscription "Muse Code" CLI path is a separate provider
(`muse_code.py`) — same vendor, different auth + transport.

Docs (2026-08): https://dev.meta.ai/docs/overview
  · Base URL `https://api.meta.ai/v1`
  · Bearer `MODEL_API_KEY` (keys look like `LLM|…`)
  · Models: muse-spark-1.2 (default), muse-spark-1.1,
    muse-spark-1.2-contributor (discounted; may train on your data)
  · `reasoning_effort`: minimal / low / medium / high / xhigh
    (`none` is a 400 — Muse Spark always reasons)
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

log = logging.getLogger("switchbay.llm.meta")

ID = "meta"
LABEL = "Meta (Muse Spark)"
API_URL = "https://api.meta.ai/v1/chat/completions"
MODELS_URL = "https://api.meta.ai/v1/models"
DEFAULT_MODEL = "muse-spark-1.2"
DEFAULT_TIMEOUT_S = 300.0

PROVIDER = {
    "id": ID,
    "label": LABEL,
    "category": "byok",
    "default_model": DEFAULT_MODEL,
    "key_placeholder": "LLM|…",
    "key_help_url": "https://dev.meta.ai/",
    "model_suggestions": [
        "muse-spark-1.2",
        "muse-spark-1.1",
        "muse-spark-1.2-contributor",
    ],
    "capabilities": {
        "chat": True,
        "streaming": True,
        "tools": True,
        # HTTP: switchbay tool registry only (propose_*/create_report).
        "shell": False,
        "file_write": False,
        "key_validation": True,
        # Multimodal *understanding* is on the API; we don't offer
        # image/video *generation* through Settings → Media.
        "image": False,
        "video": False,
        "voice": False,
    },
}


def has_key() -> bool:
    return secrets.has(ID) or bool(
        os.environ.get("MODEL_API_KEY") or os.environ.get("META_API_KEY")
    )


def _api_key() -> str:
    key = (
        secrets.get(ID)
        or os.environ.get("MODEL_API_KEY")
        or os.environ.get("META_API_KEY")
    )
    if not key:
        raise base.ProviderError(
            "Meta Model API key required. Set it in Settings "
            "(https://dev.meta.ai/).",
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
        f"Meta: {msg}",
        code=code,
        status=status,
        retryable=code in ("rate-limit", "server", "timeout"),
    )


# Muse Spark is a reasoning model. `none` is rejected with HTTP 400.
# Contributor vs standard is a billing/training-tier, not a reasoning gate.


def reasoning_options(model: str | None = None) -> list[dict]:
    del model
    return [
        base.reasoning_option("minimal", "Minimal", "shortest reasoning pass"),
        base.reasoning_option("low", "Low", "light reasoning — faster, cheaper"),
        base.reasoning_option("medium", "Medium", "moderate depth"),
        base.reasoning_option("high", "High", "deep reasoning"),
        base.reasoning_option("xhigh", "Extra high", "maximum reasoning depth"),
    ]


async def chat_stream(req: base.ChatRequest) -> AsyncIterator[base.ChunkEvent]:
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
    # Muse Spark is tuned at temperature 1.0 and is a reasoning model —
    # don't send temperature (docs: leave unset; none isn't supported).
    if req.max_tokens:
        body["max_completion_tokens"] = req.max_tokens
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
            "Could not reach api.meta.ai",
            code="network", retryable=True, cause=e,
        ) from e
    except TimeoutError as e:
        raise base.ProviderError(
            f"Request timed out after {int(DEFAULT_TIMEOUT_S)}s",
            code="timeout", retryable=True, cause=e,
        ) from e


async def list_models() -> list[str]:
    """GET /v1/models. Cached daily by model_cache."""
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
    out = [
        it["id"] for it in items
        if isinstance(it, dict) and isinstance(it.get("id"), str)
        and it["id"].lower().startswith("muse-")
    ]
    # Newest-looking first (1.2 before 1.1); contributor last so the
    # standard tier is the obvious pick.
    def _rank(mid: str) -> tuple:
        low = mid.lower()
        contrib = 1 if "contributor" in low else 0
        return (contrib, -len(low), low)
    out.sort(key=_rank)
    return out


async def validate_key(*, workspace: str | None = None) -> bool:
    del workspace
    req = base.ChatRequest(
        messages=[{"role": "user", "content": "ping"}],
        max_tokens=1,
    )
    async for _ in chat_stream(req):
        return True
    return True
