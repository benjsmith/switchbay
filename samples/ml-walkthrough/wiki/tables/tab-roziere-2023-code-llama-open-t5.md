---
title: "[tab] Table p.11 — Table 5: Comparison of Code Llama models with and without FIM (infilling) training, on HumanEval/MBPP pass@1/10/100 and autoregressive test loss, prior to long-context fine-tuning (LCFT) — roziere-2023-code-llama-open"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230737-local-roziere-2023-code-llama.pdf.extracted.md"]
extracted_from: roziere-2023-code-llama-open
table_index: 5
row_count: 6
is_snapshot: false
db_table: tab_roziere_2023_code_llama_open_t5
extraction_sha: 05ed05d2d76c420b6af4a1afe6e1dec99939ccf62c5a0c0a258b09cbe1889346
extraction_method: multimodal-sonnet
source_pages: ["11"]
numeric_review_done: 2026-08-01T07:24:28Z
verdict: ok
---

Extracted from [[roziere-2023-code-llama-open]] (vault:20260728-230737-local-roziere-2023-code-llama.pdf.extracted.md), source pages [11], original: vault/roziere-2023-code-llama.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

| Model | FIM | Size | HumanEval / pass@1 | HumanEval / pass@10 | HumanEval / pass@100 | MBPP / pass@1 | MBPP / pass@10 | MBPP / pass@100 | Test loss |
|---|---|---|---|---|---|---|---|---|---|
| Code Llama (w/o LCFT) | ✗ | 7B | 33.2% | 43.3% | 49.9% | 44.8% | 52.5% | 57.1% | 0.408 |
| Code Llama (w/o LCFT) | ✗ | 13B | 36.8% | 49.2% | 57.9% | 48.2% | 57.4% | 61.6% | 0.372 |
| Code Llama (w/o LCFT) | ✓ | 7B | 33.6% | 44.0% | 48.8% | 44.2% | 51.4% | 55.5% | 0.407 |
| Code Llama (w/o LCFT) | ✓ | 13B | 36.2% | 48.3% | 54.6% | 48.0% | 56.8% | 60.8% | 0.373 |
| Absolute gap | ✗ - ✓ | 7B | -0.4% | -0.7% | 1.1% | 0.6% | 1.1% | 1.6% | 0.001 |
| Absolute gap | ✗ - ✓ | 13B | 0.7% | 0.9% | 3.3% | 0.2% | 0.6% | 0.8% | -0.001 |
