---
title: "[con] Quantized finetuning"
type: concept
created: 2026-07-24
updated: 2026-07-28
sources:
  - 20260728-230730-local-dettmers-2023-qlora.pdf.extracted.md
  - 20260728-231916-local-wiki-foundation-model.md.extracted.md
---

Fine-tuning a model held in reduced numeric precision, so adaptation fits hardware that could never hold training in full precision.

It presses on the cost asymmetry of [[foundation-model|foundation models]]: building one is highly resource-intensive, while [[wikipedia-foundation-model|adapting an existing one is far less costly]], reusing pre-trained capabilities and typically needing only fine-tuning on smaller task-specific datasets (vault:20260728-231916-local-wiki-foundation-model.md.extracted.md).

Corpus entry [[dettmers-2023-qlora-efficient-finetuning|QLoRA]], titled for efficient finetuning of quantized [[large-language-model|LLMs]] (vault:20260728-230730-local-dettmers-2023-qlora.pdf.extracted.md).

4-bit NormalFloat, double quantization, paged optimizers (vault:20260728-230730-local-dettmers-2023-qlora.pdf.extracted.md).

QLoRA backpropagates gradients through a frozen 4-bit quantized base model into LoRA adapters: base weights dequantize 4-bit→BFloat16 for forward/backward matmuls, but only adapter weights get gradient updates — no gradient computed for the 4-bit weights themselves (vault:20260728-230730-local-dettmers-2023-qlora.pdf.extracted.md).

Three named innovations. **NF4** (4-bit NormalFloat): information-theoretically optimal datatype for zero-centered normally-distributed weights (neural net weights ~N(0,σ)); beats 4-bit Int/Float empirically [[tab-dettmers-2023-qlora-efficient-finetuning-t2]]. **Double quantization**: quantizes the quantization constants themselves (8-bit, blocksize 256), saving ~0.37 bits/param (~3GB at 65B scale). **Paged optimizers**: NVIDIA unified memory pages optimizer states CPU↔GPU automatically, absorbing gradient-checkpointing memory spikes (vault:20260728-230730-local-dettmers-2023-qlora.pdf.extracted.md).

Memory: cuts 65B finetuning from >780GB to <48GB, fitting a single GPU, without degrading 16-bit task performance [[tab-dettmers-2023-qlora-efficient-finetuning-t4]] (vault:20260728-230730-local-dettmers-2023-qlora.pdf.extracted.md).

Resulting model family **Guanaco**: 65B reaches 99.3% of ChatGPT on Vicuna benchmark after 24h on one professional GPU; 33B reaches 97.8% in <12h on a consumer GPU [[tab-dettmers-2023-qlora-efficient-finetuning-t6]]; trained on small OASST1 subset (~9k examples) — data quality beats dataset size [[tab-dettmers-2023-qlora-efficient-finetuning-t11]] (vault:20260728-230730-local-dettmers-2023-qlora.pdf.extracted.md).

Stated limitations: 16-bit-matching not directly verified at 33B/65B scale; evaluation limited to MMLU/Vicuna/OA, not BigBench/RAFT/HELM; only limited bias evaluation; untested at coarser (e.g. 3-bit) precision or with other adapter methods (vault:20260728-230730-local-dettmers-2023-qlora.pdf.extracted.md).
