---
title: "[con] Mixture of experts"
type: concept
created: 2026-07-24
updated: 2026-07-28
sources:
  - 20260728-230734-local-jiang-2024-mixtral.pdf.extracted.md
---

A sparsely-activated architecture: many expert sub-networks, few active per token.

Corpus entry [[jiang-2024-mixtral-experts|Mixtral of Experts]]
(vault:20260728-230734-local-jiang-2024-mixtral.pdf.extracted.md) — the mixture-of-experts member of the
[[mistral-7b|Mistral]] line.

Sparse-MoE layer = router network + n expert FFNs, replacing the dense FFN block (vault:20260728-230734-local-jiang-2024-mixtral.pdf.extracted.md).
Gate is a softmax over the top-K logits of a linear layer; only top-K experts fire per token.

**Decoupled knobs.** n (total experts) sets sparse param count; K (active experts) sets per-token compute (vault:20260728-230734-local-jiang-2024-mixtral.pdf.extracted.md).
→ capacity rises with n without raising inference FLOPs, since K is fixed.
The trade: inference compute scales with active params, but serving memory scales with total sparse params (vault:20260728-230734-local-jiang-2024-mixtral.pdf.extracted.md).
MoE FFN ops cast as sparse matmul (Megablocks-style) for efficient single-GPU execution, or Expert Parallelism across GPUs.

**Experts may not specialise by topic.** Evidence here is one model — [[mixtral|Mixtral 8x7B]], 8 experts, top-2 ([[tab-jiang-2024-mixtral-experts-t1|architecture parameters]]) — so read it as a finding about that router, not a law of MoE (vault:20260728-230734-local-jiang-2024-mixtral.pdf.extracted.md).
In it, ArXiv, biology and philosophy text show near-identical expert-assignment distributions.
What shows instead is syntactic and positional locality — the same expert for repeated tokens such as Python `self` or indentation.
Consecutive tokens repeat expert assignment far above chance, most pronounced at deeper layers (vault:20260728-230734-local-jiang-2024-mixtral.pdf.extracted.md), quantified in [[tab-jiang-2024-mixtral-experts-t7|per-domain repetition rates by layer]].

Routing evidence, with the layer breakdown and scope limit: [[evi-moe-experts-specialise-by-syntax-not-topic]].
Quantitative anchor for the n-vs-K split: [[fact-mixtral-47b-total-13b-active]].

Contrast with dense [[transformer-architecture|transformers]].
