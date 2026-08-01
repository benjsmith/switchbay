---
title: "[ent] Mamba"
type: entity
created: 2026-07-24
updated: 2026-07-28
sources:
  - 20260728-230732-local-gu-2023-mamba.pdf.extracted.md
---

Selective [[state-space-model|state-space]] sequence model. Corpus entry
[[gu-2023-mamba-linear-time-sequence|Gu and Dao (2023)]], titled *Mamba: Linear-Time Sequence Modeling
with Selective State Spaces* (vault:20260728-230732-local-gu-2023-mamba.pdf.extracted.md).

**Selection mechanism.** Prior SSMs compress context with fixed dynamics; selection makes parameters functions of the input (vault:20260728-230732-local-gu-2023-mamba.pdf.extracted.md).

SSM params (Δ, B, C) made functions of input → time-varying, input-dependent filtering: model selectively propagates/forgets info along sequence per-token, vs prior LTI (linear-time-invariant) SSMs w/ fixed params (vault:20260728-230732-local-gu-2023-mamba.pdf.extracted.md). Δ generalizes RNN gate: large Δ → resets state, focuses on current input; small Δ → ignores input, persists state (vault:20260728-230732-local-gu-2023-mamba.pdf.extracted.md). Selectivity solves Selective Copying [[tab-gu-2023-mamba-linear-time-sequence-t1]] / induction-heads [[tab-gu-2023-mamba-linear-time-sequence-t11]] synthetics where LTI models (conv, linear recurrence) fail from lack of content-awareness (vault:20260728-230732-local-gu-2023-mamba.pdf.extracted.md).

**Hardware-aware scan.** Selectivity breaks convolution mode (needs time-invariance) → computed via parallel scan in recurrent mode instead, w/ kernel fusion + recomputation; avoids materializing expanded state in GPU HBM, keeps it in SRAM. Up to 3× faster than prior methods on A100 (vault:20260728-230732-local-gu-2023-mamba.pdf.extracted.md).

**Architecture.** Drops [[attention]] and MLP blocks entirely — single homogenous block fusing SSM w/ gated MLP (SiLU/SwiGLU), stacked (vault:20260728-230732-local-gu-2023-mamba.pdf.extracted.md).

**Results.** 5× higher generation throughput vs same-size Transformers; linear-time scaling in sequence length, quality improves to 1M-length sequences (vault:20260728-230732-local-gu-2023-mamba.pdf.extracted.md). SOTA across language, audio, genomics; Mamba-3B outperforms same-size Transformers, matches Transformers twice its size on pretraining + downstream (4pt higher avg vs Pythia-3B, exceeds Pythia-7B) [[tab-gu-2023-mamba-linear-time-sequence-t2]] (vault:20260728-230732-local-gu-2023-mamba.pdf.extracted.md). Halves FID on challenging speech-generation benchmark vs SaShiMi/Hyena baselines [[tab-gu-2023-mamba-linear-time-sequence-t3]] (vault:20260728-230732-local-gu-2023-mamba.pdf.extracted.md).

Positioned against [[transformer-architecture]].
