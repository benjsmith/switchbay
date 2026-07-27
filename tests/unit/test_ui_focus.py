"""ui_focus multi-surface store + combined prompt lines."""

from __future__ import annotations

from pathlib import Path

from switchbay import sheet_focus, ui_focus


def test_save_load_surfaces(tmp_path: Path):
    saved = ui_focus.save(tmp_path, "table", {"sql": "SELECT 1"})
    assert saved["surface"] == "table"
    assert saved["sql"] == "SELECT 1"
    assert saved["updated_at"]
    loaded = ui_focus.load(tmp_path, "table")
    assert loaded is not None
    assert loaded["sql"] == "SELECT 1"


def test_combined_prompt_includes_fresh_surfaces(tmp_path: Path):
    sheet_focus.save(tmp_path, {"a1": "H18", "used_range": "A1:H17"})
    ui_focus.save(tmp_path, "table", {"sql": "SELECT * FROM pages LIMIT 5"})
    ui_focus.save(tmp_path, "plot", {"id": "sales", "name": "Sales"})
    ui_focus.save(tmp_path, "sketch", {
        "sketch_id": "slide-1", "name": "Title", "slide_index": 0,
        "deck_title": "My deck",
    })
    text = ui_focus.combined_prompt_lines(tmp_path)
    assert text is not None
    assert "Sheet cell H18" in text
    assert "Table SQL" in text
    assert "Plot" in text and "sales" in text
    assert "Sketch" in text and "slide-1" in text


def test_empty_workspace_no_prompt(tmp_path: Path):
    assert ui_focus.combined_prompt_lines(tmp_path) is None
