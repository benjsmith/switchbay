---
title: "[con] Speculative decoding"
type: concept
created: 2026-07-24
updated: 2026-07-29
sources:
  - 20260728-230735-local-leviathan-2023-speculative-sampling.pdf.extracted.md
  - wiki-transformer-architecture.md
  - 20260728-230735-local-leviathan-2023-speculative-sampling.pdf.extracted.md
---

An inference-time speedup: a cheap draft model proposes tokens, the target model
verifies them in parallel.

Corpus entry [[leviathan-2023-fast-inference-from|Chen et al. (2023)]], DeepMind
(vault:20260728-230735-local-leviathan-2023-speculative-sampling.pdf.extracted.md). **Attribution note:** this vault entry
was ingested with a Leviathan et al. title against Chen et al.'s arXiv ID; the stored PDF
is Chen et al. See the source stub for the full correction. Leviathan, Kalman & Matias
published the same technique concurrently, but that paper is not in this vault.

Speculative sampling accelerates transformer decoding by enabling the generation of multiple tokens from each transformer call (vault:20260728-230735-local-leviathan-2023-speculative-sampling.pdf.extracted.md).
Draft model generates K tokens autoregressively → target model scores all K+1 continuations in one parallel pass.
Works because latency of parallel scoring of short continuations is comparable to sampling a single token from the larger target model.

**Acceptance rule.** Accept draft token w/ prob min(1, q/p) — q = target prob, p = draft prob; on reject, resample from normalized max(0, q−p) (vault:20260728-230735-local-leviathan-2023-speculative-sampling.pdf.extracted.md).
Modified rejection sampling scheme preserves the distribution of the target model within hardware numerics.
→ not an approximation. Output distribution is the target's, exactly; only latency and numerics differ.

**Measured.** 2-2.5x decoding speedup ([[tab-leviathan-2023-fast-inference-from-t1|measured per-benchmark speedups]]) benchmarked with Chinchilla, a 70 billion parameter language model ([[tab-leviathan-2023-fast-inference-from-t2|draft and target hyperparameters]]), in a distributed setup (vault:20260728-230735-local-leviathan-2023-speculative-sampling.pdf.extracted.md).
Achieved without compromising sample quality, and without modifying the target model itself — no retraining, no architecture change.
Gain depends on draft-model acceptance rate, so it varies by domain and decoding method.

Attacks the same serving cost that [[mixture-of-experts]] and [[state-space-model|state-space models]] attack architecturally — see [[inference-economics-of-open-models]]. Unlike those, it leaves [[transformer-architecture|the transformer]] untouched.
