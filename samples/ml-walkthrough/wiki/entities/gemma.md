---
title: "[ent] Gemma"
type: entity
created: 2026-07-24
updated: 2026-07-28
sources:
  - 20260728-230731-local-gemma-team-2024-gemma.pdf.extracted.md
---

Open [[large-language-model|LLM]] family from Google. Corpus entry
[[gemma-2024-gemma-open-models|Gemma Team (2024)]], titled *Gemma: Open Models Based on
Gemini Research and Technology* (vault:20260728-230731-local-gemma-team-2024-gemma.pdf.extracted.md).

Two sizes: 2B and 7B params (vault:20260728-230731-local-gemma-team-2024-gemma.pdf.extracted.md).
7B targets GPU/TPU deployment; 2B targets CPU and on-device use.
Built from Gemini research and tech, sharing architecture, data and training recipes — but unlike Gemini, not multimodal and not multilingual-tuned (vault:20260728-230731-local-gemma-team-2024-gemma.pdf.extracted.md).

**Architecture.** [[transformer-architecture|Transformer]] decoder, 8192-token context (vault:20260728-230731-local-gemma-team-2024-gemma.pdf.extracted.md).
18 layers with d_model 2048 (2B); 28 layers with d_model 3072 (7B) [[tab-gemma-2024-gemma-open-models-t1]].
7B uses [[attention|multi-head attention]], 2B multi-query — the smaller model trades expressiveness for decode memory.
RoPE embeddings, shared input/output embeddings, GeGLU activations, RMSNorm.
Vocab 256k tokens, shared with the Gemini tokenizer (vault:20260728-230731-local-gemma-team-2024-gemma.pdf.extracted.md).

**Training.** 2B on 3T tokens, 7B on 6T (vault:20260728-230731-local-gemma-team-2024-gemma.pdf.extracted.md).
Both released as pretrained plus [[instruction-tuning|instruction-tuned]] (SFT+[[rlhf|RLHF]]) checkpoints.

**Results.** Outperforms similarly-sized open models on 11 of 18 text tasks (vault:20260728-230731-local-gemma-team-2024-gemma.pdf.extracted.md).
7B MMLU 64.3 vs Mistral-7B 62.5 and LLaMA2-13B 54.8; 18-benchmark average 56.9 vs 54.5 and 52.4 [[tab-gemma-2024-gemma-open-models-t6]].

**Release posture.** Paper's discussion claims better performance on 6 safety benchmarks, but names none of them; its own safety table lists ten [[tab-gemma-2024-gemma-open-models-t8]], with Gemma 7B behind Mistral on BBQ Ambig, Winogender, TruthfulQA and Winobias 1_2 — treat the headline safety claim as the authors' framing, not a settled result (vault:20260728-230731-local-gemma-team-2024-gemma.pdf.extracted.md).
Also tested for memorization and personal-data leakage.
Red-teaming, a published model card and a Generative AI Responsible Toolkit ship alongside the weights.
Paper judges release net-positive despite its irreversibility, and acknowledges misuse risk (vault:20260728-230731-local-gemma-team-2024-gemma.pdf.extracted.md).

Part of [[open-weight-model-wave]].
