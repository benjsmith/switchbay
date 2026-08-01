---
title: "[src] Chain-of-Thought Prompting Elicits Reasoning in Large Language Models — wei, 2022"
type: source
created: 2022
updated: 2026-04-12
sources: [20260728-230742-local-wei-2022-chain-of-thought.pdf.extracted.md]
vault_sha256: ce9db15330162a13e7a1871650bb3e5ba28a6962bbf96c045b2609202c74eec0
---

Chain-of-Thought Prompting Elicits Reasoning in Large Language Models Jason Wei Xuezhi Wang Dale Schuurmans Maarten Bosma Brian Ichter Fei Xia Ed H. Chi Quoc V . Le Denny Zhou Google Research, Brain Team {jasonwei,dennyzhou}@google.com Abstract We explore how generating a chain of thought—a series of intermediate reasoning steps—signiﬁcantly improves the ability of large language models to perform complex reasoning. In particular, we show how such reasoning abilities emerge (vault:20260728-230742-local-wei-2022-chain-of-thought.pdf.extracted.md)

<!-- extracted-tables -->
## Extracted tables (8)

- [[tab-wei-2022-chain-of-thought-prompting-elicits-t1]] — Table p.20 — Table 1: Chain of thought prompting outperforms standard prompting for various large language models on five arithmetic reasoning benchmarks. All metrics are accuracy (%). Ext. calc.: post-hoc external calculator for arithmetic computations only. Prior best numbers are from: a: Cobbe et al. (2021), b & e: Pi et al. (2022), c: Lan et al. (2021), d: Piękos et al. (2021).
- [[tab-wei-2022-chain-of-thought-prompting-elicits-t2]] — Table p.21 — Table 2: Standard prompting versus chain of thought prompting on five arithmetic reasoning benchmarks (GSM8K, SVAMP, ASDiv, AQuA, MAWPS), broken out by model family and size. Chain of thought prompting is an emergent ability of model scale.
- [[tab-wei-2022-chain-of-thought-prompting-elicits-t3]] — Table p.21 — Table 3: Standard prompting versus chain of thought prompting on the four subsets of the MAWPS benchmark (SingleOp, SingleEq, AddSub, MultiArith), by model family and size.
- [[tab-wei-2022-chain-of-thought-prompting-elicits-t4]] — Table p.22 — Table 4: Standard prompting versus chain of thought prompting on five commonsense reasoning benchmarks (CSQA, StrategyQA, Date Understanding, Sports Understanding, SayCan), by model family and size.
- [[tab-wei-2022-chain-of-thought-prompting-elicits-t5]] — Table p.22 — Table 5: Standard prompting versus chain of thought prompting enables length generalization to longer inference examples on two symbolic manipulation tasks (Last Letter Concatenation and Coin Flip / state tracking). Column '2' is in-domain (2-word names / 2 potential flips); 'OOD: 3' and 'OOD: 4' are out-of-domain lengths.
- [[tab-wei-2022-chain-of-thought-prompting-elicits-t6]] — Table p.23 — Table 6 (KEY ABLATION TABLE): Ablation and robustness results for arithmetic reasoning datasets (GSM8K, SVAMP, ASDiv, MAWPS), LaMDA 137B. Ablations tested: equation only, variable compute only, reasoning after answer. Robustness rows tested: different annotators (B, C), intentionally concise style, and three independent exemplar sets sampled from GSM8K (α, β, γ). Standard deviation (±) is over five random orderings of the few-shot exemplars.
- [[tab-wei-2022-chain-of-thought-prompting-elicits-t7]] — Table p.23 — Table 7: Ablation and robustness results for four datasets in commonsense and symbolic reasoning (Date Understanding, Sports Understanding, SayCan under Commonsense; Last Letter Concatenation ['Concat'] and Coin Flip ['Coin'] under Symbolic). Results shown for LaMDA 137B, except SayCan which uses PaLM (540B) since its eval set is only 120 examples. Standard deviation (±) is over five random exemplar orderings.
- [[tab-wei-2022-chain-of-thought-prompting-elicits-t8]] — Table p.29 — Table 12: Summary of math word problem benchmarks used in this paper with example problems. N = number of evaluation examples.
<!-- /extracted-tables -->
