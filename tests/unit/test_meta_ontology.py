"""Optional .curator/meta-ontology.yaml: absent file leaves behaviour alone."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from switchbay import ce_tools, cebridge, meta_ontology, okf_export
from switchbay.meta_ontology import MetaOntologyError


def _write(workspace: Path, text: str) -> None:
    path = workspace / ".curator" / "meta-ontology.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_shipped_example_is_the_default_vocabulary():
    root = Path(__file__).resolve().parents[2]
    ont = meta_ontology.load_file(root / "examples" / "meta-ontology.yaml")
    by_type = {n.type: n for n in ont.nodes}
    assert by_type["evidence"].label == "Evidence"
    assert by_type["fact"].label == "Facts"
    assert by_type["hypothesis"].label == "Hypothesis"
    assert by_type["assumption"].claims is True
    assert by_type["evidence"].color == "#73af48"
    assert {e.type for e in ont.edges} >= {
        "wikilink", "cites", "sources", "relates_to", "supports", "contradicts",
    }
    assert ont.edge("supports").source == ("evidence",)
    assert ont.edge("supports").target == ("hypothesis",)
    assert ont.edge("contradicts").source == ("evidence",)
    assert ont.edge("contradicts").target == ("hypothesis",)
    assert ont.edge("supports").color != ont.edge("contradicts").color
    assert ont.edge("wikilink").source == ()
    assert "State the claim" in by_type["hypothesis"].description
    assert "change the verdict" in by_type["hypothesis"].description
    assert "Do not write the hypotheses inline" in by_type["analysis"].description
    assert "evidence → hypothesis" in ont.curation_text()
    assert "under supports" in ont.curation_text()
    keys = {k.key: k for k in ont.schema_keys}
    assert keys["uncertainty"].values == ("attested", "inferred", "unattested")
    assert keys["confidence"].minimum == 0
    assert keys["confidence"].maximum == 1
    assert "An observation" in by_type["evidence"].description
    assert "one source" in by_type["evidence"].description
    # Viewer payload and OKF export are the same terms.
    assert ont.to_viewer()["nodes"][0]["type"] == ont.to_export()["nodes"][0]["type"]
    assert "label Evidence" in ont.curation_text() or "- evidence" in ont.curation_text()


def test_absent_file_adds_nothing(tmp_path: Path):
    assert meta_ontology.load(tmp_path) is None
    assert meta_ontology.curation_system(tmp_path) == ""
    data = {
        "palette": {"evidence": "#111111"},
        "nodes": [{"id": "e", "type": "evidence", "title": "Latency"}],
        "edges": [{"type": "wikilink", "source": "a", "target": "b"}],
    }
    assert meta_ontology.apply_to_graph_if_configured(tmp_path, data) is False
    assert "metaOntology" not in data
    assert "typeLabel" not in data["nodes"][0]
    assert data["palette"]["evidence"] == "#111111"
    raw = b'{"nodes":[{"type":"evidence"}]}'
    assert meta_ontology.patch_graph_json(raw, tmp_path) == raw


def test_present_file_drives_prompt_legend_and_colours(tmp_path: Path):
    _write(tmp_path, """
version: 1
nodes:
  - type: evidence
    label: Observation
    color: "#112233"
    claims: true
    description: Record the method, the result, and the interpretation.
edges:
  - type: cites
    label: cites
    description: Put the citation in the same paragraph as the claim.
schema_keys:
  - key: uncertainty
    values: [attested, inferred, unattested]
    description: How the statement is backed.
""")
    text = meta_ontology.curation_system(tmp_path)
    assert "label Observation" in text
    assert "same paragraph" in text
    assert "uncertainty" in text
    data = {
        "palette": {"evidence": "#73af48"},
        "nodes": [{"id": "e", "type": "evidence"}],
        "pages": {"e": {"type": "evidence"}},
        "edges": [{"type": "cites"}],
    }
    assert meta_ontology.apply_to_graph_if_configured(tmp_path, data) is True
    assert data["nodes"][0]["type"] == "evidence"
    assert data["nodes"][0]["typeLabel"] == "Observation"
    assert data["pages"]["e"]["typeLabel"] == "Observation"
    assert data["edges"][0]["typeLabel"] == "cites"
    assert data["palette"]["evidence"] == "#112233"
    assert data["metaOntology"]["nodes"][0]["label"] == "Observation"
    patched = json.loads(meta_ontology.patch_graph_json(
        b'{"nodes":[{"type":"evidence"}]}', tmp_path,
    ))
    assert patched["nodes"][0]["typeLabel"] == "Observation"


def test_broken_file_is_reported_and_does_not_stamp_the_graph(tmp_path: Path):
    _write(tmp_path, "version: 1\nnodes: [true]\n")
    with pytest.raises(MetaOntologyError):
        meta_ontology.load(tmp_path)
    message = meta_ontology.curation_system(tmp_path)
    assert "failed to load" in message
    data = {"nodes": [{"type": "evidence"}]}
    assert meta_ontology.apply_to_graph_if_configured(tmp_path, data) is False
    assert "metaOntology" not in data
    assert meta_ontology.patch_graph_json(b'{"nodes":[]}', tmp_path) == b'{"nodes":[]}'


def test_unknown_key_is_rejected(tmp_path: Path):
    _write(tmp_path, """
version: 1
nodes:
  - type: fact
    description: One claim.
    widget: extra
""")
    with pytest.raises(MetaOntologyError, match="unknown keys"):
        meta_ontology.load(tmp_path)


def test_read_cached_stamps_only_when_configured(tmp_path: Path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "data.json").write_text(json.dumps({
        "palette": {"fact": "#ffffff"},
        "nodes": [{"id": "f", "type": "fact"}],
        "pages": {},
        "edges": [],
    }), encoding="utf-8")
    monkeypatch.setattr(cebridge, "output_dir", lambda _ws: bundle)
    plain = cebridge.read_cached(tmp_path)
    assert plain is not None
    assert "metaOntology" not in plain
    assert plain["nodes"][0]["type"] == "fact"
    _write(tmp_path, """
version: 1
nodes:
  - type: fact
    label: Claim
    color: "#010203"
    description: One atomic claim.
""")
    stamped = cebridge.read_cached(tmp_path)
    assert stamped is not None
    assert stamped["nodes"][0]["typeLabel"] == "Claim"
    assert stamped["palette"]["fact"] == "#010203"


@pytest.mark.asyncio
async def test_curate_prompt_omits_ontology_unless_configured(tmp_path: Path, monkeypatch):
    from switchbay import daemon

    monkeypatch.setattr(
        "switchbay.ce_host.wave_prime",
        lambda *_a, **_k: {"mode": "idle"},
    )
    plain = await daemon._curate_extra_system(tmp_path, "", local=False)
    assert "meta-ontology" not in plain.lower()
    _write(tmp_path, """
version: 1
nodes:
  - type: evidence
    label: Observation
    description: Record the method, the result, and the interpretation.
""")
    steered = await daemon._curate_extra_system(tmp_path, "", local=False)
    assert "Workspace meta-ontology" in steered
    assert "label Observation" in steered


def test_okf_export_is_untouched_without_a_config(tmp_path: Path, monkeypatch):
    concept = tmp_path / "facts" / "latency.md"
    concept.parent.mkdir()
    original = "---\ntype: fact\ntitle: Latency\n---\n\nIt rose.\n"
    concept.write_text(original, encoding="utf-8")
    sentinel = {"ok": True, "out": str(tmp_path)}

    def fake_run(script, args=None, *, cwd, timeout=180, require_json=True):
        return sentinel

    monkeypatch.setattr(cebridge, "run_script", fake_run)
    out = ce_tools._ce_run(tmp_path, {
        "script": "okf_export.py",
        "args": ["--out", str(tmp_path)],
    })
    assert out is sentinel
    assert "meta_ontology" not in out
    assert concept.read_text(encoding="utf-8") == original
    assert not (tmp_path / "x_ce_ontology.yaml").exists()


def test_okf_export_uses_the_same_definitions(tmp_path: Path):
    _write(tmp_path, """
version: 1
nodes:
  - type: evidence
    label: Observation
    description: Record the method, the result, and the interpretation.
edges:
  - type: cites
    label: cites
    description: Same paragraph as the claim.
""")
    ont = meta_ontology.load(tmp_path)
    assert ont is not None
    bundle = tmp_path / "okf"
    kept = bundle / "sources" / "readme.md"
    kept.parent.mkdir(parents=True)
    kept.write_text("---\ntype: source\ntitle: Readme\n---\n\nA source.\n", encoding="utf-8")
    (bundle / "index.md").write_text("# index\n", encoding="utf-8")
    concept = bundle / "evidence" / "cpu.md"
    concept.parent.mkdir()
    concept.write_text(
        "---\ntype: evidence\ntitle: CPU\n---\n\nThe series moved.\n",
        encoding="utf-8",
    )
    result = {"ok": True}
    okf_export.finalize_after_ce(tmp_path, ["--out", str(bundle)], result)
    text = concept.read_text(encoding="utf-8")
    assert "type: evidence" in text
    assert "x_ce_type_label: Observation" in text
    assert "method, the result, and the interpretation" in text
    assert kept.read_text(encoding="utf-8").startswith("---\ntype: source\n")
    assert (bundle / "index.md").read_text(encoding="utf-8") == "# index\n"
    sidecar = yaml_load(bundle / "x_ce_ontology.yaml")
    assert sidecar["nodes"][0]["label"] == "Observation"
    assert sidecar["edges"][0]["type"] == "cites"
    assert result["meta_ontology"]["concepts"] == 1


def test_export_labels_figure_and_table_when_the_file_omits_them(tmp_path: Path):
    _write(tmp_path, """
version: 1
nodes:
  - type: evidence
    label: Observation
    description: Record the method, the result, and the interpretation.
""")
    bundle = tmp_path / "okf"
    figure = bundle / "figures" / "latency.md"
    table = bundle / "tables" / "scores.md"
    extracted = bundle / "tables" / "lifted.md"
    other = bundle / "concepts" / "shop.md"
    for path, text in (
        (figure, "---\ntype: figure\ntitle: Latency\n---\n\nA plot.\n"),
        (table, "---\ntype: table\ntitle: Scores\n---\n\nA table.\n"),
        (extracted, "---\ntype: extracted-table\ntitle: Lifted\n---\n\nNumbers.\n"),
        (other, "---\ntype: concept\ntitle: Shop\n---\n\nA concept.\n"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    ont = meta_ontology.load(tmp_path)
    assert ont is not None
    count = okf_export.apply_to_export_tree(bundle, ont)
    assert count == 3
    fig = figure.read_text(encoding="utf-8")
    assert "type: figure" in fig
    assert "x_ce_type_label: Figures" in fig
    assert "Name the data file in sources" in fig
    tab = table.read_text(encoding="utf-8")
    assert "type: table" in tab
    assert "x_ce_type_label: Tables" in tab
    assert "Keep the numbers as they are" in tab
    lifted = extracted.read_text(encoding="utf-8")
    assert "type: extracted-table" in lifted
    assert "x_ce_type_label: Tables" in lifted
    assert other.read_text(encoding="utf-8").startswith("---\ntype: concept\n")
    sidecar = yaml_load(bundle / "x_ce_ontology.yaml")
    labels = {node["type"]: node["label"] for node in sidecar["nodes"]}
    assert labels["evidence"] == "Observation"
    assert labels["figure"] == "Figures"
    assert labels["table"] == "Tables"


def test_export_keeps_a_figure_description_from_the_file(tmp_path: Path):
    _write(tmp_path, """
version: 1
nodes:
  - type: figure
    label: Plot
    description: Name the data file in the caption.
""")
    bundle = tmp_path / "okf"
    figure = bundle / "figures" / "latency.md"
    figure.parent.mkdir(parents=True)
    figure.write_text("---\ntype: figure\ntitle: Latency\n---\n\nA plot.\n", encoding="utf-8")
    ont = meta_ontology.load(tmp_path)
    assert ont is not None
    okf_export.apply_to_export_tree(bundle, ont)
    text = figure.read_text(encoding="utf-8")
    assert "x_ce_type_label: Plot" in text
    assert "Name the data file in the caption" in text
    sidecar = yaml_load(bundle / "x_ce_ontology.yaml")
    types = [node["type"] for node in sidecar["nodes"]]
    assert types[0] == "figure"
    assert "table" in types


def test_shipped_example_figure_and_table_match_export_defaults():
    root = Path(__file__).resolve().parents[2]
    ont = meta_ontology.load_file(root / "examples" / "meta-ontology.yaml")
    for default in meta_ontology.EXPORT_DEFAULT_NODES:
        node = ont.node(default.type)
        assert node is not None
        assert node.label == default.label
        assert node.folder == default.folder
        assert node.color == default.color
        assert " ".join(node.description.split()) == default.description


def test_export_dir_reads_flags_and_does_not_guess(tmp_path: Path):
    assert okf_export.export_dir(["--out", str(tmp_path)], {}) == tmp_path
    assert okf_export.export_dir(["--output=okf"], {}) == Path("okf")
    assert okf_export.export_dir([], {"out": str(tmp_path)}) == tmp_path
    assert okf_export.export_dir([], {"out": str(tmp_path / "missing")}) is None
    assert okf_export.export_dir([], {}) is None


def test_yaml_without_edges_parses(tmp_path: Path):
    _write(tmp_path, """
version: 1
nodes:
  - type: fact
    description: One atomic claim.
""")
    ont = meta_ontology.load(tmp_path)
    assert ont is not None
    assert ont.edges == ()
    assert "Edge types:" not in ont.curation_text()
    data = {"nodes": [{"id": "f", "type": "fact"}], "edges": [], "pages": {}}
    assert meta_ontology.apply_to_graph_if_configured(tmp_path, data) is True
    assert data["edges"] == []


def test_edges_without_endpoints_stay_untyped(tmp_path: Path):
    _write(tmp_path, """
version: 1
nodes:
  - type: fact
    description: One atomic claim.
edges:
  - type: cites
    description: Same paragraph as the claim.
""")
    ont = meta_ontology.load(tmp_path)
    assert ont is not None
    assert ont.edge("cites").typed is False
    exported = ont.to_export()["edges"][0]
    assert exported["type"] == "cites"
    assert "source" not in exported
    assert "target" not in exported
    assert "source type" not in ont.curation_text()


def test_source_without_target_is_rejected(tmp_path: Path):
    _write(tmp_path, """
version: 1
edges:
  - type: supports
    source: [evidence]
    description: When the result matches.
""")
    with pytest.raises(MetaOntologyError, match="set together"):
        meta_ontology.load(tmp_path)


def test_string_endpoint_and_fallback_colour(tmp_path: Path):
    _write(tmp_path, """
version: 1
nodes:
  - type: evidence
    description: An observation.
  - type: hypothesis
    description: State the claim.
edges:
  - type: supports
    source: evidence
    target: hypothesis
    description: When the result matches a prediction.
  - type: contradicts
    source: [evidence]
    target: [hypothesis]
    description: When the result conflicts with a prediction.
""")
    ont = meta_ontology.load(tmp_path)
    assert ont is not None
    assert ont.edge("supports").source == ("evidence",)
    assert ont.edge_color("supports") != ont.edge_color("contradicts")
    viewer = {edge["type"]: edge for edge in ont.to_viewer()["edges"]}
    assert viewer["supports"]["color"]
    assert viewer["contradicts"]["color"]
    assert "color" not in ont.to_export()["edges"][0]


def test_typed_edges_are_drawn_and_hypothesis_type_is_kept(tmp_path: Path):
    _write(tmp_path, """
version: 1
nodes:
  - type: evidence
    label: Evidence
    folder: evidence
    color: "#73af48"
    description: An observation.
  - type: hypothesis
    label: Hypothesis
    folder: hypotheses
    color: "#7570b3"
    description: State the claim and what would change the verdict.
edges:
  - type: supports
    label: supports
    color: "#0072b2"
    source: [evidence]
    target: [hypothesis]
    description: When the result matches a prediction.
  - type: contradicts
    label: contradicts
    color: "#d55e00"
    source: [evidence]
    target: [hypothesis]
    description: When the result conflicts with a prediction.
""")
    evidence = tmp_path / "wiki" / "evidence" / "cpu.md"
    hypothesis = tmp_path / "wiki" / "hypotheses" / "queue.md"
    evidence.parent.mkdir(parents=True)
    hypothesis.parent.mkdir(parents=True)
    evidence.write_text("""---
type: evidence
title: CPU
supports:
  - hypotheses/queue
contradicts: [hypotheses/queue.md]
---

The series moved.
""", encoding="utf-8")
    hypothesis.write_text("""---
type: hypothesis
title: "[hyp] Queue"
---

The queue grows.
""", encoding="utf-8")
    data = {
        "palette": {},
        "nodes": [
            {"id": "evidence/cpu", "type": "evidence", "title": "CPU", "degree": 0},
            {"id": "hypotheses/queue", "type": "unclassified", "title": "Queue", "degree": 0},
        ],
        "pages": {
            "evidence/cpu": {"id": "evidence/cpu", "type": "evidence", "properties": {}},
            "hypotheses/queue": {"id": "hypotheses/queue", "type": "unclassified", "properties": {}},
        },
        "edges": [{"source": "evidence/cpu", "target": "hypotheses/queue", "type": "wikilink"}],
    }
    assert meta_ontology.apply_to_graph_if_configured(tmp_path, data) is True
    assert data["nodes"][1]["type"] == "hypothesis"
    assert data["pages"]["hypotheses/queue"]["type"] == "hypothesis"
    typed = [edge for edge in data["edges"] if edge["type"] in {"supports", "contradicts"}]
    assert {(edge["type"], edge["color"]) for edge in typed} == {
        ("supports", "#0072b2"),
        ("contradicts", "#d55e00"),
    }
    assert all(edge["target"] == "hypotheses/queue" for edge in typed)
    assert data["nodes"][0]["degree"] == 2
    assert data["pages"]["evidence/cpu"]["properties"]["supports"] == ["hypotheses/queue"]
    meta_ontology.apply_to_graph_if_configured(tmp_path, data)
    assert len([edge for edge in data["edges"] if edge["type"] == "supports"]) == 1
    assert data["nodes"][0]["degree"] == 2


def test_export_carries_typed_edges(tmp_path: Path):
    _write(tmp_path, """
version: 1
nodes:
  - type: evidence
    label: Observation
    description: Record the method, the result, and the interpretation.
  - type: hypothesis
    label: Hypothesis
    folder: hypotheses
    description: State the claim and what would change the verdict.
edges:
  - type: supports
    label: supports
    color: "#0072b2"
    source: [evidence]
    target: [hypothesis]
    description: When the result matches a prediction.
""")
    wiki_evidence = tmp_path / "wiki" / "evidence" / "cpu.md"
    wiki_hypothesis = tmp_path / "wiki" / "hypotheses" / "queue.md"
    wiki_evidence.parent.mkdir(parents=True)
    wiki_hypothesis.parent.mkdir(parents=True)
    wiki_evidence.write_text("""---
type: evidence
title: CPU
supports:
  - hypotheses/queue
---

The series moved.
""", encoding="utf-8")
    wiki_hypothesis.write_text("""---
type: hypothesis
title: Queue
---

The queue grows.
""", encoding="utf-8")
    bundle = tmp_path / "okf"
    concept = bundle / "evidence" / "cpu.md"
    other = bundle / "hypotheses" / "queue.md"
    concept.parent.mkdir(parents=True)
    other.parent.mkdir(parents=True)
    concept.write_text("---\ntype: evidence\ntitle: CPU\n---\n\nThe series moved.\n", encoding="utf-8")
    other.write_text("---\ntype: hypothesis\ntitle: Queue\n---\n\nThe queue grows.\n", encoding="utf-8")
    ont = meta_ontology.load(tmp_path)
    assert ont is not None
    okf_export.apply_to_export_tree(bundle, ont, workspace=tmp_path)
    text = concept.read_text(encoding="utf-8")
    assert "x_ce_type_label: Observation" in text
    exported = yaml_load_text(text.split("---", 2)[1])
    assert exported["x_ce_edges"] == [
        {"type": "supports", "target": "hypotheses/queue"},
    ]
    untouched = okf_export.annotate_edges(
        "---\ntype: evidence\ntitle: CPU\n---\n\nBody.\n", None,
    )
    assert "x_ce_edges" not in untouched
    sidecar = yaml_load(bundle / "x_ce_ontology.yaml")
    supports = next(edge for edge in sidecar["edges"] if edge["type"] == "supports")
    assert supports["source"] == ["evidence"]
    assert supports["target"] == ["hypothesis"]
    assert supports["color"] == "#0072b2"


def yaml_load(path: Path):
    import yaml
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def yaml_load_text(text: str):
    import yaml
    return yaml.safe_load(text)
