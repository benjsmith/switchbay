---
title: "[con] Chain-of-thought prompting"
type: concept
created: 2026-07-24
updated: 2026-07-28
sources:
  - 20260728-231916-local-wiki-prompt-engineering.md.extracted.md
  - 20260728-230742-local-wei-2022-chain-of-thought.pdf.extracted.md
---

Prompting technique: model produces intermediate reasoning steps before final answer.
One of [[prompt-engineering|prompt engineering]]'s techniques, [[wikipedia-prompt-engineering|alongside few-shot prompting, role assignment, multi-shot]], [[tree-of-thoughts|tree-of-thought]] prompting (vault:20260728-231916-local-wiki-prompt-engineering.md.extracted.md).

[[wei-2022-chain-of-thought-prompting-elicits|Wei et al. (2022)]]: eliciting reasoning in [[large-language-model|large language models]] via chain-of-thought prompting (vault:20260728-230742-local-wei-2022-chain-of-thought.pdf.extracted.md).

Prompt = few-shot ⟨input, chain of thought, output⟩ triples, not simple input-output pairs (vault:20260728-230742-local-wei-2022-chain-of-thought.pdf.extracted.md).
Chain of thought = intermediate natural language reasoning steps leading to final output.

**Emergent with scale.** Chain-of-thought prompting is an emergent ability of scale (vault:20260728-230742-local-wei-2022-chain-of-thought.pdf.extracted.md).
Gains appear only above ~100B parameters; smaller models produce fluent but illogical chains, scoring below standard prompting — by-size breakdown in [[tab-wei-2022-chain-of-thought-prompting-elicits-t2]].

**Results.** PaLM 540B + eight chain-of-thought exemplars → new state of the art on GSM8K, surpassing finetuned GPT-3 with a verifier (vault:20260728-230742-local-wei-2022-chain-of-thought.pdf.extracted.md) — [[tab-wei-2022-chain-of-thought-prompting-elicits-t1]].
Gains scale with problem difficulty; GSM8K performance more than doubled for the largest GPT and PaLM models.
StrategyQA 75.6% vs 69.4% prior SOTA (the paper's body text; its own appendix table reports PaLM 540B CoT at 77.8 on StrategyQA — a main-text/appendix split, not a transcription error, so cite by locus [[tab-wei-2022-chain-of-thought-prompting-elicits-t4]]); sports understanding 95.4% vs an unaided sports enthusiast's 84%; gain minimal on CSQA (vault:20260728-230742-local-wei-2022-chain-of-thought.pdf.extracted.md).
Symbolic tasks (last-letter concatenation, coin flip) reach near-100% in-domain solve rates for PaLM 540B, and generalize to inputs longer than the exemplars (vault:20260728-230742-local-wei-2022-chain-of-thought.pdf.extracted.md) — in-domain and OOD lengths in [[tab-wei-2022-chain-of-thought-prompting-elicits-t5]].

**Ablations rule out trivial explanations.** Equation-only prompting does not help much on GSM8K (vault:20260728-230742-local-wei-2022-chain-of-thought.pdf.extracted.md).
Variable-compute-only prompting (dots matching equation length) and chain-of-thought-after-answer both perform about the same as baseline — so the gain is not extra compute or mere exposure to the reasoning tokens ([[tab-wei-2022-chain-of-thought-prompting-elicits-t6]]).

Ablation detail — the three variants and what each rules out: [[evi-cot-ablations-rule-out-extra-compute]].
Training-time counterpart: [[evi-instruction-tuning-without-cot-degrades-reasoning]].

Extended by [[tree-of-thoughts]]; used as planning step inside [[agent-loop]].
