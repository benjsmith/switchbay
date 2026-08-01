---
title: "[tab] Table p.29 — Table 11: Induction heads, full test accuracy (%) by sequence length — gu-2023-mamba-linear-time-sequence"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230732-local-gu-2023-mamba.pdf.extracted.md"]
extracted_from: gu-2023-mamba-linear-time-sequence
table_index: 11
row_count: 6
is_snapshot: false
db_table: tab_gu_2023_mamba_linear_time_sequence_t11
extraction_sha: adf70ed1803c85b1899dec3e21f3af0b124411439e8654b840ea65f7b9f52b2e
extraction_method: multimodal-sonnet
source_pages: ["29"]
numeric_review_done: 2026-07-30T22:33:00Z
verdict: ok
---

Extracted from [[gu-2023-mamba-linear-time-sequence]] (vault:20260728-230732-local-gu-2023-mamba.pdf.extracted.md), source pages [29], original: vault/gu-2023-mamba.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

| Model | Params | 2⁶ | 2⁷ | 2⁸ | 2⁹ | 2¹⁰ | 2¹¹ | 2¹² | 2¹³ | 2¹⁴ | 2¹⁵ | 2¹⁶ | 2¹⁷ | 2¹⁸ | 2¹⁹ | 2²⁰ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MHA-Abs | 137K | ✓ | 99.6 | 100.0 | 58.6 | 26.6 | 18.8 | 9.8 | 10.9 | 7.8 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| MHA-RoPE | 137K | ✓ | ✓ | 100.0 | 83.6 | 31.3 | 18.4 | 8.6 | 9.0 | 5.5 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| MHA-xPos | 137K | ✓ | ✓ | 100.0 | 99.6 | 67.6 | 25.4 | 7.0 | 9.0 | 7.8 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| H3 | 153K | ✓ | ✓ | 100.0 | 80.9 | 39.5 | 23.8 | 14.8 | 8.2 | 5.9 | 6.6 | 8.2 | 4.7 | 8.2 | 6.3 | 7.4 |
| Hyena | 69M* | 97.7 | ✓ | 100.0 | ✓ | 44.1 | 12.5 | 6.6 | 5.1 | 7.0 | 5.9 | 6.6 | 6.6 | 5.9 | 6.3 | 9.8 |
| Mamba | 74K | ✓ | ✓ | 100.0 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
