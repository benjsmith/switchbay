---
title: "[tab] Table p.28 — Table 10: Full pass@1/10/100 scores on HumanEval and MBPP for Llama 2, Code Llama, and Code Llama - Python across FIM and LCFT ablation configurations — roziere-2023-code-llama-open"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230737-local-roziere-2023-code-llama.pdf.extracted.md"]
extracted_from: roziere-2023-code-llama-open
table_index: 10
row_count: 20
is_snapshot: false
db_table: tab_roziere_2023_code_llama_open_t10
extraction_sha: 05ed05d2d76c420b6af4a1afe6e1dec99939ccf62c5a0c0a258b09cbe1889346
extraction_method: multimodal-sonnet
source_pages: ["28"]
numeric_review_done: 2026-08-01T07:24:37Z
verdict: ok
---

Extracted from [[roziere-2023-code-llama-open]] (vault:20260728-230737-local-roziere-2023-code-llama.pdf.extracted.md), source pages [28], original: vault/roziere-2023-code-llama.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

> **The paper disagrees with itself here.** This table (p.28, Table 10) and
> [[tab-roziere-2023-code-llama-open-t2]] (p.6, Table 2) report different MBPP
> pass@100 values for the same models: Llama 2 70B is **85.5%** here and
> **83.1%** there; Llama 2 34B is **83.1%** here and **77.6%** there. Both
> transcriptions were verified against their page images. Cite by table, not
> just by paper.

<!-- cross-table-conflicts -->
> **This source reports conflicting values for these cells in more than one of its own tables.** Both transcriptions were verified against the source page; the disagreement is the paper's, not a transcription error. Check the source before citing either number.
>
> - `code llama` / `humaneval / pass@1`: **32.3%** here, **33.5%** in [[tab-roziere-2023-code-llama-open-t2]]
> - `code llama` / `humaneval / pass@10`: **63.9%** here, **59.6%** in [[tab-roziere-2023-code-llama-open-t2]]
> - `code llama` / `humaneval / pass@100`: **88.0%** here, **85.9%** in [[tab-roziere-2023-code-llama-open-t2]]
> - `code llama` / `mbpp / pass@1`: **46.2%** here, **41.4%** in [[tab-roziere-2023-code-llama-open-t2]]
> - `code llama` / `mbpp / pass@10`: **68.8%** here, **66.7%** in [[tab-roziere-2023-code-llama-open-t2]]
> - `code llama` / `mbpp / pass@100`: **85.5%** here, **82.5%** in [[tab-roziere-2023-code-llama-open-t2]]
> - `code llama - python` / `humaneval / pass@1`: **40.2%** here, **38.4%** in [[tab-roziere-2023-code-llama-open-t2]]
> - `code llama - python` / `humaneval / pass@10`: **70.0%** here, **70.3%** in [[tab-roziere-2023-code-llama-open-t2]]
> - `code llama - python` / `humaneval / pass@100`: **90.2%** here, **90.6%** in [[tab-roziere-2023-code-llama-open-t2]]
> - `code llama - python` / `mbpp / pass@1`: **50.2%** here, **47.6%** in [[tab-roziere-2023-code-llama-open-t2]]
> - `code llama - python` / `mbpp / pass@10`: **71.2%** here, **70.3%** in [[tab-roziere-2023-code-llama-open-t2]]
> - `code llama - python` / `mbpp / pass@100`: **85.6%** here, **84.8%** in [[tab-roziere-2023-code-llama-open-t2]]
<!-- /cross-table-conflicts -->

| Model | Size | FIM | LCFT | HumanEval / pass@1 | HumanEval / pass@10 | HumanEval / pass@100 | MBPP / pass@1 | MBPP / pass@10 | MBPP / pass@100 |
|---|---|---|---|---|---|---|---|---|---|
| Llama 2 | 7B | ✗ | ✗ | 12.2% | 25.2% | 44.4% | 20.8% | 41.8% | 65.5% |
| Llama 2 | 13B | ✗ | ✗ | 20.1% | 34.8% | 61.2% | 27.6% | 48.1% | 69.5% |
| Llama 2 | 34B | ✗ | ✗ | 22.6% | 47.0% | 79.5% | 33.8% | 56.9% | 83.1% |
| Llama 2 | 70B | ✗ | ✗ | 30.5% | 59.4% | 87.0% | 45.4% | 66.2% | 85.5% |
| Code Llama | 7B | ✗ | ✗ | 32.3% | 63.9% | 88.0% | 46.2% | 68.8% | 85.5% |
| Code Llama | 7B | ✓ | ✗ | 34.1% | 62.6% | 87.5% | 44.6% | 68.2% | 84.4% |
| Code Llama | 7B | ✗ | ✓ | 34.1% | 62.5% | 87.6% | 42.6% | 65.4% | 76.8% |
| Code Llama | 7B | ✓ | ✓ | 33.5% | 59.6% | 85.9% | 41.4% | 66.7% | 82.5% |
| Code Llama | 13B | ✗ | ✗ | 36.6% | 72.9% | 92.3% | 48.3% | 72.0% | 84.7% |
| Code Llama | 13B | ✓ | ✗ | 36.6% | 71.9% | 91.4% | 48.2% | 72.8% | 86.9% |
| Code Llama | 13B | ✗ | ✓ | 37.8% | 70.6% | 92.4% | 48.0% | 71.2% | 84.1% |
| Code Llama | 13B | ✓ | ✓ | 36.0% | 69.4% | 89.8% | 47.0% | 71.7% | 87.1% |
| Code Llama | 34B | ✗ | ✗ | 48.2% | 77.7% | 93.3% | 56.4% | 76.8% | 87.7% |
| Code Llama | 34B | ✗ | ✓ | 48.8% | 76.8% | 93.0% | 55.0% | 76.2% | 86.6% |
| Code Llama - Python | 7B | ✗ | ✗ | 40.2% | 70.0% | 90.2% | 50.2% | 71.2% | 85.6% |
| Code Llama - Python | 7B | ✗ | ✓ | 38.4% | 70.3% | 90.6% | 47.6% | 70.3% | 84.8% |
| Code Llama - Python | 13B | ✗ | ✗ | 45.7% | 80.0% | 92.7% | 52.4% | 74.5% | 86.8% |
| Code Llama - Python | 13B | ✗ | ✓ | 43.3% | 77.4% | 94.1% | 49.0% | 74.0% | 87.6% |
| Code Llama - Python | 34B | ✗ | ✗ | 56.1% | 82.9% | 96.4% | 57.6% | 77.3% | 87.6% |
| Code Llama - Python | 34B | ✗ | ✓ | 53.7% | 82.8% | 94.7% | 56.2% | 76.4% | 88.2% |
