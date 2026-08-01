---
title: "[tab] Table p.12 — Table 7: Average single line completion performance on LCC-balanced (exact match and BLEU), comparing models before/after long-context fine-tuning, across three context-length buckets — roziere-2023-code-llama-open"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230737-local-roziere-2023-code-llama.pdf.extracted.md"]
extracted_from: roziere-2023-code-llama-open
table_index: 7
row_count: 6
is_snapshot: false
db_table: tab_roziere_2023_code_llama_open_t7
extraction_sha: 05ed05d2d76c420b6af4a1afe6e1dec99939ccf62c5a0c0a258b09cbe1889346
extraction_method: multimodal-sonnet
source_pages: ["12"]
numeric_review_done: 2026-08-01T07:24:32Z
verdict: ok
---

Extracted from [[roziere-2023-code-llama-open]] (vault:20260728-230737-local-roziere-2023-code-llama.pdf.extracted.md), source pages [12], original: vault/roziere-2023-code-llama.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

| Model | Size | LCFT | EM (1) | BLEU (1) | EM (2) | BLEU (2) | EM (3) | BLEU (3) |
|---|---|---|---|---|---|---|---|---|
| Code Llama | 7B | ✗ | 36.86 | 60.16 | 47.82 | 69.20 | 46.29 | 67.75 |
| Code Llama | 7B | ✓ | 39.23 | 61.84 | 51.94 | 71.89 | 50.20 | 70.22 |
| Code Llama | 13B | ✗ | 37.96 | 61.33 | 50.49 | 69.99 | 49.22 | 69.87 |
| Code Llama | 13B | ✓ | 41.06 | 62.76 | 52.67 | 72.29 | 52.15 | 71.00 |
| Code Llama | 34B | ✗ | 42.52 | 63.74 | 54.13 | 72.38 | 52.34 | 71.36 |
| Code Llama | 34B | ✓ | 44.89 | 65.99 | 56.80 | 73.79 | 53.71 | 72.69 |
