---
title: "[tab] Table p.15 — Table 4: SC09 unconditional generation metrics — gu-2023-mamba-linear-time-sequence"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230732-local-gu-2023-mamba.pdf.extracted.md"]
extracted_from: gu-2023-mamba-linear-time-sequence
table_index: 3
row_count: 10
is_snapshot: false
db_table: tab_gu_2023_mamba_linear_time_sequence_t3
extraction_sha: adf70ed1803c85b1899dec3e21f3af0b124411439e8654b840ea65f7b9f52b2e
extraction_method: multimodal-sonnet
source_pages: ["15"]
numeric_review_done: 2026-07-30T22:32:43Z
verdict: ok
---

Extracted from [[gu-2023-mamba-linear-time-sequence]] (vault:20260728-230732-local-gu-2023-mamba.pdf.extracted.md), source pages [15], original: vault/gu-2023-mamba.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

| Model | Params | NLL↓ | FID↓ | IS↑ | mIS↑ | AM↓ |
|---|---|---|---|---|---|---|
| SampleRNN | 35.0M | 2.042 | 8.96 | 1.71 | 3.02 | 1.76 |
| WaveNet | 4.2M | 1.925 | 5.08 | 2.27 | 5.80 | 1.47 |
| SaShiMi | 5.8M | 1.873 | 1.99 | 5.13 | 42.57 | 0.74 |
| WaveGAN | 19.1M | - | 2.03 | 4.90 | 36.10 | 0.80 |
| DiffWave | 24.1M | - | 1.92 | 5.26 | 51.21 | 0.68 |
| + SaShiMi | 23.0M | - | 1.42 | 5.94 | 69.17 | 0.59 |
| Mamba | 6.1M | 1.852 | 0.94 | 6.26 | 88.54 | 0.52 |
| Mamba | 24.3M | 1.860 | 0.67 | 7.33 | 144.9 | 0.36 |
| Train | - | - | 0.00 | 8.56 | 292.5 | 0.16 |
| Test | - | - | 0.02 | 8.33 | 257.6 | 0.19 |
