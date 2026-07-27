"""Local-model context safety net: cap tool output that would blow the
32k window (esp. the ~26k-token CE skill)."""

from __future__ import annotations

from switchbay import daemon


def test_small_output_passes_through():
    out = {"ok": True, "rows": [1, 2, 3]}
    assert daemon._cap_local_tool_output("search_wiki", out) is out


def test_big_load_skill_redirects_to_wiki_tools():
    huge = "x" * (daemon._LOCAL_TOOL_RESULT_CAP + 5000)
    capped = daemon._cap_local_tool_output("load_skill", huge)
    assert capped["ok"] is False
    assert "wiki tools" in capped["note"]
    assert "search_wiki" in capped["note"]


def test_other_big_output_truncated_preview():
    huge = "y" * (daemon._LOCAL_TOOL_RESULT_CAP + 5000)
    capped = daemon._cap_local_tool_output("read_wiki_page", huge)
    assert capped["truncated"] is True
    assert len(capped["preview"]) <= daemon._LOCAL_TOOL_RESULT_CAP + 64
    assert "truncated for local context" in capped["preview"]
