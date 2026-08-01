---
title: "[tab] Table p.33 — Table 18: Function Key Retrieval Accuracy (%) ablations of RoPE base-period configuration, comparing pre-LCFT and post-LCFT settings across context lengths 4000/8000/16000/24000 and key positions 0/0.2/0.4 — roziere-2023-code-llama-open"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230737-local-roziere-2023-code-llama.pdf.extracted.md"]
extracted_from: roziere-2023-code-llama-open
table_index: 18
row_count: 7
is_snapshot: false
db_table: tab_roziere_2023_code_llama_open_t18
extraction_sha: 05ed05d2d76c420b6af4a1afe6e1dec99939ccf62c5a0c0a258b09cbe1889346
extraction_method: multimodal-sonnet
source_pages: ["33"]
numeric_review_done: 2026-08-01T07:24:52Z
verdict: ok
---

Extracted from [[roziere-2023-code-llama-open]] (vault:20260728-230737-local-roziere-2023-code-llama.pdf.extracted.md), source pages [33], original: vault/roziere-2023-code-llama.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

| Configuration | 4000 / pos 0 (%) | 4000 / pos 0.2 (%) | 4000 / pos 0.4 (%) | 8000 / pos 0 (%) | 8000 / pos 0.2 (%) | 8000 / pos 0.4 (%) | 16000 / pos 0 (%) | 16000 / pos 0.2 (%) | 16000 / pos 0.4 (%) | 24000 / pos 0 (%) | 24000 / pos 0.2 (%) | 24000 / pos 0.4 (%) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| After code-training |  |  |  |  |  |  |  |  |  |  |  |  |
| θ = 10^4 | 95.3 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| θ = 10^6 | 95.3 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| Long context fine-tuning |  |  |  |  |  |  |  |  |  |  |  |  |
| θ = 10^4 | 33.6 | 93.0 | 97.7 | 0.0 | 0.8 | 58.6 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| freq. scaling 1/4 | 100.0 | 100.0 | 100.0 | 100.0 | 99.2 | 99.2 | 2.34 | 99.2 | 100.0 | 0.0 | 0.0 | 0.0 |
| Ours (θ = 10^6) | 95.3 | 95.3 | 100.0 | 100.0 | 95.3 | 100.0 | 54.7 | 100.0 | 98.4 | 3.1 | 85.9 | 85.9 |
