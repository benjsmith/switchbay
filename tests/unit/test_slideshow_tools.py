"""HTML slideshow tool registration and authoring."""

from __future__ import annotations

from pathlib import Path

from switchbay import tools


def test_slideshow_tools_replace_sketch_decks():
    names = set(tools.REGISTRY)
    assert "create_slideshow" in names
    assert "author_sketch" in names
    for obsolete in (
        "make_slides_from_doc",
        "make_slides_from_docs",
        "compose_analysis",
        "author_slide",
    ):
        assert obsolete not in names


def test_create_slideshow_writes_package(tmp_path: Path):
    out = tools.REGISTRY["create_slideshow"].handler(tmp_path, {
        "title": "Demo talk",
        "slides": [
            {"layout": "title", "heading": "Hello"},
            {"layout": "bullets", "heading": "Points", "bullets": ["one"]},
        ],
    })
    assert out["ok"]
    assert out["slug"] == "demo-talk"
    html = (tmp_path / "slideshows" / "demo-talk" / "index.html").read_text(
        encoding="utf-8",
    )
    assert "Hello" in html
    assert "@page{size:13.333in 7.5in;margin:0}" in html
    assert "page-break-after:always" in html
