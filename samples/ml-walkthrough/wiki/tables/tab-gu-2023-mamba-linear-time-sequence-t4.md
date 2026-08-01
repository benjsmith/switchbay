---
title: "[tab] Table p.15 — Table 5: SC09 model ablations (outer/center block architecture) — gu-2023-mamba-linear-time-sequence"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230732-local-gu-2023-mamba.pdf.extracted.md"]
extracted_from: gu-2023-mamba-linear-time-sequence
table_index: 4
row_count: 6
is_snapshot: false
db_table: tab_gu_2023_mamba_linear_time_sequence_t4
extraction_sha: adf70ed1803c85b1899dec3e21f3af0b124411439e8654b840ea65f7b9f52b2e
extraction_method: multimodal-sonnet
source_pages: ["15"]
numeric_review_done: 2026-07-30T22:32:46Z
verdict: ok
---

Extracted from [[gu-2023-mamba-linear-time-sequence]] (vault:20260728-230732-local-gu-2023-mamba.pdf.extracted.md), source pages [15], original: vault/gu-2023-mamba.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

| Outer | Center | NLL↓ | FID↓ | IS↑ | mIS↑ | AM↓ |
|---|---|---|---|---|---|---|
| S4+MLP | MHA+MLP | 1.859 | 1.45 | 5.06 | 47.03 | 0.70 |
| S4+MLP | S4+MLP | 1.867 | 1.43 | 5.42 | 53.54 | 0.65 |
| S4+MLP | Mamba | 1.859 | 1.42 | 5.71 | 56.51 | 0.64 |
| Mamba | MHA+MLP | 1.850 | 1.37 | 5.63 | 58.23 | 0.62 |
| Mamba | S4+MLP | 1.853 | 1.07 | 6.05 | 73.34 | 0.55 |
| Mamba | Mamba | 1.852 | 0.94 | 6.26 | 88.54 | 0.52 |
