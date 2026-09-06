"""HTML slideshow quality gate: no blank pages, inline tables, a story."""

from __future__ import annotations

from pathlib import Path

from switchbay import slideshow_html, tools


WIKI_TABLE = """---
title: "[tbl] Attention lineage"
type: summary-table
---

Prose above the table.

| Act | Name | Number |
|---|---|---|
| 1 | [[bahdanau-2014]] additive | none (no BLEU in vault) |
| 2 | [[vaswani-2017]] multi-head | 28.4 BLEU EN-DE |
| 3 | [[dao-2022]] FlashAttention | 15% BERT-large; 3× GPT-2 |
"""

TEST7_SLIDES = [
    {"layout": "title"},
    {
        "layout": "cards",
        "cards": [
            {"title": "2014", "body": "Additive soft-search."},
            {"title": "2017", "body": "Multi-head scaled dot-product. 28.4 BLEU."},
            {"title": "2022", "body": "FlashAttention: same math, IO-aware kernel."},
        ],
    },
    {"layout": "split"},
    {
        "layout": "bullets",
        "bullets": [
            "Transformer: attention only — no recurrence, no convolution.",
            "WMT 2014 English-to-German: 28.4 BLEU.",
        ],
    },
    {
        "layout": "cards",
        "cards": [
            {"title": "Exact, not approximate", "body": "Tiling keeps softmax in SRAM."},
            {"title": "Dao 2022", "body": "15% BERT-large. 3× GPT-2."},
        ],
    },
    {"layout": "split"},
    {
        "layout": "close",
        "bullets": [
            "Topics: transformer-architectures · inference-efficiency",
            "Spine: [[attention-lineage-bahdanau-to-flashattention]]",
            "Table: [[tbl-attention-lineage-bahdanau-to-flashattention]]",
        ],
    },
]


def _wiki_table(workspace: Path) -> None:
    p = workspace / "wiki" / "tables" / "tbl-attention-lineage-bahdanau-to-flashattention.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(WIKI_TABLE, encoding="utf-8")


def test_extract_quote_keeps_first_sentence():
    from switchbay.slide_charts import extract_quote
    q = extract_quote(
        "> We conjecture that the use of a fixed-length vector is a bottleneck. "
        "We propose to extend this by allowing a model to search.\n"
    )
    assert "fixed-length vector is a bottleneck" in q
    assert "propose to extend" not in q


def test_parse_markdown_table_skips_prose():
    parsed = slideshow_html.parse_markdown_table(WIKI_TABLE)
    assert parsed is not None
    assert parsed["columns"][0] == "Act"
    assert len(parsed["rows"]) == 3
    assert "28.4" in parsed["rows"][1][2]


def test_display_text_uses_wikilink_label():
    assert slideshow_html.display_text("see [[foo|Bar]]") == "see Bar"
    assert slideshow_html.display_text("[[entities/graphormer]]") == "graphormer"


def test_blank_and_metadata_deck_is_refused(tmp_path: Path):
    out = tools.REGISTRY["create_slideshow"].handler(tmp_path, {
        "title": "Empty",
        "slides": [
            {"layout": "title"},
            {"layout": "split"},
            {
                "layout": "close",
                "bullets": [
                    "Topics: x",
                    "Table: [[tbl-missing]]",
                ],
            },
        ],
    })
    assert out["ok"] is False
    err = str(out.get("error") or "").lower()
    assert "refused" in err or "lede" in err or "blank" in err or "table" in err


def test_test7_payload_inlines_wiki_table_and_drops_blanks(tmp_path: Path):
    _wiki_table(tmp_path)
    out = tools.REGISTRY["create_slideshow"].handler(tmp_path, {
        "title": "Attention lineage: Bahdanau → multi-head → FlashAttention",
        "slides": TEST7_SLIDES,
        "slug": "attention-lineage-bahdanau-multihead-flashattention",
    })
    assert out["ok"] is True, out
    html = (
        tmp_path / "slideshows" / "attention-lineage-bahdanau-multihead-flashattention"
        / "index.html"
    ).read_text(encoding="utf-8")
    assert "<h1>" in html
    assert "2014" in html
    assert "28.4" in html
    assert "BERT-large" in html
    assert "<table class=\"sheet\">" in html
    assert "Topics: transformer-architectures" not in html
    # empty split shells must not survive
    assert html.count('class="slide') >= 4
    assert html.count('<div class="col grow" style="flex:1.1"></div>') == 0
    # Wide wiki tables are trimmed so they fit 16:9.
    assert html.count("<th>") <= 4


def test_table_layout_renders_rows(tmp_path: Path):
    slideshow_html.write_slideshow(
        tmp_path,
        "tbl-demo",
        title="Numbers",
        slides=[
            {
                "layout": "table",
                "heading": "Vault numbers",
                "lede": "Only sourced figures.",
                "columns": ["Act", "Number"],
                "rows": [["2", "28.4 BLEU"], ["3", "15% BERT-large"]],
            },
        ],
    )
    html = (tmp_path / "slideshows" / "tbl-demo" / "index.html").read_text(
        encoding="utf-8",
    )
    assert "28.4 BLEU" in html
    assert "<th>" in html
    assert "sheet" in html


def test_backlog_gap_slide_is_dropped(tmp_path: Path):
    _wiki_table(tmp_path)
    out = tools.REGISTRY["create_slideshow"].handler(tmp_path, {
        "title": "A sentence used to be one vector",
        "slug": "gap-drop",
        "slides": [
            {
                "layout": "title",
                "heading": "A sentence used to be one vector",
                "lede": "That bottleneck is why attention exists.",
            },
            {
                "layout": "stats",
                "heading": "Same paper. Two leaderboards.",
                "stats": [
                    {"value": "28.4", "label": "BLEU EN-DE"},
                    {"value": "41.8", "label": "BLEU EN-FR"},
                ],
            },
            {
                "layout": "quote",
                "heading": "2014",
                "quote": "We conjecture that the use of a fixed-length vector is a bottleneck.",
                "quote_attr": "Bahdanau, Cho & Bengio",
            },
            {
                "layout": "bullets",
                "heading": "Still missing — and not this story.",
                "bullets": [
                    "The Gemini 1.5 original PDF is still missing.",
                    "FlashAttention-1 appendix Tables 7–21 were skipped as needing review. Do not invent those rows.",
                    "The Alammar GIFs were never ingested.",
                ],
                "cite": "remaining gaps, not the closer",
            },
            {
                "layout": "close",
                "heading": "The kernel changed.",
                "lede": "The math of attention did not change in 2022. The GPU kernel did.",
            },
        ],
    })
    assert out["ok"] is True, out
    html = (tmp_path / "slideshows" / "gap-drop" / "index.html").read_text(
        encoding="utf-8",
    )
    assert "Still missing" not in html
    assert "never ingested" not in html
    assert "remaining gaps" not in html
    assert "The kernel changed." in html
    assert "28.4" in html


def test_dictionary_bullets_escape_once():
    html = slideshow_html._bullets_html([
        {"title": "A & B", "body": "C < D"},
    ])
    assert "A &amp; B" in html
    assert "A &amp;amp; B" not in html
    assert "C &lt; D" in html
    assert "&amp;lt;" not in html


def test_media_generation_off_skips_image_gen(tmp_path: Path, monkeypatch):
    called: list[int] = []

    def _feat(name: str) -> bool:
        return name != "media_generation"

    def _boom(*_a, **_k):
        called.append(1)
        raise AssertionError("generate_image should not run")

    monkeypatch.setattr("switchbay.admin_policy.feature_enabled", _feat)
    monkeypatch.setattr("switchbay.media_gen.generate_image", _boom)
    out = tools.REGISTRY["create_slideshow"].handler(tmp_path, {
        "title": "A sentence used to be one vector",
        "slug": "no-gen",
        "slides": [
            {
                "layout": "title",
                "heading": "A sentence used to be one vector",
                "lede": "That bottleneck is why attention exists.",
            },
            {
                "layout": "quote",
                "heading": "2014",
                "quote": "We conjecture that the use of a fixed-length vector is a bottleneck.",
                "quote_attr": "Bahdanau",
                "image_prompt": "a GPU kernel diagram of tiled softmax",
            },
            {
                "layout": "close",
                "heading": "The kernel changed.",
                "lede": "The math of attention did not change in 2022.",
            },
        ],
    })
    assert out["ok"] is True, out
    assert called == []


def test_curator_jargon_is_refused(tmp_path: Path):
    out = tools.REGISTRY["create_slideshow"].handler(tmp_path, {
        "title": "Lineage",
        "slides": [
            {
                "layout": "title",
                "heading": "Lineage",
                "lede": "A vault-backed working set of attention.",
            },
            {
                "layout": "cards",
                "heading": "Act 1",
                "cards": [{"title": "A", "body": "b"}],
            },
            {
                "layout": "close",
                "heading": "End",
                "lede": "Remember this.",
            },
        ],
    })
    assert out["ok"] is False
    assert "curator" in str(out.get("error") or "").lower() or "vault-backed" in str(out.get("error") or "").lower()


def test_quote_stats_chart_layouts(tmp_path: Path):
    ev = tmp_path / "wiki" / "evidence" / "vaswani.md"
    ev.parent.mkdir(parents=True)
    ev.write_text(
        "# Vaswani\n\n> dispensing with recurrence and convolutions entirely.\n",
        encoding="utf-8",
    )
    out = tools.REGISTRY["create_slideshow"].handler(tmp_path, {
        "title": "Attention is all you need",
        "slides": [
            {
                "layout": "title",
                "heading": "Drop the recurrence.",
                "lede": "A 2017 paper replaced RNNs with attention and beat the translation leaderboards.",
            },
            {
                "layout": "quote",
                "heading": "Their words",
                "quote_from": "wiki/evidence/vaswani.md",
                "attr": "Vaswani et al., 2017",
            },
            {
                "layout": "stats",
                "heading": "WMT 2014",
                "stats": [
                    {"value": "28.4", "label": "BLEU EN-DE", "hint": "new SOTA"},
                    {"value": "41.8", "label": "BLEU EN-FR", "hint": "3.5 days, 8 GPUs"},
                ],
            },
            {
                "layout": "chart",
                "heading": "Same paper, two tasks",
                "chart_title": "BLEU",
                "chart": [
                    {"label": "EN-DE", "value": 28.4, "unit": "BLEU"},
                    {"label": "EN-FR", "value": 41.8, "unit": "BLEU"},
                ],
            },
            {
                "layout": "close",
                "heading": "Attention was enough.",
                "lede": "No recurrence. No convolution. Better BLEU, less train time.",
            },
        ],
    })
    assert out["ok"] is True, out
    html = (tmp_path / "slideshows" / "attention-is-all-you-need" / "index.html").read_text(
        encoding="utf-8",
    )
    assert "dispensing with recurrence" in html
    assert "28.4" in html
    assert "41.8" in html
    assert "<svg" in html
    assert "stat-v" in html


def test_write_slideshow_still_allows_short_decks(tmp_path: Path):
    """Low-level API stays permissive; the agent tool is the quality gate."""
    slideshow_html.write_slideshow(
        tmp_path,
        "short",
        title="Short",
        slides=[
            {"layout": "title", "heading": "One"},
            {"layout": "bullets", "heading": "Two", "bullets": ["a"]},
        ],
    )
    html = (tmp_path / "slideshows" / "short" / "index.html").read_text(
        encoding="utf-8",
    )
    assert "One" in html
    assert "Two" in html
