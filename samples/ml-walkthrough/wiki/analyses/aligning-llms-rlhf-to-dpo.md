---
title: "[ana] Aligning LLMs: from RLHF toward its alternatives"
type: analysis
created: 2026-07-24
updated: 2026-07-29
sources:
  - 20260728-231916-local-wiki-rlhf.md.extracted.md
  - 20260728-230735-local-rafailov-2023-dpo.pdf.extracted.md
  - 20260728-230724-local-bai-2022-constitutional-ai.pdf.extracted.md
  - 20260728-230728-local-chung-2022-flan.pdf.extracted.md
  - 20260728-231916-local-wiki-large-language-model.md.extracted.md
---

# Aligning LLMs: from RLHF toward its alternatives

A pre-trained [[large-language-model|language model]] predicts the next word. It
does not, on its own, follow instructions or decline harmful requests. Three
distinct interventions in this corpus close that gap, and they are not
interchangeable.

## Instruction tuning comes first

Generative pre-trained transformers are pre-trained to predict the next word, then
"[[wikipedia-large-language-model|often fine-tuned to follow instructions and to behave as assistants]]"
(vault:20260728-231916-local-wiki-large-language-model.md.extracted.md). That is [[instruction-tuning]], and
[[chung-2022-scaling-instruction-finetuned-language|Chung et al.]] is the corpus entry on scaling it
(vault:20260728-230728-local-chung-2022-flan.pdf.extracted.md). It teaches format and compliance — not preference.

The paper's focus: scaling the number of tasks, the model size, and chain-of-thought data (vault:20260728-230728-local-chung-2022-flan.pdf.extracted.md).
That scaling has a ceiling, and the ceiling is the interesting part. Instruction tuning without any chain-of-thought examples in the mixture degrades reasoning below the no-finetuning baseline it started from (vault:20260728-230728-local-chung-2022-flan.pdf.extracted.md).
Adding back just nine [[chain-of-thought-prompting|chain-of-thought]] datasets, a small slice of the 1,836-task mixture [[tab-chung-2022-scaling-instruction-finetuned-language-t3]], restores and then improves reasoning on every evaluation (vault:20260728-230728-local-chung-2022-flan.pdf.extracted.md).
Scaling tasks and model size both help on their own terms, but the CoT result says something sharper: instruction tuning transmits whatever prompting paradigm its data contains, and no more. It cannot manufacture a reasoning capability the mixture never demonstrated.

## RLHF adds preference, and a bottleneck

[[rlhf|RLHF]] exists because explicitly defining a reward function that accurately
approximates human preferences is challenging. Instead a reward model is trained
directly from feedback: supervised first, on ranking data from human annotators, to
predict whether a response is good or bad; then used as the reward function to
improve the policy through an algorithm such as proximal policy optimization
(vault:20260728-231916-local-wiki-rlhf.md.extracted.md).

It works, and it is bounded by its data. RLHF does not require massive amounts of
data to improve performance, but sourcing high-quality preference data is still an
expensive process, and data not carefully collected from a representative sample
yields a model with unwanted biases (vault:20260728-231916-local-wiki-rlhf.md.extracted.md). See
[[evi-preference-data-is-the-bottleneck]].

## Two ways out

The corpus carries one attack on each half of that bottleneck, and — read
together — they turn out to be opposite bets on where the real expense lives.

[[constitutional-ai|Constitutional AI]] changes the *source* of the feedback —
[[bai-2022-constitutional-ai-harmlessness|titled for harmlessness from AI feedback]] (vault:20260728-230724-local-bai-2022-constitutional-ai.pdf.extracted.md),
which is to say feedback that does not require the expensive human annotation pass.

The process involves both a supervised learning phase and a reinforcement learning phase (vault:20260728-230724-local-bai-2022-constitutional-ai.pdf.extracted.md).
In the supervised phase the model samples a response to a prompt built to elicit harm, critiques it against a principle drawn from a short constitution, revises it, and repeats — 16 hand-written principles in total, drawn at random at each step (vault:20260728-230724-local-bai-2022-constitutional-ai.pdf.extracted.md).
In the RL phase the finetuned model generates pairs of responses, and a feedback model rather than a human picks the less harmful one as a multiple-choice judgment (vault:20260728-230724-local-bai-2022-constitutional-ai.pdf.extracted.md).

Here is the asymmetry most summaries drop: a hybrid human/AI preference model — human labels for helpfulness, AI labels only for harmlessness (vault:20260728-230724-local-bai-2022-constitutional-ai.pdf.extracted.md).
Constitutional AI does not remove human labeling from the pipeline; it removes human labeling from one half of it. The authors are explicit that this was a choice, not a limit of the method — they could have mixed human and AI labels for both dimensions, and used AI-only labels for harmlessness specifically to demonstrate the technique (vault:20260728-230724-local-bai-2022-constitutional-ai.pdf.extracted.md).
Helpfulness still runs on the same expensive human annotation pass that bounds ordinary RLHF; only harmlessness got cheaper.
The payoff is real: crowdworkers preferred the resulting model over a human-labeled harmlessness baseline at matched helpfulness, a Pareto improvement, and unlike that baseline it stayed non-evasive rather than refusing to engage (vault:20260728-230724-local-bai-2022-constitutional-ai.pdf.extracted.md).

[[direct-preference-optimization|DPO]] changes the *machinery* that consumes it.
Its title — *[[rafailov-2023-direct-preference-optimization|Your Language Model is Secretly a Reward Model]]*
(vault:20260728-230735-local-rafailov-2023-dpo.pdf.extracted.md) — asserts that the separately-trained reward model at
the centre of the RLHF pipeline is not needed at all.

A new parameterization of the reward model enables the optimal policy in closed form (vault:20260728-230735-local-rafailov-2023-dpo.pdf.extracted.md).
Substituting that closed form into the Bradley-Terry preference model cancels the partition function, leaving preference probability a function of the policy's own log-ratios against a reference model and nothing else (vault:20260728-230735-local-rafailov-2023-dpo.pdf.extracted.md).
What that eliminates: fitting a separate reward model, and sampling from the policy during training — together, the source of the actor-critic instability that troubles PPO-based RLHF (vault:20260728-230735-local-rafailov-2023-dpo.pdf.extracted.md).
What it costs is worth taking as seriously as the wins: by the paper's own account, out-of-distribution generalization against an explicit reward function is under-studied, it is unclear whether a DPO policy can self-label unlabeled prompts the way PPO-trained policies can, reward over-optimization behavior in this setting is unclear, and every result is on models no larger than 6B parameters (vault:20260728-230735-local-rafailov-2023-dpo.pdf.extracted.md).
The reward model DPO discards was also a checkable, reusable object sitting between the preference data and the policy. DPO trades that inspection point for simplicity, and the paper is candid that whether the trade holds up past 6B parameters and outside the training distribution is still open.

Put side by side, Constitutional AI and DPO answer the same question — RLHF's preference-data bottleneck is expensive, so what gets cut? — in opposite ways. Constitutional AI keeps the separate preference model and the RL loop, and spends its engineering making the *input* to that model cheaper: self-critique, revision, a written constitution standing in for a slice of the human annotation. DPO keeps the human-labeled preference data and spends its engineering removing the preference model and the RL loop that consumes it. This corpus dates Constitutional AI to 2022 (vault:20260728-230724-local-bai-2022-constitutional-ai.pdf.extracted.md) and DPO to 2023 (vault:20260728-230735-local-rafailov-2023-dpo.pdf.extracted.md) — opposite bets on the same cost problem, within a year of each other. Neither paper addresses the other, and nothing in this corpus stages them head-to-head; whether Constitutional AI's AI-generated preferences could drive DPO's classification loss instead of a trained preference model — dropping the reward model on both sides of the bottleneck at once — is a combination no source here tries.

## Open questions and next steps

- No source in this corpus runs Constitutional AI and DPO against each other or combines them. Whether AI-generated preference labels can drive DPO's closed-form objective instead of a trained preference model is open.
- DPO's own limitations section names out-of-distribution generalization, self-labeling of unlabeled prompts, and reward over-optimization as unresolved (vault:20260728-230735-local-rafailov-2023-dpo.pdf.extracted.md) — worth checking whether later corpus entries settle any of these.
- Constitutional AI's 16 principles were chosen "in an ad hoc manner for research purposes," by the authors' own description (vault:20260728-230724-local-bai-2022-constitutional-ai.pdf.extracted.md) — what a deliberately designed constitution would change is untested here.
- Flan's without-CoT degradation raises the question of whether other latent capabilities quietly regress whenever instruction tuning omits their prompting paradigm from the mix — the corpus only tests this for chain-of-thought reasoning.

## Reading this critically

The RLHF description drew on [[wikipedia-rlhf|an encyclopedia extract]] with real prose from the start (vault:20260728-231916-local-wiki-rlhf.md.extracted.md) — that part was always solid. The DPO and Constitutional AI claims used to rest on paper titles alone, because the vault held attribution records and PDFs rather than extracted text. That gap is closed: the derivation, the reward-model-elimination argument, DPO's own stated limitations, Constitutional AI's hybrid-PM asymmetry, and Flan's CoT-ablation finding are now grounded in the papers' own extracted text, not proxied through titles.

What remains this page's synthesis, not a citation: framing Constitutional AI and DPO as opposite responses to the same cost problem is a reading of the two papers side by side, not a claim either paper makes about the other — nothing in this corpus stages that comparison, and no source here runs the two methods head-to-head or checks either paper's self-reported results independently. That is the honest gap now: not missing detail, but missing adjudication between sources that don't reference each other.
