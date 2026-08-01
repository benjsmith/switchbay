---
title: "[con] Instruction tuning"
type: concept
created: 2026-07-24
updated: 2026-07-28
sources:
  - 20260728-231916-local-wiki-large-language-model.md.extracted.md
  - 20260728-230728-local-chung-2022-flan.pdf.extracted.md
---

Fine-tuning a pre-trained [[large-language-model|LLM]] to follow instructions and
behave as an assistant. Generative pre-trained transformers are pre-trained to
[[wikipedia-large-language-model|predict the next word, then often fine-tuned this way]]
(vault:20260728-231916-local-wiki-large-language-model.md.extracted.md).

[[chung-2022-scaling-instruction-finetuned-language|Chung et al. (2022)]] is the corpus entry on scaling
instruction-finetuned language models (vault:20260728-230728-local-chung-2022-flan.pdf.extracted.md).

Instruction finetuning scales with the number of tasks and the model size (vault:20260728-230728-local-chung-2022-flan.pdf.extracted.md).
Third axis studied: whether [[chain-of-thought-prompting|chain-of-thought]] data is in the finetuning mix.
Flan collection: 1,836 tasks, 473 datasets, 146 task categories, 4 mixtures — Muffin, T0-SF, NIV2, CoT.

**CoT data is load-bearing.** Finetuning without CoT data degrades reasoning vs no finetuning at all (vault:20260728-230728-local-chung-2022-flan.pdf.extracted.md).
Adding just 9 CoT datasets to the mix restores and then boosts reasoning on every eval.

**Results.** Flan-PaLM 540B beats PaLM 540B by +9.4% average [[tab-chung-2022-scaling-instruction-finetuned-language-t3]] (vault:20260728-230728-local-chung-2022-flan.pdf.extracted.md).
Flan-PaLM 540B reaches 75.2% 5-shot MMLU via CoT + self-consistency, a new SOTA [[tab-chung-2022-scaling-instruction-finetuned-language-t4]].
Flan-T5-XL at just 3B params hits 52.4% MMLU [[tab-chung-2022-scaling-instruction-finetuned-language-t5]], beating GPT-3 175B's 43.9% [[tab-chung-2022-scaling-instruction-finetuned-language-t1]] (vault:20260728-230728-local-chung-2022-flan.pdf.extracted.md).

Recipe generalizes across model families — PaLM, T5, U-PaLM — spanning sizes, architectures, pretraining objectives [[tab-chung-2022-scaling-instruction-finetuned-language-t5]] (vault:20260728-230728-local-chung-2022-flan.pdf.extracted.md).

Method + stratification behind the CoT result: [[evi-instruction-tuning-without-cot-degrades-reasoning]].

Adjacent: [[rlhf]] and [[direct-preference-optimization]] tune for preference
rather than instruction-following.
