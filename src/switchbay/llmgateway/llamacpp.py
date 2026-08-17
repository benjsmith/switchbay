"""llama.cpp (managed local) provider — the Ornith installer's server.

Talks the OpenAI-compatible chat-completions API of the daemon-managed
`llama-server` (see localllm.py: one-click install, RAM-planned quant/
context, KV q8_0). Distinct from the Ollama provider: this server is
switchbay's own child process, and the model is whatever the
installer configured (Ornith 9B/35B).
"""

from __future__ import annotations

import json
import logging
from typing import AsyncIterator

import aiohttp

from . import base
from .openai_compat import (
    messages_to_openai as _to_openai_messages,
    parse_sse as _compat_parse_sse,
    tools_to_openai as _tools_to_openai,
)
from .. import localllm

log = logging.getLogger("switchbay.llm.llamacpp")

ID = "llamacpp"
LABEL = "llama.cpp (local)"
DEFAULT_MODEL = "local"
DEFAULT_TIMEOUT_S = 900.0  # long contexts on small machines are slow

PROVIDER = {
    "id": ID,
    "label": LABEL,
    "category": "local",
    "default_model": DEFAULT_MODEL,
    "auth_help": (
        "Managed llama-server — Settings → Local agent model. Install "
        "any catalog GGUF (Ornith, Qwen, Llama, …); the active model's "
        "alias is what the ladder uses."
    ),
    "model_suggestions": [],  # filled live from installed GGUFs
    "capabilities": {
        "chat": True,
        "streaming": True,
        # llama-server runs with --jinja, so the model's own chat
        # template renders the tool schemas AND parses its native
        # tool-call syntax back into OpenAI `tool_calls`. We just have
        # to send the tools and read them back (see chat_stream).
        "tools": True,
        # Execution surface — see base.CAPABILITY_NOTES.
        # local HTTP: switchbay tool registry only.
        "shell": False,
        "file_write": False,
        "key_validation": True,
    },
}


def is_installed() -> bool:
    from .. import local_models
    cfg = localllm.load_config()
    if cfg and str(cfg.get("backend") or "llamacpp") in ("", "llamacpp"):
        return True
    return any(
        str(m.get("backend") or "llamacpp") in ("", "llamacpp")
        for m in local_models.list_installed()
    )


def has_key() -> bool:
    """Available when a GGUF is installed — not when an MLX-only
    localllm config happens to exist."""
    return is_installed()


def _http_error(status: int, text: str) -> base.ProviderError:
    code: base.ErrorCode = (
        "model-not-found" if status == 404 else
        "server" if status >= 500 else
        "http"
    )
    msg = (text or "").strip()[:400] or f"HTTP {status}"
    return base.ProviderError(
        f"llama.cpp: {msg}", code=code, status=status,
        retryable=code == "server",
    )


# ── Reasoning effort ────────────────────────────────────────────────
# A GGUF chat template exposes thinking as a BOOLEAN
# (`enable_thinking`), not a scale, so this provider honestly offers two
# options rather than pretending to a four-rung ladder it can't deliver
# (see base.REASONING_NOTES).


def reasoning_options(model: str | None = None) -> list[dict]:
    return [
        base.reasoning_option(
            base.REASONING_OFF, "Off",
            "no thinking — use for one-shot drafting"),
        base.reasoning_option(
            "on", "On", "thinking enabled (default; most of the capability)"),
    ]


def _thinking_enabled(req: base.ChatRequest, cfg: dict) -> bool:
    """Resolve thinking for this request.

    Precedence: explicit per-request `reasoning` bool (the one-shot
    drafting path) → picker `reasoning_effort` → the Settings default,
    which is ON because Ornith derives most of its capability from
    thinking.
    """
    if req.reasoning is not None:
        return bool(req.reasoning)
    effort = base.coerce_effort(req.reasoning_effort, reasoning_options(req.model))
    if effort:
        return effort != base.REASONING_OFF
    return bool(cfg.get("reasoning", True))


async def chat_stream(req: base.ChatRequest) -> AsyncIterator[base.ChunkEvent]:
    cfg = localllm.load_config() or {}
    base_url = localllm.server_url_for(cfg)
    # Prefer request model, else active alias from install/activate.
    model_id = (
        req.model
        or str(cfg.get("alias") or "").strip()
        or DEFAULT_MODEL
    )
    body: dict = {
        "model": model_id,
        "messages": _to_openai_messages(req.messages, req.system),
        "stream": True,
        "stream_options": {"include_usage": True},
        # Reasoning is ON by default: Ornith derives most of its
        # capability from thinking, and the reasoning stream is surfaced
        # as ReasoningChunk but NEVER replayed into the model's context
        # (see daemon _flush_reasoning), so it can't accumulate across
        # turns. The circling/attractor failure mode is held on the
        # rails by the daemon's loop guard (repeated-identical-call
        # short-circuit + _AGENT_MAX_TURNS) — code, not prompt bloat —
        # so we keep the harness minimal. Users can still force it off
        # in Settings (writes reasoning:false). A per-request override
        # (req.reasoning) wins over the Settings default — one-shot
        # content drafts pass False to avoid an all-reasoning empty body.
        "chat_template_kwargs": {
            "enable_thinking": _thinking_enabled(req, cfg),
        },
    }
    tools = _tools_to_openai(req.tools)
    if tools:
        body["tools"] = tools
    if req.temperature is not None:
        body["temperature"] = req.temperature
    if req.max_tokens:
        body["max_tokens"] = req.max_tokens

    timeout = aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT_S)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{base_url}/v1/chat/completions", json=body,
            ) as resp:
                if resp.status != 200:
                    raise _http_error(resp.status, await resp.text())
                async for chunk in _parse_sse(resp.content):
                    yield chunk
    except aiohttp.ClientConnectionError as e:
        raise base.ProviderError(
            "The local model server isn't running. If Ornith is "
            "installed the daemon starts it at boot — check Settings → "
            "Local agent model (it may still be loading the weights).",
            code="network", retryable=True, cause=e,
        ) from e
    except TimeoutError as e:
        raise base.ProviderError(
            f"Local model timed out after {int(DEFAULT_TIMEOUT_S)}s",
            code="timeout", retryable=True, cause=e,
        ) from e


async def _parse_sse(content) -> AsyncIterator[base.ChunkEvent]:
    async for chunk in _compat_parse_sse(content):
        yield chunk


async def list_models() -> list[str]:
    """Installed GGUF aliases (and active config) — not Ornith-only."""
    from .. import local_models  # late: avoid import cycle at module load

    out: list[str] = []
    seen: set[str] = set()
    for m in local_models.list_installed():
        if not isinstance(m, dict):
            continue
        backend = str(m.get("backend") or "llamacpp")
        if backend not in ("llamacpp", ""):
            continue
        for key in ("alias", "id"):
            val = str(m.get(key) or "").strip()
            if val and val not in seen:
                seen.add(val)
                out.append(val)
                break
    cfg = localllm.load_config()
    if cfg:
        for key in ("alias", "candidate_id", "model"):
            val = str(cfg.get(key) or "").strip()
            if val and val not in seen:
                seen.add(val)
                out.insert(0, val)
                break
    return out


async def validate_key(*, workspace: str | None = None) -> bool:
    del workspace
    if localllm.load_config() is None:
        raise base.ProviderError(
            "Not installed — Settings → Local agent model.",
            code="auth",
        )
    if not await localllm.server_healthy():
        raise base.ProviderError(
            "Installed but the server isn't answering yet (a large "
            "model can take a minute or two to load).",
            code="network", retryable=True,
        )
    return True
