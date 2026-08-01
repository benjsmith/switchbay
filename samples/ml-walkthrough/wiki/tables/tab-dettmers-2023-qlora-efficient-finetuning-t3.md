---
title: "[tab] Table p.7 — Table 3: GLUE / Super-NaturalInstructions accuracy across data types — dettmers-2023-qlora-efficient-finetuning"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230730-local-dettmers-2023-qlora.pdf.extracted.md"]
extracted_from: dettmers-2023-qlora-efficient-finetuning
table_index: 3
row_count: 6
is_snapshot: false
db_table: tab_dettmers_2023_qlora_efficient_finetuning_t3
extraction_sha: 33a4e757c19d6ea8d3cca8958fce8fe405e290272e135c99ee66065c775d5bd1
extraction_method: multimodal-sonnet
source_pages: ["7"]
numeric_review_done: 2026-07-30T22:31:47Z
verdict: ok
---

Extracted from [[dettmers-2023-qlora-efficient-finetuning]] (vault:20260728-230730-local-dettmers-2023-qlora.pdf.extracted.md), source pages [7], original: vault/dettmers-2023-qlora.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

| Dataset / Model | GLUE (Acc.) / RoBERTa-large | Super-NaturalInstructions (RougeL) / T5-80M | Super-NaturalInstructions (RougeL) / T5-250M | Super-NaturalInstructions (RougeL) / T5-780M | Super-NaturalInstructions (RougeL) / T5-3B | Super-NaturalInstructions (RougeL) / T5-11B |
|---|---|---|---|---|---|---|
| BF16 | 88.6 | 40.1 | 42.1 | 48.0 | 54.3 | 62.0 |
| BF16 replication | 88.6 | 40.0 | 42.2 | 47.3 | 54.9 | - |
| LoRA BF16 | 88.8 | 40.5 | 42.6 | 47.1 | 55.4 | 60.7 |
| QLoRA Int8 | 88.8 | 40.4 | 42.9 | 45.4 | 56.5 | 60.7 |
| QLoRA FP4 | 88.6 | 40.3 | 42.4 | 47.5 | 55.6 | 60.9 |
| QLoRA NF4 + DQ | - | 40.4 | 42.7 | 47.7 | 55.3 | 60.9 |
