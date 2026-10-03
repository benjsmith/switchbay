"""Lock procedure/execution Graph palette hexes + sidebar/template coverage."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GRAPH = ROOT / "frontend" / "src" / "widgets" / "graph"

PROC = "#5e4fa2"
EXEC = "#c51b8a"


def test_css_vars_and_sidebar_dots():
    css = (GRAPH / "ce-graph.css").read_text()
    assert f"--type-procedure:     {PROC}" in css or f"--type-procedure: {PROC}" in css or f"--type-procedure:{PROC}" in css.replace(" ", "")
    assert PROC in css
    assert EXEC in css
    assert "--type-procedure" in css
    assert "--type-execution" in css
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


def test_sidebar_canonical_order_and_labels():
    src = (GRAPH / "static" / "sidebar.js").read_text()
    assert "procedure:" in src and "procedures:" in src
    assert "execution:" in src and "executions:" in src
    assert "'procedure'" in src and "'execution'" in src
    assert "Procedures" in src
    assert "Executions" in src


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
