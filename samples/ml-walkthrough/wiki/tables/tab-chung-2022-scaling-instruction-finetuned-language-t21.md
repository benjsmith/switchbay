---
title: "[tab] Table p.45 — Table 21: MGSM per-language performance — chung-2022-scaling-instruction-finetuned-language"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230728-local-chung-2022-flan.pdf.extracted.md"]
extracted_from: chung-2022-scaling-instruction-finetuned-language
table_index: 21
row_count: 24
is_snapshot: false
db_table: tab_chung_2022_scaling_instruction_finetuned_language_t21
extraction_sha: 771f758c1b711c2a63ca2439e80ab90751351d721632897a058c0205ba9e2a22
extraction_method: multimodal-sonnet
source_pages: ["45"]
numeric_review_done: 2026-07-30T22:31:30Z
verdict: ok
---

Extracted from [[chung-2022-scaling-instruction-finetuned-language]] (vault:20260728-230728-local-chung-2022-flan.pdf.extracted.md), source pages [45], original: vault/chung-2022-flan.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

| Params | Model | bn | de | es | fr | ja | ru | sw | te | th | zh | Avg. |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| - | davinci | 2.0 | 16.0 | 10.8 | 10.8 | 0.8 | 4.4 | 1.2 | 1.2 | 3.2 | 6.8 | 5.7 |
| - | text-davinci-002 | 6.4 | 36.0 | 40.4 | 37.6 | 26.0 | 28.4 | 11.2 | 0.4 | 10.8 | 40.0 | 23.7 |
| - | text-davinci-003 | 10.8 | 54.4 | 54.8 | 53.2 | 40.8 | 38.0 | 24.4 | 4.8 | 29.2 | 49.2 | 36.0 |
| - | code-davinci-002 | 3.6 | 60.4 | 62.8 | 58.0 | 39.2 | 37.6 | 26.4 | 1.2 | 10.0 | 51.2 | 35.0 |
| 80M | T5-Small | 0.0 | 1.2 | 0.8 | 0.8 | 0.4 | 0.0 | 0.8 | 0.0 | 0.0 | 0.4 | 0.4 |
|  | Flan-T5-Small | 0.0 | 0.4 | 0.4 | 0.4 | 0.0 | 0.0 | 0.4 | 0.0 | 0.0 | 0.0 | 0.2 |
| 250M | T5-Base | 0.0 | 1.6 | 2.8 | 0.4 | 0.0 | 0.0 | 0.4 | 0.0 | 0.0 | 0.0 | 0.5 |
|  | Flan-T5-Base | 0.0 | 1.2 | 1.6 | 0.4 | 0.0 | 0.0 | 1.2 | 0.0 | 0.0 | 0.0 | 0.4 |
| 780M | T5-Large | 0.0 | 0.8 | 0.8 | 0.8 | 0.0 | 0.0 | 0.8 | 0.0 | 0.0 | 0.0 | 0.3 |
|  | Flan-T5-Large | 0.0 | 1.6 | 2.4 | 2.4 | 0.0 | 0.4 | 0.0 | 0.0 | 0.0 | 0.0 | 0.7 |
| 3B | T5-XL | 0.0 | 2.0 | 2.0 | 1.6 | 0.8 | 0.0 | 1.2 | 0.0 | 0.0 | 0.0 | 0.8 |
|  | Flan-T5-XL | 0.0 | 2.4 | 6.0 | 7.2 | 0.0 | 2.8 | 0.4 | 0.0 | 0.0 | 0.0 | 1.9 |
| 11B | T5-XXL | 0.0 | 4.0 | 3.2 | 1.6 | 0.4 | 0.0 | 0.0 | 0.0 | 0.0 | 0.4 | 1.0 |
|  | Flan-T5-XXL | 0.0 | 14.8 | 14.8 | 13.2 | 0.0 | 5.2 | 0.4 | 0.0 | 0.4 | 0.0 | 4.9 |
| 8B | PaLM | 1.6 | 6.0 | 2.8 | 4.8 | 3.2 | 3.2 | 2.4 | 2.0 | 4.0 | 4.4 | 3.4 |
|  | Flan-PaLM | 2.0 | 17.6 | 15.2 | 16.4 | 6.0 | 13.2 | 1.6 | 2.0 | 0.0 | 8.0 | 8.2 |
| 62B | PaLM | 13.2 | 24.8 | 25.6 | 25.2 | 12.8 | 21.2 | 9.2 | 10.8 | 14.8 | 24.0 | 18.2 |
|  | Flan-PaLM | 17.6 | 40.4 | 46.4 | 40.8 | 21.6 | 36.4 | 14.8 | 12.0 | 22.8 | 32.0 | 28.5 |
| 62B | cont-PaLM | 28.0 | 44.8 | 44.4 | 39.2 | 24.0 | 36.8 | 21.2 | 19.6 | 28.0 | 33.6 | 32.0 |
|  | Flan-cont-PaLM | 34.4 | 52.8 | 53.6 | 53.2 | 36.0 | 43.2 | 27.2 | 28.8 | 29.6 | 44.0 | 40.3 |
| 540B | PaLM | 41.6 | 47.2 | 57.6 | 47.2 | 40.0 | 48.8 | 35.6 | 44.8 | 53.2 | 42.8 | 45.9 |
|  | Flan-PaLM | 55.2 | 60.8 | 68.0 | 63.2 | 56.4 | 60.8 | 50.4 | 46.4 | 55.6 | 53.2 | 57.0 |
| 540B | U-PaLM | 44.8 | 54.4 | 58.0 | 55.2 | 44.0 | 54.8 | 44.4 | 44.4 | 51.2 | 48.0 | 49.9 |
|  | Flan-U-PaLM | 56.4 | 65.6 | 72.4 | 70.8 | 53.6 | 64.8 | 50.4 | 52.8 | 57.2 | 59.6 | 60.4 |
