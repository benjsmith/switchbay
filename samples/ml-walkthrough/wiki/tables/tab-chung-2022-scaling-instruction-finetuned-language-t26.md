---
title: "[tab] Table p.52 — Table 26: Flan-T5 model card — chung-2022-scaling-instruction-finetuned-language"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230728-local-chung-2022-flan.pdf.extracted.md"]
extracted_from: chung-2022-scaling-instruction-finetuned-language
table_index: 26
row_count: 27
is_snapshot: false
db_table: tab_chung_2022_scaling_instruction_finetuned_language_t26
extraction_sha: 771f758c1b711c2a63ca2439e80ab90751351d721632897a058c0205ba9e2a22
extraction_method: multimodal-sonnet
source_pages: ["52"]
numeric_review_done: 2026-07-30T22:31:40Z
verdict: ok
---

Extracted from [[chung-2022-scaling-instruction-finetuned-language]] (vault:20260728-230728-local-chung-2022-flan.pdf.extracted.md), source pages [52], original: vault/chung-2022-flan.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

| Model Summary |  |
|---|---|
| Model architecture | Dense encoder-decoder models of 5 different sizes. See Table 2. |
| Input(s) | The model takes text as input. See https://github.com/google-research/t5x/blob/main/docs/models.md |
| Output(s) | The model generates text as output. See https://github.com/google-research/t5x/blob/main/docs/models.md |
| Usage |  |
| Application | The primary use is research on language models, including: research on zero-shot NLP tasks and in-context few-shot learning NLP tasks, such as reasoning, and question answering; advancing fairness and safety research, and understanding limitations of current large language models. |
| Known Caveats | Language models, including Flan-T5, can potentially be used for language generation in a harmful way, according to Rae et al. (2021a). Flan-T5 should not be used directly in any application, without a prior assessment of safety and fairness concerns specific to the application. |
| System Type |  |
| System Description | This is a standalone model. |
| Upstream Dependencies | None. |
| Upstream Dependencies | None. |
| Implementation Frameworks |  |
| Hardware & Software for Training | Hardware: TPU v3 or TPU v4 (Jouppi et al., 2020). Software: T5X (Roberts et al., 2022), JAX (Bradbury et al., 2018). |
| Hardware & Software for Deployment | Hardware: TPU v3 or TPU v4 (Jouppi et al., 2020). Software: T5X (Roberts et al., 2022). |
| Compute Requirements | Number of chips ≥ 4. |
| Model Characteristics |  |
| Model Initialization | These models are based on pretrained T5 (Raffel et al., 2020) and fine-tuned with instructions for better zero-shot and few-shot performance. There is one fine-tuned Flan model per T5 model size. |
| Model Status | This is a static model trained on an offline dataset. |
| Model Stats | Flan-T5-small has 77 million weights. Flan-T5-base has 250 million weights. Flan-T5-large has 780 million weights. Flan-T5-XL has 3 billion weights. Flan-T5-XXL has 11 billion weights. See Table 2 for details. |
| Data Overview |  |
| Fine-tuning Dataset | See Section 2.1. |
| Evaluation Dataset | See Section 2.3. |
| Evaluation Results |  |
| Evaluation Results | See Table 5. |
| Model Usage & Limitations |  |
| Sensitive Use | Flan-T5 should not be applied for any unacceptable use cases, e.g., generation of abusive speech. |
| Known Limitations | Flan-T5 has not been tested in real world applications. |
| Ethical Considerations & Risks | Flan-T5 is fine-tuned on a large corpus of text data that was not filtered for explicit content or assessed for existing biases. As a result the model itself is potentially vulnerable to generating equivalently inappropriate content or replicating inherent biases in the underlying data. |
