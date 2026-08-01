---
title: "[ana] Inference economics of open-weight models"
type: analysis
created: 2026-07-29
updated: 2026-07-29
sources:
  - 20260728-230740-local-touvron-2023-llama.pdf.extracted.md
  - 20260728-230734-local-jiang-2024-mixtral.pdf.extracted.md
  - 20260728-230732-local-gu-2023-mamba.pdf.extracted.md
  - 20260728-230730-local-dettmers-2023-qlora.pdf.extracted.md
---

# Inference economics of open-weight models

Four papers in this corpus solve the same fork by four unrelated mechanisms: the
compute-optimal point for training a model is not the compute-optimal point for
serving it.

## Training past the training optimum: LLaMA

[[llama|LLaMA]] states the fork outright. Hoffmann's objective disregards the
inference budget, which becomes critical when serving a language model at scale
(vault:20260728-230740-local-touvron-2023-llama.pdf.extracted.md). Given a target
performance level, the preferred model is not the fastest to train but the fastest
at inference (vault:20260728-230740-local-touvron-2023-llama.pdf.extracted.md).
Hoffmann recommends a 10B model on 200B tokens; LLaMA's 7B continues to improve
past 1T tokens (vault:20260728-230740-local-touvron-2023-llama.pdf.extracted.md).
Training compute is a one-time cost; a smaller model trained well past its own
training-optimal point pays that overrun back on every query for the rest of its
serving life.

## Decoupling capacity from compute: Mixtral

[[mixtral|Mixtral]] attacks the same asymmetry by decoupling two numbers that a
dense model ties together. One can increase the model's parameter count while
keeping its computational cost effectively constant
(vault:20260728-230734-local-jiang-2024-mixtral.pdf.extracted.md), because only
the top-K experts fire per token — 2 of 8 here
([[tab-jiang-2024-mixtral-experts-t1|architecture parameters]]), out of 47B total,
13B active (vault:20260728-230734-local-jiang-2024-mixtral.pdf.extracted.md). But the memory
costs for serving Mixtral are proportional to its sparse parameter count, not the
active count that drives inference compute
(vault:20260728-230734-local-jiang-2024-mixtral.pdf.extracted.md).
[[mixture-of-experts|Mixture-of-experts]] doesn't remove a cost, it relocates one:
FLOPs stay cheap, VRAM stays expensive.

## Trading the cache for a scan: Mamba

[[mamba|Mamba]] attacks the asymmetry from the cache side instead of the parameter
side. Unrolling the model autoregressively during inference requires only constant
time per step since it does not require a cache of previous elements
(vault:20260728-230732-local-gu-2023-mamba.pdf.extracted.md). A transformer's
key-value cache grows with context length, so serving memory rises with every
generated token; Mamba's recurrent state is a fixed-size summary instead.
Selectivity breaks the convolution mode, so Mamba computes the scan recurrently,
using kernel fusion to keep the expanded state in GPU SRAM rather than HBM
(vault:20260728-230732-local-gu-2023-mamba.pdf.extracted.md). The result is up to
3x faster than previous methods on A100 GPUs
(vault:20260728-230732-local-gu-2023-mamba.pdf.extracted.md). See
[[state-space-model]] for the mechanism; the point here is narrower — a constant
state is a serving-cost decision as much as an architectural one.

## Quantizing the base, not the task: QLoRA

[[quantized-finetuning|QLoRA]] works the adaptation side of this ledger, not
inference serving. It reduces average memory requirements for finetuning a 65B
model from >780GB of GPU memory to <48GB
(vault:20260728-230730-local-dettmers-2023-qlora.pdf.extracted.md), by
backpropagating through a frozen 4-bit base into small trainable adapters
(vault:20260728-230730-local-dettmers-2023-qlora.pdf.extracted.md). The frozen
base only dequantizes to BFloat16 for the forward and backward matmuls; no
gradient is computed for the 4-bit weights themselves
(vault:20260728-230730-local-dettmers-2023-qlora.pdf.extracted.md). That is a
training-time trick. **Speculation, not in the vault:** whether it stays a
serving-time win depends on deployment choice — an adapter served alongside a
still-4-bit base keeps the footprint, while merging the adapter into the base for
simpler deployment likely forces a re-quantization step the paper never evaluates.

## Four axes, one seam

[[open-weight-model-wave|The broader wave]] treats openness and efficiency as
inseparable; these papers show separate currencies paid for cheaper deployment.
LLaMA spends training compute. Mixtral spends serving memory. Mamba spends
architectural generality — no [[attention]], no cache. QLoRA is the odd one out and
should be read as such: it buys cheaper *adaptation*, not cheaper serving, and
belongs here only because adaptation cost is what decides whether an open release is
usable by anyone without a cluster. None of the four mechanisms overlap, and nothing
in this vault confirms they compose. **Speculation:** a 4-bit-quantized, Mamba-backboned mixture of
experts would in principle stack all three inference-side savings — no KV cache,
sparse active compute, quantized storage — but that combination isn't tested
anywhere here, and the three savings target different resources — cache footprint in
HBM, FLOPs per token, and stored parameter width respectively — so they need not be
additive. Separately, the rise of long chain-of-thought reasoning models after this
corpus's 2023-2024 window pushes the opposite direction from LLaMA's argument:
when a model generates many tokens per query, the per-token savings Mixtral and
Mamba buy matter more, while LLaMA's bet on shrinking the model itself matters
less if reasoning-length growth dominates total inference cost.

## Open questions and next steps

**Hypotheses**
- Quantization (QLoRA-style 4-bit) and expert sparsity (Mixtral-style) compose
  sub-additively on serving memory, since both eventually bottleneck on the same
  HBM bandwidth rather than on independent resources.
- A 4-bit-quantized Mamba shows smaller quality loss than a 4-bit-quantized
  attention transformer of matched size, because there is no KV cache for
  quantization noise to compound across during long generation.
- The inference-optimal training/token ratio implied by LLaMA's argument shifts
  further toward "smaller, longer" once Mixtral-style sparsity or Mamba-style
  linear scanning are available, since both lower the per-token serving cost that
  makes over-training worthwhile in the first place.
- LoRA adapters folded back into their base model show no serving-time memory
  advantage over an equivalently-sized dense fine-tune — QLoRA's savings are
  training-only unless the merged model is separately re-quantized.

**Experiments that would discriminate between them**
- Measure decode-phase latency and peak memory for Mamba versus a KV-cached
  transformer of matched benchmark quality, sweeping batch size and context
  length, to see whether Mamba's throughput edge needs less batching to pay off
  than Mixtral's routing overhead does.
- Serve a 4-bit-quantized Mixtral and a 4-bit dense model with equal active-
  parameter count side by side, and compare cost-per-token and peak VRAM, to test
  whether quantization and MoE sparsity savings stack or overlap.
- Track quality-per-unit-lifetime-cost (training cost plus N inference queries)
  across several values of N for LLaMA-scale models, to find where the
  Hoffmann-optimal and inference-optimal training curves actually cross.
- Benchmark inference memory and latency for a QLoRA-tuned model before and after
  merging its adapter into the base, to confirm whether the 4-bit footprint
  survives deployment.

**Source requests**
- Hoffmann et al., "Training Compute-Optimal Large Language Models" (arXiv:2203.15556)
  — LLaMA's entire argument is framed against this paper's scaling law, but the
  law itself isn't in the vault.
- Kwon et al., "Efficient Memory Management for Large Language Model Serving with
  PagedAttention" (arXiv:2309.06180) — the vLLM/PagedAttention paper Mixtral's own
  release leaned on for KV-cache-efficient serving.
- Ainslie et al., "GQA: Training Generalized Multi-Query Transformer Models"
  (arXiv:2305.13245) — the mainstream transformer-side answer to the same
  KV-cache problem Mamba solves architecturally instead.
- Gu, Goel, and Ré, "Efficiently Modeling Long Sequences with Structured State
  Spaces" (S4, arXiv:2111.00396) — the direct predecessor Mamba's selection
  mechanism is built on top of.

**Adjacent concepts worth a dedicated page**
- KV cache — the resource Mamba eliminates and Mixtral's memory story implicitly
  assumes; ties three of the four papers together and has no page of its own yet.
- Test-time / inference-time compute scaling — long-reasoning generation inflates
  tokens per query, which bends the LLaMA-style train/serve cost calculus in the
  opposite direction from what this analysis assumes.
- Batch-size-dependent arithmetic intensity — Mixtral notes MoE needs batched
  workloads to reach good device utilization; worth separating single-query
  latency from throughput-at-scale as its own topic.
- Adapter merging and deployment — whether a fine-tuned adapter is served
  separately (small memory add-on) or folded into the base changes the
  serving-cost story QLoRA never addresses.
