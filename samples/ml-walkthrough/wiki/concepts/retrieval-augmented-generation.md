---
title: "[con] Retrieval-augmented generation"
type: concept
created: 2026-07-24
updated: 2026-07-28
sources:
  - 20260728-231916-local-wiki-rag.md.extracted.md
---

A technique letting [[large-language-model|LLMs]] retrieve and incorporate new
information from external data sources: [[wikipedia-rag|the model consults a specified document set]]
first, then answers (vault:20260728-231916-local-wiki-rag.md.extracted.md). Those documents supplement pre-existing
training data, so the model can use domain-specific or updated information it was
never trained on — internal company data, authoritative sources. First proposed in
2020; now widely adopted.

Unlike an LLM relying on static training data, RAG pulls relevant text from
databases, uploaded documents or web sources. Per Ars Technica, "RAG is a way of
improving LLM performance, in essence by blending the LLM process with a web search
or other document look-up process to help LLMs stick to the facts"
(vault:20260728-231916-local-wiki-rag.md.extracted.md).

**Three claimed gains** (vault:20260728-231916-local-wiki-rag.md.extracted.md):
- Fewer hallucinations — the failure mode behind chatbots describing nonexistent
  policies, or recommending nonexistent legal cases to lawyers seeking citations.
- Less retraining on new data, saving computational and financial cost.
- Citable sources in responses, so users can cross-check retrieved content.

The term was introduced in a 2020 paper describing a parametric language model
combined with a non-parametric external memory accessed by retrieval at inference
time (vault:20260728-231916-local-wiki-rag.md.extracted.md).

See [[evi-rag-reduces-hallucination]] and [[fact-rag-introduced-2020]].
