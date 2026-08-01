---
title: "[tab] Table p.20 — Table 1: Chain of thought prompting outperforms standard prompting for various large language models on five arithmetic reasoning benchmarks. All metrics are accuracy (%). Ext. calc.: post-hoc external calculator for arithmetic computations only. Prior best numbers are from: a: Cobbe et al. (2021), b & e: Pi et al. (2022), c: Lan et al. (2021), d: Piękos et al. (2021). — wei-2022-chain-of-thought-prompting-elicits"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230742-local-wei-2022-chain-of-thought.pdf.extracted.md"]
extracted_from: wei-2022-chain-of-thought-prompting-elicits
table_index: 1
row_count: 16
is_snapshot: false
db_table: tab_wei_2022_chain_of_thought_prompting_elicits_t1
extraction_sha: 7d9f878c23b460e4566aa4ec9201b1abfb3b8faefb2b1356e411cb90fef72a12
extraction_method: multimodal-sonnet
source_pages: ["20"]
numeric_review_done: 2026-08-01T07:26:27Z
verdict: ok
---

Extracted from [[wei-2022-chain-of-thought-prompting-elicits]] (vault:20260728-230742-local-wei-2022-chain-of-thought.pdf.extracted.md), source pages [20], original: vault/wei-2022-chain-of-thought.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

| Model | Prompting | GSM8K (%) | SVAMP (%) | ASDiv (%) | AQuA (%) | MAWPS (%) |
|---|---|---|---|---|---|---|
| Prior best | N/A (finetuning) | 55^a | 57.4^b | 75.3^c | 37.9^d | 88.4^e |
| UL2 20B | Standard | 4.1 | 10.1 | 16.0 | 20.5 | 16.6 |
| UL2 20B | Chain of thought | 4.4 (+0.3) | 12.5 (+2.4) | 16.9 (+0.9) | 23.6 (+3.1) | 19.1 (+2.5) |
| UL2 20B | + ext. calc | 6.9 | 28.3 | 34.3 | 23.6 | 42.7 |
| LaMDA 137B | Standard | 6.5 | 29.5 | 40.1 | 25.5 | 43.2 |
| LaMDA 137B | Chain of thought | 14.3 (+7.8) | 37.5 (+8.0) | 46.6 (+6.5) | 20.6 (-4.9) | 57.9 (+14.7) |
| LaMDA 137B | + ext. calc | 17.8 | 42.1 | 53.4 | 20.6 | 69.3 |
| GPT-3 175B (text-davinci-002) | Standard | 15.6 | 65.7 | 70.3 | 24.8 | 72.7 |
| GPT-3 175B (text-davinci-002) | Chain of thought | 46.9 (+31.3) | 68.9 (+3.2) | 71.3 (+1.0) | 35.8 (+11.0) | 87.1 (+14.4) |
| GPT-3 175B (text-davinci-002) | + ext. calc | 49.6 | 70.3 | 71.1 | 35.8 | 87.5 |
| Codex (code-davinci-002) | Standard | 19.7 | 69.9 | 74.0 | 29.5 | 78.7 |
| Codex (code-davinci-002) | Chain of thought | 63.1 (+43.4) | 76.4 (+6.5) | 80.4 (+6.4) | 45.3 (+15.8) | 92.6 (+13.9) |
| Codex (code-davinci-002) | + ext. calc | 65.4 | 77.0 | 80.0 | 45.3 | 93.3 |
| PaLM 540B | Standard | 17.9 | 69.4 | 72.1 | 25.2 | 79.2 |
| PaLM 540B | Chain of thought | 56.9 (+39.0) | 79.0 (+9.6) | 73.9 (+1.8) | 35.8 (+10.6) | 93.3 (+14.2) |
| PaLM 540B | + ext. calc | 58.6 | 79.8 | 72.6 | 35.8 | 93.5 |
