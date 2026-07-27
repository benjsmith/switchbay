"""Google Gemini provider — streaming via SSE.

BYOK pattern. Uses the Generative Language `streamGenerateContent`
endpoint with `?alt=sse` so we get the same `data: {…}` line shape as
the other providers.
"""

from __future__ import annotations

import json
import logging
import os
from typing import AsyncIterator
from urllib.parse import quote

import aiohttp

from .. import secrets
from . import base

log = logging.getLogger("switchbay.llm.gemini")

ID = "gemini"
LABEL = "Google Gemini"
API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-2.5-pro"
DEFAULT_TIMEOUT_S = 300.0

PROVIDER = {
    "id": ID,
    "label": LABEL,
    "category": "byok",
    "default_model": DEFAULT_MODEL,
    "key_placeholder": "AIza…",
    "key_help_url": "https://aistudio.google.com/app/apikey",
    "model_suggestions": [
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-1.5-pro",
    ],
    "capabilities": {
        "chat": True,
        "streaming": True,
        "tools": False,
        # Execution surface — see base.CAPABILITY_NOTES.
        # HTTP: switchbay tool registry only (propose_*/create_report).
        "shell": False,
        "file_write": False,
        "key_validation": True,
    },
}


def has_key() -> bool:
    return secrets.has(ID) or bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))


def _api_key() -> str:
    key = (
        secrets.get(ID)
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
    )
    if not key:
        raise base.ProviderError(
            "Gemini API key required. Set it in Settings.",
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
        f"Gemini: {msg}",
        code=code,
        status=status,
        retryable=code in ("rate-limit", "server", "timeout"),
    )


def _to_gemini_contents(messages: list[dict]) -> list[dict]:
    """Translate canonical {role, content} into Gemini's
    `[{role: user|model, parts: [{text: ...}]}]` shape."""
    out: list[dict] = []
    for m in messages:
        role = m.get("role") or "user"
        # Gemini uses `model` for assistant turns.
        if role == "assistant":
            role = "model"
        if role not in ("user", "model"):
            role = "user"
        content = m.get("content")
        if isinstance(content, str):
            parts = [{"text": content}]
        elif isinstance(content, list):
            # Best-effort: pick out text fragments. Multimodal blocks
            # would need richer translation we don't need today.
            parts = []
            for b in content:
                if isinstance(b, dict) and "text" in b:
                    parts.append({"text": str(b["text"])})
            if not parts:
                parts = [{"text": ""}]
        else:
            parts = [{"text": str(content or "")}]
        out.append({"role": role, "parts": parts})
    return out


async def chat_stream(req: base.ChatRequest) -> AsyncIterator[base.ChunkEvent]:
    model = req.model or DEFAULT_MODEL
    url = f"{API_BASE}/{quote(model)}:streamGenerateContent?alt=sse"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": _api_key(),
    }
    body: dict = {
        "contents": _to_gemini_contents(req.messages),
        "generationConfig": {},
    }
    if req.system:
        # `systemInstruction` is the canonical place for a system prompt.
        body["systemInstruction"] = {"parts": [{"text": req.system}]}
    if req.temperature is not None:
        body["generationConfig"]["temperature"] = req.temperature
    if req.max_tokens:
        body["generationConfig"]["maxOutputTokens"] = req.max_tokens
    if not body["generationConfig"]:
        del body["generationConfig"]

    timeout = aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT_S)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=headers, json=body) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise _http_error(resp.status, text)
                async for chunk in _parse_sse(resp.content):
                    yield chunk
    except aiohttp.ClientConnectionError as e:
        raise base.ProviderError(
            "Could not reach generativelanguage.googleapis.com",
            code="network", retryable=True, cause=e,
        ) from e
    except TimeoutError as e:
        raise base.ProviderError(
            f"Request timed out after {int(DEFAULT_TIMEOUT_S)}s",
            code="timeout", retryable=True, cause=e,
        ) from e


async def _parse_sse(content) -> AsyncIterator[base.ChunkEvent]:
    """Each `data: {…}` line is a partial GenerateContentResponse. We
    extract `candidates[0].content.parts[].text` for streaming text and
    finishReason / usageMetadata for the terminal DoneChunk."""
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
        try:
            evt = json.loads(payload)
        except json.JSONDecodeError:
            continue
        for cand in evt.get("candidates") or []:
            content_obj = cand.get("content") or {}
            for part in content_obj.get("parts") or []:
                text = part.get("text")
                if isinstance(text, str) and text:
                    yield base.TextChunk(text=text)
            fr = cand.get("finishReason")
            if isinstance(fr, str):
                stop_reason = fr.lower()
        usage = evt.get("usageMetadata") or {}
        if "promptTokenCount" in usage:
            input_tokens = usage["promptTokenCount"]
        if "candidatesTokenCount" in usage:
            output_tokens = usage["candidatesTokenCount"]

    yield base.DoneChunk(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        stop_reason=stop_reason,
    )


async def list_models() -> list[str]:
    """Query GET /v1beta/models for the user's available Gemini models.
    Filters to ones that support generateContent (drops embedding /
    aqa-only / etc). Returns short ids (e.g. "gemini-2.5-pro") not
    the full "models/gemini-2.5-pro" paths the API uses internally."""
    if not has_key():
        return []
    timeout = aiohttp.ClientTimeout(total=10.0)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                f"{API_BASE}",
                headers={"x-goog-api-key": _api_key()},
            ) as resp:
                if resp.status != 200:
                    return []
                body = await resp.json()
    except (aiohttp.ClientConnectionError, TimeoutError, ValueError):
        return []
    items = body.get("models") if isinstance(body, dict) else None
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        name = it.get("name") or ""
        methods = it.get("supportedGenerationMethods") or []
        if not isinstance(name, str) or "generateContent" not in methods:
            continue
        # API returns "models/gemini-2.5-pro" — strip the prefix so
        # the picker shows the bare id like the rest of our suggestions.
        short = name.split("/", 1)[-1] if name.startswith("models/") else name
        # Drop legacy / embed-only entries we don't want to expose.
        low = short.lower()
        if any(s in low for s in ("embedding", "aqa", "vision", "tuned")):
            continue
        if "gemini" not in low:
            continue
        out.append(short)
    out.sort(key=lambda m: (len(m), m))
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
