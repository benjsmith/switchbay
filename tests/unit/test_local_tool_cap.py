"""Local-model context safety net: cap tool output that would blow the
32k window (esp. the ~26k-token CE skill)."""

from __future__ import annotations

from switchbay import daemon, tools


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
    capped = daemon._cap_local_tool_output("ce_run", huge)
    assert capped["truncated"] is True
    assert len(capped["preview"]) <= daemon._LOCAL_TOOL_RESULT_CAP + 64
    assert "truncated for context" in capped["preview"]


def test_wiki_cite_target():
    assert tools.wiki_cite_target("wiki/entities/graphormer.md") == "entities/graphormer"
    assert tools.wiki_cite_target("entities/graphormer") == "entities/graphormer"


def test_read_wiki_page_under_cap_keeps_full_body():
    body = "Graphormer is Ying et al. 2021.\n" * 20
    out = {
        "page": "wiki/entities/graphormer.md",
        "title": "[ent] Graphormer",
        "type": "entity",
        "content": body,
        "truncated": False,
        "wikilink": "[[entities/graphormer]]",
    }
    capped = daemon._cap_tool_output("read_wiki_page", out, local=True)
    assert capped["content"] == body
    assert capped["wikilink"] == "[[entities/graphormer]]"


def test_read_wiki_page_cap_keeps_cite():
    body = "Graphormer is Ying et al. 2021. " + ("x" * 8000)
    capped = daemon._cap_tool_output("read_wiki_page", {
        "page": "wiki/entities/graphormer.md",
        "title": "[ent] Graphormer",
        "type": "entity",
        "content": body,
        "truncated": False,
        "wikilink": "[[entities/graphormer]]",
    }, local=True)
    assert capped["page"] == "wiki/entities/graphormer.md"
    assert capped["title"] == "[ent] Graphormer"
    assert capped["wikilink"] == "[[entities/graphormer]]"
    assert "preview" not in capped
    assert capped["truncated"] is True
    assert capped["content"].startswith("Graphormer is Ying")
    assert "truncated for context" in capped["content"]


def test_wiki_cites_appended_when_model_forgets():
    cites = daemon._wiki_cites_from_tool("read_wiki_page", {
        "page": "wiki/entities/graphormer.md",
        "wikilink": "[[entities/graphormer]]",
    })
    assert cites == ["[[entities/graphormer]]"]
    text = "Graphormer is a transformer for graphs."
    assert "[[entities/graphormer]]" in daemon._with_wiki_cites(text, cites)
    already = "See [[entities/graphormer]] for the page."
    assert daemon._with_wiki_cites(already, cites) == already
