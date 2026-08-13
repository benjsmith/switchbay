"""Meta Model API + Muse Code providers."""

from __future__ import annotations

from pathlib import Path

import pytest

from switchbay import llmgateway
from switchbay.llmgateway import meta, muse_code


def test_registered_and_labelled():
    assert "meta" in llmgateway.PROVIDERS
    assert "muse-code" in llmgateway.PROVIDERS
    assert llmgateway.get("meta").LABEL == "Meta (Muse Spark)"
    assert llmgateway.get("muse-code").LABEL == "Muse Code"


def test_execute_surface():
    assert not llmgateway.can_execute("meta")
    assert llmgateway.can_execute("muse-code")


def test_meta_reasoning_never_offers_none():
    ids = [o["id"] for o in meta.reasoning_options("muse-spark-1.2")]
    assert ids == ["minimal", "low", "medium", "high", "xhigh"]
    assert "none" not in ids


def test_muse_code_reasoning_matches_cli():
    ids = [o["id"] for o in llmgateway.reasoning_options("muse-code", "muse-spark-1.2")]
    assert ids == ["minimal", "low", "medium", "high", "xhigh"]


def test_muse_argv_headless_flags(tmp_path: Path):
    argv = muse_code.build_argv(
        binary="/usr/bin/muse",
        prompt="hello",
        workspace=tmp_path,
        model="muse-spark-1.2",
        effort="high",
        session_id="sess-1",
    )
    assert argv[:3] == ["/usr/bin/muse", "exec", "--json"]
    assert "--workspace" in argv and str(tmp_path) in argv
    assert "--trust-workspace" in argv
    assert "--disable-approval" in argv
    assert "--yolo" not in argv
    assert argv[argv.index("--model") + 1] == "muse-spark-1.2"
    assert argv[argv.index("--reasoning-effort") + 1] == "high"
    assert argv[argv.index("--session-id") + 1] == "sess-1"
    assert argv[-1] == "hello"


def test_parse_grok_shaped_text():
    chunks = muse_code.parse_exec_event({"type": "text", "data": "hi"})
    assert len(chunks) == 1
    assert chunks[0].type == "text"
    assert chunks[0].text == "hi"


def test_parse_claude_shaped_assistant():
    chunks = muse_code.parse_exec_event({
        "type": "assistant",
        "session_id": "abc",
        "message": {"content": [{"type": "text", "text": "done"}]},
    })
    assert [c.text for c in chunks] == ["done"]
    assert muse_code._session_id_of({
        "type": "assistant", "session_id": "abc",
    }) == "abc"


def test_parse_codex_shaped_item():
    chunks = muse_code.parse_exec_event({
        "type": "item.completed",
        "item": {"type": "agent_message", "text": "ok"},
    })
    assert [c.text for c in chunks] == ["ok"]


def test_parse_skips_audit_envelopes():
    assert muse_code.parse_exec_event({
        "payload_type": "tool_batch.effect.started",
        "payload": {"text": "should not dump"},
    }) == []
    assert muse_code.parse_exec_event({
        "type": "record",
        "payload": {"text": "nope"},
    }) == []


def test_parse_error_raises():
    with pytest.raises(llmgateway.ProviderError, match="boom"):
        muse_code.parse_exec_event({"type": "error", "message": "boom"})


def test_meta_suggestions_put_contributor_last():
    sugg = meta.PROVIDER["model_suggestions"]
    assert sugg[0] == "muse-spark-1.2"
    assert sugg[-1] == "muse-spark-1.2-contributor"


def test_muse_refuses_non_workspace(tmp_path: Path):
    with pytest.raises(llmgateway.ProviderError):
        muse_code._verify_workspace(None)
    with pytest.raises(llmgateway.ProviderError):
        muse_code._verify_workspace("relative")
    with pytest.raises(llmgateway.ProviderError):
        muse_code._verify_workspace(str(tmp_path / "missing"))
