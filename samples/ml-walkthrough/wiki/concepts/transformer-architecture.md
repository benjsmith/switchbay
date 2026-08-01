---
title: "[con] Transformer architecture"
type: concept
created: 2026-07-24
updated: 2026-07-28
sources:
  - 20260728-231916-local-wiki-transformer-architecture.md.extracted.md
---

A family of neural architectures built on multi-head [[attention]]
(vault:20260728-231916-local-wiki-transformer-architecture.md.extracted.md). Text becomes tokens; each token becomes
a vector via a word-embedding lookup. At every layer each token is contextualized
against the other unmasked tokens in the context window, amplifying key tokens and
diminishing less important ones.

[[wikipedia-transformer-architecture|Self-attention alone is permutation-invariant]], so transformers inject position
explicitly — positional encodings or learned positional embeddings — for token
order to matter (vault:20260728-231916-local-wiki-transformer-architecture.md.extracted.md).

No recurrent units, so training time drops relative to earlier recurrent
architectures such as LSTM (vault:20260728-231916-local-wiki-transformer-architecture.md.extracted.md). Modern designs
group into **encoder-only** (representation learning, e.g. [[bert]]),
**decoder-only** (autoregressive generation) and **encoder-decoder** (conditional
sequence-to-sequence) variants.

[[fact-transformer-proposed-2017-google|Originated in the 2017 paper]] "Attention Is All You Need" by researchers at Google,
as an improvement on prior machine-translation architectures
(vault:20260728-231916-local-wiki-transformer-architecture.md.extracted.md). Now used in NLP, vision transformers,
reinforcement learning, audio, multimodal learning, robotics and chess, and behind
pre-trained systems such as GPTs and [[bert|BERT]].

Challenged for long sequences by [[state-space-model|selective state-space models]];
served faster by [[speculative-decoding]].
