---
title: "[evi] Chain-of-thought ablations rule out extra compute as the mechanism"
type: evidence
created: 2026-07-29
updated: 2026-07-29
sources:
  - 20260728-230742-local-wei-2022-chain-of-thought.pdf.extracted.md
---

**Method.** Three variants isolate why [[chain-of-thought-prompting]] works, GSM8K.
Ablation study with three variations of chain of thought (vault:20260728-230742-local-wei-2022-chain-of-thought.pdf.extracted.md) — reported in [[tab-wei-2022-chain-of-thought-prompting-elicits-t6]].
Equation only → equation before answer, no NL steps.
Variable compute only → dot sequence (...) matching equation length, isolates token count.
Reasoning after answer → steps given only after answer, isolates knowledge access.

**Result.** Equation only prompting does not help much for GSM8K (vault:20260728-230742-local-wei-2022-chain-of-thought.pdf.extracted.md).
Helps on easier one/two-step sets where the equation is trivial to derive.
Variable-compute-only and reasoning-after-answer both perform about the same as baseline ([[tab-wei-2022-chain-of-thought-prompting-elicits-t6]]).

**Interpretation.** Gain ≠ extra computation. Gain ≠ mere exposure to reasoning-shaped tokens. Steps must precede + produce answer, not just accompany it.

**Downstream.** Anchors mechanism claims for [[chain-of-thought-prompting]] — rules out "more tokens" and "knowledge activation" as sufficient explanations. Constrains what [[tree-of-thoughts]] search can be adding on top.
