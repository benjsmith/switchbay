---
title: "[tab] Table p.7 — Table 3: effect of scaling number of finetuning tasks (8B/62B/540B PaLM) — chung-2022-scaling-instruction-finetuned-language"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230728-local-chung-2022-flan.pdf.extracted.md"]
extracted_from: chung-2022-scaling-instruction-finetuned-language
table_index: 3
row_count: 15
is_snapshot: false
db_table: tab_chung_2022_scaling_instruction_finetuned_language_t3
extraction_sha: 771f758c1b711c2a63ca2439e80ab90751351d721632897a058c0205ba9e2a22
extraction_method: multimodal-sonnet
source_pages: ["7"]
numeric_review_done: 2026-07-30T22:30:49Z
verdict: ok
---

Extracted from [[chung-2022-scaling-instruction-finetuned-language]] (vault:20260728-230728-local-chung-2022-flan.pdf.extracted.md), source pages [7], original: vault/chung-2022-flan.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

| Model | Finetuning Mixtures | Tasks | Norm. avg. | MMLU / Direct | MMLU / CoT | BBH / Direct | BBH / CoT | TyDiQA / Direct | MGSM / CoT |
|---|---|---|---|---|---|---|---|---|---|
| 8B | None (no finetuning) | 0 | 6.4 | 24.3 | 24.1 | 30.8 | 30.1 | 25.0 | 3.4 |
|  | CoT | 9 | 8.3 (+1.9) | 26.3 | 32.1 | 19.8 | 26.6 | 39.3 | 10.4 |
|  | CoT, Muffin | 89 | 14.8 (+8.4) | 37.6 | 38.4 | 31.0 | 30.9 | 32.4 | 8.4 |
|  | CoT, Muffin, T0-SF | 282 | 20.5 (+14.1) | 47.7 | 39.7 | 33.1 | 30.9 | 49.0 | 8.5 |
|  | CoT, Muffin, T0-SF, NIV2 | 1,836 | 21.9 (+15.5) | 49.3 | 41.3 | 36.4 | 31.1 | 47.5 | 8.2 |
| 62B | None (no finetuning) | 0 | 28.4 | 55.1 | 49.0 | 37.4 | 43.0 | 40.5 | 18.2 |
|  | CoT | 9 | 29.0 (+0.4) | 48.5 | 48.7 | 34.5 | 39.5 | 48.8 | 32.6 |
|  | CoT, Muffin | 89 | 33.4 (+6.0) | 55.3 | 51.4 | 42.8 | 40.2 | 53.0 | 23.9 |
|  | CoT, Muffin, T0-SF | 282 | 37.9 (+9.5) | 60.0 | 56.0 | 44.7 | 43.8 | 58.2 | 30.0 |
|  | CoT, Muffin, T0-SF, NIV2 | 1,836 | 38.8 (+10.4) | 59.6 | 56.9 | 47.5 | 44.9 | 58.7 | 28.5 |
| 540B | None (no finetuning) | 0 | 49.1 | 71.3 | 62.9 | 49.1 | 63.7 | 52.9 | 45.9 |
|  | CoT | 9 | 52.6 (+3.5) | 68.8 | 64.8 | 50.5 | 61.1 | 61.2 | 59.4 |
|  | CoT, Muffin | 89 | 57.0 (+7.9) | 71.8 | 66.7 | 56.7 | 64.0 | 65.3 | 63.0 |
|  | CoT, Muffin, T0-SF | 282 | 57.5 (+8.4) | 72.9 | 68.2 | 57.3 | 64.0 | 65.8 | 61.6 |
|  | CoT, Muffin, T0-SF, NIV2 | 1,836 | 58.5 (+9.4) | 73.2 | 68.1 | 58.8 | 65.6 | 67.4 | 61.3 |
