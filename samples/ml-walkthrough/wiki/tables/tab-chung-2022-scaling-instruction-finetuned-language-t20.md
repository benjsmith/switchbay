---
title: "[tab] Table p.44 — Table 20: TyDiQA per-language performance (exact match) — chung-2022-scaling-instruction-finetuned-language"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230728-local-chung-2022-flan.pdf.extracted.md"]
extracted_from: chung-2022-scaling-instruction-finetuned-language
table_index: 20
row_count: 24
is_snapshot: false
db_table: tab_chung_2022_scaling_instruction_finetuned_language_t20
extraction_sha: 771f758c1b711c2a63ca2439e80ab90751351d721632897a058c0205ba9e2a22
extraction_method: multimodal-sonnet
source_pages: ["44"]
numeric_review_done: 2026-07-30T22:31:28Z
verdict: ok
---

Extracted from [[chung-2022-scaling-instruction-finetuned-language]] (vault:20260728-230728-local-chung-2022-flan.pdf.extracted.md), source pages [44], original: vault/chung-2022-flan.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

| Params | Model | ar | bn | fi | id | ko | ru | sw | te | Avg. |
|---|---|---|---|---|---|---|---|---|---|---|
| - | davinci | 18.1 | 6.2 | 34.1 | 37.0 | 34.8 | 21.9 | 15.6 | 5.2 | 21.6 |
| - | text-davinci-002 | 34.3 | 38.9 | 48.6 | 49.7 | 56.2 | 30.1 | 52.9 | 18.4 | 41.1 |
| - | text-davinci-003 | 39.2 | 38.1 | 52.0 | 54.5 | 51.4 | 28.9 | 55.9 | 29.3 | 43.7 |
| - | code-davinci-002 | 42.5 | 47.8 | 50.5 | 58.1 | 57.2 | 38.7 | 62.1 | 27.7 | 48.1 |
| 80M | T5-Small | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
|  | Flan-T5-Small | 0.2 | 0.0 | 0.9 | 3.0 | 0.0 | 0.6 | 3.8 | 0.1 | 1.1 |
| 250M | T5-Base | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
|  | Flan-T5-Base | 0.0 | 0.0 | 11.0 | 9.7 | 0.0 | 3.9 | 7.8 | 0.0 | 4.1 |
| 780M | T5-Large | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
|  | Flan-T5-Large | 0.0 | 0.0 | 37.5 | 27.3 | 0.4 | 14.3 | 18.8 | 0.1 | 12.3 |
| 3B | T5-XL | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.1 | 0.0 |
|  | Flan-T5-XL | 0.1 | 0.0 | 46.8 | 50.3 | 0.4 | 17.5 | 14.8 | 2.7 | 16.6 |
| 11B | T5-XXL | 0.0 | 0.0 | 0.0 | 0.2 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
|  | Flan-T5-XXL | 0.4 | 0.0 | 43.7 | 56.8 | 0.0 | 17.6 | 32.7 | 1.0 | 19.0 |
| 8B | PaLM | 21.6 | 9.7 | 33.0 | 29.6 | 36.2 | 23.3 | 35.5 | 11.2 | 25.0 |
|  | Flan-PaLM | 48.6 | 35.4 | 61.4 | 57.3 | 51.1 | 45.8 | 51.1 | 29.3 | 47.5 |
| 62B | PaLM | 31.2 | 42.5 | 41.7 | 41.6 | 49.3 | 29.2 | 58.1 | 30.6 | 40.5 |
|  | Flan-PaLM | 58.0 | 53.1 | 65.5 | 65.3 | 61.2 | 47.0 | 69.7 | 49.6 | 58.7 |
| 62B | cont-PaLM | 39.4 | 48.7 | 44.0 | 49.2 | 52.5 | 35.6 | 60.9 | 35.3 | 45.7 |
|  | Flan-cont-PaLM | 59.4 | 67.3 | 64.5 | 67.6 | 63.4 | 51.1 | 73.7 | 54.3 | 62.7 |
| 540B | PaLM | 45.1 | 54.9 | 51.5 | 56.8 | 60.5 | 38.8 | 63.9 | 51.9 | 52.9 |
|  | Flan-PaLM | 63.8 | 66.4 | 68.7 | 75.4 | 69.2 | 54.3 | 78.4 | 66.2 | 67.8 |
| 540B | U-PaLM | 46.3 | 60.2 | 50.5 | 56.8 | 62.3 | 40.0 | 64.1 | 56.8 | 54.6 |
|  | Flan-U-PaLM | 65.5 | 67.3 | 69.4 | 74.9 | 68.8 | 54.6 | 76.0 | 70.0 | 68.3 |
