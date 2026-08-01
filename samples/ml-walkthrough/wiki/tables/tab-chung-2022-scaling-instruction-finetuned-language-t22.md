---
title: "[tab] Table p.46 — Table 22: hyperparameters used for all finetuned models — chung-2022-scaling-instruction-finetuned-language"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230728-local-chung-2022-flan.pdf.extracted.md"]
extracted_from: chung-2022-scaling-instruction-finetuned-language
table_index: 22
row_count: 10
is_snapshot: false
db_table: tab_chung_2022_scaling_instruction_finetuned_language_t22
extraction_sha: 771f758c1b711c2a63ca2439e80ab90751351d721632897a058c0205ba9e2a22
extraction_method: multimodal-sonnet
source_pages: ["46"]
numeric_review_done: 2026-07-30T22:31:31Z
verdict: ok
---

Extracted from [[chung-2022-scaling-instruction-finetuned-language]] (vault:20260728-230728-local-chung-2022-flan.pdf.extracted.md), source pages [46], original: vault/chung-2022-flan.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

| Params | Model | Batch size | Dropout | LR | Steps |
|---|---|---|---|---|---|
| 80M | Flan-T5-Small | 64 | 0.05 | 5e-4 | 98k |
| 250M | Flan-T5-Base | 64 | 0.05 | 5e-4 | 84k |
| 780M | Flan-T5-Large | 64 | 0.05 | 5e-4 | 64k |
| 3B | Flan-T5-XL | 64 | 0.05 | 5e-4 | 38k |
| 11B | Flan-T5-XXL | 64 | 0.05 | 5e-4 | 14k |
| 8B | Flan-PaLM | 32 | 0.05 | 3e-3 | 40k |
| 62B | Flan-PaLM | 32 | 0.05 | 3e-3 | 40k |
| 540B | Flan-PaLM | 32 | 0.1 | 1e-3 | 21k |
| 62B | Flan-cont-PaLM | 32 | 0.05 | 3e-3 | 60k |
| 540B | Flan-U-PaLM | 32 | 0.1 | 1e-3 | 30k |
