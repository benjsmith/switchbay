"""Deterministic wiki inject + wikilink wiring."""

from __future__ import annotations

from pathlib import Path

from switchbay import plots, wiki_sync


def _page(ws: Path, rel: str, title: str, body: str, ptype: str = "concept") -> Path:
    p = ws / "wiki" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        f"---\ntitle: \"{title}\"\ntype: {ptype}\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return p


def test_inject_on_disk_pages_adds_missing_node(tmp_path: Path) -> None:
    _page(tmp_path, "concepts/attention.md", "[con] Attention", "About attention.")
    data: dict = {"pages": {}, "nodes": [], "edges": []}
    n = wiki_sync.inject_on_disk_pages(tmp_path, data)
    assert n >= 1
    assert "concepts/attention" in data["pages"]
    ids = [x["id"] for x in data["nodes"]]
    assert "concepts/attention" in ids


def test_inject_caps_body_html(tmp_path: Path) -> None:
    blob = "word " * 5000
    _page(tmp_path, "concepts/huge.md", "[con] Huge", blob)
    data: dict = {"pages": {}, "nodes": [], "edges": []}
    wiki_sync.inject_on_disk_pages(tmp_path, data)
    html = data["pages"]["concepts/huge"]["body_html"]
    assert len(html) < wiki_sync._BODY_HTML_CAP + 200
    slim = {"pages": {"concepts/huge": {"body_html": "<p>" + "x" * 50_000 + "</p>"}}}
    wiki_sync.slim_graph_payload(slim)
    assert len(slim["pages"]["concepts/huge"]["body_html"]) < 8_000


def test_inject_adds_wikilink_edges(tmp_path: Path) -> None:
    _page(tmp_path, "concepts/attention.md", "[con] Attention", "See also.")
    _page(
        tmp_path, "analyses/note.md", "[ana] Note",
        "Uses [[attention]] heavily.", "analysis",
    )
    data: dict = {"pages": {}, "nodes": [], "edges": []}
    wiki_sync.inject_on_disk_pages(tmp_path, data)
    trips = {(e["source"], e["target"]) for e in data["edges"]}
    assert ("analyses/note", "concepts/attention") in trips


def test_wire_new_page_wraps_title_mention(tmp_path: Path) -> None:
    _page(tmp_path, "concepts/attention.md", "[con] Attention", "The mechanism.")
    dest = _page(
        tmp_path, "analyses/life.md", "[ana] Life",
        "Attention is discussed here.", "analysis",
    )
    out = wiki_sync.wire_new_page(tmp_path, "wiki/analyses/life.md")
    assert out["ok"]
    text = dest.read_text(encoding="utf-8")
    assert "[[attention]]" in text


def test_save_plot_persists_caption_and_provenance(tmp_path: Path) -> None:
    rec = plots.save_plot(
        tmp_path,
        name="Life expectancy",
        spec={"description": "Years of life.", "mark": "line", "data": {"values": []}},
        origin="tables/owid.md#t1",
        analysis="analyses/longevity",
        sources=["vault/owid.extracted.md"],
        relates_to=["concepts/longevity"],
    )
    loaded = plots.get_plot(tmp_path, rec["id"])
    assert loaded is not None
    assert loaded.get("caption") == "Years of life."
    assert loaded.get("origin") == "tables/owid.md#t1"
    assert loaded.get("analysis") == "analyses/longevity"
    assert "concepts/longevity" in (loaded.get("relates_to") or [])


def test_figure_page_markdown_carries_caption_and_links() -> None:
    plot = {
        "id": "life-exp",
        "name": "Life expectancy",
        "caption": "Years of life by country.",
        "origin": "tables/owid-life.md#t1",
        "analysis": "wiki/analyses/longevity.md",
        "sources": ["vault/owid.extracted.md"],
        "relates_to": ["concepts/longevity"],
        "spec": {"description": "ignored when caption set"},
    }
    md = plots.figure_page_markdown(plot, asset_name="life-exp.png", today="2026-08-17")
    assert "Years of life by country." in md
    assert "origin: created" in md
    assert "source_analysis: longevity" in md
    assert "[[longevity]]" in md
    assert "[[owid-life]]" in md
    assert "![[figures/_assets/life-exp.png]]" in md
