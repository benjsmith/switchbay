---
title: "[tab] Table p.6 — Table 2: Code Llama pass@1/10/100 scores on HumanEval and MBPP, compared against other published models — roziere-2023-code-llama-open"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230737-local-roziere-2023-code-llama.pdf.extracted.md"]
extracted_from: roziere-2023-code-llama-open
table_index: 2
row_count: 26
is_snapshot: false
db_table: tab_roziere_2023_code_llama_open_t2
extraction_sha: 05ed05d2d76c420b6af4a1afe6e1dec99939ccf62c5a0c0a258b09cbe1889346
extraction_method: multimodal-sonnet
source_pages: ["6"]
numeric_review_done: 2026-08-01T07:24:23Z
verdict: ok
---

Extracted from [[roziere-2023-code-llama-open]] (vault:20260728-230737-local-roziere-2023-code-llama.pdf.extracted.md), source pages [6], original: vault/roziere-2023-code-llama.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

> **The paper disagrees with itself here.** This table (p.6, Table 2) and
> [[tab-roziere-2023-code-llama-open-t10]] (p.28, Table 10) report different
> MBPP pass@100 values for the same models: Llama 2 70B is **83.1%** here and
> **85.5%** there; Llama 2 34B is **77.6%** here and **83.1%** there. Both
> transcriptions were verified against their page images. Cite by table, not
> just by paper.

<!-- cross-table-conflicts -->
> **This source reports conflicting values for these cells in more than one of its own tables.** Both transcriptions were verified against the source page; the disagreement is the paper's, not a transcription error. Check the source before citing either number.
>
> - `code llama` / `humaneval / pass@1`: **33.5%** here, **32.3%** in [[tab-roziere-2023-code-llama-open-t10]]
> - `code llama` / `humaneval / pass@10`: **59.6%** here, **63.9%** in [[tab-roziere-2023-code-llama-open-t10]]
> - `code llama` / `humaneval / pass@100`: **85.9%** here, **88.0%** in [[tab-roziere-2023-code-llama-open-t10]]
> - `code llama` / `mbpp / pass@1`: **41.4%** here, **46.2%** in [[tab-roziere-2023-code-llama-open-t10]]
> - `code llama` / `mbpp / pass@10`: **66.7%** here, **68.8%** in [[tab-roziere-2023-code-llama-open-t10]]
> - `code llama` / `mbpp / pass@100`: **82.5%** here, **85.5%** in [[tab-roziere-2023-code-llama-open-t10]]
> - `code llama - python` / `humaneval / pass@1`: **38.4%** here, **40.2%** in [[tab-roziere-2023-code-llama-open-t10]]
> - `code llama - python` / `humaneval / pass@10`: **70.3%** here, **70.0%** in [[tab-roziere-2023-code-llama-open-t10]]
> - `code llama - python` / `humaneval / pass@100`: **90.6%** here, **90.2%** in [[tab-roziere-2023-code-llama-open-t10]]
> - `code llama - python` / `mbpp / pass@1`: **47.6%** here, **50.2%** in [[tab-roziere-2023-code-llama-open-t10]]
> - `code llama - python` / `mbpp / pass@10`: **70.3%** here, **71.2%** in [[tab-roziere-2023-code-llama-open-t10]]
> - `code llama - python` / `mbpp / pass@100`: **84.8%** here, **85.6%** in [[tab-roziere-2023-code-llama-open-t10]]
<!-- /cross-table-conflicts -->

| Model | Size | HumanEval / pass@1 | HumanEval / pass@10 | HumanEval / pass@100 | MBPP / pass@1 | MBPP / pass@10 | MBPP / pass@100 |
|---|---|---|---|---|---|---|---|
| code-cushman-001 | 12B | 33.5% | - | - | 45.9% | - | - |
| GPT-3.5 (ChatGPT) | - | 48.1% | - | - | 52.2% | - | - |
| GPT-4 | - | 67.0% | - | - | - | - | - |
| PaLM | 540B | 26.2% | - | - | 36.8% | - | - |
| PaLM-Coder | 540B | 35.9% | - | 88.4% | 47.0% | - | - |
| PaLM 2-S | - | 37.6% | - | 88.4% | 50.0% | - | - |
| StarCoder Base | 15.5B | 30.4% | - | - | 49.0% | - | - |
| StarCoder Python | 15.5B | 33.6% | - | - | 52.7% | - | - |
| StarCoder Prompted | 15.5B | 40.8% | - | - | 49.5% | - | - |
| Llama 2 | 7B | 12.2% | 25.2% | 44.4% | 20.8% | 41.8% | 65.5% |
| Llama 2 | 13B | 20.1% | 34.8% | 61.2% | 27.6% | 48.1% | 69.5% |
| Llama 2 | 34B | 22.6% | 47.0% | 79.5% | 33.8% | 56.9% | 77.6% |
| Llama 2 | 70B | 30.5% | 59.4% | 87.0% | 45.4% | 66.2% | 83.1% |
| Code Llama | 7B | 33.5% | 59.6% | 85.9% | 41.4% | 66.7% | 82.5% |
| Code Llama | 13B | 36.0% | 69.4% | 89.8% | 47.0% | 71.7% | 87.1% |
| Code Llama | 34B | 48.8% | 76.8% | 93.0% | 55.0% | 76.2% | 86.6% |
| Code Llama | 70B | 53.0% | 84.6% | 96.2% | 62.4% | 81.1% | 91.9% |
| Code Llama - Instruct | 7B | 34.8% | 64.3% | 88.1% | 44.4% | 65.4% | 76.8% |
| Code Llama - Instruct | 13B | 42.7% | 71.6% | 91.6% | 49.4% | 71.2% | 84.1% |
| Code Llama - Instruct | 34B | 41.5% | 77.2% | 93.5% | 57.0% | 74.6% | 85.4% |
| Code Llama - Instruct | 70B | 67.8% | 90.3% | 97.3% | 62.2% | 79.6% | 89.2% |
| Unnatural Code Llama | 34B | 62.2% | 85.2% | 95.4% | 61.2% | 76.6% | 86.7% |
| Code Llama - Python | 7B | 38.4% | 70.3% | 90.6% | 47.6% | 70.3% | 84.8% |
| Code Llama - Python | 13B | 43.3% | 77.4% | 94.1% | 49.0% | 74.0% | 87.6% |
| Code Llama - Python | 34B | 53.7% | 82.8% | 94.7% | 56.2% | 76.4% | 88.2% |
| Code Llama - Python | 70B | 57.3% | 89.3% | 98.4% | 65.6% | 81.5% | 91.9% |
