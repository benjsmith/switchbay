"""OpenAI-compat tool conversion + SSE tool_calls accumulation."""

from __future__ import annotations

import json

import pytest

from switchbay.llmgateway import base
from switchbay.llmgateway.openai_compat import (
    messages_to_openai,
    parse_sse,
    tools_to_openai,
)


def test_tools_to_openai_shape():
    tools = [{
        "name": "search_wiki",
        "description": "find pages",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
        },
    }]
    out = tools_to_openai(tools)
    assert out is not None
    assert out[0]["type"] == "function"
    assert out[0]["function"]["name"] == "search_wiki"
    assert out[0]["function"]["parameters"]["properties"]["query"]["type"] == "string"


def test_tools_to_openai_empty():
    assert tools_to_openai(None) is None
    assert tools_to_openai([]) is None


def test_messages_round_trip_tool_use_and_result():
    messages = [
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "looking"},
                {
                    "type": "tool_use",
                    "id": "call_1",
                    "name": "search_wiki",
                    "input": {"query": "transformers"},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "call_1",
                    "content": '{"results":[]}',
                },
            ],
        },
    ]
    out = messages_to_openai(messages, system="sys")
    assert out[0] == {"role": "system", "content": "sys"}
    assert out[1]["role"] == "assistant"
    assert out[1]["tool_calls"][0]["function"]["name"] == "search_wiki"
    assert json.loads(out[1]["tool_calls"][0]["function"]["arguments"]) == {
        "query": "transformers",
    }
    assert out[2]["role"] == "tool"
    assert out[2]["tool_call_id"] == "call_1"


class _FakeContent:
    """Minimal async iterator of SSE bytes lines."""

    def __init__(self, lines: list[str]):
        self._lines = lines
        self._i = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._i >= len(self._lines):
            raise StopAsyncIteration
        line = self._lines[self._i]
        self._i += 1
        return (line + "\n").encode("utf-8")


@pytest.mark.asyncio
async def test_parse_sse_emits_tool_use_and_stop_reason():
    payload1 = {
        "choices": [{
            "delta": {
                "tool_calls": [{
                    "index": 0,
                    "id": "call_abc",
                    "function": {"name": "search_wiki", "arguments": ""},
                }],
            },
        }],
    }
    payload2 = {
        "choices": [{
            "delta": {
                "tool_calls": [{
                    "index": 0,
                    "function": {"arguments": '{"query":"x"}'},
                }],
            },
            "finish_reason": "tool_calls",
        }],
    }
    lines = [
        f"data: {json.dumps(payload1)}",
        f"data: {json.dumps(payload2)}",
        "data: [DONE]",
    ]
    events = []
    async for ev in parse_sse(_FakeContent(lines)):
        events.append(ev)
    tools = [e for e in events if isinstance(e, base.ToolUseChunk)]
    dones = [e for e in events if isinstance(e, base.DoneChunk)]
    assert len(tools) == 1
    assert tools[0].name == "search_wiki"
    assert tools[0].input == {"query": "x"}
    assert tools[0].id == "call_abc"
    assert dones and dones[-1].stop_reason == "tool_use"
