---
title: "[tab] Table p.4 — Table 2: Comparison of Mistral 7B with Llama 2 7B/13B and Code-Llama 7B across commonsense reasoning, world knowledge, reading comprehension, math, and code benchmarks — jiang-2023-mistral-7b"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230734-local-jiang-2023-mistral-7b.pdf.extracted.md"]
extracted_from: jiang-2023-mistral-7b
table_index: 2
row_count: 4
is_snapshot: false
db_table: tab_jiang_2023_mistral_7b_t2
extraction_sha: dfbac4e7035344b305c947481f2e7e8a02f7a24a563917eb6e47f6591d14c5ae
extraction_method: multimodal-sonnet
source_pages: ["4"]
numeric_review_done: 2026-08-01T07:25:32Z
verdict: ok
---

Extracted from [[jiang-2023-mistral-7b]] (vault:20260728-230734-local-jiang-2023-mistral-7b.pdf.extracted.md), source pages [4], original: vault/jiang-2023-mistral-7b.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

> **Mistral's two papers report different scores for Mistral 7B.** This table
> (Mistral 7B paper) and [[tab-jiang-2024-mixtral-experts-t2]] (Mixtral paper)
> disagree on the same model across most benchmarks — MMLU **60.1** vs 62.5,
> TriviaQA **69.9** vs 62.5, NQ **28.8** vs 23.2, HumanEval **30.5** vs 26.2,
> MBPP **47.5** vs 50.2, GSM8K **52.2** vs 50.0, Math **13.1** vs 12.7. Both
> were verified against their page images, so this is the same lab reporting its
> own model differently a few months apart — likely a re-evaluation under
> changed harness settings, though neither paper says so. Cite by paper.

| Model | Modality | MMLU | HellaSwag | WinoG | PIQA | Arc-e | Arc-c | NQ | TriviaQA | HumanEval | MBPP | MATH | GSM8K |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| LLaMA 2 7B | Pretrained | 44.4% | 77.1% | 69.5% | 77.9% | 68.7% | 43.2% | 24.7% | 63.8% | 11.6% | 26.1% | 3.9% | 16.0% |
| LLaMA 2 13B | Pretrained | 55.6% | 80.7% | 72.9% | 80.8% | 75.2% | 48.8% | 29.0% | 69.6% | 18.9% | 35.4% | 6.0% | 34.3% |
| Code-Llama 7B | Finetuned | 36.9% | 62.9% | 62.3% | 72.8% | 59.4% | 34.5% | 11.0% | 34.9% | 31.1% | 52.5% | 5.2% | 20.8% |
| Mistral 7B | Pretrained | 60.1% | 81.3% | 75.3% | 83.0% | 80.0% | 55.5% | 28.8% | 69.9% | 30.5% | 47.5% | 13.1% | 52.2% |
