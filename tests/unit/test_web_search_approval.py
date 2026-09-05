"""Native CLI web search is ungagged but not auto-approved."""

from __future__ import annotations

from pathlib import Path

from switchbay import permissions
from switchbay.llmgateway import claude_code, claude_code_settings, grok_build, openai_codex


def test_claude_no_longer_disallows_web_search():
    names = claude_code.DISALLOWED_TOOL_NAMES
    assert "WebSearch" not in names
    assert "WebFetch" not in names
    assert "Task" in names
    assert "WebSearch" not in claude_code.DISALLOWED_TOOLS.split(",")
    assert "WebFetch" not in claude_code.DISALLOWED_TOOLS.split(",")


def test_claude_allowlist_does_not_pre_approve_web_search(tmp_path: Path):
    cfg = claude_code_settings.build_settings(tmp_path, 8765)
    allow = cfg["permissions"]["allow"]
    joined = "\n".join(allow)
    assert "WebSearch" not in joined
    assert "WebFetch" not in joined


def test_web_search_is_not_on_builtin_floor(tmp_path: Path):
    for tool, payload in (
        ("WebSearch", {"query": "qwen mlx"}),
        ("web_search", {"query": "qwen mlx"}),
        ("WebFetch", {"url": "https://example.edu/p"}),
        ("web_fetch", {"url": "https://example.edu/p"}),
    ):
        pat = permissions.pattern_for(tool, payload)
        assert not permissions.is_pre_approved(
            tmp_path, pat, tool=tool, tool_input=payload,
        )
        assert permissions.is_web_search_tool(tool)


def test_web_search_pattern_shows_query():
    pat = permissions.pattern_for("WebSearch", {"query": "transformer attention"})
    assert pat == "WebSearch(transformer attention)"
    fetch = permissions.pattern_for("WebFetch", {"url": "https://example.edu/a"})
    assert "example.edu" in fetch


def test_grok_hookless_disallows_web_search():
    assert "web_search" in grok_build.HOOKLESS_DISALLOWED_TOOLS
    assert "web_fetch" in grok_build.HOOKLESS_DISALLOWED_TOOLS
    # Hooked path still recognizes the prefixes so --deny can name them,
    # but HARD_DENY_RULES do not gag web search (the rail card does).
    hard = " ".join(grok_build.HARD_DENY_RULES)
    assert "WebSearch" not in hard
    assert "web_search" not in hard


def test_codex_disables_web_search_until_sentinel(tmp_path: Path):
    argv = openai_codex.web_search_overrides(tmp_path)
    assert argv == ["-c", "tools.web_search=false"]
    permissions.add_pattern(tmp_path, permissions.CODEX_WEB_SEARCH_SENTINEL)
    assert openai_codex.web_search_overrides(tmp_path) == [
        "-c", "tools.web_search=true",
    ]
