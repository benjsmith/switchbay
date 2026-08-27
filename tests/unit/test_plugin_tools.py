"""VS Code plugin tool allowlist: no :8765 round-trips."""

from __future__ import annotations

import os
from pathlib import Path

from switchbay import plugin_tools, tools
from switchbay.mcp_server import _ensure_array_items, _list_tools, copilot_schema_violations


def test_plugin_allowlist_drops_daemon_coupled_tools() -> None:
    coupled = plugin_tools.DAEMON_COUPLED
    allowed = set(plugin_tools.ALLOWED_TOOLS)
    assert coupled.isdisjoint(allowed)
    for name in (
        "search_wiki",
        "read_wiki_page",
        "list_wiki_pages",
        "ce_lint",
        "ce_ingest",
        "propose_wiki_page",
        "orchestration_report",
        "save_plot",
        "create_report",
    ):
        assert name in allowed, name
    assert "create_slideshow" in allowed or "author_slide" in allowed
    assert "author_sketch" in allowed or "compose_analysis" in allowed
    assert "run_command" not in allowed


def test_plugin_profile_detects_vscode(monkeypatch) -> None:
    monkeypatch.delenv("CSWY_PROFILE", raising=False)
    assert plugin_tools.is_plugin_profile() is False
    monkeypatch.setenv("CSWY_PROFILE", "vscode")
    assert plugin_tools.is_plugin_profile() is True
    monkeypatch.setenv("CSWY_PROFILE", "plugin")
    assert plugin_tools.is_plugin_profile() is True


def test_daemon_json_fails_fast_in_plugin_profile(monkeypatch) -> None:
    monkeypatch.setenv("CSWY_PROFILE", "vscode")
    body = tools._daemon_json("GET", "/api/sheet/focus")
    assert body["ok"] is False
    assert "8765" in body["error"]


def test_ask_thread_fails_fast_in_plugin_profile(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CSWY_PROFILE", "vscode")
    body = tools._ask_thread(tmp_path, {"message": "hi"})
    assert body["ok"] is False
    assert "8765" in body["error"]


def test_mcp_list_under_plugin_profile_omits_coupled(monkeypatch) -> None:
    monkeypatch.setenv("CSWY_PROFILE", "vscode")
    listed = {t["name"] for t in _list_tools(list(plugin_tools.ALLOWED_TOOLS))["tools"]}
    assert "search_wiki" in listed
    assert "sheet_set_formula" not in listed
    assert "ask_thread" not in listed
    assert "plot_show" not in listed


def test_copilot_schema_collapses_nested_object_arrays() -> None:
    raw = {
        "type": "object",
        "properties": {
            "slides": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "heading": {"type": "string"},
                        "bullets": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "wiki_topics": {"type": "array", "items": {"type": "string"}},
        },
    }
    out = _ensure_array_items(raw)
    assert out["properties"]["wiki_topics"]["type"] == "array"
    assert out["properties"]["wiki_topics"]["items"] == {"type": "string"}
    assert out["properties"]["slides"]["type"] == "string"
    assert copilot_schema_violations(out) == []


def test_plugin_mcp_tools_are_copilot_safe(monkeypatch) -> None:
    monkeypatch.setenv("CSWY_PROFILE", "vscode")
    listed = _list_tools(list(plugin_tools.ALLOWED_TOOLS))["tools"]
    assert listed
    bad: list[str] = []
    for tool in listed:
        for path in copilot_schema_violations(tool["inputSchema"], tool["name"]):
            bad.append(path)
    assert bad == []


def test_create_slideshow_accepts_json_string_slides(tmp_path: Path) -> None:
    import json

    out = tools.REGISTRY["create_slideshow"].handler(tmp_path, {
        "title": "JSON slides",
        "slides": json.dumps([
            {"layout": "title", "heading": "Hello"},
            {"layout": "bullets", "heading": "Points", "bullets": "one\ntwo"},
        ]),
    })
    assert out["ok"]
    html = (tmp_path / "slideshows" / "json-slides" / "index.html").read_text(
        encoding="utf-8",
    )
    assert "Hello" in html
    assert "one" in html
