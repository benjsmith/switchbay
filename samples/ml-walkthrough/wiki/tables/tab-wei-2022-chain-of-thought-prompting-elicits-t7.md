---
title: "[tab] Table p.23 — Table 7: Ablation and robustness results for four datasets in commonsense and symbolic reasoning (Date Understanding, Sports Understanding, SayCan under Commonsense; Last Letter Concatenation ['Concat'] and Coin Flip ['Coin'] under Symbolic). Results shown for LaMDA 137B, except SayCan which uses PaLM (540B) since its eval set is only 120 examples. Standard deviation (±) is over five random exemplar orderings. — wei-2022-chain-of-thought-prompting-elicits"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230742-local-wei-2022-chain-of-thought.pdf.extracted.md"]
extracted_from: wei-2022-chain-of-thought-prompting-elicits
table_index: 7
row_count: 6
is_snapshot: false
db_table: tab_wei_2022_chain_of_thought_prompting_elicits_t7
extraction_sha: 7d9f878c23b460e4566aa4ec9201b1abfb3b8faefb2b1356e411cb90fef72a12
extraction_method: multimodal-sonnet
source_pages: ["23"]
numeric_review_done: 2026-08-01T07:26:40Z
verdict: ok
---

Extracted from [[wei-2022-chain-of-thought-prompting-elicits]] (vault:20260728-230742-local-wei-2022-chain-of-thought.pdf.extracted.md), source pages [23], original: vault/wei-2022-chain-of-thought.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

| Condition | Date (% ± std) | Sports (% ± std) | SayCan (% ± std) | Concat (% ± std) | Coin (% ± std) |
|---|---|---|---|---|---|
| Standard prompting | 21.5 ±0.6 | 59.5 ±3.0 | 80.8 ±1.8 | 5.8 ±0.6 | 49.0 ±2.1 |
| Chain of thought prompting | 26.8 ±2.1 | 85.8 ±1.8 | 91.7 ±1.4 | 77.5 ±3.8 | 99.6 ±0.3 |
| [Ablations] · variable compute only | 21.3 ±0.7 | 61.6 ±2.2 | 74.2 ±2.3 | 7.2 ±1.6 | 50.7 ±0.7 |
| [Ablations] · reasoning after answer | 20.9 ±1.0 | 63.0 ±2.0 | 83.3 ±0.6 | 0.0 ±0.0 | 50.2 ±0.5 |
| [Robustness] · different annotator (B) | 27.4 ±1.7 | 75.4 ±2.7 | 88.3 ±1.4 | 76.0 ±1.9 | 77.5 ±7.9 |
| [Robustness] · different annotator (C) | 25.5 ±2.5 | 81.1 ±3.6 | 85.0 ±1.8 | 68.1 ±2.2 | 71.4 ±11.1 |
