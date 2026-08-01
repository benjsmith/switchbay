---
title: "[src] QLoRA: Efficient Finetuning of Quantized LLMs — dettmers, 2023"
type: source
created: 2023
updated: 2026-04-12
sources: [20260728-230730-local-dettmers-2023-qlora.pdf.extracted.md]
vault_sha256: b0e7e80be8372fb0925094034ca6aa45a5a42a9f82dfdb632bf891cccd7f374c
---

QL ORA: Efficient Finetuning of Quantized LLMs Tim Dettmers∗ Artidoro Pagnoni∗ Ari Holtzman Luke Zettlemoyer University of Washington {dettmers,artidoro,ahai,lsz}@cs.washington.edu Abstract We present QL ORA, an efficient finetuning approach that reduces memory us- age enough to finetune a 65B parameter model on a single 48GB GPU while preserving full 16-bit finetuning task performance. QL ORA backpropagates gradi- (vault:20260728-230730-local-dettmers-2023-qlora.pdf.extracted.md)

<!-- extracted-tables -->
## Extracted tables (13)

- [[tab-dettmers-2023-qlora-efficient-finetuning-t1]] — Table p.2 — Table 1: Elo ratings, Vicuna benchmark tournament
- [[tab-dettmers-2023-qlora-efficient-finetuning-t10]] — Table p.24 — Table 10: MMLU results, train on source+target vs target-only ablation
- [[tab-dettmers-2023-qlora-efficient-finetuning-t11]] — Table p.24 — Table 11: MMLU accuracy vs dataset size and finetuning epochs
- [[tab-dettmers-2023-qlora-efficient-finetuning-t12]] — Table p.25 — Table 12: Aggregated pairwise GPT-4 judgments between systems
- [[tab-dettmers-2023-qlora-efficient-finetuning-t13]] — Table p.26 — Table 13: Complete model ordering from pairwise GPT-4 judgments
- [[tab-dettmers-2023-qlora-efficient-finetuning-t2]] — Table p.7 — Table 2: Pile Common Crawl mean perplexity by 4-bit data type
- [[tab-dettmers-2023-qlora-efficient-finetuning-t3]] — Table p.7 — Table 3: GLUE / Super-NaturalInstructions accuracy across data types
- [[tab-dettmers-2023-qlora-efficient-finetuning-t4]] — Table p.8 — Table 4: Mean 5-shot MMLU accuracy, LLaMA 7B–65B × Alpaca/FLAN v2 × data type
- [[tab-dettmers-2023-qlora-efficient-finetuning-t5]] — Table p.8 — Table 5: MMLU 5-shot test results by finetuning dataset and LLaMA size
- [[tab-dettmers-2023-qlora-efficient-finetuning-t6]] — Table p.10 — Table 6: Zero-shot Vicuna benchmark scores vs ChatGPT
- [[tab-dettmers-2023-qlora-efficient-finetuning-t7]] — Table p.11 — Table 7: Elo rating tournament, human raters vs GPT-4 judges
- [[tab-dettmers-2023-qlora-efficient-finetuning-t8]] — Table p.15 — Table 8: CrowS bias evaluation scores
- [[tab-dettmers-2023-qlora-efficient-finetuning-t9]] — Table p.23 — Table 9: QLoRA finetuning training hyperparameters
<!-- /extracted-tables -->
