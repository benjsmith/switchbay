---
title: "[con] Large language model"
type: concept
created: 2026-07-24
updated: 2026-07-28
sources:
  - 20260728-231916-local-wiki-large-language-model.md.extracted.md
---

An AI model, [[wikipedia-large-language-model|typically a neural network, trained on a vast amount of text]] for NLP
tasks — especially language generation (vault:20260728-231916-local-wiki-large-language-model.md.extracted.md). LLMs
generate, summarize, translate and analyze text, and are the foundational
technology behind modern chatbots. Biased or inaccurate training data makes output
less reliable.

Typically based on [[transformer-architecture|transformer architecture]]. Generative
pre-trained transformers (GPTs) are LLMs pre-trained to predict the next word, then
often fine-tuned to follow instructions and behave as assistants
(vault:20260728-231916-local-wiki-large-language-model.md.extracted.md) — see [[instruction-tuning]].

Benchmarks attempt to measure reasoning, factual accuracy, alignment and safety
(vault:20260728-231916-local-wiki-large-language-model.md.extracted.md).

Open-weight examples in this corpus: [[llama]], [[mistral-7b]], [[mixtral]],
[[gemma]], [[code-llama]]. Grounding via [[retrieval-augmented-generation]];
alignment via [[rlhf]] and [[direct-preference-optimization]].
