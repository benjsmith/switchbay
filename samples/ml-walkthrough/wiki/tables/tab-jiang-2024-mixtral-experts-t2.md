---
title: "[tab] Table p.4 — Table 2: Comparison of Mixtral with Llama (and Mistral 7B) across commonsense reasoning, world knowledge, reading comprehension, math, and code benchmarks — jiang-2024-mixtral-experts"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230734-local-jiang-2024-mixtral.pdf.extracted.md"]
extracted_from: jiang-2024-mixtral-experts
table_index: 2
row_count: 6
is_snapshot: false
db_table: tab_jiang_2024_mixtral_experts_t2
extraction_sha: f8bbf0e9d979b7a8ce7be65119266545a229a85b57e077d8bd048e458bb642da
extraction_method: multimodal-sonnet
source_pages: ["4"]
numeric_review_done: 2026-08-01T07:25:42Z
verdict: ok
---

Extracted from [[jiang-2024-mixtral-experts]] (vault:20260728-230734-local-jiang-2024-mixtral.pdf.extracted.md), source pages [3], original: vault/jiang-2024-mixtral.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

> **Mistral's two papers report different scores for Mistral 7B.** This table
> (Mixtral paper) and [[tab-jiang-2023-mistral-7b-t2]] (Mistral 7B paper)
> disagree on the same model across most benchmarks — MMLU **62.5** vs 60.1,
> TriviaQA **62.5** vs 69.9, NQ **23.2** vs 28.8, HumanEval **26.2** vs 30.5,
> MBPP **50.2** vs 47.5, GSM8K **50.0** vs 52.2, Math **12.7** vs 13.1. Both
> were verified against their page images, so this is the same lab reporting its
> own model differently a few months apart — likely a re-evaluation under
> changed harness settings, though neither paper says so. Cite by paper.
> The Mixtral rows in this table are unaffected.

| Model | Active Params | MMLU | HellaS | WinoG | PIQA | Arc-e | Arc-c | NQ | TriQA | HumanE | MBPP | Math | GSM8K |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| LLaMA 2 7B | 7B | 44.4% | 77.1% | 69.5% | 77.9% | 68.7% | 43.2% | 17.5% | 56.6% | 11.6% | 26.1% | 3.9% | 16.0% |
| LLaMA 2 13B | 13B | 55.6% | 80.7% | 72.9% | 80.8% | 75.2% | 48.8% | 16.7% | 64.0% | 18.9% | 35.4% | 6.0% | 34.3% |
| LLaMA 1 33B | 33B | 56.8% | 83.7% | 76.2% | 82.2% | 79.6% | 54.4% | 24.1% | 68.5% | 25.0% | 40.9% | 8.4% | 44.1% |
| LLaMA 2 70B | 70B | 69.9% | 85.4% | 80.4% | 82.6% | 79.9% | 56.5% | 25.4% | 73.0% | 29.3% | 49.8% | 13.8% | 69.6% |
| Mistral 7B | 7B | 62.5% | 81.0% | 74.2% | 82.2% | 80.5% | 54.9% | 23.2% | 62.5% | 26.2% | 50.2% | 12.7% | 50.0% |
| Mixtral 8x7B | 13B | 70.6% | 84.4% | 77.2% | 83.6% | 83.1% | 59.7% | 30.6% | 71.5% | 40.2% | 60.7% | 28.4% | 74.4% |
