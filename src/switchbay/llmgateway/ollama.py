"""Ollama (local) provider — streaming via NDJSON over HTTP.

No API key. The "key" is "is the local Ollama server running?" which
we probe at has_key() time. Endpoint defaults to localhost:11434 but
can be overridden via OLLAMA_HOST. Models live on the user's machine;
we surface a few common defaults but the user can paste any tag.
"""

from __future__ import annotations

import json
import logging
import os
from typing import AsyncIterator

import aiohttp

from . import base

log = logging.getLogger("switchbay.llm.ollama")

ID = "ollama"
LABEL = "Ollama (local)"
DEFAULT_MODEL = "llama3.2"
DEFAULT_TIMEOUT_S = 600.0  # local inference can be slow on small machines


def _host() -> str:
    """Resolve the Ollama base URL from env or default."""
    h = (os.environ.get("OLLAMA_HOST") or "").strip()
    if not h:
        return "http://127.0.0.1:11434"
    if not h.startswith(("http://", "https://")):
        h = f"http://{h}"
    return h.rstrip("/")


PROVIDER = {
    "id": ID,
    "label": LABEL,
    "category": "local",
    "default_model": DEFAULT_MODEL,
    "auth_help": (
        "Install Ollama from https://ollama.com and run "
        "`ollama serve` in a terminal (or use the menu-bar app). Pull a model "
        "with e.g. `ollama pull llama3.2`."
    ),
    "model_suggestions": [
        "llama3.2",
        "llama3.1",
        "qwen2.5",
        "mistral",
        "phi4",
        "gemma3",
    ],
    "capabilities": {
        "chat": True,
        "streaming": True,
        "tools": False,
        # Execution surface — see base.CAPABILITY_NOTES.
        # local HTTP: switchbay tool registry only.
        "shell": False,
        "file_write": False,
        "key_validation": True,
    },
}


def has_key() -> bool:
    """For Ollama, "has_key" means "is the daemon reachable?". We don't
    actually ping every call — the Settings UI shows availability via
    validate_key. has_key just returns True so the UI shows "available"
    and lets the user attempt a chat (which will surface a clear
    network error if Ollama isn't running)."""
    return True


def _http_error(status: int, text: str) -> base.ProviderError:
    code: base.ErrorCode = (
        "model-not-found" if status == 404 else
        "server" if status >= 500 else
        "http"
    )
    msg = (text or "").strip()[:400] or f"HTTP {status}"
    try:
        data = json.loads(text)
        if isinstance(data, dict) and data.get("error"):
            msg = str(data["error"])
    except (ValueError, TypeError):
        pass
    return base.ProviderError(
        f"Ollama: {msg}",
        code=code,
        status=status,
        retryable=code == "server",
    )


def _to_ollama_messages(
    messages: list[dict], system: str | None,
) -> list[dict]:
    out: list[dict] = []
    if system:
        out.append({"role": "system", "content": system})
    for m in messages:
        role = m.get("role") or "user"
        content = m.get("content")
        if isinstance(content, str):
            out.append({"role": role, "content": content})
        else:
            out.append({"role": role, "content": str(content or "")})
    return out


async def chat_stream(req: base.ChatRequest) -> AsyncIterator[base.ChunkEvent]:
    url = f"{_host()}/api/chat"
    headers = {"Content-Type": "application/json"}
    body: dict = {
        "model": req.model or DEFAULT_MODEL,
        "messages": _to_ollama_messages(req.messages, req.system),
        "stream": True,
        "options": {},
    }
    if req.temperature is not None:
        body["options"]["temperature"] = req.temperature
    if req.max_tokens:
        body["options"]["num_predict"] = req.max_tokens
    if not body["options"]:
        del body["options"]

    timeout = aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT_S)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=headers, json=body) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise _http_error(resp.status, text)
                async for chunk in _parse_ndjson(resp.content):
                    yield chunk
    except aiohttp.ClientConnectionError as e:
        raise base.ProviderError(
            f"Could not reach Ollama at {_host()}. "
            "Is `ollama serve` running?",
            code="network", retryable=True, cause=e,
        ) from e
    except TimeoutError as e:
        raise base.ProviderError(
            f"Ollama request timed out after {int(DEFAULT_TIMEOUT_S)}s",
            code="timeout", retryable=True, cause=e,
        ) from e


async def _parse_ndjson(content) -> AsyncIterator[base.ChunkEvent]:
    """Ollama emits one JSON object per line. Each carries either a
    `message.content` delta (during generation) or `done: true` plus
    final usage counters at the end."""
    input_tokens: int | None = None
    output_tokens: int | None = None
    stop_reason: str | None = None

    async for raw in content:
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n").strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = evt.get("message") or {}
        text = msg.get("content")
        if isinstance(text, str) and text:
            yield base.TextChunk(text=text)
        if evt.get("done"):
            stop_reason = evt.get("done_reason") or "stop"
            if "prompt_eval_count" in evt:
                input_tokens = evt["prompt_eval_count"]
            if "eval_count" in evt:
                output_tokens = evt["eval_count"]
            break

    yield base.DoneChunk(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        stop_reason=stop_reason,
    )


async def list_models() -> list[str]:
    """Live list of models the user has pulled locally — `ollama list`
    via the HTTP API. Returns names sorted alphabetically. Empty on
    connection error so the UI falls back to suggestions."""
    timeout = aiohttp.ClientTimeout(total=5.0)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{_host()}/api/tags") as resp:
                if resp.status != 200:
                    return []
                body = await resp.json()
    except (aiohttp.ClientConnectionError, TimeoutError, ValueError):
        return []
    items = body.get("models") if isinstance(body, dict) else None
    if not isinstance(items, list):
        return []
    names: list[str] = []
    for it in items:
        if isinstance(it, dict):
            n = it.get("name") or it.get("model")
            if isinstance(n, str) and n:
                names.append(n)
    return sorted(set(names))


async def validate_key(*, workspace: str | None = None) -> bool:
    """Probe `GET /api/tags` to confirm Ollama is up. The Settings
    "Test" button uses this rather than a chat round-trip so we don't
    block on model loading."""
    del workspace
    timeout = aiohttp.ClientTimeout(total=5.0)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{_host()}/api/tags") as resp:
                if resp.status == 200:
                    return True
                raise _http_error(resp.status, await resp.text())
    except aiohttp.ClientConnectionError as e:
        raise base.ProviderError(
            f"Could not reach Ollama at {_host()}. "
            "Is `ollama serve` running?",
            code="network", retryable=True, cause=e,
        ) from e
    except TimeoutError as e:
        raise base.ProviderError(
            "Ollama probe timed out", code="timeout", retryable=True, cause=e,
        ) from e
