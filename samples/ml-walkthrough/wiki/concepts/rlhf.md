---
title: "[con] RLHF"
type: concept
created: 2026-07-24
updated: 2026-07-28
sources:
  - 20260728-231916-local-wiki-rlhf.md.extracted.md
---

Reinforcement learning from human feedback: aligning an agent with human
preferences by [[wikipedia-rlhf|training a reward model to represent those preferences]], then using
it to train other models by reinforcement learning (vault:20260728-231916-local-wiki-rlhf.md.extracted.md).

**Why the indirection.** In classical RL the agent optimizes a policy against a
reward signal derived from task performance. Explicitly defining a reward function
that accurately approximates human preferences is challenging, so RLHF trains a
reward model directly from feedback instead (vault:20260728-231916-local-wiki-rlhf.md.extracted.md).

**Pipeline.** The reward model is first trained supervised, to predict whether a
response to a prompt is good or bad, from ranking data collected from human
annotators. It then serves as the reward function improving the agent's policy
through an optimization algorithm such as proximal policy optimization
(vault:20260728-231916-local-wiki-rlhf.md.extracted.md).

Applied to NLP tasks including summarization and conversational agents, to computer
vision tasks such as text-to-image models, and to video-game bots
(vault:20260728-231916-local-wiki-rlhf.md.extracted.md).

**Limits.** Effective, but constrained by how preference data is collected. RLHF
does not need massive data to improve performance, yet sourcing high-quality
preference data remains expensive; data not carefully collected from a
representative sample yields unwanted biases (vault:20260728-231916-local-wiki-rlhf.md.extracted.md).

Alternatives in this corpus: [[direct-preference-optimization]],
[[constitutional-ai]]. Analysis: [[aligning-llms-rlhf-to-dpo]].
