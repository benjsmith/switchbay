---
title: "[tab] Table p.8 — Table 4: Flan-PaLM vs. PaLM 540B on MMLU/BBH-nlp/BBH-alg/TyDiQA/MGSM — chung-2022-scaling-instruction-finetuned-language"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230728-local-chung-2022-flan.pdf.extracted.md"]
extracted_from: chung-2022-scaling-instruction-finetuned-language
table_index: 4
row_count: 7
is_snapshot: false
db_table: tab_chung_2022_scaling_instruction_finetuned_language_t4
extraction_sha: 771f758c1b711c2a63ca2439e80ab90751351d721632897a058c0205ba9e2a22
extraction_method: multimodal-sonnet
source_pages: ["8"]
numeric_review_done: 2026-07-30T22:30:51Z
verdict: ok
---

Extracted from [[chung-2022-scaling-instruction-finetuned-language]] (vault:20260728-230728-local-chung-2022-flan.pdf.extracted.md), source pages [8], original: vault/chung-2022-flan.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

|  | MMLU | BBH-nlp | BBH-alg | TyDiQA | MGSM |
|---|---|---|---|---|---|
| Prior best | 69.3^a | 73.5^b | 73.9^b | 81.9^c | 55.0^d |
| PaLM 540B - direct prompting | 69.3 | 62.7 | 38.3 | 52.9 | 18.3 |
| PaLM 540B - CoT prompting | 64.5 | 71.2 | 57.6 | - | 45.9 |
| PaLM 540B - CoT + self-consistency | 69.5 | 78.2 | 62.2 | - | 57.9 |
| Flan-PaLM 540B - direct prompting | 72.2 | 70.0 | 48.2 | 67.8 | 21.2 |
| Flan-PaLM 540B - CoT prompting | 70.2 | 72.4 | 61.3 | - | 57.0 |
| Flan-PaLM 540B - CoT + self-consistency | 75.2 | 78.4 | 66.5 | - | 72.0 |
