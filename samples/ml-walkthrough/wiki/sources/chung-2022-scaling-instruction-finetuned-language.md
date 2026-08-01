---
title: "[src] Scaling Instruction-Finetuned Language Models — chung, 2022"
type: source
created: 2022
updated: 2026-04-12
sources: [20260728-230728-local-chung-2022-flan.pdf.extracted.md]
vault_sha256: 30a90be0cc0ff75cd94e6485cb4d894d59c6814d714c13fa2f14ae5202682e3a
---

Scaling Instruction-Finetuned Language Models Hyung Won Chung∗ Le Hou∗ Shayne Longpre∗ Barret Zoph† Yi Tay† William Fedus† Yunxuan Li Xuezhi Wang Mostafa Dehghani Siddhartha Brahma Albert Webson Shixiang Shane Gu Zhuyun Dai Mirac Suzgun Xinyun Chen Aakanksha Chowdhery Alex Castro-Ros Marie Pellat Kevin Robinson Dasha Valter Sharan Narang Gaurav Mishra Adams Yu Vincent Zhao Yanping Huang Andrew Dai Hongkun Yu Slav Petrov Ed H. Chi (vault:20260728-230728-local-chung-2022-flan.pdf.extracted.md)

<!-- extracted-tables -->
## Extracted tables (26)

- [[tab-chung-2022-scaling-instruction-finetuned-language-t1]] — Table p.2 — Table 1: average 5-shot MMLU scores (%), models vs. human baselines vs. forecasts
- [[tab-chung-2022-scaling-instruction-finetuned-language-t10]] — Table p.33 — Table 10: translation misgendering performance, disaggregated by model/pronoun/slice
- [[tab-chung-2022-scaling-instruction-finetuned-language-t11]] — Table p.35 — Table 11: MMLU[:10] individual task performance (tasks 1-10 of 57)
- [[tab-chung-2022-scaling-instruction-finetuned-language-t12]] — Table p.36 — Table 12: MMLU[10:20] individual task performance (tasks 11-20 of 57)
- [[tab-chung-2022-scaling-instruction-finetuned-language-t13]] — Table p.37 — Table 13: MMLU[20:30] individual task performance (tasks 21-30 of 57)
- [[tab-chung-2022-scaling-instruction-finetuned-language-t14]] — Table p.38 — Table 14: MMLU[30:40] individual task performance (tasks 31-40 of 57)
- [[tab-chung-2022-scaling-instruction-finetuned-language-t15]] — Table p.39 — Table 15: MMLU[40:50] individual task performance (tasks 41-50 of 57)
- [[tab-chung-2022-scaling-instruction-finetuned-language-t16]] — Table p.40 — Table 16: MMLU[50:57] individual task performance (tasks 51-57 of 57) + overall Average
- [[tab-chung-2022-scaling-instruction-finetuned-language-t17]] — Table p.41 — Table 17: BBH[:9] individual task performance (tasks 1-9 of 27)
- [[tab-chung-2022-scaling-instruction-finetuned-language-t18]] — Table p.42 — Table 18: BBH[9:18] individual task performance (tasks 10-18 of 27)
- [[tab-chung-2022-scaling-instruction-finetuned-language-t19]] — Table p.43 — Table 19: BBH[18:27] individual task performance (tasks 19-27 of 27) + overall Average
- [[tab-chung-2022-scaling-instruction-finetuned-language-t2]] — Table p.5 — Table 2: model sizes, architectures and finetuning compute
- [[tab-chung-2022-scaling-instruction-finetuned-language-t20]] — Table p.44 — Table 20: TyDiQA per-language performance (exact match)
- [[tab-chung-2022-scaling-instruction-finetuned-language-t21]] — Table p.45 — Table 21: MGSM per-language performance
- [[tab-chung-2022-scaling-instruction-finetuned-language-t22]] — Table p.46 — Table 22: hyperparameters used for all finetuned models
- [[tab-chung-2022-scaling-instruction-finetuned-language-t23]] — Table p.46 — Table 23: maximum example cap and mixture proportion rates
- [[tab-chung-2022-scaling-instruction-finetuned-language-t24]] — Table p.47 — Table 24: finetuning data card — collections and individual datasets
- [[tab-chung-2022-scaling-instruction-finetuned-language-t25]] — Table p.51 — Table 25: Flan-PaLM model card
- [[tab-chung-2022-scaling-instruction-finetuned-language-t26]] — Table p.52 — Table 26: Flan-T5 model card
- [[tab-chung-2022-scaling-instruction-finetuned-language-t3]] — Table p.7 — Table 3: effect of scaling number of finetuning tasks (8B/62B/540B PaLM)
- [[tab-chung-2022-scaling-instruction-finetuned-language-t4]] — Table p.8 — Table 4: Flan-PaLM vs. PaLM 540B on MMLU/BBH-nlp/BBH-alg/TyDiQA/MGSM
- [[tab-chung-2022-scaling-instruction-finetuned-language-t5]] — Table p.11 — Table 5: instruction finetuning (Flan) vs. base models, all model families
- [[tab-chung-2022-scaling-instruction-finetuned-language-t6]] — Table p.27 — Table 6: probability (%) of generating a toxic continuation, non-toxic vs. toxic prompts
- [[tab-chung-2022-scaling-instruction-finetuned-language-t7]] — Table p.30 — Table 7: toxicity classification AUC on CivilComments
- [[tab-chung-2022-scaling-instruction-finetuned-language-t8]] — Table p.32 — Table 8: translation misgendering languages (26) by resource level
- [[tab-chung-2022-scaling-instruction-finetuned-language-t9]] — Table p.33 — Table 9: examples of translation misgendering evaluation sets and scoring
<!-- /extracted-tables -->
