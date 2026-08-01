---
title: "[ent] Mistral 7B"
type: entity
created: 2026-07-24
updated: 2026-07-28
sources:
  - 20260728-230734-local-jiang-2023-mistral-7b.pdf.extracted.md
---

Open-weight 7B [[large-language-model|language model]]. Corpus entry
[[jiang-2023-mistral-7b|Jiang et al. (2023)]] (vault:20260728-230734-local-jiang-2023-mistral-7b.pdf.extracted.md).

**Architecture.** [[attention|Grouped-query attention and sliding window attention]] (vault:20260728-230734-local-jiang-2023-mistral-7b.pdf.extracted.md).

Transformer: dim 4096, 32 layers, 32 heads, 8 kv-heads (grouped-query attention, GQA), head_dim 128, hidden_dim 14336, vocab 32000, context 8192 (vault:20260728-230734-local-jiang-2023-mistral-7b.pdf.extracted.md), tabulated in [[tab-jiang-2023-mistral-7b-t1|architecture parameters]]. GQA → faster inference, lower decoding memory, higher batch throughput. Sliding-window attention (SWA), W=4096: each token attends ≤W prior tokens; stacked layers give theoretical span ~131K tokens by last layer; 2x speedup vs vanilla attention on 16K sequences w/ FlashAttention+xFormers (vault:20260728-230734-local-jiang-2023-mistral-7b.pdf.extracted.md). Rolling buffer KV cache exploits fixed span → 8x cache-memory cut at 32K seq len, no quality loss (vault:20260728-230734-local-jiang-2023-mistral-7b.pdf.extracted.md).

**Benchmarks.** Outperforms Llama 2 13B on every evaluated benchmark; beats Llama 1 34B on math/code/reasoning. MMLU 60.1% vs Llama 2 13B 55.6%; GSM8K 52.2% vs 34.3%; HumanEval 30.5% vs 18.9%; MATH 13.1% vs 6.0% (vault:20260728-230734-local-jiang-2023-mistral-7b.pdf.extracted.md), all rows in [[tab-jiang-2023-mistral-7b-t2|the full benchmark table]]. These are the figures as reported in Mistral 7B's own paper; the later Mixtral paper [[tab-jiang-2024-mixtral-experts-t2]] reports the same model differently on most of these benchmarks (MMLU 62.5%, GSM8K 50.0%, HumanEval 26.2%, MATH 12.7%), without explaining the change.

**Instruct variant.** Mistral 7B – Instruct, [[instruction-tuning|fine-tuned on public HF instruction datasets]], no proprietary data/tricks. MT-Bench 6.84 vs Llama 2 13B – Chat 6.65 ([[tab-jiang-2023-mistral-7b-t3|MT-Bench and Arena ELO table]]); outperforms all 7B chat models (vault:20260728-230734-local-jiang-2023-mistral-7b.pdf.extracted.md).

**Release.** Apache 2.0 license (vault:20260728-230734-local-jiang-2023-mistral-7b.pdf.extracted.md).

Sparse sibling: [[mixtral]]. Part of [[open-weight-model-wave]].
