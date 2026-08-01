---
title: "[tab] Table p.42 — Table 26: Model card for Code Llama and its variants (details, intended use, hardware/software, training data, evaluation, ethical considerations) — roziere-2023-code-llama-open"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230737-local-roziere-2023-code-llama.pdf.extracted.md"]
extracted_from: roziere-2023-code-llama-open
table_index: 26
row_count: 16
is_snapshot: false
db_table: tab_roziere_2023_code_llama_open_t26
extraction_sha: 05ed05d2d76c420b6af4a1afe6e1dec99939ccf62c5a0c0a258b09cbe1889346
extraction_method: multimodal-sonnet
source_pages: ["42"]
numeric_review_done: 2026-08-01T07:25:03Z
verdict: ok
---

Extracted from [[roziere-2023-code-llama-open]] (vault:20260728-230737-local-roziere-2023-code-llama.pdf.extracted.md), source pages [42], original: vault/roziere-2023-code-llama.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

| Section | Field | Value |
|---|---|---|
| Model details | Model Developers | Meta AI |
| Model details | Variations | Code Llama comes in four model sizes, and three variants: the base Code Llama, Code Llama - Python designed specifically for Python and Code Llama - Instruct for instruction following and safer deployment. All variants are available in sizes of 7B, 13B, 34B and 70B parameters. |
| Model details | Input | Models input text only. |
| Model details | Output | Models output text only. |
| Model details | Model Architecture | Code Llama and its variants are autoregressive language models using optimized transformer architectures. Code Llama 7B, 13B and 70B additionally support infilling text generation. All models but Code Llama - Python 70B and Code Llama - Instruct 70B were fine-tuned with up to 16K tokens, and support up to 100K tokens at inference time. |
| Model details | Model Dates | Code Llama and its variants have been trained between January 2023 and January 2024. |
| Model details | Status | This is a static model trained on an offline dataset. Future versions of Code Llama - Instruct will be released as we improve model safety with community feedback. |
| Model details | Licence | A custom commercial license is available at: ai.meta.com/resources/models-and-libraries/llama-downloads/. |
| Model details | Where to send comments | Instructions on how to provide feedback or comments on the model can be found in the model README, or by opening an issue in the GitHub repository (https://github.com/facebookresearch/codellama/). |
| Intended Use | Intended Use Cases | Code Llama and its variants are intended for commercial and research use in English and relevant programming languages. The base model Code Llama can be adapted for a variety of code synthesis and understanding tasks, Code Llama - Python is designed specifically to handle the Python programming language, and Code Llama - Instruct is intended to be safer to use for code assistant and generation applications. |
| Intended Use | Out-of-Scope Uses | Use in any manner that violates applicable laws or regulations (including trade compliance laws). Use in languages other than English. Use in any other way that is prohibited by the Acceptable Use Policy and Licensing Agreement for Code Llama and its variants. |
| Hardware and Software | Training Factors | We used custom training libraries. The training and fine-tuning of the released models have been performed on Meta's Research Super Cluster. |
| Hardware and Software | Carbon Footprint | In aggregate, training all 12 Code Llama models required 1400K GPU hours of computation on hardware of type A100-80GB (TDP of 350-400W). Estimated total emissions were 228.55 tCO2eq, 100% of which were offset by Meta's sustainability program. |
| Training Data |  | All experiments reported here and the released models have been trained and fine-tuned using the same data as Llama 2 (Touvron et al., 2023b) with different weights (see Section 2 and Table 1). Code Llama - Instruct uses additional instruction fine-tuning data. |
| Evaluation Results |  | See evaluations for the main models and detailed ablations Section 3 and safety evaluations Section 4. |
| Ethical Considerations and Limitations |  | Code Llama and its variants are a new technology that carries risks with use. Testing conducted to date has been in English, and has not covered, nor could it cover all scenarios. For these reasons, as with all LLMs, Code Llama's potential outputs cannot be predicted in advance, and the model may in some instances produce inaccurate or objectionable responses to user prompts. Therefore, before deploying any applications of Code Llama, developers should perform safety testing and tuning tailored to their specific applications of the model. Please see the Responsible Use Guide available at https://ai.meta.com/llama/responsible-user-guide. |
