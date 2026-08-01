---
title: "[tab] Table p.16 — Table 6: Ablations — architecture (block) and inner SSM layer, perplexity — gu-2023-mamba-linear-time-sequence"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230732-local-gu-2023-mamba.pdf.extracted.md"]
extracted_from: gu-2023-mamba-linear-time-sequence
table_index: 5
row_count: 8
is_snapshot: false
db_table: tab_gu_2023_mamba_linear_time_sequence_t5
extraction_sha: adf70ed1803c85b1899dec3e21f3af0b124411439e8654b840ea65f7b9f52b2e
extraction_method: multimodal-sonnet
source_pages: ["16"]
numeric_review_done: 2026-07-30T22:32:47Z
verdict: ok
---

Extracted from [[gu-2023-mamba-linear-time-sequence]] (vault:20260728-230732-local-gu-2023-mamba.pdf.extracted.md), source pages [16], original: vault/gu-2023-mamba.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

| Model | Arch. | SSM Layer | Perplexity |
|---|---|---|---|
| Hyena | H3 | Hyena | 10.24 |
| H3 | H3 | S4 (complex) | 10.30 |
| - | H3 | S4 (real) | 10.34 |
| - | H3 | S6 | 8.95 |
| - | Mamba | Hyena | 10.75 |
| - | Mamba | S4 (complex) | 10.54 |
| - | Mamba | S4 (real) | 10.56 |
| Mamba | Mamba | S6 | 8.69 |
