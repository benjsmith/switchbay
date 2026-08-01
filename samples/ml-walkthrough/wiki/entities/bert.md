---
title: "[ent] BERT"
type: entity
created: 2026-07-24
updated: 2026-07-28
sources:
  - 20260728-231916-local-wiki-bert.md.extracted.md
---

Bidirectional encoder representations from transformers — a language model
[[wikipedia-bert|introduced in October 2018 by researchers at Google]] (vault:20260728-231916-local-wiki-bert.md.extracted.md). Learns to
represent text as a sequence of vectors by self-supervised learning, on the
encoder-only [[transformer-architecture|transformer architecture]].

Dramatically improved the state of the art for
[[large-language-model|large language models]]; as of 2020 a ubiquitous baseline in
NLP experiments (vault:20260728-231916-local-wiki-bert.md.extracted.md).

**Training.** Masked token prediction and next-sentence prediction, giving
contextual latent token representations similar to ELMo and GPT-2. Applied to
coreference resolution and polysemy resolution; improved on ELMo and spawned
"BERTology", the study of what BERT learns (vault:20260728-231916-local-wiki-bert.md.extracted.md).

**Sizes.** Originally English at two sizes — BERT-BASE (110M parameters) and
BERT-LARGE (340M) — both trained on the Toronto BookCorpus (800M words) and English
Wikipedia (2,500M words), weights released on GitHub. On 11 March 2020, 24 smaller
models followed, the smallest BERT-TINY at 4M parameters (vault:20260728-231916-local-wiki-bert.md.extracted.md).

An early [[foundation-model]] (vault:20260728-231916-local-wiki-foundation-model.md.extracted.md).
See [[fact-bert-base-110m-large-340m]].
