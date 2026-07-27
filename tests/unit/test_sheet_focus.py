"""Unit tests for sheet_focus A1 helpers + focus persistence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from switchbay import sheet_focus


def test_col_letter_roundtrip():
    assert sheet_focus.col_to_letter(0) == "A"
    assert sheet_focus.col_to_letter(25) == "Z"
    assert sheet_focus.col_to_letter(26) == "AA"
    assert sheet_focus.col_to_letter(27) == "AB"
    assert sheet_focus.letter_to_col("A") == 0
    assert sheet_focus.letter_to_col("Z") == 25
    assert sheet_focus.letter_to_col("AA") == 26
    assert sheet_focus.letter_to_col("H") == 7


def test_parse_a1_cell():
    assert sheet_focus.parse_a1_cell("H18") == (17, 7)
    assert sheet_focus.parse_a1_cell("a1") == (0, 0)
    assert sheet_focus.parse_a1_cell("$C$2") == (1, 2)
    with pytest.raises(ValueError):
        sheet_focus.parse_a1_cell("not-a-cell")


def test_parse_a1_range():
    assert sheet_focus.parse_a1_range("H18") == (17, 7, 1, 1)
    assert sheet_focus.parse_a1_range("C2:H17") == (1, 2, 16, 6)
    assert sheet_focus.parse_a1_range("H17:C2") == (1, 2, 16, 6)


def test_cell_to_a1():
    assert sheet_focus.cell_to_a1(17, 7) == "H18"
    assert sheet_focus.cell_to_a1(0, 0) == "A1"


def test_normalise_formula():
    assert sheet_focus.normalise_formula("SUM(A1:A4)") == "=SUM(A1:A4)"
    assert sheet_focus.normalise_formula("=AVERAGE(C2:C17)") == "=AVERAGE(C2:C17)"


def test_validate_writes():
    out = sheet_focus.validate_writes([
        {"cell": "c18", "formula": "AVERAGE(C2:C17)"},
        {"cell": "D18", "formula": "=SUM(D2:D17)"},
    ])
    assert out == [
        {"cell": "C18", "formula": "=AVERAGE(C2:C17)"},
        {"cell": "D18", "formula": "=SUM(D2:D17)"},
    ]
    with pytest.raises(ValueError):
        sheet_focus.validate_writes([])
    with pytest.raises(ValueError):
        sheet_focus.validate_writes([{"cell": "ZZ", "formula": "=1"}])


def test_save_load_caps(tmp_path: Path):
    long = "x" * 200
    preview = [[long, 1.5]] + [[i, f"r{i}"] for i in range(50)]
    saved = sheet_focus.save(tmp_path, {
        "a1": "h18",
        "range": "h18",
        "value": long,
        "used_range": "a1:h17",
        "headers": ["A", "B"] + list("CDEFGHIJKLMNOP"),
        "preview": preview,
    })
    assert saved["a1"] == "H18"
    assert saved["used_range"] == "A1:H17"
    assert len(saved["value"]) <= sheet_focus.MAX_CELL_CHARS
    assert len(saved["headers"]) == sheet_focus.MAX_PREVIEW_COLS
    assert len(saved["preview"]) == sheet_focus.MAX_PREVIEW_ROWS
    assert saved["updated_at"]

    loaded = sheet_focus.load(tmp_path)
    assert loaded is not None
    assert loaded["a1"] == "H18"


def test_is_fresh_and_prompt_line(tmp_path: Path):
    assert sheet_focus.focus_prompt_line(None) is None
    focus = sheet_focus.save(tmp_path, {"a1": "H18", "used_range": "A1:H17"})
    assert sheet_focus.is_fresh(focus)
    line = sheet_focus.focus_prompt_line(focus)
    assert line is not None
    assert "H18" in line
    assert "sheet_set_formula" in line

    stale = dict(focus)
    stale["updated_at"] = (
        datetime.now(timezone.utc) - timedelta(minutes=30)
    ).isoformat()
    assert not sheet_focus.is_fresh(stale)
    assert sheet_focus.focus_prompt_line(stale) is None
