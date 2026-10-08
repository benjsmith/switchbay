"""Lock procedure/execution Graph palette hexes + label-type coverage.

The PWA Graph is Curiosity Engine's own viewer (via /embed/ce); the
`widgets/graph` fork remains only for the VS Code graph webview.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"
GRAPH = FRONTEND / "widgets" / "graph"
EMBED = FRONTEND / "widgets" / "embed"

PROC = "#5e4fa2"
EXEC = "#c51b8a"


def test_css_vars_and_dots():
    palette = (FRONTEND / "palette.css").read_text()
    assert f"--type-procedure:{PROC}" in palette.replace(" ", "")
    assert f"--type-execution:{EXEC}" in palette.replace(" ", "")
    css = (GRAPH / "ce-graph.css").read_text()
    assert ".dot.dot-procedure" in css
    assert ".dot.dot-execution" in css


def test_replay_type_color_map():
    src = (GRAPH / "curationReplayAnim.ts").read_text()
    assert f'procedure: "{PROC}"' in src
    assert f'execution: "{EXEC}"' in src


def test_atlas_type_keys_include_procedure_execution():
    src = (GRAPH / "atlas.ts").read_text()
    assert '"procedure"' in src
    assert '"execution"' in src


def test_ce_embed_label_types_include_procedure_execution():
    # CE's own embed shell lacks these two rows; Switchbay's copy adds them.
    src = (EMBED / "ceEmbedShell.html").read_text()
    assert 'data-type="procedure"' in src
    assert 'data-type="execution"' in src
    assert "dot-procedure" in src
    assert "dot-execution" in src


def test_graph_canonical_and_label_types():
    src = (GRAPH / "static" / "graph.js").read_text()
    assert "procedure:" in src and "procedures:" in src
    assert "execution:" in src and "executions:" in src
    assert "'procedure'" in src and "'execution'" in src


def test_template_label_rows_include_procedure_execution():
    src = (GRAPH / "template.ts").read_text()
    assert 'data-type="procedure"' in src
    assert 'data-type="execution"' in src
    assert "Procedures" in src
    assert "Executions" in src
    assert "dot-procedure" in src
    assert "dot-execution" in src
