---
title: "[con] State space model"
type: concept
created: 2026-07-24
updated: 2026-07-28
sources:
  - 20260728-230732-local-gu-2023-mamba.pdf.extracted.md
  - 20260728-231916-local-wiki-transformer-architecture.md.extracted.md
---

Sequence models whose cost grows linearly rather than quadratically in sequence
length — the standing challenge to
[[transformer-architecture|transformer]] attention, which contextualizes each token
[[wikipedia-transformer-architecture|against every other unmasked token in the context window]]
(vault:20260728-231916-local-wiki-transformer-architecture.md.extracted.md).

Corpus entry [[gu-2023-mamba-linear-time-sequence|Mamba]], titled for linear-time sequence modeling with
selective state spaces (vault:20260728-230732-local-gu-2023-mamba.pdf.extracted.md).

Structured state space sequence models (S4) (vault:20260728-230732-local-gu-2023-mamba.pdf.extracted.md).
An RNN/CNN hybrid inspired by a continuous system mapping x(t)→y(t) through a latent h(t)∈R^N, with params (Δ,A,B,C).
A fixed discretization rule (e.g. zero-order hold) turns continuous (Δ,A,B) into discrete (A,B) — the first step of the SSM forward pass.
Structure imposed on A (diagonal is most common) is what makes the discretized recurrence and convolution tractable to compute (vault:20260728-230732-local-gu-2023-mamba.pdf.extracted.md).

**Dual views.** The linear recurrence h_t=Ah_{t-1}+Bx_t, y_t=Ch_t is equivalent to a global convolution y=x∗K with K=(CB,CAB,...) (vault:20260728-230732-local-gu-2023-mamba.pdf.extracted.md).
Convolution mode gives parallel training, since the full sequence is known ahead; recurrent mode gives constant-per-step autoregressive inference.
Recurrent scan costs O(BLDN) FLOPs, convolution O(BLD log L) — both linear or near-linear in L, against attention's quadratic scaling (vault:20260728-230732-local-gu-2023-mamba.pdf.extracted.md).

**The LTI limit.** Linear time-invariance means (Δ,A,B,C) are fixed across timesteps, and that is exactly what underwrites the recurrence↔convolution equivalence (vault:20260728-230732-local-gu-2023-mamba.pdf.extracted.md).
Fixed dynamics cannot select content-dependent information from context → motivated the input-varying, selective departure.

See [[mamba]].
