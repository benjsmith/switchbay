"""Durable library packages: reports, worksheets, catalog search."""

from __future__ import annotations

from pathlib import Path

from switchbay import library, report_html, report_packages, worksheets_store


def test_report_package_write_and_list(tmp_path: Path):
    html = report_html.render_report(
        title="Demo Report",
        summary="A short lede.",
        sections=[
            {"heading": "One", "paragraphs": ["Hello."], "bullets": ["a", "b"]},
            {"heading": "Two", "paragraphs": ["World."]},
        ],
        sources=["wiki/entities/foo"],
    )
    res = report_packages.write_html_package(
        tmp_path, "demo-report",
        title="Demo Report",
        html=html,
        summary="A short lede.",
        sources=["wiki/entities/foo"],
    )
    assert res["ok"]
    assert "report:demo-report" in res["wikilink"]
    entry = report_packages.entry_path(tmp_path, "demo-report")
    assert entry is not None and entry.is_file()
    items = report_packages.list_packages(tmp_path)
    assert len(items) == 1
    assert items[0]["slug"] == "demo-report"
    assert items[0]["title"] == "Demo Report"


def test_worksheet_save_load(tmp_path: Path):
    snap = {
        "id": "wb1",
        "sheets": {
            "s1": {"id": "s1", "name": "Assumptions"},
            "s2": {"id": "s2", "name": "Model"},
        },
        "sheetOrder": ["s1", "s2"],
    }
    res = worksheets_store.save_snapshot(
        tmp_path, "fin-model", snap, title="Financial model",
    )
    assert res["ok"]
    assert res["sheet_names"] == ["Assumptions", "Model"]
    loaded = worksheets_store.load_snapshot(tmp_path, "fin-model")
    assert loaded is not None
    assert loaded["id"] == "wb1"
    items = worksheets_store.list_packages(tmp_path)
    assert len(items) == 1
    assert items[0]["slug"] == "fin-model"


def test_library_search(tmp_path: Path):
    report_packages.write_html_package(
        tmp_path, "alpha-report",
        title="Alpha Analysis",
        html="<html><body>x</body></html>",
        summary="about transformers",
    )
    worksheets_store.save_snapshot(
        tmp_path, "beta-sheet",
        {"sheets": {"s": {"name": "Main"}}},
        title="Beta Budget",
    )
    # minimal slideshow package
    d = tmp_path / "slideshows" / "gamma-show"
    d.mkdir(parents=True)
    (d / "index.html").write_text("<html></html>", encoding="utf-8")
    (d / "deck.json").write_text(
        '{"title": "Gamma Deck"}', encoding="utf-8",
    )

    catalog = library.list_all(tmp_path)
    assert catalog["counts"]["reports"] == 1
    assert catalog["counts"]["worksheets"] == 1
    assert catalog["counts"]["slideshows"] == 1

    hits = library.search(tmp_path, "alpha")
    assert any(h["slug"] == "alpha-report" for h in hits)
    hits2 = library.search(tmp_path, "budget")
    assert any(h["slug"] == "beta-sheet" for h in hits2)
