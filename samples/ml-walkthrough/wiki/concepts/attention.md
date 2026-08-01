---
title: "[con] Attention"
type: concept
created: 2026-07-24
updated: 2026-07-28
sources:
  - 20260728-231916-local-wiki-attention.md.extracted.md
---

A method that [[wikipedia-attention|scores the importance of each component of a sequence]] relative to
the others (vault:20260728-231916-local-wiki-attention.md.extracted.md). In NLP those scores are "soft" weights over
the words of a sentence; more generally, attention encodes token embeddings across
a fixed-width sequence ranging from tens to millions of tokens.

Soft vs hard weights: hard weights are computed on the backward training pass;
soft weights exist only in the forward pass and so change with every input step
(vault:20260728-231916-local-wiki-attention.md.extracted.md).

**Why it displaced recurrence.** Recurrent nets favour information late in a
sentence, attenuating the predictive weight of earlier tokens. Attention gives a
token equal, direct access to any part of the sentence rather than access only via
the previous state (vault:20260728-231916-local-wiki-attention.md.extracted.md). Early designs put attention inside a
serial RNN translation system; the [[transformer-architecture|transformer]] removed
the slower sequential RNN and leaned on the faster parallel attention scheme.

See [[evi-attention-replaces-recurrence]].
