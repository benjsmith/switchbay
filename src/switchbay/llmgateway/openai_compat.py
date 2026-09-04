"""Shared OpenAI chat-completions + Responses helpers for HTTP providers.

Anthropic-shaped `tools` / message blocks are the daemon's canonical
form. llama.cpp, OpenAI, xAI, and GitHub Copilot all speak OpenAI's
function-tool dialect on chat/completions — convert here once so
providers don't silently drop `req.tools` or fail multi-turn
tool_result replay.

The Responses API (`/responses`) is a separate wire: flat function
tools, `input` items, and SSE event types. Copilot's dialect rotates
`item_id` per delta; parsers key by `output_index` / `call_id`.
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


def tools_to_responses(tools: list[dict] | None) -> list[dict] | None:
    """Anthropic-shaped tools → OpenAI Responses function tools.

    Chat Completions nest ``function: {name, parameters}``. Responses
    wants a flat ``{type, name, parameters, strict}``.
    """
    if not tools:
        return None
    out: list[dict] = []
    for t in tools:
        if not isinstance(t, dict) or not t.get("name"):
            continue
        out.append({
            "type": "function",
            "name": t["name"],
            "description": t.get("description") or "",
            "parameters": t.get("input_schema") or {
                "type": "object", "properties": {},
            },
            "strict": False,
        })
    return out or None


def _responses_assistant_message(text: str, msg_id: str) -> dict:
    return {
        "type": "message",
        "id": msg_id,
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def _block_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content or "")
    parts: list[str] = []
    for b in content:
        if isinstance(b, dict):
            if b.get("type") == "text":
                parts.append(str(b.get("text") or ""))
            elif isinstance(b.get("text"), str):
                parts.append(b["text"])
        elif isinstance(b, str):
            parts.append(b)
    return "".join(parts)


def messages_to_responses(
    messages: list[dict], system: str | None,
) -> tuple[str | None, list[dict]]:
    """Canonical messages → Responses ``(instructions, input items)``.

    ``system`` (and any ``role: system`` turns) become ``instructions``.
    Tool replay uses ``function_call`` / ``function_call_output`` keyed
    by the canonical tool id.
    """
    instructions_parts: list[str] = []
    if system and str(system).strip():
        instructions_parts.append(str(system).strip())
    items: list[dict] = []
    asst_n = 0
    for m in messages:
        role = m.get("role") or "user"
        content = m.get("content")
        if role == "system":
            text = _block_text(content).strip()
            if text:
                instructions_parts.append(text)
            continue
        if isinstance(content, str):
            if role == "assistant":
                if content.strip():
                    asst_n += 1
                    items.append(_responses_assistant_message(content, f"msg_{asst_n}"))
            else:
                items.append({"role": "user", "content": content})
            continue
        if not isinstance(content, list):
            text = str(content or "")
            if role == "assistant":
                if text.strip():
                    asst_n += 1
                    items.append(_responses_assistant_message(text, f"msg_{asst_n}"))
            else:
                items.append({"role": "user", "content": text})
            continue
        text_parts: list[str] = []
        calls: list[dict] = []
        results: list[dict] = []
        for b in content:
            if not isinstance(b, dict):
                text_parts.append(str(b))
                continue
            bt = b.get("type")
            if bt == "text":
                text_parts.append(str(b.get("text") or ""))
            elif bt == "tool_use":
                args = b.get("input") or {}
                calls.append({
                    "type": "function_call",
                    "call_id": str(b.get("id") or ""),
                    "name": str(b.get("name") or ""),
                    "arguments": json.dumps(args) if not isinstance(args, str) else args,
                })
            elif bt == "tool_result":
                rc = b.get("content")
                if isinstance(rc, list):
                    rc = "".join(
                        str(x.get("text") or "") if isinstance(x, dict) else str(x)
                        for x in rc
                    )
                results.append({
                    "type": "function_call_output",
                    "call_id": str(b.get("tool_use_id") or ""),
                    "output": str(rc if rc is not None else ""),
                })
            else:
                text_parts.append(str(b.get("text") or ""))
        if results:
            items.extend(results)
            continue
        text = "".join(text_parts)
        if text.strip():
            if role == "assistant":
                asst_n += 1
                items.append(_responses_assistant_message(text, f"msg_{asst_n}"))
            else:
                items.append({"role": "user", "content": text})
        items.extend(calls)
    instructions = "\n\n".join(instructions_parts).strip() or None
    return instructions, items


def _responses_output_index(evt: dict, fallback: int) -> int:
    raw = evt.get("output_index")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return fallback


def _harvest_output_text(item: dict) -> str:
    chunks: list[str] = []
    for c in item.get("content") or []:
        if isinstance(c, dict) and c.get("type") in ("output_text", "text"):
            t = c.get("text")
            if isinstance(t, str) and t:
                chunks.append(t)
    return "".join(chunks)


async def parse_responses_sse(
    content: Any,
) -> AsyncIterator[base.ChunkEvent]:
    """Parse an OpenAI/Copilot Responses SSE stream into ChunkEvents.

    Copilot tags every delta with a fresh encrypted ``item_id``. Join
    tool-call state by ``output_index`` (and ``call_id`` when present),
    never by ``item_id``.
    """
    input_tokens: int | None = None
    output_tokens: int | None = None
    stop_reason: str | None = None
    tool_acc: dict[int, dict[str, str]] = {}
    completed = False
    stream_error: str | None = None
    saw_text = False
    next_tool_idx = 0

    def slot(idx: int) -> dict[str, str]:
        return tool_acc.setdefault(idx, {"id": "", "name": "", "args": ""})

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
            completed = True
            break
        try:
            evt = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if not isinstance(evt, dict):
            continue
        etype = str(evt.get("type") or "")
        if etype in ("error", "response.failed") or (not etype and evt.get("error")):
            err = evt.get("error")
            if err is None:
                resp = evt.get("response")
                if isinstance(resp, dict):
                    err = resp.get("error")
            if err is None:
                err = evt.get("message") or evt
            stream_error = _sse_error_message(err)
            break
        if etype == "response.output_text.delta":
            delta = evt.get("delta")
            if isinstance(delta, str) and delta:
                saw_text = True
                yield base.TextChunk(text=delta)
            continue
        if etype == "response.reasoning_summary_text.delta":
            delta = evt.get("delta")
            if isinstance(delta, str) and delta:
                yield base.ReasoningChunk(text=delta)
            continue
        if etype == "response.output_item.added":
            item = evt.get("item") if isinstance(evt.get("item"), dict) else {}
            if item.get("type") == "function_call":
                idx = _responses_output_index(evt, next_tool_idx)
                next_tool_idx = max(next_tool_idx, idx + 1)
                s = slot(idx)
                if item.get("call_id"):
                    s["id"] = str(item["call_id"])
                if item.get("name"):
                    s["name"] = str(item["name"])
                args = item.get("arguments")
                if isinstance(args, str) and args:
                    s["args"] = args
            continue
        if etype == "response.function_call_arguments.delta":
            idx = _responses_output_index(evt, max(next_tool_idx - 1, 0))
            s = slot(idx)
            delta = evt.get("delta")
            if isinstance(delta, str) and delta:
                s["args"] += delta
            continue
        if etype == "response.output_item.done":
            item = evt.get("item") if isinstance(evt.get("item"), dict) else {}
            itype = str(item.get("type") or "")
            if itype == "function_call":
                idx = _responses_output_index(evt, max(next_tool_idx - 1, 0))
                s = slot(idx)
                if item.get("call_id"):
                    s["id"] = str(item["call_id"])
                if item.get("name"):
                    s["name"] = str(item["name"])
                args = item.get("arguments")
                if isinstance(args, str) and args:
                    s["args"] = args
            elif itype == "message" and not saw_text:
                harvested = _harvest_output_text(item)
                if harvested:
                    saw_text = True
                    yield base.TextChunk(text=harvested)
            continue
        if etype == "response.completed":
            completed = True
            resp = evt.get("response") if isinstance(evt.get("response"), dict) else {}
            usage = resp.get("usage") if isinstance(resp.get("usage"), dict) else {}
            if "input_tokens" in usage:
                input_tokens = usage["input_tokens"]
            elif "prompt_tokens" in usage:
                input_tokens = usage["prompt_tokens"]
            if "output_tokens" in usage:
                output_tokens = usage["output_tokens"]
            elif "completion_tokens" in usage:
                output_tokens = usage["completion_tokens"]
            if not saw_text:
                for item in resp.get("output") or []:
                    if not isinstance(item, dict) or item.get("type") != "message":
                        continue
                    harvested = _harvest_output_text(item)
                    if harvested:
                        saw_text = True
                        yield base.TextChunk(text=harvested)
            if not tool_acc:
                for i, item in enumerate(resp.get("output") or []):
                    if not isinstance(item, dict) or item.get("type") != "function_call":
                        continue
                    s = slot(i)
                    if item.get("call_id"):
                        s["id"] = str(item["call_id"])
                    if item.get("name"):
                        s["name"] = str(item["name"])
                    args = item.get("arguments")
                    if isinstance(args, str) and args:
                        s["args"] = args
            continue

    if stream_error:
        if _oomish(stream_error):
            raise base.ProviderError(
                "The local model ran out of memory mid-reply. Stop other "
                "local servers in Settings, then retry (or use a cloud "
                f"provider). {stream_error}",
                code="server", retryable=True,
            )
        raise base.ProviderError(
            f"Model server error: {stream_error}",
            code="server", retryable=True,
        )
    if not completed and not saw_text and not tool_acc:
        raise base.ProviderError(
            "The model stopped generating mid-reply.",
            code="server", retryable=True,
        )

    for idx in sorted(tool_acc):
        s = tool_acc[idx]
        if not s["name"]:
            continue
        try:
            args = json.loads(s["args"]) if s["args"].strip() else {}
        except json.JSONDecodeError:
            args = {}
        if not isinstance(args, dict):
            args = {}
        yield base.ToolUseChunk(
            id=s["id"] or f"call_{idx}",
            name=s["name"],
            input=args,
        )
    if tool_acc:
        stop_reason = "tool_use"
    yield base.DoneChunk(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        stop_reason=stop_reason,
    )
