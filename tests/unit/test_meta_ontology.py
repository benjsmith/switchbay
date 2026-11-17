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
    assert {e.type for e in ont.edges} >= {"wikilink", "cites", "sources", "relates_to"}
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


def test_export_dir_reads_flags_and_does_not_guess(tmp_path: Path):
    assert okf_export.export_dir(["--out", str(tmp_path)], {}) == tmp_path
    assert okf_export.export_dir(["--output=okf"], {}) == Path("okf")
    assert okf_export.export_dir([], {"out": str(tmp_path)}) == tmp_path
    assert okf_export.export_dir([], {"out": str(tmp_path / "missing")}) is None
    assert okf_export.export_dir([], {}) is None


def yaml_load(path: Path):
    import yaml
    return yaml.safe_load(path.read_text(encoding="utf-8"))
