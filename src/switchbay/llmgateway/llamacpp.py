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


def has_key() -> bool:
    """Configured = the installer completed on this machine."""
    return localllm.load_config() is not None


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


def _tools_to_openai(tools: list[dict] | None) -> list[dict] | None:
    """Anthropic-shaped tools ({name, description, input_schema}) →
    OpenAI function tools. Sending these is the whole fix: with --jinja,
    llama-server renders them through Ornith's chat template and parses
    the model's native `[tool_call]…[/tool_call]` output back into
    structured `tool_calls`. Omit them and the model emits that syntax
    as plain text (it leaks into the rail and nothing executes)."""
    if not tools:
        return None
    out: list[dict] = []
    for t in tools:
        if not isinstance(t, dict) or not t.get("name"):
            continue
        out.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description") or "",
                "parameters": t.get("input_schema") or {"type": "object", "properties": {}},
            },
        })
    return out or None


def _to_openai_messages(messages: list[dict], system: str | None) -> list[dict]:
    """Canonical {role, content} — content may be Anthropic-style block
    lists for tool turns — into OpenAI chat-completions messages.
    `tool_use` blocks become an assistant message's `tool_calls`;
    `tool_result` blocks become `tool`-role messages keyed by id."""
    out: list[dict] = []
    if system:
        out.append({"role": "system", "content": system})
    for m in messages:
        role = m.get("role") or "user"
        content = m.get("content")
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        if not isinstance(content, list):
            out.append({"role": role, "content": str(content or "")})
            continue
        text_parts: list[str] = []
        tool_calls: list[dict] = []
        tool_msgs: list[dict] = []
        for b in content:
            if not isinstance(b, dict):
                text_parts.append(str(b))
                continue
            bt = b.get("type")
            if bt == "text":
                text_parts.append(str(b.get("text") or ""))
            elif bt == "tool_use":
                tool_calls.append({
                    "id": str(b.get("id") or ""),
                    "type": "function",
                    "function": {
                        "name": str(b.get("name") or ""),
                        "arguments": json.dumps(b.get("input") or {}),
                    },
                })
            elif bt == "tool_result":
                rc = b.get("content")
                if isinstance(rc, list):
                    rc = "".join(
                        str(x.get("text") or "") if isinstance(x, dict) else str(x)
                        for x in rc
                    )
                tool_msgs.append({
                    "role": "tool",
                    "tool_call_id": str(b.get("tool_use_id") or ""),
                    "content": str(rc if rc is not None else ""),
                })
            else:
                text_parts.append(str(b.get("text") or ""))
        if tool_calls:
            # An assistant turn: prose (if any) + the calls it made.
            out.append({
                "role": "assistant",
                "content": "".join(text_parts).strip() or None,
                "tool_calls": tool_calls,
            })
        elif tool_msgs:
            out.extend(tool_msgs)
        else:
            out.append({"role": role, "content": "".join(text_parts)})
    return out


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
            "enable_thinking": (
                bool(req.reasoning)
                if req.reasoning is not None
                else bool(cfg.get("reasoning", True))
            ),
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
    input_tokens: int | None = None
    output_tokens: int | None = None
    stop_reason: str | None = None
    # Streamed tool_calls arrive as deltas keyed by index: the first
    # carries id + name + a leading "{"; the rest append `arguments`
    # fragments. Accumulate, then emit one ToolUseChunk per call once
    # the arguments are a complete JSON string.
    tool_acc: dict[int, dict[str, str]] = {}
    async for raw in content:
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line.startswith("data: "):
            continue
        payload = line[6:]
        if payload == "[DONE]":
            break
        if not payload:
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
            # Ornith (and o1-style models) stream private chain-of-
            # thought here — surface it as reasoning, never as content.
            rzn = delta.get("reasoning_content")
            if isinstance(rzn, str) and rzn:
                yield base.ReasoningChunk(text=rzn)
            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index", 0) if isinstance(tc, dict) else 0
                slot = tool_acc.setdefault(idx, {"id": "", "name": "", "args": ""})
                if tc.get("id"):
                    slot["id"] = str(tc["id"])
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["name"] = str(fn["name"])
                arg = fn.get("arguments")
                if isinstance(arg, str):
                    slot["args"] += arg
            fr = choice.get("finish_reason")
            if isinstance(fr, str):
                stop_reason = fr
        usage = evt.get("usage") or {}
        if "prompt_tokens" in usage:
            input_tokens = usage["prompt_tokens"]
        if "completion_tokens" in usage:
            output_tokens = usage["completion_tokens"]
    # Flush accumulated tool calls in index order.
    for idx in sorted(tool_acc):
        slot = tool_acc[idx]
        if not slot["name"]:
            continue
        try:
            args = json.loads(slot["args"]) if slot["args"].strip() else {}
        except json.JSONDecodeError:
            args = {}
        if not isinstance(args, dict):
            args = {}
        yield base.ToolUseChunk(
            id=slot["id"] or f"call_{idx}", name=slot["name"], input=args,
        )
    # OpenAI signals tool intent with finish_reason "tool_calls"; the
    # daemon's agent loop keys off "tool_use" to run another turn.
    if tool_acc:
        stop_reason = "tool_use"
    yield base.DoneChunk(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        stop_reason=stop_reason,
    )


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
