---
title: "[ent] Code Llama"
type: entity
created: 2026-07-24
updated: 2026-07-28
sources:
  - 20260728-230737-local-roziere-2023-code-llama.pdf.extracted.md
---

Code-specialised [[llama|LLaMA]] derivative. Corpus entry
[[roziere-2023-code-llama-open|Roziere et al. (2023)]], titled *Code Llama: Open
Foundation Models for Code* (vault:20260728-230737-local-roziere-2023-code-llama.pdf.extracted.md).

Family of large language models for code, based on Llama 2 (vault:20260728-230737-local-roziere-2023-code-llama.pdf.extracted.md).
Three variants — base, Python-specialised, Instruct — each at 7B/13B/34B/70B [[tab-roziere-2023-code-llama-open-t26]].
Built as a cascade from Llama 2: code-training → infilling → long-context FT → [[instruction-tuning|instruction FT]].
Base variant trained on 500B code-heavy tokens; the 70B on 1T.
Dataset mix: 85% code, 8% natural language about code, 7% natural language (vault:20260728-230737-local-roziere-2023-code-llama.pdf.extracted.md) [[tab-roziere-2023-code-llama-open-t1]].

**Infilling.** Causal masking splits documents into prefix/middle/suffix, trained in PSM and SPM formats; 7B/13B/70B only, not the 34B base (vault:20260728-230737-local-roziere-2023-code-llama.pdf.extracted.md) [[tab-roziere-2023-code-llama-open-t26]].

**Long context.** LCFT stage raises training length from 4,096 to 16,384 tokens (vault:20260728-230737-local-roziere-2023-code-llama.pdf.extracted.md).
RoPE base period goes 10,000 → 1,000,000 [[tab-roziere-2023-code-llama-open-t18]], and the model extrapolates stably to 100,000 tokens [[tab-roziere-2023-code-llama-open-t26]].

**Instruct.** Llama 2 [[rlhf|RLHF]] data plus self-instruct — ~14,000 triplets generated via execution feedback — plus rehearsal (vault:20260728-230737-local-roziere-2023-code-llama.pdf.extracted.md).

**Results.** SOTA among open models: up to 67% HumanEval and 65% MBPP (vault:20260728-230737-local-roziere-2023-code-llama.pdf.extracted.md).
Pass@1 HumanEval/MBPP: base 70B 53.0%/62.4%; Instruct 70B 67.8%/62.2%; Python 70B 57.3%/65.6% [[tab-roziere-2023-code-llama-open-t2]].
Code Llama - Python 7B beats Llama 2 70B on both benchmarks — specialisation beats raw scale here (vault:20260728-230737-local-roziere-2023-code-llama.pdf.extracted.md) [[tab-roziere-2023-code-llama-open-t2]].

Part of [[open-weight-model-wave]].
