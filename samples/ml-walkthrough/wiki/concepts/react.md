---
title: "[con] ReAct"
type: concept
created: 2026-07-24
updated: 2026-07-28
sources:
  - 20260728-230744-local-yao-2022-react.pdf.extracted.md
---

Corpus entry [[yao-2022-react-synergizing-reasoning|Yao et al. (2022)]], titled for synergizing reasoning
and acting in language models — interleaving reasoning traces with actions rather
than separating them (vault:20260728-230744-local-yao-2022-react.pdf.extracted.md).

Augmented action space = env actions ∪ language (thoughts) (vault:20260728-230744-local-yao-2022-react.pdf.extracted.md). Thought = no env effect, no observation — just composes info from context, updates context for next step. Thought-action-observation loop: reasoning guides acting (decompose goals, track subgoals, handle exceptions), acting grounds reasoning in external state (vault:20260728-230744-local-yao-2022-react.pdf.extracted.md).

Vs [[chain-of-thought-prompting]]: CoT static, ungrounded — reasons only over internal reps → hallucination + error propagation compound unchecked. ReAct's [[retrieval-augmented-generation|external grounding]] (Wikipedia API) cuts hallucinated-fact failure mode to 0% vs CoT's 56% on HotpotQA; false-positive rate 6% vs 14% (vault:20260728-230744-local-yao-2022-react.pdf.extracted.md) — failure-mode breakdown in [[tab-yao-2022-react-synergizing-reasoning-t2]].

QA action space: search[entity] (first 5 sentences, else top-5 similar-entity suggestions), lookup[string] (next sentence containing string, Ctrl+F-style), finish[answer] (vault:20260728-230744-local-yao-2022-react.pdf.extracted.md).

Results (PaLM-540B): HotpotQA EM 27.4 (Act 25.7, CoT 29.4, best ReAct→CoT-SC 35.1); FEVER Acc 60.9 (Act 58.9, CoT 56.3, best CoT-SC→ReAct 64.6) [[tab-yao-2022-react-synergizing-reasoning-t1]]. ALFWorld: 71% success best-of-6 vs Act 45%, BUTLER 37% — abs +34% over imitation/RL [[tab-yao-2022-react-synergizing-reasoning-t3]]. WebShop: 40.0% SR vs Act 30.1%, IL 29.1% — abs +10% [[tab-yao-2022-react-synergizing-reasoning-t4]] (vault:20260728-230744-local-yao-2022-react.pdf.extracted.md).

Act-only (no thoughts) underperforms ReAct on all 4 tasks — reasoning needed to synthesize answers, decompose goals, track env state. Reason-only (CoT) beats ReAct on raw HotpotQA EM but loses on groundedness/trust (vault:20260728-230744-local-yao-2022-react.pdf.extracted.md).

Humans can inspect/distinguish internal-vs-external info in trace, steer agent mid-episode via thought editing (vault:20260728-230744-local-yao-2022-react.pdf.extracted.md).

The canonical shape of an [[agent-loop]].
