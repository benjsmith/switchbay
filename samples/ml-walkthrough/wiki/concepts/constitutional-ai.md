---
title: "[con] Constitutional AI"
type: concept
created: 2026-07-24
updated: 2026-07-28
sources:
  - 20260728-230724-local-bai-2022-constitutional-ai.pdf.extracted.md
  - 20260728-231916-local-wiki-rlhf.md.extracted.md
---

[[bai-2022-constitutional-ai-harmlessness|Bai et al. (2022)]], titled *Constitutional AI:
Harmlessness from AI Feedback* (vault:20260728-230724-local-bai-2022-constitutional-ai.pdf.extracted.md) — feedback
sourced from a model rather than from human annotators.

That targets a stated limit of [[rlhf]]: sourcing high-quality human preference
data is expensive, and [[wikipedia-rlhf|data not collected from a representative sample]] yields
unwanted biases (vault:20260728-231916-local-wiki-rlhf.md.extracted.md).

**Method.** Self-critique and revision, then RL from AI feedback (vault:20260728-230724-local-bai-2022-constitutional-ai.pdf.extracted.md).

Two stages. SL stage: helpful-only RLHF model samples response to harmful prompt → self-critiques against principle drawn from 16 hand-written rules ("constitution") → revises → repeats, cycling principles → finetunes pretrained LM on final revisions = SL-CAI (vault:20260728-230724-local-bai-2022-constitutional-ai.pdf.extracted.md). RL stage = "RLAIF": SL-CAI generates response pairs → feedback model picks less-harmful option per constitutional principle, multiple-choice format → labels distilled into preference model (hybrid: human labels for helpfulness, AI labels for harmlessness) → RL-finetune against that PM, rest of pipeline matches standard RLHF (vault:20260728-230724-local-bai-2022-constitutional-ai.pdf.extracted.md). [[chain-of-thought-prompting|Chain-of-thought]] during critique/RL labeling improves accuracy + transparency (vault:20260728-230724-local-bai-2022-constitutional-ai.pdf.extracted.md).

**Results.** RL-CAI preferred by crowdworkers over HH-RLHF (human-labeled harmlessness) at matched helpfulness — Pareto improvement — while staying non-evasive, explaining objections rather than refusing (vault:20260728-230724-local-bai-2022-constitutional-ai.pdf.extracted.md). SL-CAI alone trades off: less helpful than both RL models, more harmless than helpful-only baseline (vault:20260728-230724-local-bai-2022-constitutional-ai.pdf.extracted.md).
