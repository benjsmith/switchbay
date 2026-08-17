"""Grok Build live model list — CLI catalogue, not the xAI HTTP list."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from switchbay.llmgateway import grok_build


CLI_SAMPLE = """\
You are logged in with grok.com.

Default model: grok-4.6

Available models:
  * grok-4.6 (default)
  - grok-4.5
"""


def test_parse_models_cli_default_first():
    assert grok_build.parse_models_cli(CLI_SAMPLE) == ["grok-4.6", "grok-4.5"]


def test_parse_models_cli_empty():
    assert grok_build.parse_models_cli("") == []
    assert grok_build.parse_models_cli("not logged in\n") == []


def test_models_from_cache_skips_hidden(tmp_path: Path):
    p = tmp_path / "models_cache.json"
    p.write_text(json.dumps({
        "models": {
            "grok-4.6": {"info": {"id": "grok-4.6", "hidden": False}},
            "grok-4.5": {"info": {"id": "grok-4.5"}},
            "internal-preview": {"info": {"id": "internal-preview", "hidden": True}},
        },
    }), encoding="utf-8")
    assert grok_build.models_from_cache(p) == ["grok-4.6", "grok-4.5"]


def test_models_from_cache_missing(tmp_path: Path):
    assert grok_build.models_from_cache(tmp_path / "nope.json") == []


def test_parse_tool_call_accepts_grok_acp_fields():
    parsed = grok_build.parse_tool_call({
        "type": "tool_call",
        "toolCallId": "call_1",
        "title": "Read",
        "toolName": "read_file",
        "rawInput": {"path": "src/main.rs"},
    })
    assert parsed == ("call_1", "read_file", {"path": "src/main.rs"})


def test_parse_tool_call_skips_update_and_empty_name():
    assert grok_build.parse_tool_call({
        "type": "tool_call_update", "toolCallId": "call_1",
    }) is None
    assert grok_build.parse_tool_call({"type": "tool_call"}) is None
    assert grok_build.parse_tool_call({
        "type": "tool_use", "id": "x", "name": "Bash",
        "input": {"command": "ls"},
    }) == ("x", "Bash", {"command": "ls"})


def test_hard_deny_rules_use_supported_prefixes():
    for rule in grok_build.HARD_DENY_RULES:
        prefix = rule.split("(", 1)[0]
        assert prefix in grok_build.DENY_PREFIXES, rule
    argv = grok_build.deny_argv()
    assert "NotebookEdit(*)" not in argv
    assert argv.count("--deny") == len(grok_build.HARD_DENY_RULES)
    assert "Bash(mdfind*)" in argv


def test_deny_argv_skips_unknown_prefixes():
    argv = grok_build.deny_argv([
        "NotebookEdit(*)",
        "Shell(*)",
        "Bash(mdfind*)",
        "Write(*)",
    ])
    assert argv == ["--deny", "Bash(mdfind*)", "--deny", "Write(*)"]


def test_static_suggestions_include_46():
    assert "grok-4.6" in grok_build.PROVIDER["model_suggestions"]
    assert grok_build.DEFAULT_MODEL == "grok-4.6"


def test_reasoning_xhigh_on_46_not_45():
    assert [o["id"] for o in grok_build.reasoning_options("grok-4.5")] == [
        "low", "medium", "high",
    ]
    assert [o["id"] for o in grok_build.reasoning_options("grok-4.6")] == [
        "low", "medium", "high", "xhigh",
    ]
    assert [o["id"] for o in grok_build.reasoning_options("grok-composer-2.5-fast")] == []


@pytest.mark.asyncio
async def test_list_models_falls_back_to_cache(monkeypatch, tmp_path: Path):
    cache = tmp_path / "models_cache.json"
    cache.write_text(json.dumps({
        "models": {"grok-4.6": {"info": {"id": "grok-4.6"}}},
    }), encoding="utf-8")
    monkeypatch.setattr(grok_build, "grok_binary", lambda: None)
    monkeypatch.setattr(grok_build, "models_from_cache", lambda path=None: ["grok-4.6"])
    assert await grok_build.list_models() == ["grok-4.6"]
