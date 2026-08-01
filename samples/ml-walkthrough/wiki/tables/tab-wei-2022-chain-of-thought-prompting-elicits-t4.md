---
title: "[tab] Table p.22 — Table 4: Standard prompting versus chain of thought prompting on five commonsense reasoning benchmarks (CSQA, StrategyQA, Date Understanding, Sports Understanding, SayCan), by model family and size. — wei-2022-chain-of-thought-prompting-elicits"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230742-local-wei-2022-chain-of-thought.pdf.extracted.md"]
extracted_from: wei-2022-chain-of-thought-prompting-elicits
table_index: 4
row_count: 14
is_snapshot: false
db_table: tab_wei_2022_chain_of_thought_prompting_elicits_t4
extraction_sha: 7d9f878c23b460e4566aa4ec9201b1abfb3b8faefb2b1356e411cb90fef72a12
extraction_method: multimodal-sonnet
source_pages: ["22"]
numeric_review_done: 2026-08-01T07:26:34Z
verdict: ok
---

Extracted from [[wei-2022-chain-of-thought-prompting-elicits]] (vault:20260728-230742-local-wei-2022-chain-of-thought.pdf.extracted.md), source pages [22], original: vault/wei-2022-chain-of-thought.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

> **The paper's body text disagrees with this table.** This appendix table gives
> PaLM 540B CoT on StrategyQA as **77.8**; the paper's own results section claims
> **75.6%** against a 69.4% prior state of the art. Both readings were confirmed
> against the source. [[chain-of-thought-prompting]] cites the body-text
> figure, which is why it does not match the row below. Cite by locus.

| Model | Size | CSQA / standard (%) | CSQA / CoT (%) | StrategyQA / standard (%) | StrategyQA / CoT (%) | Date / standard (%) | Date / CoT (%) | Sports / standard (%) | Sports / CoT (%) | SayCan / standard (%) | SayCan / CoT (%) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| UL2 | 20B | 34.2 | 51.4 | 59.0 | 53.3 | 13.5 | 14.0 | 57.9 | 65.3 | 20.0 | 41.7 |
| LaMDA | 420M | 20.1 | 19.2 | 46.4 | 24.9 | 1.9 | 1.6 | 50.0 | 49.7 | 7.5 | 7.5 |
| LaMDA | 2B | 20.2 | 19.6 | 52.6 | 45.2 | 8.0 | 6.8 | 49.3 | 57.5 | 8.3 | 8.3 |
| LaMDA | 8B | 19.0 | 20.3 | 54.1 | 46.8 | 9.5 | 5.4 | 50.0 | 52.1 | 28.3 | 33.3 |
| LaMDA | 68B | 37.0 | 44.1 | 59.6 | 62.2 | 15.5 | 18.6 | 55.2 | 77.5 | 35.0 | 42.5 |
| LaMDA | 137B | 53.6 | 57.9 | 62.4 | 65.4 | 21.5 | 26.8 | 59.5 | 85.8 | 43.3 | 46.6 |
| GPT | 350M | 14.7 | 15.2 | 20.6 | 0.9 | 4.3 | 0.9 | 33.8 | 41.6 | 12.5 | 0.8 |
| GPT | 1.3B | 12.0 | 19.2 | 45.8 | 35.7 | 4.0 | 1.4 | 0.0 | 26.9 | 20.8 | 9.2 |
| GPT | 6.7B | 19.0 | 24.0 | 53.6 | 50.0 | 8.9 | 4.9 | 0.0 | 4.4 | 17.5 | 35.0 |
| GPT | 175B | 79.5 | 73.5 | 65.9 | 65.4 | 43.8 | 52.1 | 69.6 | 82.4 | 81.7 | 87.5 |
| Codex | - | 82.3 | 77.9 | 67.1 | 73.2 | 49.0 | 64.8 | 71.7 | 98.5 | 85.8 | 88.3 |
| PaLM | 8B | 19.8 | 24.9 | 55.6 | 53.5 | 12.9 | 13.1 | 55.1 | 75.2 | 34.2 | 40.0 |
| PaLM | 62B | 65.4 | 68.1 | 58.4 | 63.4 | 29.8 | 44.7 | 72.1 | 93.6 | 65.8 | 70.0 |
| PaLM | 540B | 78.1 | 79.9 | 68.6 | 77.8 | 49.0 | 65.3 | 80.5 | 95.4 | 80.8 | 91.7 |
