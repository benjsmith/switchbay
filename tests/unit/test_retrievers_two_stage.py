"""Unit tests for v0.9.2 two-stage / type-demotion retrieval helpers."""

from __future__ import annotations

from bench.retrievers import demote_analyses, query_is_needle, _type_rank, _page_type


def test_page_type_from_paths():
    assert _page_type("wiki/analyses/foo.md") == "analyses"
    assert _page_type("facts/bar.md") == "facts"
    assert _page_type("sources/lb2-1.md") == "sources"
    assert _page_type("concepts/x.md") == "concepts"


def test_type_rank_analyses_last():
    assert _type_rank("facts/a.md") < _type_rank("analyses/z.md")
    assert _type_rank("sources/s.md") < _type_rank("concepts/c.md")
    assert _type_rank("figures/f.md") < _type_rank("analyses/a.md")


def test_demote_analyses_needle_puts_analyses_last():
    pages = [
        "wiki/analyses/big-theme.md",
        "wiki/facts/caption-fig5.md",
        "wiki/sources/lb2-x.md",
        "wiki/concepts/dropout.md",
        "wiki/entities/alexnet.md",
    ]
    out = demote_analyses(pages, needle=True)
    assert out[0].endswith("lb2-x.md") or "sources" in out[0]
    assert out[1].endswith("caption-fig5.md") or "facts" in out[1]
    assert out[-1].endswith("big-theme.md")


def test_demote_analyses_stable_for_same_type():
    pages = ["wiki/facts/a.md", "wiki/facts/b.md", "wiki/facts/c.md"]
    assert demote_analyses(pages, needle=True) == pages


def test_query_is_needle_passage_and_fig():
    assert query_is_needle(
        'In AI Safety, what claim does the passage establish? Passage: “The diagram is based on meta-analysis.”'
    )
    assert query_is_needle("What does Fig. 5 show about pedestrian crossing?")
    assert query_is_needle('Quote: "Each node represents a value query"')


def test_query_is_needle_false_for_open_synthesis():
    assert not query_is_needle(
        "What should a journalist know about privacy and fairness in ML systems?"
    )
    assert not query_is_needle(
        "Compare bagging and boosting for an exam essay outline."
    )
