---
title: "[tab] Table p.42 — Table 18: BBH[9:18] individual task performance (tasks 10-18 of 27) — chung-2022-scaling-instruction-finetuned-language"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230728-local-chung-2022-flan.pdf.extracted.md"]
extracted_from: chung-2022-scaling-instruction-finetuned-language
table_index: 18
row_count: 24
is_snapshot: false
db_table: tab_chung_2022_scaling_instruction_finetuned_language_t18
extraction_sha: 771f758c1b711c2a63ca2439e80ab90751351d721632897a058c0205ba9e2a22
extraction_method: multimodal-sonnet
source_pages: ["42"]
numeric_review_done: 2026-07-30T22:31:24Z
verdict: ok
---

Extracted from [[chung-2022-scaling-instruction-finetuned-language]] (vault:20260728-230728-local-chung-2022-flan.pdf.extracted.md), source pages [42], original: vault/chung-2022-flan.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

| Params | Model | Logical Deduction Seven Objects / Direct | Logical Deduction Seven Objects / CoT | Logical Deduction Three Objects / Direct | Logical Deduction Three Objects / CoT | Movie Recommendation / Direct | Movie Recommendation / CoT | Multistep Arithmetic / Direct | Multistep Arithmetic / CoT | Navigate / Direct | Navigate / CoT | Object Counting / Direct | Object Counting / CoT | Penguins in a Table / Direct | Penguins in a Table / CoT | Reasoning about Colored Objects / Direct | Reasoning about Colored Objects / CoT | Ruin Names / Direct | Ruin Names / CoT |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| - | davinci | 20.0 | 27.2 | 38.0 | 52.0 | 58.8 | 71.2 | 0.8 | 1.6 | 58.0 | 66.0 | 33.2 | 49.6 | 28.1 | 35.6 | 13.2 | 41.2 | 18.4 | 33.2 |
| - | text-davinci-002 | 26.8 | 38.0 | 45.2 | 87.6 | 72.0 | 78.8 | 1.2 | 53.2 | 68.0 | 88.8 | 44.0 | 77.2 | 47.3 | 81.5 | 47.6 | 78.4 | 65.6 | 62.8 |
| - | text-davinci-003 | 40.0 | 52.4 | 62.0 | 88.0 | 79.2 | 83.6 | 1.2 | 49.6 | 53.2 | 94.4 | 33.2 | 82.0 | 52.1 | 83.6 | 67.2 | 86.8 | 82.0 | 58.8 |
| - | code-davinci-002 | 26.0 | 38.8 | 52.8 | 87.6 | 84.8 | 90.4 | 1.2 | 47.6 | 50.4 | 96.4 | 45.2 | 93.2 | 66.4 | 79.5 | 67.6 | 91.6 | 75.2 | 68.4 |
| 80M | T5-Small | 13.2 | 5.2 | 31.6 | 14.0 | 26.0 | 14.8 | 0.0 | 0.0 | 55.2 | 40.0 | 10.0 | 0.0 | 21.9 | 19.2 | 16.0 | 11.2 | 22.4 | 1.6 |
|  | Flan-T5-Small | 16.8 | 11.2 | 30.8 | 30.0 | 43.2 | 20.4 | 0.0 | 1.6 | 58.0 | 58.0 | 5.6 | 3.2 | 21.9 | 10.3 | 17.2 | 10.8 | 13.2 | 0.8 |
| 250M | T5-Base | 14.8 | 2.4 | 29.6 | 22.4 | 27.6 | 0.4 | 0.4 | 0.0 | 48.0 | 42.0 | 8.8 | 0.0 | 21.9 | 19.2 | 15.6 | 12.4 | 28.0 | 2.4 |
|  | Flan-T5-Base | 27.2 | 18.8 | 44.4 | 42.0 | 38.4 | 36.8 | 0.0 | 1.2 | 61.6 | 47.6 | 20.0 | 10.0 | 24.0 | 22.6 | 31.2 | 26.8 | 13.2 | 10.4 |
| 780M | T5-Large | 13.2 | 8.0 | 32.4 | 26.0 | 24.8 | 23.2 | 0.4 | 0.0 | 42.0 | 42.0 | 9.6 | 6.4 | 21.9 | 23.3 | 10.4 | 14.8 | 27.6 | 0.4 |
|  | Flan-T5-Large | 42.4 | 21.6 | 50.8 | 40.8 | 54.0 | 48.0 | 0.8 | 0.0 | 56.0 | 54.0 | 28.4 | 20.4 | 42.5 | 28.8 | 42.0 | 36.4 | 21.2 | 21.6 |
| 3B | T5-XL | 13.6 | 15.2 | 35.2 | 35.6 | 25.2 | 23.6 | 0.8 | 0.8 | 42.0 | 38.0 | 6.4 | 25.2 | 21.2 | 25.3 | 12.8 | 14.8 | 26.0 | 0.8 |
|  | Flan-T5-XL | 52.4 | 28.4 | 60.8 | 51.2 | 56.0 | 49.6 | 1.6 | 0.4 | 60.0 | 46.0 | 36.4 | 18.0 | 40.4 | 29.5 | 51.6 | 49.6 | 33.6 | 26.0 |
| 11B | T5-XXL | 18.0 | 18.0 | 36.8 | 42.8 | 46.0 | 45.2 | 0.0 | 0.0 | 41.6 | 37.2 | 31.6 | 33.2 | 21.2 | 24.7 | 16.4 | 22.8 | 20.8 | 0.0 |
|  | Flan-T5-XXL | 59.6 | 51.2 | 71.2 | 63.2 | 60.4 | 41.2 | 0.8 | 0.4 | 58.4 | 60.0 | 42.0 | 40.0 | 42.5 | 44.5 | 58.0 | 50.8 | 53.6 | 35.6 |
| 8B | PaLM | 13.2 | 14.8 | 35.6 | 36.4 | 28.4 | 26.4 | 0.8 | 1.2 | 58.0 | 58.0 | 36.8 | 18.8 | 25.3 | 19.9 | 18.0 | 18.8 | 21.2 | 24.4 |
|  | Flan-PaLM | 25.6 | 12.8 | 47.6 | 40.8 | 72.8 | 43.6 | 0.8 | 0.8 | 58.4 | 55.6 | 30.0 | 24.8 | 26.7 | 30.1 | 28.4 | 34.0 | 36.8 | 32.0 |
| 62B | PaLM | 19.6 | 20.0 | 36.8 | 52.4 | 60.8 | 70.8 | 0.8 | 1.6 | 56.4 | 55.2 | 41.6 | 50.4 | 24.0 | 37.0 | 17.2 | 48.0 | 50.4 | 54.0 |
|  | Flan-PaLM | 48.8 | 34.0 | 74.0 | 56.0 | 82.0 | 72.8 | 1.2 | 1.6 | 60.4 | 49.2 | 50.4 | 51.2 | 37.0 | 49.3 | 50.4 | 46.0 | 63.6 | 54.8 |
| 62B | cont-PaLM | 22.4 | 26.0 | 50.0 | 68.4 | 58.4 | 86.8 | 1.2 | 34.4 | 58.0 | 68.4 | 49.6 | 70.0 | 32.2 | 44.5 | 25.2 | 57.2 | 51.6 | 60.4 |
|  | Flan-cont-PaLM | 51.2 | 30.8 | 70.0 | 56.8 | 84.0 | 82.4 | 1.2 | 21.2 | 61.6 | 57.6 | 50.8 | 62.4 | 44.5 | 55.5 | 52.0 | 56.8 | 60.8 | 76.0 |
| 540B | PaLM | 24.8 | 43.6 | 63.6 | 78.0 | 87.2 | 92.0 | 1.6 | 19.6 | 62.4 | 79.6 | 51.2 | 83.2 | 44.5 | 65.1 | 38.0 | 74.4 | 76.0 | 61.6 |
|  | Flan-PaLM | 50.8 | 48.4 | 85.6 | 87.2 | 85.6 | 82.4 | 0.8 | 29.6 | 68.4 | 78.0 | 54.0 | 88.8 | 55.5 | 72.6 | 66.4 | 82.4 | 81.2 | 68.0 |
| 540B | U-PaLM | 24.4 | 44.4 | 60.4 | 69.6 | 86.0 | 90.8 | 1.6 | 18.8 | 55.6 | 82.0 | 50.4 | 81.6 | 48.6 | 63.7 | 40.4 | 74.8 | 79.6 | 65.6 |
|  | Flan-U-PaLM | 56.0 | 46.4 | 91.2 | 87.2 | 83.6 | 86.4 | 0.8 | 17.2 | 76.8 | 76.4 | 60.8 | 83.2 | 56.2 | 67.8 | 65.6 | 78.0 | 77.2 | 64.8 |
