---
title: "[src] LLaMA: Open and Efficient Foundation Language Models — touvron, 2023"
type: source
created: 2023
updated: 2026-04-12
sources: [20260728-230740-local-touvron-2023-llama.pdf.extracted.md]
vault_sha256: 4423905e47e71f175768e5bc57c28fdbee4b4e4e40b0369b114d87d5195956a3
---

LLaMA: Open and Efﬁcient Foundation Language Models Hugo Touvron∗, Thibaut Lavril∗, Gautier Izacard∗, Xavier Martinet Marie-Anne Lachaux, Timothee Lacroix, Baptiste Rozière, Naman Goyal Eric Hambro, Faisal Azhar, Aurelien Rodriguez, Armand Joulin Edouard Grave∗, Guillaume Lample∗ Meta AI Abstract We introduce LLaMA, a collection of founda- tion language models ranging from 7B to 65B parameters. We train our models on trillions (vault:20260728-230740-local-touvron-2023-llama.pdf.extracted.md)

<!-- extracted-tables -->
## Extracted tables (16)

- [[tab-touvron-2023-llama-open-efficient-t1]] — Table p.2 — Table 1: Pre-training data. Data mixtures used for pretraining: sampling proportion, number of epochs on the subset when training on 1.4T tokens, and disk size.
- [[tab-touvron-2023-llama-open-efficient-t10]] — Table p.7 — Table 10: Instruction finetuning - MMLU (5-shot). Comparison of models of moderate size with and without instruction finetuning on MMLU. Single MMLU score per model.
- [[tab-touvron-2023-llama-open-efficient-t11]] — Table p.8 — Table 11: RealToxicityPrompts. Averaged toxicity score (0=non-toxic, 1=toxic) on Basic and Respectful prompt categories, LLaMA models only.
- [[tab-touvron-2023-llama-open-efficient-t12]] — Table p.9 — Table 12: CrowS-Pairs. Bias score by category (higher = higher bias), comparing LLaMA-65B, GPT3-175B and OPT-175B.
- [[tab-touvron-2023-llama-open-efficient-t13]] — Table p.10 — Table 13: WinoGender. Co-reference resolution accuracy for LLaMA models (7B/13B/33B/65B), by pronoun category including 'gotcha' subsets.
- [[tab-touvron-2023-llama-open-efficient-t14]] — Table p.10 — Table 14: TruthfulQA. Fraction of truthful and truthful*informative answers. GPT-3, LLaMA.
- [[tab-touvron-2023-llama-open-efficient-t15]] — Table p.11 — Table 15: Carbon footprint of training different models in the same data center. OPT-175B, BLOOM-175B, LLaMA 7B/13B/33B/65B.
- [[tab-touvron-2023-llama-open-efficient-t16]] — Table p.18 — Table 16 (Appendix B, MMLU): Detailed 5-shot results per subject/domain on the MMLU test sets, comparing GPT-3, Gopher, Chinchilla, LLaMA (7B/13B/33B/65B), and LLaMA-I (65B). Includes 57 individual subject rows plus 4 category-average rows (Humanities, STEM, Social Science, Others) and an overall 'All' row.
- [[tab-touvron-2023-llama-open-efficient-t2]] — Table p.3 — Table 2: Model sizes, architectures, and optimization hyper-parameters.
- [[tab-touvron-2023-llama-open-efficient-t3]] — Table p.4 — Table 3: Zero-shot performance on Common Sense Reasoning tasks (BoolQ, PIQA, SIQA, HellaSwag, WinoGrande, ARC-e, ARC-c, OBQA), comparing GPT-3, Gopher, Chinchilla, PaLM, PaLM-cont and LLaMA.
- [[tab-touvron-2023-llama-open-efficient-t4]] — Table p.4 — Table 4: NaturalQuestions. Exact match performance, 0/1/5/64-shot, GPT-3, Gopher, Chinchilla, PaLM, LLaMA.
- [[tab-touvron-2023-llama-open-efficient-t5]] — Table p.5 — Table 5: TriviaQA. Zero-shot and few-shot exact match performance on the filtered dev set. Gopher, Chinchilla, LLaMA.
- [[tab-touvron-2023-llama-open-efficient-t6]] — Table p.5 — Table 6: Reading Comprehension. Zero-shot accuracy on RACE-middle and RACE-high. GPT-3, PaLM, LLaMA.
- [[tab-touvron-2023-llama-open-efficient-t7]] — Table p.6 — Table 7: Model performance on quantitative reasoning datasets (MATH, GSM8k), with and without maj1@k majority voting. PaLM, Minerva, LLaMA.
- [[tab-touvron-2023-llama-open-efficient-t8]] — Table p.6 — Table 8: Model performance for code generation. pass@1 and pass@100 (HumanEval) / pass@1 and pass@80 (MBPP). LaMDA, PaLM, PaLM-cont, LLaMA. Values marked with * are read from figures in Chowdhery et al. (2022).
- [[tab-touvron-2023-llama-open-efficient-t9]] — Table p.7 — Table 9: Massive Multitask Language Understanding (MMLU). Five-shot accuracy by domain group. GPT-NeoX, GPT-3, Gopher, Chinchilla, PaLM, LLaMA.
<!-- /extracted-tables -->
