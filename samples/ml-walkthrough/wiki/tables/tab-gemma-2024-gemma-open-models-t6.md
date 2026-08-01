---
title: "[tab] Table p.6 — Academic benchmark results, compared to similarly sized open models (Table 6) — gemma-2024-gemma-open-models"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230731-local-gemma-team-2024-gemma.pdf.extracted.md"]
extracted_from: gemma-2024-gemma-open-models
table_index: 6
row_count: 19
is_snapshot: false
db_table: tab_gemma_2024_gemma_open_models_t6
extraction_sha: d8f89e0a7e62c57e035d391b3174d8307a73f72ee84f6494ba58aa8fe7e38383
extraction_method: multimodal-sonnet
source_pages: ["6"]
numeric_review_done: 2026-07-30T22:32:23Z
verdict: ok
---

Extracted from [[gemma-2024-gemma-open-models]] (vault:20260728-230731-local-gemma-team-2024-gemma.pdf.extracted.md), source pages [6], original: vault/gemma-team-2024-gemma.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

| Benchmark | metric | LLaMA-2 / 7B | LLaMA-2 / 13B | Mistral / 7B | Gemma / 2B | Gemma / 7B |
|---|---|---|---|---|---|---|
| MMLU | 5-shot, top-1 | 45.3 | 54.8 | 62.5 | 42.3 | 64.3 |
| HellaSwag | 0-shot | 77.2 | 80.7 | 81.0 | 71.4 | 81.2 |
| PIQA | 0-shot | 78.8 | 80.5 | 82.2 | 77.3 | 81.2 |
| SIQA | 0-shot | 48.3 | 50.3 | 47.0* | 49.7 | 51.8 |
| Boolq | 0-shot | 77.4 | 81.7 | 83.2* | 69.4 | 83.2 |
| Winogrande | partial scoring | 69.2 | 72.8 | 74.2 | 65.4 | 72.3 |
| CQA | 7-shot | 57.8 | 67.3 | 66.3* | 65.3 | 71.3 |
| OBQA |  | 58.6 | 57.0 | 52.2 | 47.8 | 52.8 |
| ARC-e |  | 75.2 | 77.3 | 80.5 | 73.2 | 81.5 |
| ARC-c |  | 45.9 | 49.4 | 54.9 | 42.1 | 53.2 |
| TriviaQA | 5-shot | 72.1 | 79.6 | 62.5 | 53.2 | 63.4 |
| NQ | 5-shot | 25.7 | 31.2 | 23.2 | 12.5 | 23.0 |
| HumanEval | pass@1 | 12.8 | 18.3 | 26.2 | 22.0 | 32.3 |
| MBPP† | 3-shot | 20.8 | 30.6 | 40.2* | 29.2 | 44.4 |
| GSM8K | maj@1 | 14.6 | 28.7 | 35.4* | 17.7 | 46.4 |
| MATH | 4-shot | 2.5 | 3.9 | 12.7 | 11.8 | 24.3 |
| AGIEval |  | 29.3 | 39.1 | 41.2* | 24.2 | 41.7 |
| BBH |  | 32.6 | 39.4 | 56.1* | 35.2 | 55.1 |
| Average |  | 46.9 | 52.4 | 54.5 | 45.0 | 56.9 |
