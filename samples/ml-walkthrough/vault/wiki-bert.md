---
title: "BERT (language model) (Wikipedia)"
source_url: "https://en.wikipedia.org/wiki/BERT_(language_model)"
license: "CC BY-SA 4.0"
license_url: "https://creativecommons.org/licenses/by-sa/4.0/"
type: encyclopedia
wikipedia_title: "BERT (language model)"
wikipedia_revid: 1364345417
wikipedia_rev_timestamp: "2026-07-16T01:07:24Z"
retrieved: "2026-07-24"
---

# BERT (language model)

> **Attribution.** This text is adapted from the English Wikipedia article
> [BERT (language model)](https://en.wikipedia.org/wiki/BERT_(language_model)) (revision 1364345417),
> licensed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
> Contributors: see the article history on Wikipedia. Changes: plain-text
> extract via MediaWiki API.

Bidirectional encoder representations from transformers (BERT) is a language model introduced in October 2018 by researchers at Google. It learns to represent text as a sequence of vectors using self-supervised learning. It uses the encoder-only transformer architecture. BERT dramatically improved the state of the art for large language models. As of 2020, BERT is a ubiquitous baseline in natural language processing (NLP) experiments. 
BERT is trained by masked token prediction and next sentence prediction. With this training, BERT learns contextual, latent representations of tokens in their context, similar to ELMo and GPT-2. It found applications for many natural language processing tasks, such as coreference resolution and polysemy resolution. It improved on ELMo and spawned the study of "BERTology", which attempts to interpret what is learned by BERT.
BERT was originally implemented in the English language at two model sizes, BERTBASE (110 million parameters) and BERTLARGE (340 million parameters). Both were trained on the Toronto BookCorpus (800M words) and English Wikipedia  (2,500M words). The weights were released on GitHub. On March 11, 2020, 24 smaller models were released, the smallest being BERTTINY with just 4 million parameters.
