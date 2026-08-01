---
title: "[tab] Table p.6 — Table 2: Types of success and failure modes of ReAct and CoT on HotpotQA, as well as their percentages in randomly selected examples studied by human. — yao-2022-react-synergizing-reasoning"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230744-local-yao-2022-react.pdf.extracted.md"]
extracted_from: yao-2022-react-synergizing-reasoning
table_index: 2
row_count: 6
is_snapshot: false
db_table: tab_yao_2022_react_synergizing_reasoning_t2
extraction_sha: f285b0971ae4a790e402fb93966bed3adde2cf0a04977d08b2b40d6ab0cace69
extraction_method: multimodal-sonnet
source_pages: ["6"]
numeric_review_done: 2026-08-01T07:25:20Z
verdict: ok
---

Extracted from [[yao-2022-react-synergizing-reasoning]] (vault:20260728-230744-local-yao-2022-react.pdf.extracted.md), source pages [6], original: vault/yao-2022-react.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

| Category | Type | Definition | ReAct | CoT |
|---|---|---|---|---|
| Success | True positive | Correct reasoning trace and facts | 94% | 86% |
| Success | False positive | Hallucinated reasoning trace or facts | 6% | 14% |
| Failure | Reasoning error | Wrong reasoning trace (including failing to recover from repetitive steps) | 47% | 16% |
| Failure | Search result error | Search return empty or does not contain useful information | 23% | - |
| Failure | Hallucination | Hallucinated reasoning trace or facts | 0% | 56% |
| Failure | Label ambiguity | Right prediction but did not match the label precisely | 29% | 28% |
