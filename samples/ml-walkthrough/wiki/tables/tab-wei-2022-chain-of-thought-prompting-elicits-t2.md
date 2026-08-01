---
title: "[tab] Table p.21 — Table 2: Standard prompting versus chain of thought prompting on five arithmetic reasoning benchmarks (GSM8K, SVAMP, ASDiv, AQuA, MAWPS), broken out by model family and size. Chain of thought prompting is an emergent ability of model scale. — wei-2022-chain-of-thought-prompting-elicits"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230742-local-wei-2022-chain-of-thought.pdf.extracted.md"]
extracted_from: wei-2022-chain-of-thought-prompting-elicits
table_index: 2
row_count: 14
is_snapshot: false
db_table: tab_wei_2022_chain_of_thought_prompting_elicits_t2
extraction_sha: 7d9f878c23b460e4566aa4ec9201b1abfb3b8faefb2b1356e411cb90fef72a12
extraction_method: multimodal-sonnet
source_pages: ["21"]
numeric_review_done: 2026-08-01T07:26:29Z
verdict: ok
---

Extracted from [[wei-2022-chain-of-thought-prompting-elicits]] (vault:20260728-230742-local-wei-2022-chain-of-thought.pdf.extracted.md), source pages [21], original: vault/wei-2022-chain-of-thought.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

> **The paper disagrees with itself here.** This table's CoT value for SVAMP is
> **37.5** (single seed); the ablation table
> [[tab-wei-2022-chain-of-thought-prompting-elicits-t6]] reports **36.7** for the
> same model and benchmark (a 5-seed mean). Both are as printed and both were
> verified against their page images. Cite by table.

| Model | Size | GSM8K / standard (%) | GSM8K / CoT (%) | SVAMP / standard (%) | SVAMP / CoT (%) | ASDiv / standard (%) | ASDiv / CoT (%) | AQuA / standard (%) | AQuA / CoT (%) | MAWPS / standard (%) | MAWPS / CoT (%) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| UL2 | 20B | 4.1 | 4.4 | 10.1 | 12.5 | 16.0 | 16.9 | 20.5 | 23.6 | 16.6 | 19.1 |
| LaMDA | 420M | 2.6 | 0.4 | 2.5 | 1.6 | 3.2 | 0.8 | 23.5 | 8.3 | 3.2 | 0.9 |
| LaMDA | 2B | 3.6 | 1.9 | 3.3 | 2.4 | 4.1 | 3.8 | 22.9 | 17.7 | 3.9 | 3.1 |
| LaMDA | 8B | 3.2 | 1.6 | 4.3 | 3.4 | 5.9 | 5.0 | 22.8 | 18.6 | 5.3 | 4.8 |
| LaMDA | 68B | 5.7 | 8.2 | 13.6 | 18.8 | 21.8 | 23.1 | 22.3 | 20.2 | 21.6 | 30.6 |
| LaMDA | 137B | 6.5 | 14.3 | 29.5 | 37.5 | 40.1 | 46.6 | 25.5 | 20.6 | 43.2 | 57.9 |
| GPT | 350M | 2.2 | 0.5 | 1.4 | 0.8 | 2.1 | 0.8 | 18.1 | 8.7 | 2.4 | 1.1 |
| GPT | 1.3B | 2.4 | 0.5 | 1.5 | 1.7 | 2.6 | 1.4 | 12.6 | 4.3 | 3.1 | 1.7 |
| GPT | 6.7B | 4.0 | 2.4 | 6.1 | 3.1 | 8.6 | 3.6 | 15.4 | 13.4 | 8.8 | 3.5 |
| GPT | 175B | 15.6 | 46.9 | 65.7 | 68.9 | 70.3 | 71.3 | 24.8 | 35.8 | 72.7 | 87.1 |
| Codex | - | 19.7 | 63.1 | 69.9 | 76.4 | 74.0 | 80.4 | 29.5 | 45.3 | 78.7 | 92.6 |
| PaLM | 8B | 4.9 | 4.1 | 15.1 | 16.8 | 23.7 | 25.2 | 19.3 | 21.7 | 26.2 | 30.5 |
| PaLM | 62B | 9.6 | 29.9 | 48.2 | 46.7 | 58.7 | 61.9 | 25.6 | 22.4 | 61.8 | 80.3 |
| PaLM | 540B | 17.9 | 56.9 | 69.4 | 79.0 | 72.1 | 73.9 | 25.2 | 35.8 | 79.2 | 93.3 |
