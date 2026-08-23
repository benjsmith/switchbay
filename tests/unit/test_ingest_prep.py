"""Readable ingest staging — files, HTML/XML/JSON, path containment."""

from __future__ import annotations

from pathlib import Path

from switchbay import ce_tools, ingest_prep, tools
from switchbay.agents import orchestration, rail_default


def _ixbrl_like_html() -> str:
    hidden = (
        '<div style="display:none"><ix:header><ix:hidden>'
        + ("xmlns:us-gaap='http://www.xbrl.org/2003/instance' " * 800)
        + "</ix:hidden></ix:header></div>"
    )
    return (
        "<html><head><title>Form 10-K</title></head><body>"
        f"{hidden}"
        "<h1>Cover</h1><p>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</p>"
        "<h2>Item 1. Business</h2><p>We sell widgets worldwide.</p>"
        "<h2>Item 8. Financial Statements</h2>"
        "<p>Net income was twelve billion dollars.</p>"
        "<table><tr><th>Year</th><th>Revenue</th></tr>"
        "<tr><td>2024</td><td>50</td></tr></table>"
        "</body></html>"
    )


def _jats_like_xml() -> str:
    return (
        '<?xml version="1.0"?><article>'
        "<front><title-group>"
        "<article-title>CRISPR editing of BRCA1</article-title>"
        "</title-group>"
        "<abstract><p>We report efficient editing in iPS cells.</p></abstract>"
        "</front>"
        "<body><sec><title>Methods</title>"
        "<p>Guide RNAs targeted exon 11.</p></sec></body>"
        "</article>"
    )


def test_html_skips_hidden_schema_and_keeps_priority_heading():
    text = ingest_prep.readable_html(_ixbrl_like_html().encode("utf-8"))
    assert "Net income was twelve billion" in text
    assert "Item 8. Financial Statements" in text
    assert "xmlns:us-gaap" not in text
    assert "http://www.xbrl.org" not in text
    assert "| Year | Revenue |" in text or "2024" in text


def test_html_priority_keeps_late_results_section():
    filler = "".join(
        f"<h2>Note {i}</h2><p>{'word ' * 400}</p>" for i in range(30)
    )
    html = (
        "<html><body><h1>Paper</h1>"
        f"{filler}"
        "<h2>Results</h2><p>The knockout survived.</p>"
        "</body></html>"
    )
    text = ingest_prep.readable_html(html.encode("utf-8"), max_bytes=8_000)
    assert "The knockout survived" in text
    assert "Results" in text


def test_xml_scientific_article_preserves_fields():
    text = ingest_prep.readable_xml(_jats_like_xml().encode("utf-8"))
    assert "CRISPR editing of BRCA1" in text
    assert "efficient editing in iPS cells" in text
    assert "Guide RNAs targeted exon 11" in text


def test_json_large_array_keeps_metadata():
    obj = {
        "accession": "GSE123",
        "platform": "HiSeq",
        "samples": [{"id": i, "tpm": 0.1 * i} for i in range(50_000)],
    }
    import json
    raw = json.dumps(obj).encode("utf-8")
    assert len(raw) > ingest_prep.MAX_READABLE_BYTES
    text = ingest_prep.readable_json(raw)
    assert "GSE123" in text
    assert "HiSeq" in text
    assert "_omitted" in text
    assert len(text.encode("utf-8")) <= ingest_prep.MAX_READABLE_BYTES


def test_csv_samples_head_and_tail():
    header = "gene,tpm,note\n"
    rows = "".join(f"g{i},{i}.0,{'x' * 40}\n" for i in range(8_000))
    raw = (header + rows).encode("utf-8")
    assert len(raw) > ingest_prep.MAX_READABLE_BYTES
    text = ingest_prep.readable_csv(raw)
    assert "gene,tpm" in text
    assert "g0," in text
    assert "g7999," in text
    assert "omitted" in text


def test_prepare_file_uses_ce_file_flag(tmp_path: Path):
    src = tmp_path / "cache" / "paper.html"
    src.parent.mkdir(parents=True)
    src.write_text(_ixbrl_like_html(), encoding="utf-8")
    prep = ingest_prep.prepare(tmp_path, "cache/paper.html")
    assert prep.error is None
    assert prep.ce_args[:1] == ["--file"]
    staged = tmp_path / prep.ce_args[1]
    assert staged.is_file()
    body = staged.read_text(encoding="utf-8")
    assert "switchbay-readable" in body
    assert "original: cache/paper.html" in body
    assert "Net income was twelve billion" in body
    assert "xmlns:us-gaap" not in body


def test_prepare_xml_file_becomes_txt(tmp_path: Path):
    src = tmp_path / "vault" / "raw" / "paper.nxml"
    src.parent.mkdir(parents=True)
    src.write_text(_jats_like_xml(), encoding="utf-8")
    prep = ingest_prep.prepare(tmp_path, "vault/raw/paper.nxml")
    assert prep.error is None
    assert prep.ce_args[0] == "--file"
    assert prep.ce_args[1].endswith(".txt")
    text = (tmp_path / prep.ce_args[1]).read_text(encoding="utf-8")
    assert "CRISPR editing of BRCA1" in text


def test_prepare_plain_pdf_is_file_passthrough(tmp_path: Path):
    src = tmp_path / "vault" / "paper.pdf"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"%PDF-1.4 fake")
    prep = ingest_prep.prepare(tmp_path, "vault/paper.pdf")
    assert prep.ce_args == ["--file", "vault/paper.pdf"]
    assert prep.staged is False


def test_prepare_directory_converts_html_copies_pdf(tmp_path: Path):
    d = tmp_path / "cache" / "batch"
    d.mkdir(parents=True)
    (d / "a.html").write_text(_ixbrl_like_html(), encoding="utf-8")
    (d / "b.pdf").write_bytes(b"%PDF-1.4 fake")
    prep = ingest_prep.prepare(tmp_path, "cache/batch")
    assert prep.error is None
    assert prep.staged is True
    assert prep.ce_args[0].startswith(".orchestrator/cache/ingest-stage/")
    stage = tmp_path / prep.ce_args[0]
    names = {p.name for p in stage.iterdir()}
    assert any(n.endswith(".txt") for n in names)
    assert any(n.endswith(".pdf") for n in names)


def test_prepare_rejects_escape(tmp_path: Path):
    prep = ingest_prep.prepare(tmp_path, "../../etc/passwd")
    assert prep.error
    assert "escape" in prep.error.lower() or "invalid" in prep.error.lower()


def test_prepare_rejects_workspace_root(tmp_path: Path):
    prep = ingest_prep.prepare(tmp_path, ".")
    assert prep.error
    assert "root" in prep.error.lower()


def test_prepare_blocks_symlink_escape(tmp_path: Path):
    outside = tmp_path.parent / "ingest-prep-secret"
    outside.mkdir(exist_ok=True)
    (outside / "s.html").write_text("<p>nope</p>", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(outside)
    prep = ingest_prep.prepare(tmp_path, "link/s.html")
    assert prep.error


def test_ce_ingest_passes_directory_or_file_to_bridge(tmp_path: Path, monkeypatch):
    src = tmp_path / "notes.html"
    src.write_text("<html><body><h1>Abstract</h1><p>Hello lab.</p></body></html>")
    seen: dict = {}

    def fake_run(script, args=None, *, cwd, timeout=120.0, require_json=True):
        seen["script"] = script
        seen["args"] = list(args or [])
        seen["cwd"] = Path(cwd)
        return {"ok": True, "results": []}

    monkeypatch.setattr(ce_tools.cebridge, "run_script", fake_run)
    out = tools.REGISTRY["ce_ingest"].handler(tmp_path, {"path": "notes.html"})
    assert seen["script"] == "local_ingest.py"
    assert seen["args"][0] == "--file"
    staged = Path(seen["cwd"]) / seen["args"][1]
    assert staged.is_file()
    assert "Hello lab" in staged.read_text(encoding="utf-8")
    assert out.get("ingest_prep", {}).get("staged") is True


def test_read_source_converts_html_and_blocks_escape(tmp_path: Path):
    src = tmp_path / "paper.html"
    src.write_text(_ixbrl_like_html(), encoding="utf-8")
    out = ingest_prep.read_source(tmp_path, {"path": "paper.html"})
    assert "error" not in out
    assert "Net income was twelve billion" in out["content"]
    assert out["conversion"] == "html-visible"
    denied = ingest_prep.read_source(tmp_path, {"path": "/etc/passwd"})
    assert "error" in denied


def test_read_source_registered_and_on_investigator_allowlist():
    assert "read_source" in tools.REGISTRY
    assert "read_source" in rail_default.ALLOWED_TOOLS
    assert "read_source" in orchestration.READ_ONLY_TOOLS
    node = orchestration.PlanNode(
        node_id="inv-0", kind="investigate", objective="x",
        tools=list(orchestration.READ_ONLY_TOOLS),
    )
    plan = orchestration.OrchestrationPlan(
        orchestration_id="r1", strategy="fanout", nodes=[node],
        objective="x",
    )
    assert orchestration.validate_plan(plan) == []
    narrowed = orchestration.narrow_tools(list(orchestration.READ_ONLY_TOOLS))
    assert "read_source" in narrowed
    assert "ce_ingest" not in narrowed


def test_prompts_cover_snippet_and_stale_tables():
    assert "extraction: snippet" in orchestration.INVESTIGATE_SYSTEM
    assert "read_source" in orchestration.INVESTIGATE_SYSTEM
    assert "stale" in orchestration.INVESTIGATE_SYSTEM.lower()
    assert "extraction: snippet" in orchestration.VERIFY_SYSTEM
    assert "wiki/tables" in orchestration.SYNTH_SYSTEM
    assert "working set" in orchestration.SYNTH_SYSTEM
    assert "primary source" in orchestration.SYNTH_SYSTEM
    assert "extraction: snippet" in orchestration.EXECUTE_SYSTEM
    assert "file or directory" in orchestration.EXECUTE_SYSTEM
