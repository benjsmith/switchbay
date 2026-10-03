"""Lock Agents/okstratr theme-sync CSS: Switchbay mint accents + status chips."""

from __future__ import annotations

from pathlib import Path

CSS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "index.css"


def _okstratr_theme_block() -> str:
    text = CSS.read_text(encoding="utf-8")
    start = text.index("Agents / okstratr theme sync")
    # Stop before the built-in Agents light block that follows.
    end = text.index(':root[data-theme="light"] .sy-agents', start)
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


def _rule_body(block: str, selector_needle: str) -> str:
    idx = block.index(selector_needle)
    return block[idx:block.index("}", idx)]


def test_standing_badge_stays_warn_not_text():
    """Placeholder .desk-obj--standing is idle amber in light and dark.

    A blanket color: var(--text) must not wash the standing badge gray.
    """
    block = _okstratr_theme_block()
    light = _rule_body(
        block,
        ':root[data-theme="light"] .sy-proxied-skill[data-kind="okstratr"] '
        ".sy-proxied-skill-html .desk-obj--standing",
    )
    dark = _rule_body(
        block,
        ':root[data-theme="dark"] .sy-proxied-skill[data-kind="okstratr"] '
        ".sy-proxied-skill-html .desk-obj--standing",
    )
    for rule in (light, dark):
        assert "color: var(--warn)" in rule
        assert "var(--text)" not in rule
        assert "var(--muted)" not in rule
    # Neutral chip wash still excludes status chips (idle amber / running green).
    neutral = _rule_body(block, ".chip:not(.running):not(.idle)")
    assert "desk-obj--standing" not in neutral
    assert ".chip.idle" not in neutral.split("{", 1)[0]
