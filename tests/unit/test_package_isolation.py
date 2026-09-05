"""CLI/MCP package isolation: allowlists and native write denials."""

from __future__ import annotations

from pathlib import Path

from switchbay.kernel.packages import (
    CODE_EDIT_ID, CODE_EXPLORE_ID, CODE_REVIEW_ID, WRITES_NONE, WRITES_REVIEW,
    blocks_native_writes, get_package, package_tool_names,
)
from switchbay.llmgateway import base, claude_code, claude_code_settings, openai_codex


def test_explore_and_review_block_native_writes():
    explore = get_package(CODE_EXPLORE_ID)
    review = get_package(CODE_REVIEW_ID)
    edit = get_package(CODE_EDIT_ID)
    assert explore is not None and review is not None and edit is not None
    assert blocks_native_writes(explore.writes)
    assert blocks_native_writes(review.writes)
    assert not blocks_native_writes(edit.writes)
    assert explore.writes == WRITES_NONE
    assert review.writes == WRITES_REVIEW


def test_package_tool_names_intersect():
    names = package_tool_names(CODE_EXPLORE_ID, ["search_wiki", "run_command", "nope"])
    assert "search_wiki" in names
    assert "run_command" not in names


def test_mcp_spec_sets_allowed_tools(tmp_path: Path):
    spec = claude_code_settings.mcp_server_spec(
        tmp_path, allowed_tools=["search_wiki", "read_wiki_page"],
    )
    assert spec["env"]["CSWY_ALLOWED_TOOLS"] == "search_wiki,read_wiki_page"
    default = claude_code_settings.mcp_server_spec(tmp_path)
    assert "CSWY_ALLOWED_TOOLS" not in default["env"]
    assert claude_code_settings.isolation_server_name(None) == "switchbay"
    named = claude_code_settings.isolation_server_name(["search_wiki"])
    assert named.startswith("switchbay_")
    assert named != "switchbay"


def test_claude_explore_disallows_edit_write_bash():
    req = base.ChatRequest(
        messages=[{"role": "user", "content": "x"}],
        package_writes="none",
        allowed_tools=["search_wiki"],
    )
    got = claude_code.disallowed_tools_for(req)
    assert "Edit" in got
    assert "Write" in got
    assert "Bash" in got
    open_req = base.ChatRequest(messages=[{"role": "user", "content": "x"}])
    open_got = claude_code.disallowed_tools_for(open_req)
    assert "Edit" not in open_got.split(",")
    assert "Task" in open_got


def test_codex_explore_sandbox_is_read_only(tmp_path: Path):
    req = base.ChatRequest(
        messages=[{"role": "user", "content": "x"}],
        package_writes="none",
    )
    assert openai_codex.sandbox_for(req, tmp_path) == "read-only"
    edit = base.ChatRequest(
        messages=[{"role": "user", "content": "x"}],
        package_writes="product",
    )
    assert openai_codex.sandbox_for(edit, tmp_path) == "workspace-write"


def test_write_mcp_config_is_per_allowlist(tmp_path: Path):
    a = claude_code_settings.write_mcp_config(
        tmp_path, allowed_tools=["search_wiki"],
    )
    b = claude_code_settings.write_mcp_config(
        tmp_path, allowed_tools=["run_command"],
    )
    assert a != b
    assert a.is_file() and b.is_file()
    assert "search_wiki" in a.read_text(encoding="utf-8")
    assert "run_command" in b.read_text(encoding="utf-8")
