"""Anthropic Claude provider — async streaming via Server-Sent Events.

Tool use is NOT yet wired (lands in step J.2 alongside the other
providers). Today: messages-in, text-stream-out.
"""

from __future__ import annotations

import json
import logging
import os
from typing import AsyncIterator

import aiohttp

from .. import secrets
from . import base

log = logging.getLogger("switchbay.llm.anthropic")

ID = "anthropic"
# "Claude (API)" — the raw Messages API (bring-your-own-key), distinct
# from "Claude Code" (the CLI, provider id `claude-code`). The distinction
# matters for the user: the API arm has NO shell, so it can only PROPOSE
# via the switchbay tool registry, while Claude Code runs a sandboxed
# shell and can execute curation. A bare "Claude" label collided with
# "Claude Code" and made the CE-action capability gate read like it was
# refusing Claude-the-model.
LABEL = "Claude (API)"
API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-4-6"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_TIMEOUT_S = 300.0  # generous; long replies + tool-using turns

PROVIDER = {
    "id": ID,
    "label": LABEL,
    "category": "byok",
    "default_model": DEFAULT_MODEL,
    "key_placeholder": "sk-ant-…",
    "key_help_url": "https://console.anthropic.com/settings/keys",
    "model_suggestions": [
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-sonnet-4-6",
        "claude-haiku-4-5-20251001",
    ],
    "capabilities": {
        "chat": True,
        "streaming": True,
        "tools": False,           # J.2
        # Execution surface — see base.CAPABILITY_NOTES.
        # HTTP: switchbay tool registry only (propose_*/create_report).
        "shell": False,
        "file_write": False,
        "key_validation": True,
    },
}


def has_key() -> bool:
    return secrets.has(ID) or bool(os.environ.get("ANTHROPIC_API_KEY"))


def _api_key() -> str:
    key = secrets.get(ID) or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise base.ProviderError(
            "Claude API key required. Set it in Settings.",
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
        f"Claude: {msg}",
        code=code,
        status=status,
        retryable=code in ("rate-limit", "server", "timeout"),
    )


async def chat_stream(req: base.ChatRequest) -> AsyncIterator[base.ChunkEvent]:
    """Stream a chat completion. Yields TextChunks then a final DoneChunk."""
    headers = {
        "Content-Type": "application/json",
        "x-api-key": _api_key(),
        "anthropic-version": ANTHROPIC_VERSION,
    }
    body: dict = {
        "model": req.model or DEFAULT_MODEL,
        "max_tokens": req.max_tokens,
        "messages": req.messages,
        "stream": True,
    }
    if req.system:
        body["system"] = req.system
    if req.temperature is not None:
        body["temperature"] = req.temperature
    if req.tools:
        body["tools"] = req.tools

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
            "Could not reach api.anthropic.com",
            code="network", retryable=True, cause=e,
        ) from e
    except TimeoutError as e:
        raise base.ProviderError(
            f"Request timed out after {int(DEFAULT_TIMEOUT_S)}s",
            code="timeout", retryable=True, cause=e,
        ) from e


async def _parse_sse(content) -> AsyncIterator[base.ChunkEvent]:
    """Parse Anthropic's SSE stream. Yields TextChunk per text delta,
    ToolUseChunk per completed tool_use block, and a final DoneChunk
    with usage + stop_reason."""
    input_tokens: int | None = None
    output_tokens: int | None = None
    stop_reason: str | None = None

    # Per-block accumulation state (Anthropic streams content_block_*
    # events; we collect input_json deltas until content_block_stop).
    block_kind: dict[int, str] = {}
    block_tool_id: dict[int, str] = {}
    block_tool_name: dict[int, str] = {}
    block_input_json: dict[int, list[str]] = {}

    async for raw in content:
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line.startswith("data: "):
            continue
        payload = line[6:]
        if not payload:
            continue
        try:
            evt = json.loads(payload)
        except json.JSONDecodeError:
            continue

        etype = evt.get("type")
        if etype == "message_start":
            usage = (evt.get("message") or {}).get("usage") or {}
            input_tokens = usage.get("input_tokens", input_tokens)
            output_tokens = usage.get("output_tokens", output_tokens)
        elif etype == "content_block_start":
            idx = evt.get("index", 0)
            block = evt.get("content_block") or {}
            kind = block.get("type", "")
            block_kind[idx] = kind
            if kind == "tool_use":
                block_tool_id[idx] = block.get("id", "")
                block_tool_name[idx] = block.get("name", "")
                block_input_json[idx] = []
        elif etype == "content_block_delta":
            idx = evt.get("index", 0)
            delta = evt.get("delta") or {}
            dtype = delta.get("type")
            if dtype == "text_delta":
                t = delta.get("text", "")
                if t:
                    yield base.TextChunk(text=t)
            elif dtype == "input_json_delta":
                block_input_json.setdefault(idx, []).append(delta.get("partial_json", ""))
        elif etype == "content_block_stop":
            idx = evt.get("index", 0)
            if block_kind.get(idx) == "tool_use":
                joined = "".join(block_input_json.get(idx, [])) or "{}"
                try:
                    parsed_input = json.loads(joined)
                except json.JSONDecodeError:
                    parsed_input = {"_parse_error": joined}
                yield base.ToolUseChunk(
                    id=block_tool_id.get(idx, ""),
                    name=block_tool_name.get(idx, ""),
                    input=parsed_input if isinstance(parsed_input, dict) else {},
                )
        elif etype == "message_delta":
            delta = evt.get("delta") or {}
            if delta.get("stop_reason"):
                stop_reason = delta["stop_reason"]
            usage = evt.get("usage") or {}
            if "output_tokens" in usage:
                output_tokens = usage["output_tokens"]
        elif etype == "error":
            err = evt.get("error") or {}
            raise base.ProviderError(
                err.get("message", "Anthropic stream error"),
                code="server",
                retryable=True,
            )
        elif etype == "message_stop":
            break

    yield base.DoneChunk(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        stop_reason=stop_reason,
    )


async def list_models() -> list[str]:
    """Query GET /v1/models for the user's available Claude models.
    Returns short ids (claude-opus-4-7, claude-sonnet-4-6, …) sorted
    by the API's response order so newest-recommended sits first."""
    if not has_key():
        return []
    headers = {
        "x-api-key": _api_key(),
        "anthropic-version": ANTHROPIC_VERSION,
    }
    timeout = aiohttp.ClientTimeout(total=10.0)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                "https://api.anthropic.com/v1/models", headers=headers,
            ) as resp:
                if resp.status != 200:
                    return []
                body = await resp.json()
    except (aiohttp.ClientConnectionError, TimeoutError, ValueError):
        return []
    items = body.get("data") if isinstance(body, dict) else None
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for it in items:
        if isinstance(it, dict) and isinstance(it.get("id"), str):
            out.append(it["id"])
    return out


async def validate_key(*, workspace: str | None = None) -> bool:
    """Cheap ping: ask for max_tokens=1 and read the first chunk.
    Used by Settings → "Test" button. The HTTP provider ignores
    `workspace`; only subprocess-backed providers honour it."""
    del workspace
    req = base.ChatRequest(
        messages=[{"role": "user", "content": "ping"}],
        max_tokens=1,
    )
    async for _ in chat_stream(req):
        return True
    return True
