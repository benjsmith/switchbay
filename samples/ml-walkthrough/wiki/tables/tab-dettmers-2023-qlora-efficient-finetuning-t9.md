---
title: "[tab] Table p.23 — Table 9: QLoRA finetuning training hyperparameters — dettmers-2023-qlora-efficient-finetuning"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230730-local-dettmers-2023-qlora.pdf.extracted.md"]
extracted_from: dettmers-2023-qlora-efficient-finetuning
table_index: 9
row_count: 16
is_snapshot: false
db_table: tab_dettmers_2023_qlora_efficient_finetuning_t9
extraction_sha: 33a4e757c19d6ea8d3cca8958fce8fe405e290272e135c99ee66065c775d5bd1
extraction_method: multimodal-sonnet
source_pages: ["23"]
numeric_review_done: 2026-07-30T22:32:04Z
verdict: ok
---

Extracted from [[dettmers-2023-qlora-efficient-finetuning]] (vault:20260728-230730-local-dettmers-2023-qlora.pdf.extracted.md), source pages [23], original: vault/dettmers-2023-qlora.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

| Parameters | Dataset | Batch size | LR | Steps | Source Length | Target Length |
|---|---|---|---|---|---|---|
| 7B | All | 16 | 2e-4 | 10000 | 384 | 128 |
| 7B | OASST1 | 16 | 2e-4 | 1875 | - | 512 |
| 7B | HH-RLHF | 16 | 2e-4 | 10000 | - | 768 |
| 7B | Longform | 16 | 2e-4 | 4000 | 512 | 1024 |
| 13B | All | 16 | 2e-4 | 10000 | 384 | 128 |
| 13B | OASST1 | 16 | 2e-4 | 1875 | - | 512 |
| 13B | HH-RLHF | 16 | 2e-4 | 10000 | - | 768 |
| 13B | Longform | 16 | 2e-4 | 4000 | 512 | 1024 |
| 33B | All | 32 | 1e-4 | 5000 | 384 | 128 |
| 33B | OASST1 | 16 | 1e-4 | 1875 | - | 512 |
| 33B | HH-RLHF | 32 | 1e-4 | 5000 | - | 768 |
| 33B | Longform | 32 | 1e-4 | 2343 | 512 | 1024 |
| 65B | All | 64 | 1e-4 | 2500 | 384 | 128 |
| 65B | OASST1 | 16 | 1e-4 | 1875 | - | 512 |
| 65B | HH-RLHF | 64 | 1e-4 | 2500 | - | 768 |
| 65B | Longform | 32 | 1e-4 | 2343 | 512 | 1024 |
