---
title: "[src] Mamba: Linear-Time Sequence Modeling with Selective State Spaces — gu, 2023"
type: source
created: 2023
updated: 2026-04-12
sources: [20260728-230732-local-gu-2023-mamba.pdf.extracted.md]
vault_sha256: e3e27a0a3480a5c6cf965d44b34c5d3093956727e7318a6844c7a9a2b15e5b10
---

Mamba: Linear-Time Sequence Modeling with Selective State Spaces Albert Gu∗1 and Tri Dao∗2 1 Machine Learning Department, Carnegie Mellon University 2 Department of Computer Science, Princeton University agu@cs.cmu.edu, tri@tridao.me Abstract Foundation models, now powering most of the exciting applications in deep learning, are almost universally based on the Transformer architecture and its core attention module. Many subquadratic-time architectures such as linear attention, (vault:20260728-230732-local-gu-2023-mamba.pdf.extracted.md)

<!-- extracted-tables -->
## Extracted tables (16)

- [[tab-gu-2023-mamba-linear-time-sequence-t1]] — Table p.11 — Table 1: Selective Copying accuracy by architecture/layer
- [[tab-gu-2023-mamba-linear-time-sequence-t10]] — Table p.17 — Table 10 (Bottom): Ablations — SSM state dimension, selective B and C
- [[tab-gu-2023-mamba-linear-time-sequence-t11]] — Table p.29 — Table 11: Induction heads, full test accuracy (%) by sequence length
- [[tab-gu-2023-mamba-linear-time-sequence-t12]] — Table p.30 — Table 12: Scaling law model sizes and hyperparameters
- [[tab-gu-2023-mamba-linear-time-sequence-t13]] — Table p.32 — DNA scaling-law model sizes (unlabeled table, section E.3.2)
- [[tab-gu-2023-mamba-linear-time-sequence-t14]] — Table p.34 — Table 13: Great Apes DNA classification accuracy (%) by sequence length
- [[tab-gu-2023-mamba-linear-time-sequence-t15]] — Table p.34 — Table 14: YouTubeMix length-scaling sequence lengths and batch sizes
- [[tab-gu-2023-mamba-linear-time-sequence-t16]] — Table p.36 — Table 15: Memory benchmark (125M models, training)
- [[tab-gu-2023-mamba-linear-time-sequence-t2]] — Table p.12 — Table 3: Zero-shot Evaluations vs. Pythia/RWKV/OPT/GPT-Neo baselines
- [[tab-gu-2023-mamba-linear-time-sequence-t3]] — Table p.15 — Table 4: SC09 unconditional generation metrics
- [[tab-gu-2023-mamba-linear-time-sequence-t4]] — Table p.15 — Table 5: SC09 model ablations (outer/center block architecture)
- [[tab-gu-2023-mamba-linear-time-sequence-t5]] — Table p.16 — Table 6: Ablations — architecture (block) and inner SSM layer, perplexity
- [[tab-gu-2023-mamba-linear-time-sequence-t6]] — Table p.16 — Table 7: Ablations — selective Δ/B/C parameters, perplexity
- [[tab-gu-2023-mamba-linear-time-sequence-t7]] — Table p.16 — Table 8: Ablations — parameterization of A, perplexity
- [[tab-gu-2023-mamba-linear-time-sequence-t8]] — Table p.17 — Table 9: Ablations — expressivity of Δ projection size, perplexity
- [[tab-gu-2023-mamba-linear-time-sequence-t9]] — Table p.17 — Table 10 (Top): Ablations — SSM state dimension, constant B and C
<!-- /extracted-tables -->
