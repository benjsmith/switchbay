"""Figure docs, gallery sections, and plot thumbnails."""

from __future__ import annotations

import json
import time
from pathlib import Path

from PIL import Image

from switchbay import library, plot_gallery, plots


def _revenue_spec() -> dict:
    return {
        "title": "Revenue by region",
        "description": "Quarterly revenue split by region.",
        "mark": "bar",
        "data": {"values": [
            {"quarter": "Q1", "region": "North", "revenue": 10},
            {"quarter": "Q1", "region": "South", "revenue": 7},
            {"quarter": "Q2", "region": "North", "revenue": 12},
            {"quarter": "Q2", "region": "South", "revenue": 9},
        ]},
        "encoding": {
            "x": {"field": "quarter", "type": "ordinal", "title": "Quarter"},
            "y": {"field": "revenue", "type": "quantitative", "axis": {"title": "Revenue"}},
            "color": {
                "field": "region",
                "type": "nominal",
                "legend": {"title": "Region"},
            },
        },
    }


def _write_extracted(workspace: Path, stem: str, title: str, caption: str) -> None:
    assets = workspace / "wiki" / "figures" / "_assets"
    assets.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (800, 480), "#f4efe6")
    image.save(assets / f"{stem}.png", format="PNG")
    page = workspace / "wiki" / "figures" / f"{stem}.md"
    page.write_text(
        "---\n"
        f'title: "{title}"\n'
        "type: figure\n"
        "origin: extracted\n"
        f"asset: {stem}.png\n"
        "sources: [meal-study]\n"
        "axis_titles:\n"
        '  - "Time"\n'
        '  - "Concentration"\n'
        "legend:\n"
        '  - "control"\n'
        '  - "treated"\n'
        "---\n\n"
        f"![[figures/_assets/{stem}.png]]\n\n"
        f"*{caption}*\n",
        encoding="utf-8",
    )


def test_chart_text_reads_spec_axes_legend_and_nested_layer():
    spec = {
        "title": {"text": ["Life", "expectancy"], "subtitle": "By country"},
        "layer": [
            {
                "mark": "line",
                "encoding": {
                    "x": {"field": "year", "type": "quantitative", "title": "Year"},
                    "y": {"field": "years", "type": "quantitative", "axis": {"title": "Years"}},
                    "color": {"field": "country", "type": "nominal", "legend": None},
                },
            },
            {
                "mark": "point",
                "encoding": {
                    "color": {
                        "field": "country",
                        "type": "nominal",
                        "legend": {"title": "Country"},
                    },
                },
                "data": {"values": [{"country": "Japan"}, {"country": "Sweden"}]},
            },
        ],
    }
    text = plot_gallery.chart_text_from_spec(spec)
    assert text["title"] == "Life expectancy"
    assert text["caption"] == "By country"
    assert text["axis_titles"] == ["Year", "Years"]
    assert "Country" in text["legend_titles"]
    assert text["legend_entries"] == ["Japan", "Sweden"]


def test_matplotlib_artists_are_read_without_ocr():
    class _Text:
        def __init__(self, value: str) -> None:
            self._value = value

        def get_text(self) -> str:
            return self._value

    class _Legend:
        def get_title(self) -> _Text:
            return _Text("Run")

        def get_texts(self) -> list[_Text]:
            return [_Text("train"), _Text("val")]

    class _Axis:
        def get_title(self) -> str:
            return "Training loss"

        def get_xlabel(self) -> str:
            return "Epoch"

        def get_ylabel(self) -> str:
            return "Loss"

        def get_legend(self) -> _Legend:
            return _Legend()

    class _Figure:
        axes = [_Axis()]

        def get_suptitle(self) -> str:
            return ""

    artists = plot_gallery.artist_dict_from_figure(_Figure())
    assert artists["xlabel"] == "Epoch"
    assert artists["ylabel"] == "Loss"
    assert artists["title"] == "Training loss"
    assert artists["legend"] == ["train", "val"]
    assert artists["legend_title"] == "Run"


def test_save_plot_writes_figure_doc_with_axes_and_legend(tmp_path: Path):
    rec = plots.save_plot(
        tmp_path,
        name="Revenue by region",
        spec=_revenue_spec(),
        origin="tables/sales.md#t1",
        sources=["vault/sales.csv"],
        analysis="wiki/analyses/sales.md",
    )
    doc = plot_gallery.figure_doc_for_plot(tmp_path, rec["id"])
    assert doc is not None
    markdown = doc["markdown"]
    assert "type: figure" in markdown
    assert "origin: created" in markdown
    assert f"source: plot:{rec['id']}" in markdown
    assert "Quarterly revenue split by region." in markdown
    assert "Quarter" in markdown
    assert "Revenue" in markdown
    assert "North" in markdown
    assert "South" in markdown
    assert "Region" in markdown
    assert f"Source script: `.workbench/plots/{rec['id']}.json`." in markdown
    assert "[[sales]]" in markdown
    asset = tmp_path / "wiki" / "figures" / "_assets" / f"{rec['id']}.png"
    assert asset.is_file()
    with Image.open(asset) as image:
        assert max(image.size) > plot_gallery.THUMB_MAX


def test_backfill_creates_a_doc_for_a_plot_file_and_skips_edits(tmp_path: Path):
    raw = {
        "id": "cohort-retention",
        "name": "Cohort retention",
        "spec": {
            "title": "Cohort retention",
            "description": "Share of each cohort still active.",
            "mark": "line",
            "data": {"values": [{"week": 1, "cohort": "Jan", "share": 0.8}]},
            "encoding": {
                "x": {"field": "week", "type": "quantitative", "title": "Weeks since signup"},
                "y": {"field": "share", "type": "quantitative", "title": "Share still active"},
                "color": {"field": "cohort", "type": "nominal", "legend": {"title": "Cohort"}},
            },
        },
        "created_at": 1,
        "updated_at": 1,
    }
    dest = tmp_path / ".workbench" / "plots"
    dest.mkdir(parents=True)
    (dest / "cohort-retention.json").write_text(json.dumps(raw), encoding="utf-8")
    created = plot_gallery.backfill_figure_docs(tmp_path)
    assert created == ["cohort-retention"]
    doc = plot_gallery.figure_doc_for_plot(tmp_path, "cohort-retention")
    assert doc is not None
    assert "Weeks since signup" in doc["markdown"]
    assert "managed: true" in doc["markdown"]
    again = plot_gallery.backfill_figure_docs(tmp_path)
    assert again == []

    page = tmp_path / "wiki" / "figures" / "cohort-retention.md"
    page.write_text(
        "---\n"
        'title: "[fig] Cohort retention"\n'
        "type: figure\n"
        "source: plot:cohort-retention\n"
        "sources: [cohort]\n"
        "---\n\n"
        "HAND EDITED\n",
        encoding="utf-8",
    )
    plots.save_plot(
        tmp_path,
        name="Cohort retention",
        spec={
            **raw["spec"],
            "encoding": {
                **raw["spec"]["encoding"],
                "x": {"field": "week", "type": "quantitative", "title": "A brand new axis"},
            },
        },
        plot_id="cohort-retention",
    )
    assert "HAND EDITED" in page.read_text(encoding="utf-8")
    assert "A brand new axis" not in page.read_text(encoding="utf-8")


def test_matplotlib_figure_updates_a_managed_doc(tmp_path: Path):
    rec = plots.save_plot(tmp_path, name="Loss curve", spec={
        "mark": "line",
        "data": {"values": [{"epoch": 1, "loss": 0.4}]},
        "encoding": {
            "x": {"field": "epoch", "type": "quantitative"},
            "y": {"field": "loss", "type": "quantitative"},
        },
    })

    class _Legend:
        def get_title(self):
            return "Run"

        def get_texts(self):
            return ["train"]

    class _Axis:
        def get_title(self):
            return "Training loss"

        def get_xlabel(self):
            return "Epoch"

        def get_ylabel(self):
            return "Loss"

        def get_legend(self):
            return _Legend()

    class _Figure:
        axes = [_Axis()]

    plot_gallery.apply_matplotlib_figure(tmp_path, rec["id"], _Figure())
    doc = plot_gallery.figure_doc_for_plot(tmp_path, rec["id"])
    assert doc is not None
    assert "Epoch" in doc["markdown"]
    assert "Loss" in doc["markdown"]
    assert "train" in doc["markdown"]


def test_gallery_splits_extracted_figures_from_generated_plots(tmp_path: Path):
    _write_extracted(tmp_path, "glucose", "Glucose curve", "Plasma glucose after the meal.")
    plots.save_plot(tmp_path, name="Revenue by region", spec=_revenue_spec())
    view = plot_gallery.gallery(tmp_path)
    extracted_titles = [item["title"] for item in view["extracted"]]
    plot_titles = [item["title"] for item in view["plots"]]
    assert extracted_titles == ["Glucose curve"]
    assert any("Revenue" in title for title in plot_titles)
    assert all(not str(item.get("source", "")).startswith("plot:") for item in view["extracted"])
    assert view["extracted"][0]["axis_titles"] == ["Time", "Concentration"]
    assert "treated" in view["extracted"][0]["legend_entries"]
    assert view["extracted"][0]["image"] == "/figures/glucose.png"
    revenue = view["plots"][0]
    assert "Quarter" in revenue["axis_titles"]
    assert "North" in revenue["legend_entries"]
    assert revenue["thumb"].endswith("/thumb")
    assert "_assets" not in revenue["thumb"]


def test_library_lists_only_generated_plots_with_thumb_urls(tmp_path: Path):
    _write_extracted(tmp_path, "glucose", "Glucose curve", "Plasma glucose after the meal.")
    plots.save_plot(tmp_path, name="Revenue by region", spec=_revenue_spec())
    catalog = library.list_all(tmp_path)
    titles = [item["title"] for item in catalog["plots"]]
    assert len(titles) == 1
    assert "Glucose" not in titles[0]
    assert catalog["plots"][0]["thumbs"] == [f"/api/plots/{catalog['plots'][0]['slug']}/thumb"]
    assert catalog["counts"]["plots"] == 1
    hits = library.search(tmp_path, "Quarter")
    assert [hit["kind"] for hit in hits] == ["plot"]
    assert library.search(tmp_path, "Glucose curve") == []
    thumb = plot_gallery.thumbnail_bytes(tmp_path, catalog["plots"][0]["slug"])
    assert thumb
    with Image.open(__import__("io").BytesIO(thumb)) as image:
        assert image.size[0] <= plot_gallery.THUMB_MAX
        assert image.size[1] <= plot_gallery.THUMB_MAX
        assert max(image.size) >= 32
    asset = next((tmp_path / "wiki" / "figures" / "_assets").glob("*.png"))
    assert asset.stat().st_size > len(thumb)


def test_listing_hundreds_of_figures_stays_quick(tmp_path: Path):
    figures = tmp_path / "wiki" / "figures"
    figures.mkdir(parents=True)
    for i in range(200):
        (figures / f"fig-{i}.md").write_text(
            "---\n"
            "type: figure\n"
            f'title: "Figure {i}"\n'
            "origin: extracted\n"
            "axis_titles:\n"
            f'  - "Axis {i}"\n'
            "---\n\n"
            f"*Caption {i}.*\n",
            encoding="utf-8",
        )
    started = time.perf_counter()
    view = plot_gallery.gallery(tmp_path)
    elapsed = time.perf_counter() - started
    assert len(view["extracted"]) == 200
    assert view["plots"] == []
    assert elapsed < 1.5, f"gallery took {elapsed:.2f}s"
