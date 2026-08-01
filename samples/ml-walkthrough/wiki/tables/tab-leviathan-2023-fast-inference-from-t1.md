---
title: "[tab] Table p.6 — Table 1: Chinchilla performance and speed on XSum and HumanEval with naive (ArS) and speculative (SpS) sampling at batch size 1 and K = 4. XSum used nucleus parameter p = 0.8; HumanEval used p = 0.95 and temperature 0.8. — leviathan-2023-fast-inference-from"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230735-local-leviathan-2023-speculative-sampling.pdf.extracted.md"]
extracted_from: leviathan-2023-fast-inference-from
table_index: 1
row_count: 6
is_snapshot: false
db_table: tab_leviathan_2023_fast_inference_from_t1
extraction_sha: ffa03c6ae46f3122570bacd7da358cae8659b6421162bbc25088622fd4889c37
extraction_method: multimodal-sonnet
source_pages: ["6"]
numeric_review_done: 2026-08-01T07:25:53Z
verdict: ok
---

Extracted from [[leviathan-2023-fast-inference-from]] (vault:20260728-230735-local-leviathan-2023-speculative-sampling.pdf.extracted.md), source pages [6], original: vault/leviathan-2023-speculative-sampling.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

| Sampling Method | Benchmark | Result | Mean Token Time | Speed Up |
|---|---|---|---|---|
| ArS (Nucleus) | XSum (ROUGE-2) | 0.112 | 14.1ms/Token | 1× |
| SpS (Nucleus) | XSum (ROUGE-2) | 0.114 | 7.52ms/Token | 1.92× |
| ArS (Greedy) | XSum (ROUGE-2) | 0.157 | 14.1ms/Token | 1× |
| SpS (Greedy) | XSum (ROUGE-2) | 0.156 | 7.00ms/Token | 2.01× |
| ArS (Nucleus) | HumanEval (100 Shot) | 45.1% | 14.1ms/Token | 1× |
| SpS (Nucleus) | HumanEval (100 Shot) | 47.0% | 5.73ms/Token | 2.46× |
