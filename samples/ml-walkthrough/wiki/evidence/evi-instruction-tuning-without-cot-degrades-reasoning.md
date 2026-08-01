---
title: "[evi] Instruction tuning without CoT degrades reasoning"
type: evidence
created: 2026-07-29
updated: 2026-07-29
sources:
  - 20260728-230728-local-chung-2022-flan.pdf.extracted.md
---

**Method.** [[chung-2022-scaling-instruction-finetuned-language|Flan]] holds task mixture and training procedure fixed across PaLM 8B/62B/540B, varying only whether the nine-dataset [[chain-of-thought-prompting|CoT]] mixture is included.
We stratify evaluations into held-out CoT benchmarks and held-out non-CoT benchmarks (vault:20260728-230728-local-chung-2022-flan.pdf.extracted.md).

**Result.** Finetuning on only non-CoT degrades performance on CoT by a substantial amount — worse than no finetuning at all (vault:20260728-230728-local-chung-2022-flan.pdf.extracted.md).
Including just nine CoT datasets in the mixture reverses this and improves performance on all evaluations (vault:20260728-230728-local-chung-2022-flan.pdf.extracted.md).

**Interpretation.** [[instruction-tuning|Instruction finetuning]] propagates whichever prompting paradigms its mixture demonstrates, and can erode a capability the mixture omits entirely — not merely fail to improve it (vault:20260728-230728-local-chung-2022-flan.pdf.extracted.md).
