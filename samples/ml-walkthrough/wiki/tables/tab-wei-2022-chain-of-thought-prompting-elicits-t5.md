---
title: "[tab] Table p.22 — Table 5: Standard prompting versus chain of thought prompting enables length generalization to longer inference examples on two symbolic manipulation tasks (Last Letter Concatenation and Coin Flip / state tracking). Column '2' is in-domain (2-word names / 2 potential flips); 'OOD: 3' and 'OOD: 4' are out-of-domain lengths. — wei-2022-chain-of-thought-prompting-elicits"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230742-local-wei-2022-chain-of-thought.pdf.extracted.md"]
extracted_from: wei-2022-chain-of-thought-prompting-elicits
table_index: 5
row_count: 9
is_snapshot: false
db_table: tab_wei_2022_chain_of_thought_prompting_elicits_t5
extraction_sha: 7d9f878c23b460e4566aa4ec9201b1abfb3b8faefb2b1356e411cb90fef72a12
extraction_method: multimodal-sonnet
source_pages: ["22"]
numeric_review_done: 2026-08-01T07:26:35Z
verdict: ok
---

Extracted from [[wei-2022-chain-of-thought-prompting-elicits]] (vault:20260728-230742-local-wei-2022-chain-of-thought.pdf.extracted.md), source pages [22], original: vault/wei-2022-chain-of-thought.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

| Model | Size | Last Letter Concatenation 2 / standard (%) | Last Letter Concatenation 2 / CoT (%) | Last Letter Concatenation OOD:3 / standard (%) | Last Letter Concatenation OOD:3 / CoT (%) | Last Letter Concatenation OOD:4 / standard (%) | Last Letter Concatenation OOD:4 / CoT (%) | Coin Flip 2 / standard (%) | Coin Flip 2 / CoT (%) | Coin Flip OOD:3 / standard (%) | Coin Flip OOD:3 / CoT (%) | Coin Flip OOD:4 / standard (%) | Coin Flip OOD:4 / CoT (%) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| UL2 | 20B | 0.6 | 18.8 | 0.0 | 0.2 | 0.0 | 0.0 | 70.4 | 67.1 | 51.6 | 52.2 | 48.7 | 50.4 |
| LaMDA | 420M | 0.3 | 1.6 | 0.0 | 0.0 | 0.0 | 0.0 | 52.9 | 49.6 | 50.0 | 50.5 | 49.5 | 49.1 |
| LaMDA | 2B | 2.3 | 6.0 | 0.0 | 0.0 | 0.0 | 0.0 | 54.9 | 55.3 | 47.4 | 48.7 | 49.8 | 50.2 |
| LaMDA | 8B | 1.5 | 11.5 | 0.0 | 0.0 | 0.0 | 0.0 | 52.9 | 55.5 | 48.2 | 49.6 | 51.2 | 50.6 |
| LaMDA | 68B | 4.4 | 52.0 | 0.0 | 0.8 | 0.0 | 2.5 | 56.2 | 83.2 | 50.4 | 69.1 | 50.9 | 59.6 |
| LaMDA | 137B | 5.8 | 77.5 | 0.0 | 34.4 | 0.0 | 13.5 | 49.0 | 99.6 | 50.7 | 91.0 | 49.1 | 74.5 |
| PaLM | 8B | 2.6 | 18.8 | 0.0 | 0.0 | 0.0 | 0.2 | 60.0 | 74.4 | 47.3 | 57.1 | 50.9 | 51.8 |
| PaLM | 62B | 6.8 | 85.0 | 0.0 | 59.6 | 0.0 | 13.4 | 91.4 | 96.8 | 43.9 | 91.0 | 38.3 | 72.4 |
| PaLM | 540B | 7.6 | 99.4 | 0.2 | 94.8 | 0.0 | 63.0 | 98.1 | 100.0 | 49.3 | 98.6 | 54.8 | 90.2 |
