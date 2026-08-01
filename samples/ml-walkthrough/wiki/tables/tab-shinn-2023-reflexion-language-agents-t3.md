---
title: "[tab] Table p.7 — Table 1: Pass@1 accuracy for various model-strategy-language combinations (base strategy = single code generation sample; all instruction-based models use zero-shot code generation) — shinn-2023-reflexion-language-agents"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230739-local-shinn-2023-reflexion.pdf.extracted.md"]
extracted_from: shinn-2023-reflexion-language-agents
table_index: 3
row_count: 5
is_snapshot: false
db_table: tab_shinn_2023_reflexion_language_agents_t3
extraction_sha: 6059b6f89fea9959bd3dab553fbb97756a3dfb1b15e3cbab2fbf3ab6664333bd
extraction_method: multimodal-sonnet
source_pages: ["7"]
numeric_review_done: 2026-08-01T07:25:07Z
verdict: ok
---

Extracted from [[shinn-2023-reflexion-language-agents]] (vault:20260728-230739-local-shinn-2023-reflexion.pdf.extracted.md), source pages [7], original: vault/shinn-2023-reflexion.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

| Benchmark + Language | Prev SOTA Pass@1 | SOTA Pass@1 | Reflexion Pass@1 |
|---|---|---|---|
| HumanEval (PY) | 65.8 (CodeT [5] + GPT-3.5) | 80.1 (GPT-4) | 91.0 |
| HumanEval (RS) | – | 60.0 (GPT-4) | 68.0 |
| MBPP (PY) | 67.7 (CodeT [5] + Codex [6]) | 80.1 (GPT-4) | 77.1 |
| MBPP (RS) | – | 70.9 (GPT-4) | 75.4 |
| Leetcode Hard (PY) | – | 7.5 (GPT-4) | 15.0 |
