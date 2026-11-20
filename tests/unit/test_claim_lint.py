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
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "metrics.parquet").write_bytes(b"not-read")
    _page(tmp_path, "figures/latency-plot.md", """---
type: figure
title: Latency plot
sources: [metrics]
---

The series.
""")
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
    _page(tmp_path, "tables/metrics.md", """---
type: table
title: Metrics
---

| id | load |
| --- | --- |
| cpu | 1 |
""")
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
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "metrics.parquet").write_bytes(b"not-read")
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


def _typed_ontology(tmp_path: Path, *, endpoints: bool = True) -> None:
    ends = (
        "    source: [evidence]\n    target: [hypothesis]\n"
        if endpoints else ""
    )
    path = tmp_path / ".curator" / "meta-ontology.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "version: 1\n"
        "nodes:\n"
        "  - type: evidence\n"
        "    folder: evidence\n"
        "    description: An observation.\n"
        "  - type: hypothesis\n"
        "    folder: hypotheses\n"
        "    description: State the claim.\n"
        "edges:\n"
        "  - type: supports\n"
        f"{ends}"
        "    description: When the result matches a prediction.\n"
        "  - type: cites\n"
        "    description: Same paragraph as the claim.\n",
        encoding="utf-8",
    )


def _vault(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir(exist_ok=True)
    (vault / "metrics.md").write_text("n", encoding="utf-8")


def test_typed_edge_passes_when_the_ends_match(tmp_path: Path):
    _vault(tmp_path)
    _typed_ontology(tmp_path)
    _page(tmp_path, "evidence/cpu.md", """---
type: evidence
title: CPU
supports:
  - hypotheses/queue
---

The series moved (vault:metrics.md).
""")
    _page(tmp_path, "hypotheses/queue.md", """---
type: hypothesis
title: Queue
---

The queue grows (vault:metrics.md).
""")
    assert claim_lint.lint_path(tmp_path) == []


def test_typed_edge_checks_the_target_and_the_endpoint_types(tmp_path: Path):
    _vault(tmp_path)
    _typed_ontology(tmp_path)
    _page(tmp_path, "facts/note.md", """---
type: fact
title: Note
supports:
  - hypotheses/missing
---

A claim (vault:metrics.md).
""")
    _page(tmp_path, "evidence/cpu.md", """---
type: evidence
title: CPU
supports: [facts/note]
---

The series moved (vault:metrics.md).
""")
    _page(tmp_path, "hypotheses/queue.md", """---
type: hypothesis
title: Queue
---

The queue grows (vault:metrics.md).
""")
    violations = claim_lint.lint_path(tmp_path)
    by_code = {}
    for item in violations:
        by_code.setdefault(item.code, []).append(item.message)
    assert any("does not resolve" in msg for msg in by_code["missing-edge-target"])
    assert any("source type fact" in msg for msg in by_code["bad-edge-endpoint"])
    assert any("target type fact" in msg for msg in by_code["bad-edge-endpoint"])


def test_edge_lint_is_quiet_without_declared_endpoints(tmp_path: Path):
    _vault(tmp_path)
    _page(tmp_path, "evidence/cpu.md", """---
type: evidence
supports:
  - hypotheses/missing
---

The series moved (vault:metrics.md).
""")
    assert claim_lint.lint_path(tmp_path) == []
    _typed_ontology(tmp_path, endpoints=False)
    assert claim_lint.lint_path(tmp_path) == []


def test_cli_exit_status(tmp_path: Path):
    _page(tmp_path, "facts/bare.md", """---
type: fact
---

Nothing is cited here.
""")
    assert claim_lint.main([str(tmp_path)]) == 1
    clean = tmp_path / "empty-case"
    text = case_page.render("Empty")
    # Drop the blank confidence and uncertainty lines. A blank key is a
    # violation; this page is the clean case with the five sections.
    text = "\n".join(
        line for line in text.splitlines()
        if line not in {"confidence:", "uncertainty:"}
    ) + "\n"
    page = clean / "wiki" / "projects" / "case.md"
    page.parent.mkdir(parents=True)
    page.write_text(text, encoding="utf-8")
    assert claim_lint.main([str(clean)]) == 0


def test_blank_frontmatter_is_reported_and_not_an_empty_list():
    fm, _body, _line = claim_lint._read_frontmatter(
        "---\n"
        "confidence:\n"
        "uncertainty:\n"
        "sources:\n"
        "  - metrics\n"
        "role: case\n"
        "---\n\n"
        "Body\n"
    )
    assert fm["confidence"] == ""
    assert fm["uncertainty"] == ""
    assert fm["sources"] == ["metrics"]
    assert fm["role"] == "case"
    assert not isinstance(fm["confidence"], list)

    text = case_page.render("Empty")
    fm, _body, _line = claim_lint._read_frontmatter(text)
    assert fm["confidence"] == ""
    assert fm["uncertainty"] == ""


def test_blank_schema_key_fails_and_a_value_passes(tmp_path: Path):
    _page(tmp_path, "facts/open.md", """---
type: fact
confidence:
uncertainty:
---

The window moved (vault:metrics.parquet).
""")
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "metrics.parquet").write_bytes(b"not-read")
    blank = claim_lint.lint_path(tmp_path)
    messages = [v.message for v in blank if v.code == "bad-schema-key"]
    assert any(m == "confidence is blank." for m in messages)
    assert any(m == "uncertainty is blank." for m in messages)
    assert not any(v.code == "unresolved-citation" for v in blank)

    _page(tmp_path, "facts/open.md", """---
type: fact
confidence: 0.4
uncertainty: inferred
title:
---

The window moved (vault:metrics.parquet).
""")
    filled = claim_lint.lint_path(tmp_path)
    assert filled == []


def test_present_citation_targets_pass(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    fixture = Path(__file__).resolve().parent / "fixtures" / "columns.parquet"
    (vault / "metrics.parquet").write_bytes(fixture.read_bytes())
    (vault / "scores.csv").write_text(
        "series,relative\ncheckout,37.14\n", encoding="utf-8",
    )
    _page(tmp_path, "tables/metrics.md", """---
type: table
title: Metrics
---

| id | load |
| --- | --- |
| cpu | 9 |
""")
    _page(tmp_path, "tables/scores.md", """---
type: table
title: Scores
---

## Onset

| series | relative |
| --- | --- |
| checkoutservice_cpu | 37.14 |
""")
    _page(tmp_path, "figures/latency-p90.md", """---
type: figure
title: latency-90
sources: [metrics.parquet]
---

![latency-90](latency-p90.png)
""")
    (tmp_path / "wiki" / "figures" / "latency-p90.png").write_bytes(b"png")
    _page(tmp_path, "hypotheses/ranking.md", """---
type: hypothesis
title: Ranked causes
---

## Onset

The ranking (table:scores).
""")
    _page(tmp_path, "facts/cited.md", """---
type: fact
confidence: 0.8
uncertainty: attested
---

CPU stepped (vault:metrics.parquet) and the row is there (table:metrics#id=cpu).

The relative column is 37.14 (table:scores#column=relative&row=checkoutservice_cpu).

The plot is (figure:latency-p90) and [[latency-p90]].

The heading is [[ranking#Onset]].

The csv row is (vault:scores.csv#column=series&row=checkout).

The parquet column is (vault:metrics.parquet#column=cpu).

```
a fenced (vault:missing.parquet) citation is not checked
```
""")
    assert claim_lint.lint_path(tmp_path) == []


def test_missing_citation_targets_fail(tmp_path: Path):
    _page(tmp_path, "tables/scores.md", """---
type: table
title: Scores
---

## Onset

| series | relative |
| --- | --- |
| checkoutservice_cpu | 37.14 |
""")
    _page(tmp_path, "facts/gaps.md", """---
type: fact
---

The file is gone (vault:missing.parquet).

The page is gone [[no-such-page]].

The table is gone (table:no-such-table).

The figure is gone (figure:no-such-plot).

The row is gone (table:scores#id=absent).

The column is gone (table:scores#column=absent).

The anchor is gone [[scores#missing-heading]].

The same sentence names this claim (vault:also-missing.parquet).
""")
    violations = claim_lint.lint_path(tmp_path)
    assert violations
    assert all(v.code == "unresolved-citation" for v in violations)

    def message_for(token: str) -> str:
        hits = [v.message for v in violations if token in v.message]
        assert len(hits) == 1, hits
        return hits[0]

    file_msg = message_for("(vault:missing.parquet)")
    assert "missing file missing.parquet" in file_msg
    assert "The file is gone" in file_msg

    page_msg = message_for("[[no-such-page]]")
    assert "missing page no-such-page" in page_msg
    assert "The page is gone" in page_msg

    table_msg = message_for("(table:no-such-table)")
    assert "missing table no-such-table" in table_msg
    assert "The table is gone" in table_msg

    figure_msg = message_for("(figure:no-such-plot)")
    assert "missing figure no-such-plot" in figure_msg
    assert "The figure is gone" in figure_msg

    row_msg = message_for("(table:scores#id=absent)")
    assert "missing row absent" in row_msg
    assert "The row is gone" in row_msg

    column_msg = message_for("(table:scores#column=absent)")
    assert "missing column absent" in column_msg
    assert "The column is gone" in column_msg

    anchor_msg = message_for("[[scores#missing-heading]]")
    assert "missing anchor missing-heading" in anchor_msg
    assert "The anchor is gone" in anchor_msg

    assert "also-missing.parquet" in message_for("(vault:also-missing.parquet)")
    assert "names this claim" in message_for("(vault:also-missing.parquet)")


def test_parquet_column_is_checked(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    fixture = Path(__file__).resolve().parent / "fixtures" / "columns.parquet"
    (vault / "metrics.parquet").write_bytes(fixture.read_bytes())
    _page(tmp_path, "facts/cpu.md", """---
type: fact
---

CPU is a column (vault:metrics.parquet#column=cpu).

Socket is not (vault:metrics.parquet#column=socket).
""")
    violations = claim_lint.lint_path(tmp_path)
    assert len(violations) == 1
    assert violations[0].code == "unresolved-citation"
    assert "missing column socket" in violations[0].message
    assert "(vault:metrics.parquet#column=socket)" in violations[0].message
    assert "Socket is not" in violations[0].message
