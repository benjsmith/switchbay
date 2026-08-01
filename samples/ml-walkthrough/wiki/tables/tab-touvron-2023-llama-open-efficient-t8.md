---
title: "[tab] Table p.6 — Table 8: Model performance for code generation. pass@1 and pass@100 (HumanEval) / pass@1 and pass@80 (MBPP). LaMDA, PaLM, PaLM-cont, LLaMA. Values marked with * are read from figures in Chowdhery et al. (2022). — touvron-2023-llama-open-efficient"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230740-local-touvron-2023-llama.pdf.extracted.md"]
extracted_from: touvron-2023-llama-open-efficient
table_index: 8
row_count: 9
is_snapshot: false
db_table: tab_touvron_2023_llama_open_efficient_t8
extraction_sha: 2e663675ae36ad12adb2f5a05281bac2747ecf8d23d92bedd9f937a89fee7136
extraction_method: multimodal-sonnet
source_pages: ["6"]
numeric_review_done: 2026-08-01T07:26:10Z
verdict: ok
---

Extracted from [[touvron-2023-llama-open-efficient]] (vault:20260728-230740-local-touvron-2023-llama.pdf.extracted.md), source pages [6], original: vault/touvron-2023-llama.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

| Model | Params | HumanEval @1 | HumanEval @100 | MBPP @1 | MBPP @80 |
|---|---|---|---|---|---|
| LaMDA | 137B | 14.0 | 47.3 | 14.8 | 62.4 |
| PaLM | 8B | 3.6* | 18.7* | 5.0* | 35.7* |
| PaLM | 62B | 15.9 | 46.3* | 21.4 | 63.2* |
| PaLM-cont | 62B | 23.7 | - | 31.2 | - |
| PaLM | 540B | 26.2 | 76.2 | 36.8 | 75.0 |
| LLaMA | 7B | 10.5 | 36.5 | 17.7 | 56.2 |
| LLaMA | 13B | 15.8 | 52.5 | 22.0 | 64.0 |
| LLaMA | 33B | 21.7 | 70.7 | 30.2 | 73.4 |
| LLaMA | 65B | 23.7 | 79.3 | 37.7 | 76.8 |
