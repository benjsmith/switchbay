---
title: "[ana] The open-weight model wave, 2023-2024"
type: analysis
created: 2026-07-24
updated: 2026-07-28
sources:
  - 20260728-230740-local-touvron-2023-llama.pdf.extracted.md
  - 20260728-230734-local-jiang-2023-mistral-7b.pdf.extracted.md
  - 20260728-230734-local-jiang-2024-mixtral.pdf.extracted.md
  - 20260728-230731-local-gemma-team-2024-gemma.pdf.extracted.md
  - 20260728-230737-local-roziere-2023-code-llama.pdf.extracted.md
  - 20260728-230732-local-gu-2023-mamba.pdf.extracted.md
  - 20260728-231916-local-wiki-foundation-model.md.extracted.md
---

# The open-weight model wave, 2023-2024

Six of the fifteen papers in this vault are open-weight model releases published
within about eighteen months of each other. Read as a group, and taking each at the
word of its own title, they trace a fairly clear progression.

## What the corpus contains

[[llama|LLaMA]] opens the sequence, titled for *open and efficient* foundation
language models (vault:20260728-230740-local-touvron-2023-llama.pdf.extracted.md) — [[touvron-2023-llama-open-efficient|efficiency named in the title]]
alongside openness. [[code-llama|Code Llama]] follows as a code-specialised
derivative (vault:20260728-230737-local-roziere-2023-code-llama.pdf.extracted.md), and [[mistral-7b|Mistral 7B]]
(vault:20260728-230734-local-jiang-2023-mistral-7b.pdf.extracted.md) and [[gemma|Gemma]]
(vault:20260728-230731-local-gemma-team-2024-gemma.pdf.extracted.md) arrive as further open releases, Gemma explicitly
[[gemma-2024-gemma-open-models|derived from Gemini research and technology]].

Then the architecture starts to move. [[mixtral|Mixtral]] is a
[[mixture-of-experts]] model (vault:20260728-230734-local-jiang-2024-mixtral.pdf.extracted.md) — sparse activation
[[jiang-2024-mixtral-experts|rather than a bigger dense stack]]. [[mamba|Mamba]] leaves
[[transformer-architecture|transformers]] altogether, titled for linear-time
[[gu-2023-mamba-linear-time-sequence|sequence modelling with selective state spaces]] (vault:20260728-230732-local-gu-2023-mamba.pdf.extracted.md).

The full inventory is in [[tbl-open-model-corpus]].

## Why openness and efficiency arrive together

The economics are the reason. Building a [[foundation-model|foundation model]] is
highly resource-intensive, with the most advanced costing hundreds of millions of
dollars across data acquisition, curation and processing plus the compute to train.
[[wikipedia-foundation-model|Adapting an existing one is far less costly]], reusing pre-trained capabilities and
typically requiring only fine-tuning on smaller task-specific datasets
(vault:20260728-231916-local-wiki-foundation-model.md.extracted.md).

Released weights are what let anyone stand on the expensive side of that asymmetry
without paying for it. Everything downstream in this corpus —
[[quantized-finetuning]] to make adaptation cheap,
[[speculative-decoding]] to make inference cheap, [[mixture-of-experts]] and
[[state-space-model|state-space models]] to make the architecture cheap — is
working the same seam.

## What this page does not claim

This page argues from titles and release posture, not from results. That was a
necessity when it was written — the vault then held attribution records and PDFs with
no extracted text — but it is now a choice: full extractions exist for all six papers,
and the entity pages ([[llama]], [[mixtral]], [[gemma]], [[code-llama]], [[mamba]],
[[mistral-7b]]) carry the parameter counts, training-token budgets and benchmark
comparisons this page deliberately still avoids.

The division of labour is intentional. This page is about the *shape* of the wave —
who released what, in what order, under which licence. [[inference-economics-of-open-models]]
is the page that argues from the numbers, asking what each release actually paid to
make serving cheap. Read them together.
