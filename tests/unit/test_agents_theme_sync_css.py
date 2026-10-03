"""Lock Agents/okstratr theme-sync CSS: Switchbay mint accents + status chips."""

from __future__ import annotations

from pathlib import Path

CSS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "index.css"


def _okstratr_theme_block() -> str:
    text = CSS.read_text()
    start = text.index("Agents / okstratr theme sync")
    # Stop before the built-in Agents light block that follows.
    end = text.index(":root[data-theme=\"light\"] .sy-agents", start)
    return text[start:end]


def test_accents_match_switchbay_mint():
    block = _okstratr_theme_block()
    assert "--accent: #2f9874" in block
    assert "--accent: #6be8b3" in block
    assert "#3d6fd9" not in block
    assert "#7aa2f7" not in block


def test_light_chip_rule_preserves_running_and_idle():
    block = _okstratr_theme_block()
    assert ".chip:not(.running):not(.idle)" in block
    assert ".chip.running" in block
    assert "color: var(--ok)" in block
    assert ".chip.idle" in block
    assert "color: var(--warn)" in block
