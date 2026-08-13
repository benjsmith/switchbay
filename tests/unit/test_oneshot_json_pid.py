"""_oneshot_json must not NameError on undefined pid."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from switchbay import daemon
from switchbay.llmgateway import base


class _FakeProvider:
    ID = "openai"
    PROVIDER = {"id": "openai", "default_model": "gpt-4o"}

    async def chat_stream(self, req: base.ChatRequest):
        # Prove reasoning_effort was resolved without NameError.
        assert req.messages
        yield base.TextChunk(text='{"ok": true, "n": 1}')
        yield base.DoneChunk(stop_reason="end")


@pytest.mark.asyncio
async def test_oneshot_json_derives_pid(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(daemon, "_effort_for", lambda pid, model, lane=None: None)
    out = await daemon._oneshot_json(
        _FakeProvider(), "gpt-4o", "return json", tmp_path,
    )
    assert out == {"ok": True, "n": 1}


@pytest.mark.asyncio
async def test_oneshot_json_works_with_module_like_provider(
    tmp_path: Path, monkeypatch,
):
    monkeypatch.setattr(daemon, "_effort_for", lambda pid, model, lane=None: None)

    async def chat_stream(req):
        yield base.TextChunk(text='{"a": 2}')
        yield base.DoneChunk()

    mod = SimpleNamespace(
        ID="xai",
        PROVIDER={"id": "xai"},
        chat_stream=chat_stream,
    )
    out = await daemon._oneshot_json(mod, "grok-4.5", "x", tmp_path)
    assert out == {"a": 2}
