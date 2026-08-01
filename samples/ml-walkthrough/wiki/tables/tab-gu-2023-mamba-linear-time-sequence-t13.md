---
title: "[tab] Table p.32 — DNA scaling-law model sizes (unlabeled table, section E.3.2) — gu-2023-mamba-linear-time-sequence"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230732-local-gu-2023-mamba.pdf.extracted.md"]
extracted_from: gu-2023-mamba-linear-time-sequence
table_index: 13
row_count: 3
is_snapshot: false
db_table: tab_gu_2023_mamba_linear_time_sequence_t13
extraction_sha: adf70ed1803c85b1899dec3e21f3af0b124411439e8654b840ea65f7b9f52b2e
extraction_method: multimodal-sonnet
source_pages: ["32"]
numeric_review_done: 2026-07-30T22:33:06Z
verdict: suspect
review_required: true
flagged_cells_count: 0
---

Extracted from [[gu-2023-mamba-linear-time-sequence]] (vault:20260728-230732-local-gu-2023-mamba.pdf.extracted.md), source pages [32], original: vault/gu-2023-mamba.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

|  | Config 1 | Config 2 | Config 3 | Config 4 | Config 5 | Config 6 | Config 7 |
|---|---|---|---|---|---|---|---|
| Blocks | 4 | 5 | 6 | 7 | 8 | 10 | 12 |
| Model Dimension | 64 | 96 | 128 | 192 | 256 | 384 | 512 |
| Params (Approx.) | 250K | 700K | 1.4M | 3.5M | 7.0M | 19.3M | 40.7M |

## Numeric review (suspect)

Reviewed 2026-07-30T22:33:06Z. 0 cells flagged.

Notes: PROVENANCE, not numeric. Every value is correct (blocks 4-12, dims 64-512, params 250K-40.7M) and the source genuinely has no caption and no column header row. But the emitted Config 1..Config 7 header is fabricated and sits where a reader expects real headers; only the frontmatter title hints at it, and that does not travel with a quoted table or a db_table row. Fix: bracket or asterisk the labels and add an inline note that the source has no column headers.
