"""Claim lint: a paragraph-level citation, case sections, schema keys."""

from __future__ import annotations

from pathlib import Path

from switchbay import case_page, claim_lint


def _page(tmp_path: Path, rel: str, text: str) -> Path:
    path = tmp_path / "wiki" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_case_template_has_the_required_sections_and_schema_keys():
    text = case_page.render("Checkout stall", summary="A blinded failure.")
    assert "title: \"Checkout stall\"" in text or "title: Checkout stall" in text
    assert "type: project" in text
    assert "role: case" in text
    assert "confidence:" in text
    assert "uncertainty:" in text
    assert case_page.missing_sections(text) == []
    assert "A blinded failure." in text
    assert case_page.missing_sections("## Objectives\n") == [
        "Constraints",
        "Evaluation methods",
        "Success criteria",
        "System context",
    ]


def test_cited_paragraph_passes_and_uncited_paragraph_fails(tmp_path: Path):
    _page(tmp_path, "facts/latency.md", """---
type: fact
title: Latency
confidence: 0.4
uncertainty: inferred
---

The latency rose after the window (vault:metrics.parquet).

[[latency-plot]] is the figure for that series.

The error count did not move.
""")
    violations = claim_lint.lint_path(tmp_path)
    assert [v.code for v in violations] == ["missing-citation"]
    assert "error count" in violations[0].message
    assert violations[0].line > 1


def test_table_cite_and_list_items_are_separate_paragraphs(tmp_path: Path):
    _page(tmp_path, "evidence/cpu.md", """---
type: evidence
---

- CPU on the edge service moved (table:metrics#id=cpu).
- Disk stayed flat.

```
this fence has no citation and is not a claim
```
""")
    violations = claim_lint.lint_path(tmp_path)
    assert len(violations) == 1
    assert violations[0].code == "missing-citation"
    assert "Disk stayed flat" in violations[0].message


def test_notes_are_exempt_and_figures_need_sources(tmp_path: Path):
    _page(tmp_path, "notes/scratch.md", """---
type: note
---

This note asserts something with no source.
""")
    _page(tmp_path, "figures/cpu.md", """---
type: figure
title: CPU
---

CPU by service.
""")
    _page(tmp_path, "figures/ok.md", """---
type: figure
sources: [metrics]
---

CPU by service (vault:metrics.parquet).
""")
    violations = claim_lint.lint_path(tmp_path)
    assert [v.code for v in violations] == ["figure-without-sources"]
    assert violations[0].path.endswith("figures/cpu.md")


def test_case_page_sections_and_schema_keys(tmp_path: Path):
    _page(tmp_path, "projects/case.md", """---
type: project
role: case
confidence: 1.4
uncertainty: Attested
---

## Objectives

Find the fault.
""")
    violations = claim_lint.lint_path(tmp_path)
    codes = {v.code for v in violations}
    assert "bad-schema-key" in codes
    assert any("confidence" in v.message for v in violations)
    assert any("uncertainty" in v.message for v in violations)
    missing = [v.message for v in violations if v.code == "missing-section"]
    assert any("Constraints" in m for m in missing)
    assert any("Success criteria" in m for m in missing)
    assert not any("Objectives" in m for m in missing)


def test_hypothesis_role_and_configured_status(tmp_path: Path):
    _page(tmp_path, "analyses/alt.md", """---
type: analysis
role: hypothesis
status: maybe
---

The neighbour saturated first (vault:metrics.parquet).
""")
    plain = claim_lint.lint_path(tmp_path)
    assert plain == []
    config = tmp_path / ".curator" / "meta-ontology.yaml"
    config.parent.mkdir()
    config.write_text("""
version: 1
schema_keys:
  - key: status
    values: [open, supported, refuted]
    description: Hypothesis state.
""", encoding="utf-8")
    configured = claim_lint.lint_path(tmp_path)
    assert [v.code for v in configured] == ["bad-schema-key"]
    assert "status" in configured[0].message


def test_cli_exit_status(tmp_path: Path):
    _page(tmp_path, "facts/bare.md", """---
type: fact
---

Nothing is cited here.
""")
    assert claim_lint.main([str(tmp_path)]) == 1
    clean = tmp_path / "empty-case"
    text = case_page.render("Empty")
    # The template's sections are present, but it is a case page with no
    # claims, so the lint is clean.
    page = clean / "wiki" / "projects" / "case.md"
    page.parent.mkdir(parents=True)
    page.write_text(text, encoding="utf-8")
    assert claim_lint.main([str(clean)]) == 0
