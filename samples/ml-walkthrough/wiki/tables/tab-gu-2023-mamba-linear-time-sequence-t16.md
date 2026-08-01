---
title: "[tab] Table p.36 — Table 15: Memory benchmark (125M models, training) — gu-2023-mamba-linear-time-sequence"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230732-local-gu-2023-mamba.pdf.extracted.md"]
extracted_from: gu-2023-mamba-linear-time-sequence
table_index: 16
row_count: 6
is_snapshot: false
db_table: tab_gu_2023_mamba_linear_time_sequence_t16
extraction_sha: adf70ed1803c85b1899dec3e21f3af0b124411439e8654b840ea65f7b9f52b2e
extraction_method: multimodal-sonnet
source_pages: ["36"]
numeric_review_done: 2026-07-30T22:33:12Z
verdict: ok
---

Extracted from [[gu-2023-mamba-linear-time-sequence]] (vault:20260728-230732-local-gu-2023-mamba.pdf.extracted.md), source pages [36], original: vault/gu-2023-mamba.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

| Batch size | Transformer (w/ FlashAttention-2) | Mamba |
|---|---|---|
| 1 | 4.6GB | 4.8GB |
| 2 | 5.2GB | 5.8GB |
| 4 | 6.9GB | 7.3GB |
| 8 | 11.5GB | 12.3GB |
| 16 | 20.7GB | 23.1GB |
| 32 | 34.5GB | 38.2GB |
