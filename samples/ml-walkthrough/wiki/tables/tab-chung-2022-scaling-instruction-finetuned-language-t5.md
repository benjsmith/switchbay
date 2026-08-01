---
title: "[tab] Table p.11 — Table 5: instruction finetuning (Flan) vs. base models, all model families — chung-2022-scaling-instruction-finetuned-language"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230728-local-chung-2022-flan.pdf.extracted.md"]
extracted_from: chung-2022-scaling-instruction-finetuned-language
table_index: 5
row_count: 20
is_snapshot: false
db_table: tab_chung_2022_scaling_instruction_finetuned_language_t5
extraction_sha: 771f758c1b711c2a63ca2439e80ab90751351d721632897a058c0205ba9e2a22
extraction_method: multimodal-sonnet
source_pages: ["11"]
numeric_review_done: 2026-07-30T22:30:54Z
verdict: ok
---

Extracted from [[chung-2022-scaling-instruction-finetuned-language]] (vault:20260728-230728-local-chung-2022-flan.pdf.extracted.md), source pages [11], original: vault/chung-2022-flan.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

| Params | Model | Norm. avg. | MMLU / Direct | MMLU / CoT | BBH / Direct | BBH / CoT | TyDiQA / Direct | MGSM / CoT |
|---|---|---|---|---|---|---|---|---|
| 80M | T5-Small | -9.2 | 26.7 | 5.6 | 27.0 | 7.2 | 0.0 | 0.4 |
|  | Flan-T5-Small | -3.1 (+6.1) | 28.7 | 12.1 | 29.1 | 19.2 | 1.1 | 0.2 |
| 250M | T5-Base | -5.1 | 25.7 | 14.5 | 27.8 | 14.6 | 0.0 | 0.5 |
|  | Flan-T5-Base | 6.5 (+11.6) | 35.9 | 33.7 | 31.3 | 27.9 | 4.1 | 0.4 |
| 780M | T5-Large | -5.0 | 25.1 | 15.0 | 27.7 | 16.1 | 0.0 | 0.3 |
|  | Flan-T5-Large | 13.8 (+18.8) | 45.1 | 40.5 | 37.5 | 31.5 | 12.3 | 0.7 |
| 3B | T5-XL | -4.1 | 25.7 | 14.5 | 27.4 | 19.2 | 0.0 | 0.8 |
|  | Flan-T5-XL | 19.1 (+23.2) | 52.4 | 45.5 | 41.0 | 35.2 | 16.6 | 1.9 |
| 11B | T5-XXL | -2.9 | 25.9 | 18.7 | 29.5 | 19.3 | 0.0 | 1.0 |
|  | Flan-T5-XXL | 23.7 (+26.6) | 55.1 | 48.6 | 45.3 | 41.4 | 19.0 | 4.9 |
| 8B | PaLM | 6.4 | 24.3 | 24.1 | 30.8 | 30.1 | 25.0 | 3.4 |
|  | Flan-PaLM | 21.9 (+15.5) | 49.3 | 41.3 | 36.4 | 31.1 | 47.5 | 8.2 |
| 62B | PaLM | 28.4 | 55.1 | 49.0 | 37.4 | 43.0 | 40.5 | 18.2 |
|  | Flan-PaLM | 38.8 (+10.4) | 59.6 | 56.9 | 47.5 | 44.9 | 58.7 | 28.5 |
| 540B | PaLM | 49.1 | 71.3 | 62.9 | 49.1 | 63.7 | 52.9 | 45.9 |
|  | Flan-PaLM | 58.4 (+9.3) | 73.5 | 70.9 | 57.9 | 66.3 | 67.8 | 57.0 |
| 62B | cont-PaLM | 38.1 | 61.2 | 57.6 | 41.7 | 53.1 | 45.7 | 32.0 |
|  | Flan-cont-PaLM | 46.7 (+8.6) | 66.1 | 62.0 | 51.0 | 53.3 | 62.7 | 40.3 |
| 540B | U-PaLM | 50.2 | 71.5 | 64.0 | 49.2 | 62.4 | 54.6 | 49.9 |
|  | Flan-U-PaLM | 59.1 (+8.9) | 74.1 | 69.8 | 59.3 | 64.9 | 68.3 | 60.4 |
