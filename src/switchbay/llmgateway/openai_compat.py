"""Shared OpenAI chat-completions helpers for HTTP providers.

Anthropic-shaped `tools` / message blocks are the daemon's canonical
form. llama.cpp, OpenAI, xAI, and GitHub Copilot all speak OpenAI's
function-tool dialect on the wire — convert here once so providers
don't silently drop `req.tools` or fail multi-turn tool_result replay.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from . import base


def tools_to_openai(tools: list[dict] | None) -> list[dict] | None:
    """Anthropic-shaped tools ({name, description, input_schema}) →
    OpenAI function tools."""
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
                "parameters": t.get("input_schema") or {
                    "type": "object", "properties": {},
                },
            },
        })
    return out or None


def messages_to_openai(
    messages: list[dict], system: str | None,
) -> list[dict]:
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


def _sse_error_message(err: Any) -> str:
    if isinstance(err, str) and err.strip():
        return err.strip()[:400]
    if isinstance(err, dict):
        msg = err.get("message") or err.get("code") or err.get("type")
        if msg:
            return str(msg).strip()[:400]
        try:
            return json.dumps(err)[:400]
        except (TypeError, ValueError):
            return "server error"
    return str(err)[:400]


def _oomish(msg: str) -> bool:
    low = msg.lower()
    return any(
        n in low
        for n in (
            "out of memory",
            "insufficient memory",
            "kiogpucommandbuffercallbackerroroutofmemory",
        )
    )


async def parse_sse(
    content: Any,
    *,
    reasoning_field: str | None = "reasoning_content",
) -> AsyncIterator[base.ChunkEvent]:
    """Parse an OpenAI-style SSE stream into ChunkEvents.

    Accumulates streamed `tool_calls` deltas and emits ToolUseChunk(s)
    with DoneChunk.stop_reason=\"tool_use\" so the daemon agent loop
    continues.

    A dropped stream (mlx_lm.server dying mid-generate on Metal OOM)
    used to look like a finished reply of garbage tokens. Incomplete
    streams without ``[DONE]`` / ``finish_reason`` raise ProviderError.
    """
    input_tokens: int | None = None
    output_tokens: int | None = None
    stop_reason: str | None = None
    tool_acc: dict[int, dict[str, str]] = {}
    saw_done = False
    stream_error: str | None = None

    async for raw in content:
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line or line.startswith(":"):
            continue
        if not line.startswith("data: "):
            continue
        payload = line[6:]
        if not payload:
            continue
        if payload == "[DONE]":
            saw_done = True
            break
        try:
            evt = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if not isinstance(evt, dict):
            continue
        err = evt.get("error")
        if err:
            stream_error = _sse_error_message(err)
            break
        for choice in evt.get("choices") or []:
            delta = choice.get("delta") or {}
            text = delta.get("content")
            if isinstance(text, str) and text:
                yield base.TextChunk(text=text)
            if reasoning_field:
                rzn = delta.get(reasoning_field)
                if isinstance(rzn, str) and rzn:
                    yield base.ReasoningChunk(text=rzn)
            for tc in delta.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                idx = tc.get("index", 0)
                slot = tool_acc.setdefault(
                    idx, {"id": "", "name": "", "args": ""},
                )
                if tc.get("id"):
                    slot["id"] = str(tc["id"])
                fn = tc.get("function") or {}
                if isinstance(fn, dict):
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

    if stream_error:
        if _oomish(stream_error):
            raise base.ProviderError(
                "The local model ran out of memory mid-reply. Stop other "
                "local servers in Settings, then retry (or use a cloud "
                f"provider). {stream_error}",
                code="server", retryable=True,
            )
        raise base.ProviderError(
            f"Local model server error: {stream_error}",
            code="server", retryable=True,
        )
    if not saw_done and not stop_reason and not tool_acc:
        raise base.ProviderError(
            "The local model stopped generating mid-reply (often out of "
            "memory). Open Settings → Watch server for the Metal/llama "
            "log, stop leftover local servers, and retry.",
            code="server", retryable=True,
        )

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
            id=slot["id"] or f"call_{idx}",
            name=slot["name"],
            input=args,
        )
    if tool_acc:
        stop_reason = "tool_use"
    yield base.DoneChunk(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        stop_reason=stop_reason,
    )
