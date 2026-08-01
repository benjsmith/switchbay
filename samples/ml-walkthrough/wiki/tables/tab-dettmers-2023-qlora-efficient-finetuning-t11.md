---
title: "[tab] Table p.24 — Table 11: MMLU accuracy vs dataset size and finetuning epochs — dettmers-2023-qlora-efficient-finetuning"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230730-local-dettmers-2023-qlora.pdf.extracted.md"]
extracted_from: dettmers-2023-qlora-efficient-finetuning
table_index: 11
row_count: 4
is_snapshot: false
db_table: tab_dettmers_2023_qlora_efficient_finetuning_t11
extraction_sha: 33a4e757c19d6ea8d3cca8958fce8fe405e290272e135c99ee66065c775d5bd1
extraction_method: multimodal-sonnet
source_pages: ["24"]
numeric_review_done: 2026-07-30T22:32:08Z
verdict: ok
---

Extracted from [[dettmers-2023-qlora-efficient-finetuning]] (vault:20260728-230730-local-dettmers-2023-qlora.pdf.extracted.md), source pages [24], original: vault/dettmers-2023-qlora.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

| Datapoints↓ Epochs→ | Chip / 1 | Chip / 2 | Chip / 3 | Unnatural Instructions / 1 | Unnatural Instructions / 2 | Unnatural Instructions / 3 | FLAN v2 / 1 | FLAN v2 / 2 | FLAN v2 / 3 | Mean |
|---|---|---|---|---|---|---|---|---|---|---|
| 50000 | 34.50 | 35.30 | 34.70 | 38.10 | 42.20 | 38.10 | 43.00 | 43.50 | 44.10 | 39.28 |
| 100000 | 33.70 | 33.90 | 34.00 | 40.10 | 41.20 | 37.00 | 43.90 | 43.70 | 44.90 | 39.16 |
| 150000 | 34.40 | 34.80 | 35.10 | 39.70 | 41.10 | 41.50 | 44.60 | 45.50 | 43.50 | 40.02 |
| Mean | 34.20 | 34.67 | 34.60 | 39.30 | 41.50 | 38.87 | 43.83 | 44.23 | 44.17 | null |
