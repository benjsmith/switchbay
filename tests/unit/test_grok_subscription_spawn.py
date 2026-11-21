"""Grok Build spawn: subscription env, pasted screenshots, tool events."""

from __future__ import annotations

import json

import pytest

from switchbay.llmgateway import base, grok_build


def test_subscription_env_drops_xai_api_key():
    env = grok_build.subscription_env({
        "PATH": "/usr/bin",
        "HOME": "/home/tester",
        "XAI_API_KEY": "xai-secret",
        "ANTHROPIC_API_KEY": "sk-ant",
        "OPENAI_API_KEY": "sk-openai",
    })
    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/home/tester"
    assert "XAI_API_KEY" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert "OPENAI_API_KEY" not in env


def test_image_attachments_are_called_out_for_read():
    text = (
        "[attached: .workbench/uploads/abc/pasted-image.png]\n"
        "[attached: notes/plan.md]\n"
        "what is in the screenshot?"
    )
    assert grok_build.image_attachment_paths(text) == [
        ".workbench/uploads/abc/pasted-image.png",
    ]
    prompt = grok_build.prompt_for_cli(text)
    assert "pasted-image.png" in prompt
    assert "Read each path" in prompt
    assert "notes/plan.md" not in prompt.split("Read each path", 1)[1]
    assert grok_build.prompt_for_cli("just text") == "just text"


class _Stdout:
    def __init__(self, lines: list[bytes]):
        self._lines = list(lines)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._lines:
            raise StopAsyncIteration
        return self._lines.pop(0)


class _Proc:
    def __init__(self, lines: list[bytes]):
        self.stdout = _Stdout(lines)
        self.stderr = None
        self.returncode = 0

    def terminate(self):
        return None

    def kill(self):
        return None

    async def wait(self):
        return 0


@pytest.mark.asyncio
async def test_spawn_uses_subscription_and_surfaces_tool_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-secret")
    monkeypatch.setattr(grok_build, "grok_binary", lambda: "/usr/bin/grok")
    monkeypatch.setattr(grok_build, "_verify_workspace", lambda raw: tmp_path)

    async def _mcp(workspace, *, allowed_tools=None):
        return "switchbay"

    monkeypatch.setattr(grok_build, "_ensure_mcp", _mcp)
    monkeypatch.setattr(grok_build, "_ensure_hooks_ok", lambda workspace, port: True)
    monkeypatch.setattr(
        grok_build.ce_toolscope, "all_rules", lambda workspace: [],
    )

    seen: dict = {}

    async def fake_exec(*argv, **kwargs):
        seen["argv"] = list(argv)
        seen["env"] = dict(kwargs.get("env") or {})
        lines = [
            json.dumps({
                "type": "tool_call",
                "toolCallId": "call-1",
                "toolName": "Read",
                "rawInput": {"file_path": ".workbench/uploads/abc/pasted-image.png"},
            }).encode() + b"\n",
            json.dumps({"type": "text", "data": "A login form."}).encode() + b"\n",
            json.dumps({
                "type": "end",
                "stopReason": "EndTurn",
                "sessionId": "sess-9",
            }).encode() + b"\n",
        ]
        return _Proc(lines)

    monkeypatch.setattr(grok_build.asyncio, "create_subprocess_exec", fake_exec)

    req = base.ChatRequest(
        messages=[{
            "role": "user",
            "content": (
                "[attached: .workbench/uploads/abc/pasted-image.png]\n"
                "what is on screen?"
            ),
        }],
        workspace=str(tmp_path),
        model="grok-4.6",
    )
    events = [event async for event in grok_build.chat_stream(req)]

    argv = seen["argv"]
    assert argv[0] == "/usr/bin/grok"
    assert "-p" in argv
    prompt = argv[argv.index("-p") + 1]
    assert "pasted-image.png" in prompt
    assert "Read each path" in prompt
    assert "XAI_API_KEY" not in seen["env"]
    assert seen["env"].get("XAI_API_KEY") is None

    tools = [e for e in events if isinstance(e, base.ToolUseChunk)]
    assert len(tools) == 1
    assert tools[0].name == "Read"
    assert tools[0].id == "call-1"
    assert tools[0].input["file_path"].endswith("pasted-image.png")
    text = [e for e in events if isinstance(e, base.TextChunk)]
    assert text[0].text == "A login form."
    done = [e for e in events if isinstance(e, base.DoneChunk)]
    assert done[0].session_id == "sess-9"
    assert done[0].stop_reason == "EndTurn"
