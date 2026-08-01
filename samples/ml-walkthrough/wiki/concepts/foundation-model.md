---
title: "[con] Foundation model"
type: concept
created: 2026-07-24
updated: 2026-07-28
sources:
  - 20260728-231916-local-wiki-foundation-model.md.extracted.md
---

A machine-learning or [[deep-learning]] model trained on vast datasets so it can be
[[wikipedia-foundation-model|applied across a wide range of use cases]]; also "large x model" (LxM)
(vault:20260728-231916-local-wiki-foundation-model.md.extracted.md). [[large-language-model|LLMs]] are the common
example.

**Cost asymmetry.** Building one is highly resource-intensive — the most advanced
cost hundreds of millions of dollars across data acquisition, curation and
processing plus the compute to train, needing sophisticated infrastructure,
extended training times and advanced hardware such as GPUs. Adapting an existing
foundation model, or using it directly, is far less costly: it reuses pre-trained
capabilities and typically needs only fine-tuning on smaller task-specific datasets
(vault:20260728-231916-local-wiki-foundation-model.md.extracted.md). That asymmetry is what
[[quantized-finetuning|quantized finetuning]] pushes on.

Early examples are language models — OpenAI's GPT series and Google's
[[bert|BERT]]. Beyond text: DALL-E, Stable Diffusion and Flamingo for images,
MusicGen and LLark for music, RT-2 for robotic control. Also under development for
astronomy, radiology, ophthalmology, genomics, earth sciences, coding, time-series
forecasting, mathematics and chemistry (vault:20260728-231916-local-wiki-foundation-model.md.extracted.md).
