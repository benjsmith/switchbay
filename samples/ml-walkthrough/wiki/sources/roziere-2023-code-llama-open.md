---
title: "[src] Code Llama: Open Foundation Models for Code — roziere, 2023"
type: source
created: 2023
updated: 2026-04-12
sources: [20260728-230737-local-roziere-2023-code-llama.pdf.extracted.md]
vault_sha256: adda6039cb6992349d83e3e297c751bb3f140ddbf38c888833097798e5e88b7d
---

Code Llama: Open Foundation Models for Code Baptiste Rozière†, Jonas Gehring†, Fabian Gloeckle†,∗, Sten Sootla†, Itai Gat, Xiaoqing Ellen Tan, Yossi Adi⋄, Jingyu Liu, Romain Sauvestre, Tal Remez, Jérémy Rapin, Artyom Kozhevnikov, Ivan Evtimov, Joanna Bitton, Manish Bhatt, Cristian Canton Ferrer, Aaron Grattafiori, Wenhan Xiong, Alexandre Défossez, Jade Copet, Faisal Azhar, Hugo Touvron, Louis Martin, Nicolas Usunier, Thomas Scialom, Gabriel Synnaeve† (vault:20260728-230737-local-roziere-2023-code-llama.pdf.extracted.md)

<!-- extracted-tables -->
## Extracted tables (26)

- [[tab-roziere-2023-code-llama-open-t1]] — Table p.5 — Table 1: Training dataset of Code Llama and Code Llama - Python, showing sampling proportion, epochs, and disk size by data category for each training phase
- [[tab-roziere-2023-code-llama-open-t10]] — Table p.28 — Table 10: Full pass@1/10/100 scores on HumanEval and MBPP for Llama 2, Code Llama, and Code Llama - Python across FIM and LCFT ablation configurations
- [[tab-roziere-2023-code-llama-open-t11]] — Table p.29 — Table 11: Multilingual HumanEval (MultiPL-E) detailed pass@1 results per language across FIM/LCFT ablation configurations
- [[tab-roziere-2023-code-llama-open-t12]] — Table p.29 — Table 12: GSM8K solve rate for Llama 2, Code Llama, and Code Llama - Python
- [[tab-roziere-2023-code-llama-open-t13]] — Table p.30 — Table 13: CodeXGLUE code-to-text (docstring generation) BLEU scores, comparing InCoder/SantaCoder/StarCoder to Code Llama with/without LCFT
- [[tab-roziere-2023-code-llama-open-t14]] — Table p.31 — Table 14: HumanEval single-line, multi-line, and random-span infilling exact-match rates in PSM/SPM format, comparing reference models to Code Llama with/without LCFT
- [[tab-roziere-2023-code-llama-open-t15]] — Table p.31 — Table 15: Code Llama - Instruct zero-shot APPS results (pass@5/10/100 across Introductory/Interview/Competition splits)
- [[tab-roziere-2023-code-llama-open-t16]] — Table p.32 — Table 16: LCC dataset statistics (code-token and Code Llama-tokenizer token counts: average, 25th/50th/75th percentile) for LCC test set and LCC-balanced, by language
- [[tab-roziere-2023-code-llama-open-t17]] — Table p.33 — Table 17: Function Key Retrieval Accuracy (%) for Code Llama and Code Llama - Instruct at 7B/13B/34B, and gpt-3.5-turbo-16k-0630, across context lengths 8000/16000/24000 tokens and key positions 0/0.2/0.4
- [[tab-roziere-2023-code-llama-open-t18]] — Table p.33 — Table 18: Function Key Retrieval Accuracy (%) ablations of RoPE base-period configuration, comparing pre-LCFT and post-LCFT settings across context lengths 4000/8000/16000/24000 and key positions 0/0.2/0.4
- [[tab-roziere-2023-code-llama-open-t19]] — Table p.37 — Table 19: TruthfulQA evaluation results (percent true+informative, percent informative, percent true) across pretrained and instruct model generations
- [[tab-roziere-2023-code-llama-open-t2]] — Table p.6 — Table 2: Code Llama pass@1/10/100 scores on HumanEval and MBPP, compared against other published models
- [[tab-roziere-2023-code-llama-open-t20]] — Table p.37 — Table 20: ToxiGen toxicity percentage by demographic group (Asian, Mexican, Muslim, Physical disability, Jewish, Middle Eastern, Chinese, Mental disability, Latino, Native American, Women, Black, LGBTQ) for pretrained and instruct models
- [[tab-roziere-2023-code-llama-open-t21]] — Table p.38 — Table 21: BOLD race-domain sentiment scores (Asian Americans, African Americans, European Americans, Hispanic and Latino Americans) for pretrained and instruct models
- [[tab-roziere-2023-code-llama-open-t22]] — Table p.38 — Table 22: BOLD gender-domain sentiment scores (American actors, American actresses) for pretrained and instruct models
- [[tab-roziere-2023-code-llama-open-t23]] — Table p.39 — Table 23: BOLD religious-ideology-domain sentiment scores (Judaism, Christianity, Islam, Buddhism, Sikhism) for pretrained and instruct models
- [[tab-roziere-2023-code-llama-open-t24]] — Table p.39 — Table 24: BOLD political-ideology-domain sentiment scores (Left-wing, Right-wing, Communism, Socialism, Democracy, Liberalism, Populism, Conservatism, Nationalism, Anarchism, Capitalism, Fascism) for pretrained and instruct models
- [[tab-roziere-2023-code-llama-open-t25]] — Table p.39 — Table 25: BOLD profession-domain sentiment scores across 18 profession subgroups (Metal-working, Sewing, Healthcare, Computer, Film & television, Artistic, Scientific, Entertainer, Dance, Nursing specialties, Writing, Professional driver types, Engineering branches, Mental health, Theatre personnel, Corporate titles, Industrial, Railway industry) for pretrained and instruct models
- [[tab-roziere-2023-code-llama-open-t26]] — Table p.42 — Table 26: Model card for Code Llama and its variants (details, intended use, hardware/software, training data, evaluation, ethical considerations)
- [[tab-roziere-2023-code-llama-open-t3]] — Table p.8 — Table 3: APPS pass@ scores (Introductory/Interview/Competition difficulty splits) for Code Llama, Code Llama - Python, and Code Llama - Instruct at multiple sizes, plus reference numbers for GPT-Neo, Codex, and AlphaCode
- [[tab-roziere-2023-code-llama-open-t4]] — Table p.9 — Table 4: Multi-Lingual HE Pass@1 scores across C++, Java, PHP, TS, C#, Bash using MultiPL-E, zero-shot greedy decoding
- [[tab-roziere-2023-code-llama-open-t5]] — Table p.11 — Table 5: Comparison of Code Llama models with and without FIM (infilling) training, on HumanEval/MBPP pass@1/10/100 and autoregressive test loss, prior to long-context fine-tuning (LCFT)
- [[tab-roziere-2023-code-llama-open-t6]] — Table p.11 — Table 6: Multilingual HumanEval single line infilling with MultiPL-E, exact match rates in PSM and SPM format for Python, Java, JavaScript
- [[tab-roziere-2023-code-llama-open-t7]] — Table p.12 — Table 7: Average single line completion performance on LCC-balanced (exact match and BLEU), comparing models before/after long-context fine-tuning, across three context-length buckets
- [[tab-roziere-2023-code-llama-open-t8]] — Table p.14 — Table 8: Impact of self-instruct (SI) data on HumanEval and MBPP (3-shot and zero-shot) scores, greedy decoding
- [[tab-roziere-2023-code-llama-open-t9]] — Table p.17 — Table 9: Evaluations on safety datasets (TruthfulQA, ToxiGen, BOLD) for pretrained (base) and instruct (aligned) models
<!-- /extracted-tables -->
