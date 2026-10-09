"""Lock procedure/execution Graph palette hexes + label-type coverage.

The Graph (PWA tab and VS Code view) is Curiosity Engine's own viewer;
Switch Bay's copy of CE's canvas shell adds the two label-type rows CE
lacks.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"
EMBED = FRONTEND / "widgets" / "embed"

PROC = "#5e4fa2"
EXEC = "#c51b8a"


def test_css_vars():
    palette = (FRONTEND / "palette.css").read_text()
    assert f"--type-procedure:{PROC}" in palette.replace(" ", "")
    assert f"--type-execution:{EXEC}" in palette.replace(" ", "")


def test_ce_embed_label_types_include_procedure_execution():
    # CE's own embed shell lacks these two rows; Switchbay's copy adds them.
    src = (EMBED / "ceEmbedShell.html").read_text()
    assert 'data-type="procedure"' in src
    assert 'data-type="execution"' in src
    assert "dot-procedure" in src
    assert "dot-execution" in src
