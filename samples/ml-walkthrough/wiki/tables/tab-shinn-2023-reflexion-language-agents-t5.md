---
title: "[tab] Table p.8 — Table 3: Pass@1 accuracy for various compromised approaches (ablation) on the Reflexion approach using GPT-4 as the base model on HumanEval Rust - 50 hardest problems — shinn-2023-reflexion-language-agents"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230739-local-shinn-2023-reflexion.pdf.extracted.md"]
extracted_from: shinn-2023-reflexion-language-agents
table_index: 5
row_count: 4
is_snapshot: false
db_table: tab_shinn_2023_reflexion_language_agents_t5
extraction_sha: 6059b6f89fea9959bd3dab553fbb97756a3dfb1b15e3cbab2fbf3ab6664333bd
extraction_method: multimodal-sonnet
source_pages: ["8"]
numeric_review_done: 2026-08-01T07:25:12Z
verdict: ok
---

Extracted from [[shinn-2023-reflexion-language-agents]] (vault:20260728-230739-local-shinn-2023-reflexion.pdf.extracted.md), source pages [8], original: vault/shinn-2023-reflexion.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

| Approach | Test Generation | Self-reflection | Pass@1 (Acc) |
|---|---|---|---|
| Base model | False | False | 0.60 |
| Test generation omission | False | True | 0.52 |
| Self-reflection omission | True | False | 0.60 |
| Reflexion | True | True | 0.68 |
