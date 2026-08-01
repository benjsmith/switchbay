---
title: "[ent] LLaMA"
type: entity
created: 2026-07-24
updated: 2026-07-28
sources:
  - 20260728-230740-local-touvron-2023-llama.pdf.extracted.md
---

Open-weight [[foundation-model|foundation]] language model family. Corpus entry
[[touvron-2023-llama-open-efficient|Touvron et al. (2023)]], titled *LLaMA: Open and Efficient
Foundation Language Models* (vault:20260728-230740-local-touvron-2023-llama.pdf.extracted.md).

Collection of foundation language models ranging from 7B to 65B parameters (vault:20260728-230740-local-touvron-2023-llama.pdf.extracted.md).
Trained on publicly available data only — no proprietary or inaccessible datasets.
7B/13B on 1T tokens; 33B/65B on 1.4T tokens [[tab-touvron-2023-llama-open-efficient-t2]].
Corpus: CommonCrawl (67%), C4, GitHub, Wikipedia, books, ArXiv, StackExchange (vault:20260728-230740-local-touvron-2023-llama.pdf.extracted.md) [[tab-touvron-2023-llama-open-efficient-t1]].

**Architecture.** Modifies vanilla [[transformer-architecture|transformer]]: pre-normalization via RMSNorm, SwiGLU activation, rotary position embeddings replacing absolute ones (vault:20260728-230740-local-touvron-2023-llama.pdf.extracted.md).
AdamW optimizer, cosine LR schedule, weight decay 0.1.
Trained on 2048 A100 GPUs (80GB); ~21 days for the full 1.4T-token run (vault:20260728-230740-local-touvron-2023-llama.pdf.extracted.md).

**Core bet.** Train a smaller model longer → cheaper at inference than training a larger one (vault:20260728-230740-local-touvron-2023-llama.pdf.extracted.md).
Hoffmann et al. recommend a 10B model on 200B tokens; LLaMA's 7B kept improving past 1T tokens — the compute-optimal point for *training* is not the optimal point for *serving*.

LLaMA-13B outperforms GPT-3 175B on most benchmarks at 10x smaller (vault:20260728-230740-local-touvron-2023-llama.pdf.extracted.md) [[tab-touvron-2023-llama-open-efficient-t3]].
LLaMA-65B is competitive with Chinchilla-70B and PaLM-540B [[tab-touvron-2023-llama-open-efficient-t9]].

Specialised for code as [[code-llama]]. Part of the wave analysed in
[[open-weight-model-wave]].
