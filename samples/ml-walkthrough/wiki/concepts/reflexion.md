---
title: "[con] Reflexion"
type: concept
created: 2026-07-24
updated: 2026-07-28
sources:
  - 20260728-230739-local-shinn-2023-reflexion.pdf.extracted.md
---

Corpus entry [[shinn-2023-reflexion-language-agents|Shinn et al. (2023)]], titled for language
agents that learn via verbal reinforcement rather than weight updates
(vault:20260728-230739-local-shinn-2023-reflexion.pdf.extracted.md).

**Three models.** Actor, Evaluator, Self-Reflection (vault:20260728-230739-local-shinn-2023-reflexion.pdf.extracted.md).

Actor (Ma) generates text/actions from state ([[chain-of-thought-prompting|CoT]] or [[react|ReAct policies]]); Evaluator (Me) scores trajectory τ → reward r = Me(τ); Self-Reflection (Msr) turns {τ, r} into verbal feedback srt, appended to memory (vault:20260728-230739-local-shinn-2023-reflexion.pdf.extracted.md).

**Memory.** Episodic buffer mem holds srt across trials — long-term memory, paired with short-term trajectory history; capped at Ω=1-3 stored experiences for context-window limits (vault:20260728-230739-local-shinn-2023-reflexion.pdf.extracted.md).

**Why verbal > gradient.** Self-reflective text acts as "semantic" gradient — concrete improvement direction — without finetuning: lightweight, interpretable, avoids credit assignment over scalar/vector rewards (vault:20260728-230739-local-shinn-2023-reflexion.pdf.extracted.md).

**Reward signals.** Exact-match grading (HotPotQA reasoning), hand-written heuristics or LLM self-eval (ALFWorld decision-making), self-generated unit tests (programming) (vault:20260728-230739-local-shinn-2023-reflexion.pdf.extracted.md).

**Results.** HumanEval pass@1 91% vs GPT-4's 80% [[tab-shinn-2023-reflexion-language-agents-t3]]; ALFWorld 130/134 tasks solved, +22% absolute over 12 trials; HotPotQA +20%; LeetcodeHard 15.0% vs GPT-4 7.5% [[tab-shinn-2023-reflexion-language-agents-t3]] (vault:20260728-230739-local-shinn-2023-reflexion.pdf.extracted.md).

**Limitations.** Language-based policy optimization can still hit local minima; long-term memory capped to sliding window; fails on WebShop — self-reflections not diverse/exploratory enough for tasks needing creative search (vault:20260728-230739-local-shinn-2023-reflexion.pdf.extracted.md).

Where it fails, and why: [[evi-reflexion-fails-without-exploratory-diversity]].

A self-correction layer over the [[agent-loop]].
