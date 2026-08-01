---
title: "[evi] Attention replaces recurrence for long-range access"
type: evidence
created: 2026-07-24
updated: 2026-07-28
sources:
  - 20260728-231916-local-wiki-attention.md.extracted.md
  - 20260728-231916-local-wiki-transformer-architecture.md.extracted.md
---

**Claim.** Parallel [[attention]] supplanted sequential recurrence in sequence
modelling.

**Mechanism.** [[wikipedia-attention|Recurrent networks favour information in words]] at the end of a
sentence, deemed more recent, attenuating the significance and predictive weight of
earlier information. Attention gives a token equal access to any part of a sentence
directly, rather than only through the previous state (vault:20260728-231916-local-wiki-attention.md.extracted.md).

**Adoption.** Early designs implemented attention inside a serial RNN translation
system; the [[transformer-architecture|transformer]] removed the slower sequential
RNN and relied more heavily on the faster parallel attention scheme
(vault:20260728-231916-local-wiki-attention.md.extracted.md). Having no recurrent units, transformers require less
[[wikipedia-transformer-architecture|training time than earlier recurrent architectures such as LSTM]]
(vault:20260728-231916-local-wiki-transformer-architecture.md.extracted.md).

**Cost carried forward.** Contextualizing every token against every other unmasked
token in the window is what [[state-space-model|linear-time models]] and
[[speculative-decoding]] later attack.
