---
title: "[evi] Mixtral's router specialises by syntax and position, not topic"
type: evidence
created: 2026-07-29
updated: 2026-07-29
sources:
  - 20260728-230734-local-jiang-2024-mixtral.pdf.extracted.md
---

**Method.** Mixtral's router: distribution of selected experts on subsets of The Pile validation dataset, layers 0, 15, and 31 (vault:20260728-230734-local-jiang-2024-mixtral.pdf.extracted.md).

**Result.** ArXiv, biology, and Philosophy documents show very similar expert assignment (vault:20260728-230734-local-jiang-2024-mixtral.pdf.extracted.md). Paper's own wording is hedged — it does not observe obvious patterns in assignment based on topic across [[mixture-of-experts|experts]]. DM Mathematics shows a marginally different distribution, plausibly from its synthetic, narrow-language nature.

Router instead tracks syntax and position. Indentation tokens in Python are always assigned to the same experts, particularly at the first and last layers; `self` in Python often gets routed through the same expert (vault:20260728-230734-local-jiang-2024-mixtral.pdf.extracted.md).
Consecutive tokens repeat the same expert far more than random — close to random at layer 0, higher at layers 15 and 31 ([[tab-jiang-2024-mixtral-experts-t7|per-domain repetition rates by layer]]).

**Interpretation.** This router organises by syntax and position rather than subject matter. Locality has downstream consequences: over-subscription risk under Expert Parallelism, and an opportunity for caching consecutive-token routing (vault:20260728-230734-local-jiang-2024-mixtral.pdf.extracted.md).

**Scope.** One [[mixtral|Mixtral]] router — 8 experts, top-2 routing. Evidence about this model, not a proven law of MoE architectures generally.
