---
title: "[tab] Table p.31 — Table 14: HumanEval single-line, multi-line, and random-span infilling exact-match rates in PSM/SPM format, comparing reference models to Code Llama with/without LCFT — roziere-2023-code-llama-open"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230737-local-roziere-2023-code-llama.pdf.extracted.md"]
extracted_from: roziere-2023-code-llama-open
table_index: 14
row_count: 7
is_snapshot: false
db_table: tab_roziere_2023_code_llama_open_t14
extraction_sha: 05ed05d2d76c420b6af4a1afe6e1dec99939ccf62c5a0c0a258b09cbe1889346
extraction_method: multimodal-sonnet
source_pages: ["31"]
numeric_review_done: 2026-08-01T07:24:43Z
verdict: ok
---

Extracted from [[roziere-2023-code-llama-open]] (vault:20260728-230737-local-roziere-2023-code-llama.pdf.extracted.md), source pages [31], original: vault/roziere-2023-code-llama.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

| Model | Size | LCFT | single-line / PSM | single-line / SPM | multi-line / PSM | multi-line / SPM | random span / PSM | random span / SPM |
|---|---|---|---|---|---|---|---|---|
| InCoder | 6B |  | 69.0% |  | 38.6% |  |  |  |
| OpenAI FIM90 | 7B |  |  | 75.1% |  | 44.1% |  | 55.1% |
| code-davinci-002 | 175B |  |  | 91.6% |  | 69.9% |  | 74.2% |
| Code Llama | 7B | ✗ | 77.0% | 83.3% | 49.7% | 51.2% | 60.7% | 39.6% |
| Code Llama | 7B | ✓ | 74.1% | 83.3% | 48.2% | 50.8% | 59.7% | 39.0% |
| Code Llama | 13B | ✗ | 80.7% | 85.9% | 53.7% | 56.7% | 64.3% | 42.7% |
| Code Llama | 13B | ✓ | 75.9% | 85.6% | 51.0% | 56.1% | 63.6% | 41.9% |
