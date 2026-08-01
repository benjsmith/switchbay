---
title: "[con] Direct preference optimization"
type: concept
created: 2026-07-24
updated: 2026-07-28
sources:
  - 20260728-230735-local-rafailov-2023-dpo.pdf.extracted.md
  - 20260728-231916-local-wiki-rlhf.md.extracted.md
---

An alternative to the [[rlhf]] pipeline. Classical RLHF trains a separate reward
model from human ranking data, then optimizes the policy against it with an
[[wikipedia-rlhf|algorithm such as proximal policy optimization]] (vault:20260728-231916-local-wiki-rlhf.md.extracted.md).

[[rafailov-2023-direct-preference-optimization|Rafailov et al. (2023)]] is the corpus entry, titled *Direct
Preference Optimization: Your Language Model is Secretly a Reward Model* — the
claim in the title being that the separate reward model is unnecessary
(vault:20260728-230735-local-rafailov-2023-dpo.pdf.extracted.md).

**Derivation.** Bradley-Terry preference model with a KL constraint (vault:20260728-230735-local-rafailov-2023-dpo.pdf.extracted.md).

RLHF's KL-constrained reward-max objective has closed-form optimal policy πr(y|x)=πref(y|x)exp(r(x,y)/β)/Z(x). Solving for r: r(x,y)=β log(πr(y|x)/πref(y|x))+β log Z(x). Sub into Bradley-Terry preference model, Z(x) cancels — preference prob becomes fn of policy log-ratios alone, so RLHF reduces to binary cross-entropy classification loss over preference pairs, no reward model needed (vault:20260728-230735-local-rafailov-2023-dpo.pdf.extracted.md).

**Implicit reward.** πθ implicitly defines r̂θ(x,y)=β log(πθ(y|x)/πref(y|x)) — "LM is secretly a reward model." DPO gradient weights each pair by how wrong this implicit reward's ordering is, raising likelihood of preferred yw, lowering dispreferred yl (vault:20260728-230735-local-rafailov-2023-dpo.pdf.extracted.md).

**KL term.** β sets deviation from πref — prevents mode-collapse to single high-reward response, keeps policy where reward estimate trustworthy (vault:20260728-230735-local-rafailov-2023-dpo.pdf.extracted.md).

**No RL loop.** Change-of-variables drops sampling from policy during training plus separate reward-fitting stage — fully differentiable classification loss, avoids PPO-style actor-critic instability (vault:20260728-230735-local-rafailov-2023-dpo.pdf.extracted.md).

**Results.** Sentiment control (IMDb, GPT-2-large): DPO's reward/KL frontier dominates PPO, PPO-GT, unlikelihood, preferred-FT. TL;DR summarization (GPT-J): DPO 61% win rate at temp 0 vs PPO's 57%; more robust across sampling temps; generalizes better OOD to CNN/DailyMail [[tab-rafailov-2023-direct-preference-optimization-t1]]. Anthropic-HH dialogue (Pythia-2.8B): only method beating chosen completions, matches Best-of-128 (vault:20260728-230735-local-rafailov-2023-dpo.pdf.extracted.md).

**Limitations.** OOD generalization vs explicit-reward RL under-studied; unclear if DPO can self-label unlabeled prompts like PPO; reward over-optimization behavior unclear; tested only to 6B params; GPT-4 win-rate judgments sensitive to prompt wording [[tab-rafailov-2023-direct-preference-optimization-t2]] (vault:20260728-230735-local-rafailov-2023-dpo.pdf.extracted.md).

See [[aligning-llms-rlhf-to-dpo]].
