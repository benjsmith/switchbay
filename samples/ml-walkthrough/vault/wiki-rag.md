---
title: "Retrieval-augmented generation (Wikipedia)"
source_url: "https://en.wikipedia.org/wiki/Retrieval-augmented_generation"
license: "CC BY-SA 4.0"
license_url: "https://creativecommons.org/licenses/by-sa/4.0/"
type: encyclopedia
wikipedia_title: "Retrieval-augmented generation"
wikipedia_revid: 1365691175
wikipedia_rev_timestamp: "2026-07-23T22:10:39Z"
retrieved: "2026-07-24"
---

# Retrieval-augmented generation

> **Attribution.** This text is adapted from the English Wikipedia article
> [Retrieval-augmented generation](https://en.wikipedia.org/wiki/Retrieval-augmented_generation) (revision 1365691175),
> licensed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
> Contributors: see the article history on Wikipedia. Changes: plain-text
> extract via MediaWiki API.

Retrieval-augmented generation (RAG) is a technique that enables large language models (LLMs) to retrieve and incorporate new information from external data sources. With RAG, LLMs first refer to a specified set of documents, then respond to user queries. These documents supplement information from the LLM's pre-existing training data. This allows LLMs to use domain-specific and/or updated information that is not available in the training data. For example, this enables LLM-based chatbots to access internal company data or generate responses based on authoritative sources. The technique was first proposed in 2020 and has since become a widely adopted approach in modern AI systems.
RAG improves LLMs by incorporating information retrieval before generating responses. Unlike LLMs that rely on static training data, RAG pulls relevant text from databases, uploaded documents, or web sources. According to Ars Technica, "RAG is a way of improving LLM performance, in essence by blending the LLM process with a web search or other document look-up process to help LLMs stick to the facts." This method helps reduce AI hallucinations, which have caused chatbots to describe policies that don't exist, or recommend nonexistent legal cases to lawyers that are looking for citations to support their arguments.
RAG also reduces the need to retrain LLMs with new data, saving on computational and financial costs. Beyond efficiency gains, RAG also allows LLMs to include sources in their responses, so users can verify the cited sources. This provides greater transparency, as users can cross-check retrieved content to ensure accuracy and relevance.
The term retrieval-augmented generation (RAG) was introduced in a 2020 paper that described combining a parametric language model with a non-parametric external memory accessed through retrieval at inference time.
