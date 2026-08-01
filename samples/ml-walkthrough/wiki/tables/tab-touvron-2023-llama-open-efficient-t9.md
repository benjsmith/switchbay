---
title: "[tab] Table p.7 — Table 9: Massive Multitask Language Understanding (MMLU). Five-shot accuracy by domain group. GPT-NeoX, GPT-3, Gopher, Chinchilla, PaLM, LLaMA. — touvron-2023-llama-open-efficient"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230740-local-touvron-2023-llama.pdf.extracted.md"]
extracted_from: touvron-2023-llama-open-efficient
table_index: 9
row_count: 11
is_snapshot: false
db_table: tab_touvron_2023_llama_open_efficient_t9
extraction_sha: 2e663675ae36ad12adb2f5a05281bac2747ecf8d23d92bedd9f937a89fee7136
extraction_method: multimodal-sonnet
source_pages: ["7"]
numeric_review_done: 2026-08-01T07:26:12Z
verdict: ok
---

Extracted from [[touvron-2023-llama-open-efficient]] (vault:20260728-230740-local-touvron-2023-llama.pdf.extracted.md), source pages [7], original: vault/touvron-2023-llama.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

> **The paper disagrees with itself here.** Chinchilla's MMLU average is
> **67.5** in this table (p.7, Table 9) and **67.6** in the `All` row of
> [[tab-touvron-2023-llama-open-efficient-t16]] (p.18, Table 16). Both
> transcriptions were verified against their page images; neither should be
> "corrected" to match the other. Cite by table.

| Model | Params | Humanities | STEM | Social Sciences | Other | Average |
|---|---|---|---|---|---|---|
| GPT-NeoX | 20B | 29.8 | 34.9 | 33.7 | 37.7 | 33.6 |
| GPT-3 | 175B | 40.8 | 36.7 | 50.4 | 48.8 | 43.9 |
| Gopher | 280B | 56.2 | 47.4 | 71.9 | 66.1 | 60.0 |
| Chinchilla | 70B | 63.6 | 54.9 | 79.3 | 73.9 | 67.5 |
| PaLM | 8B | 25.6 | 23.8 | 24.1 | 27.8 | 25.4 |
| PaLM | 62B | 59.5 | 41.9 | 62.7 | 55.8 | 53.7 |
| PaLM | 540B | 77.0 | 55.6 | 81.0 | 69.6 | 69.3 |
| LLaMA | 7B | 34.0 | 30.5 | 38.3 | 38.1 | 35.1 |
| LLaMA | 13B | 45.0 | 35.8 | 53.8 | 53.3 | 46.9 |
| LLaMA | 33B | 55.8 | 46.0 | 66.7 | 63.4 | 57.8 |
| LLaMA | 65B | 61.8 | 51.7 | 72.9 | 67.4 | 63.4 |
