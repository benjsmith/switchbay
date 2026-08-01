---
title: "[tab] Table p.8 — Table 4: Mean 5-shot MMLU accuracy, LLaMA 7B–65B × Alpaca/FLAN v2 × data type — dettmers-2023-qlora-efficient-finetuning"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230730-local-dettmers-2023-qlora.pdf.extracted.md"]
extracted_from: dettmers-2023-qlora-efficient-finetuning
table_index: 4
row_count: 3
is_snapshot: false
db_table: tab_dettmers_2023_qlora_efficient_finetuning_t4
extraction_sha: 33a4e757c19d6ea8d3cca8958fce8fe405e290272e135c99ee66065c775d5bd1
extraction_method: multimodal-sonnet
source_pages: ["8"]
numeric_review_done: 2026-07-30T22:31:49Z
verdict: ok
---

Extracted from [[dettmers-2023-qlora-efficient-finetuning]] (vault:20260728-230730-local-dettmers-2023-qlora.pdf.extracted.md), source pages [8], original: vault/dettmers-2023-qlora.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

| LLaMA Size / Dataset | Mean 5-shot MMLU Accuracy / 7B / Alpaca | Mean 5-shot MMLU Accuracy / 7B / FLAN v2 | Mean 5-shot MMLU Accuracy / 13B / Alpaca | Mean 5-shot MMLU Accuracy / 13B / FLAN v2 | Mean 5-shot MMLU Accuracy / 33B / Alpaca | Mean 5-shot MMLU Accuracy / 33B / FLAN v2 | Mean 5-shot MMLU Accuracy / 65B / Alpaca | Mean 5-shot MMLU Accuracy / 65B / FLAN v2 | Mean |
|---|---|---|---|---|---|---|---|---|---|
| BFloat16 | 38.4 | 45.6 | 47.2 | 50.6 | 57.7 | 60.5 | 61.8 | 62.5 | 53.0 |
| Float4 | 37.2 | 44.0 | 47.3 | 50.0 | 55.9 | 58.5 | 61.3 | 63.3 | 52.2 |
| NFloat4 + DQ | 39.0 | 44.5 | 47.5 | 50.7 | 57.3 | 59.2 | 61.8 | 63.9 | 53.1 |
