---
title: "Transformer (deep learning) (Wikipedia)"
source_url: "https://en.wikipedia.org/wiki/Transformer_(deep_learning)"
license: "CC BY-SA 4.0"
license_url: "https://creativecommons.org/licenses/by-sa/4.0/"
type: encyclopedia
wikipedia_title: "Transformer (deep learning)"
wikipedia_revid: 1362319941
wikipedia_rev_timestamp: "2026-07-03T05:06:03Z"
retrieved: "2026-07-24"
---

# Transformer (deep learning)

> **Attribution.** This text is adapted from the English Wikipedia article
> [Transformer (deep learning)](https://en.wikipedia.org/wiki/Transformer_(deep_learning)) (revision 1362319941),
> licensed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
> Contributors: see the article history on Wikipedia. Changes: plain-text
> extract via MediaWiki API.

In deep learning, the transformer is a family of artificial neural network architectures based on the multi-head attention mechanism, in which text is converted to numerical representations called tokens, and each token is converted into a vector via lookup from a word embedding table. At each layer, each token is then contextualized within the scope of the context window with other (unmasked) tokens via a parallel multi-head attention mechanism, allowing the signal for key tokens to be amplified and less important tokens to be diminished. Because self-attention alone is permutation-invariant, transformers inject positional information, typically through positional encodings or learned positional embeddings, so token order can affect the output.
Transformers have the advantage of having no recurrent units, therefore requiring less training time than earlier recurrent neural architectures (RNNs) such as long short-term memory (LSTM). Later variations have been widely adopted for training large language models (LLMs) on large (language) datasets. Modern transformer designs are commonly grouped into encoder-only, decoder-only, and encoder-decoder variants, depending on whether they are optimized for representation learning, autoregressive generation, or conditional sequence-to-sequence tasks.

The original version of the transformer architecture was proposed in the 2017 paper "Attention Is All You Need" by researchers at Google. The predecessors of transformers were developed as an improvement over previous architectures for machine translation, but have found many applications since. They are used in large-scale natural language processing, computer vision (vision transformers), reinforcement learning, audio, multimodal learning, robotics, and playing chess. It has also led to the development of pre-trained systems, such as generative pre-trained transformers (GPTs) and BERT (bidirectional encoder representations from transformers).
