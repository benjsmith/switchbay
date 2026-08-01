---
title: "[tab] Table p.5 — Table 2: model sizes, architectures and finetuning compute — chung-2022-scaling-instruction-finetuned-language"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230728-local-chung-2022-flan.pdf.extracted.md"]
extracted_from: chung-2022-scaling-instruction-finetuned-language
table_index: 2
row_count: 10
is_snapshot: false
db_table: tab_chung_2022_scaling_instruction_finetuned_language_t2
extraction_sha: 771f758c1b711c2a63ca2439e80ab90751351d721632897a058c0205ba9e2a22
extraction_method: multimodal-sonnet
source_pages: ["5"]
numeric_review_done: 2026-07-30T22:30:47Z
verdict: ok
---

Extracted from [[chung-2022-scaling-instruction-finetuned-language]] (vault:20260728-230728-local-chung-2022-flan.pdf.extracted.md), source pages [5], original: vault/chung-2022-flan.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

| Params | Model | Architecture | Pre-training Objective | Pre-train FLOPs | Finetune FLOPs | % Finetune Compute |
|---|---|---|---|---|---|---|
| 80M | Flan-T5-Small | encoder-decoder | span corruption | 1.8E+20 | 2.9E+18 | 1.6% |
| 250M | Flan-T5-Base | encoder-decoder | span corruption | 6.6E+20 | 9.1E+18 | 1.4% |
| 780M | Flan-T5-Large | encoder-decoder | span corruption | 2.3E+21 | 2.4E+19 | 1.1% |
| 3B | Flan-T5-XL | encoder-decoder | span corruption | 9.0E+21 | 5.6E+19 | 0.6% |
| 11B | Flan-T5-XXL | encoder-decoder | span corruption | 3.3E+22 | 7.6E+19 | 0.2% |
| 8B | Flan-PaLM | decoder-only | causal LM | 3.7E+22 | 1.6E+20 | 0.4% |
| 62B | Flan-PaLM | decoder-only | causal LM | 2.9E+23 | 1.2E+21 | 0.4% |
| 540B | Flan-PaLM | decoder-only | causal LM | 2.5E+24 | 5.6E+21 | 0.2% |
| 62B | Flan-cont-PaLM | decoder-only | causal LM | 4.8E+23 | 1.8E+21 | 0.4% |
| 540B | Flan-U-PaLM | decoder-only | prefix LM + span corruption | 2.5E+23 | 5.6E+21 | 0.2% |
