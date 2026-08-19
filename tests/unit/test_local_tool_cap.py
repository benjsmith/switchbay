"""Local-model context safety net: cap tool output that would blow the
32k window (esp. the ~26k-token CE skill)."""

from __future__ import annotations

from switchbay import daemon


def test_small_output_passes_through():
    out = {"ok": True, "rows": [1, 2, 3]}
    assert daemon._cap_local_tool_output("search_wiki", out) is out


def test_big_load_skill_becomes_frontmatter_peek():
    huge = "x" * (daemon._LOCAL_TOOL_RESULT_CAP + 5000)
    capped = daemon._cap_local_tool_output("load_skill", {
        "ok": True,
        "skill": {
            "name": "curiosity-engine",
            "description": "wiki",
            "body": huge,
        },
    })
    assert capped["ok"] is True
    assert capped["truncated"] is True
    assert capped["skill"]["detail"] == "frontmatter"
    assert "ce_sweep" in capped["skill"]["covered_by"]
    assert "progressive" in capped["note"].lower() or "section" in capped["note"].lower()
    assert huge not in str(capped["skill"])


def test_strong_model_tool_output_is_also_capped():
    huge = "z" * (daemon._TOOL_RESULT_CAP + 1000)
    capped = daemon._cap_tool_output("ce_run", huge, local=False)
    assert capped["truncated"] is True
    assert len(capped["preview"]) <= daemon._TOOL_RESULT_CAP + 64


def test_other_big_output_truncated_preview():
    huge = "y" * (daemon._LOCAL_TOOL_RESULT_CAP + 5000)
    capped = daemon._cap_local_tool_output("read_wiki_page", huge)
    assert capped["truncated"] is True
    assert len(capped["preview"]) <= daemon._LOCAL_TOOL_RESULT_CAP + 64
    assert "truncated for context" in capped["preview"]
