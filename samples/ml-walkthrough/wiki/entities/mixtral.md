---
title: "[ent] Mixtral"
type: entity
created: 2026-07-24
updated: 2026-07-28
sources:
  - 20260728-230734-local-jiang-2024-mixtral.pdf.extracted.md
---

[[mixture-of-experts|Mixture-of-experts]] model in the [[mistral-7b|Mistral]] line.
Corpus entry [[jiang-2024-mixtral-experts|Jiang et al. (2024)]], titled *Mixtral of Experts*
(vault:20260728-230734-local-jiang-2024-mixtral.pdf.extracted.md).

Sparse mixture of experts: router selects two experts per token (vault:20260728-230734-local-jiang-2024-mixtral.pdf.extracted.md).

Mixtral 8x7B: decoder-only, same base arch as Mistral 7B, but each layer replaces FFN w/ 8 expert blocks; router picks top-2 per token ([[tab-jiang-2024-mixtral-experts-t1|architecture parameters]]) via softmax over top-K gate logits, outputs combined additively (vault:20260728-230734-local-jiang-2024-mixtral.pdf.extracted.md). 47B total params, only 13B active per token → inference cost ~Mistral-7B-class despite 47B capacity; memory cost scales w/ 47B, still < Llama 2 70B (vault:20260728-230734-local-jiang-2024-mixtral.pdf.extracted.md). Context 32k tokens; 100% passkey retrieval regardless of position/length (vault:20260728-230734-local-jiang-2024-mixtral.pdf.extracted.md).

Matches/beats Llama 2 70B and GPT-3.5 on most benchmarks w/ 5x fewer active params: MMLU 70.6% vs 69.9%/70.0%, MBPP 60.7% vs 49.8%/52.2%, GSM8K 58.4% vs 53.6%/57.1% ([[tab-jiang-2024-mixtral-experts-t3|the three-way comparison table]]). Vastly ahead of Llama 2 70B on math, code, multilingual (vault:20260728-230734-local-jiang-2024-mixtral.pdf.extracted.md).

[[instruction-tuning|Instruct variant]] (SFT + [[direct-preference-optimization|DPO]]): MT-Bench 8.30, beats GPT-3.5 Turbo, Claude-2.1, Gemini Pro, Llama 2 70B-chat on human evals; LMSys Arena Elo 1121 ([[tab-jiang-2024-mixtral-experts-t6|Arena leaderboard snapshot]]), best open-weights model as of Dec 2023 (vault:20260728-230734-local-jiang-2024-mixtral.pdf.extracted.md).

Routing analysis: no clear topic-based expert specialization — math/code/philosophy/biology tokens spread ~uniformly across experts. Router instead shows syntactic/positional locality: consecutive tokens often share an expert, most pronounced at layers 15 and 31 (vault:20260728-230734-local-jiang-2024-mixtral.pdf.extracted.md), measured in [[tab-jiang-2024-mixtral-experts-t7|per-domain repetition rates by layer]].

Base + Instruct both released under Apache 2.0 (vault:20260728-230734-local-jiang-2024-mixtral.pdf.extracted.md).

Anchors: [[fact-mixtral-47b-total-13b-active]], [[evi-moe-experts-specialise-by-syntax-not-topic]].

Part of [[open-weight-model-wave]].
