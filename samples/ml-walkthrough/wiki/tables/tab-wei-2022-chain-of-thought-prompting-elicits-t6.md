---
title: "[tab] Table p.23 — Table 6 (KEY ABLATION TABLE): Ablation and robustness results for arithmetic reasoning datasets (GSM8K, SVAMP, ASDiv, MAWPS), LaMDA 137B. Ablations tested: equation only, variable compute only, reasoning after answer. Robustness rows tested: different annotators (B, C), intentionally concise style, and three independent exemplar sets sampled from GSM8K (α, β, γ). Standard deviation (±) is over five random orderings of the few-shot exemplars. — wei-2022-chain-of-thought-prompting-elicits"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230742-local-wei-2022-chain-of-thought.pdf.extracted.md"]
extracted_from: wei-2022-chain-of-thought-prompting-elicits
table_index: 6
row_count: 11
is_snapshot: false
db_table: tab_wei_2022_chain_of_thought_prompting_elicits_t6
extraction_sha: 7d9f878c23b460e4566aa4ec9201b1abfb3b8faefb2b1356e411cb90fef72a12
extraction_method: multimodal-sonnet
source_pages: ["23"]
numeric_review_done: 2026-08-01T07:26:38Z
verdict: ok
---

Extracted from [[wei-2022-chain-of-thought-prompting-elicits]] (vault:20260728-230742-local-wei-2022-chain-of-thought.pdf.extracted.md), source pages [23], original: vault/wei-2022-chain-of-thought.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

> **The paper disagrees with itself here.** This table's CoT baseline for SVAMP
> is **36.7** (a 5-seed mean); [[tab-wei-2022-chain-of-thought-prompting-elicits-t2]]
> reports **37.5** for the same model and benchmark (single seed). Both are as
> printed and both were verified against their page images. Cite by table.

| Condition | GSM8K (% ± std) | SVAMP (% ± std) | ASDiv (% ± std) | MAWPS (% ± std) |
|---|---|---|---|---|
| Standard prompting | 6.5 ±0.4 | 29.5 ±0.6 | 40.1 ±0.6 | 43.2 ±0.9 |
| Chain of thought prompting | 14.3 ±0.4 | 36.7 ±0.4 | 46.6 ±0.7 | 57.9 ±1.5 |
| [Ablations] · equation only | 5.4 ±0.2 | 35.1 ±0.4 | 45.9 ±0.6 | 50.1 ±1.0 |
| [Ablations] · variable compute only | 6.4 ±0.3 | 28.0 ±0.6 | 39.4 ±0.4 | 41.3 ±1.1 |
| [Ablations] · reasoning after answer | 6.1 ±0.4 | 30.7 ±0.9 | 38.6 ±0.6 | 43.6 ±1.0 |
| [Robustness] · different annotator (B) | 15.5 ±0.6 | 35.2 ±0.4 | 46.5 ±0.4 | 58.2 ±1.0 |
| [Robustness] · different annotator (C) | 17.6 ±1.0 | 37.5 ±2.0 | 48.7 ±0.7 | 60.1 ±2.0 |
| [Robustness] · intentionally concise style | 11.1 ±0.3 | 38.7 ±0.8 | 48.0 ±0.3 | 59.6 ±0.7 |
| [Robustness] · exemplars from GSM8K (α) | 12.6 ±0.6 | 32.8 ±1.1 | 44.1 ±0.9 | 53.9 ±1.1 |
| [Robustness] · exemplars from GSM8K (β) | 12.7 ±0.5 | 34.8 ±1.1 | 46.9 ±0.6 | 60.9 ±0.8 |
| [Robustness] · exemplars from GSM8K (γ) | 12.6 ±0.7 | 35.6 ±0.5 | 44.4 ±2.6 | 54.2 ±4.7 |
