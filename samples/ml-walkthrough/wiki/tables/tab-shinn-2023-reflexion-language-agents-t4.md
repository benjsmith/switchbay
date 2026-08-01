---
title: "[tab] Table p.8 — Table 2: Overall accuracy and test generation performance for HumanEval and MBPP (Python and Rust). TP: unit tests pass, solution pass; FN: unit tests fail, solution pass; FP: unit tests pass, solution fail; TN: unit tests fail, solution fail. For Rust, HumanEval is the hardest 50 problems from HumanEval Python translated to Rust with MultiPL-E [4]. — shinn-2023-reflexion-language-agents"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230739-local-shinn-2023-reflexion.pdf.extracted.md"]
extracted_from: shinn-2023-reflexion-language-agents
table_index: 4
row_count: 4
is_snapshot: false
db_table: tab_shinn_2023_reflexion_language_agents_t4
extraction_sha: 6059b6f89fea9959bd3dab553fbb97756a3dfb1b15e3cbab2fbf3ab6664333bd
extraction_method: multimodal-sonnet
source_pages: ["8"]
numeric_review_done: 2026-08-01T07:25:09Z
verdict: ok
---

Extracted from [[shinn-2023-reflexion-language-agents]] (vault:20260728-230739-local-shinn-2023-reflexion.pdf.extracted.md), source pages [8], original: vault/shinn-2023-reflexion.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

| Benchmark + Language | Base | Reflexion | TP | FN | FP | TN |
|---|---|---|---|---|---|---|
| HumanEval (PY) | 0.80 | 0.91 | 0.99 | 0.40 | 0.01 | 0.60 |
| MBPP (PY) | 0.80 | 0.77 | 0.84 | 0.59 | 0.16 | 0.41 |
| HumanEval (RS) | 0.60 | 0.68 | 0.87 | 0.37 | 0.13 | 0.63 |
| MBPP (RS) | 0.71 | 0.75 | 0.84 | 0.51 | 0.16 | 0.49 |
