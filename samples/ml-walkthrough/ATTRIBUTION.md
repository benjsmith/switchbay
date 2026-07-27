# Attribution — ML walkthrough sample sources

**Best-effort review applied.** Licenses were checked 2026-07-24 and
re-verified 2026-07-28 against the live arXiv abstract pages
(`creativecommons.org/licenses/…` badge) and Wikipedia’s site-wide
CC BY-SA 4.0. Re-check before redistribution if much time has passed.

## Creative Commons Attribution 4.0 (papers)

Each paper PDF lives in `vault/<slug>.pdf` with a matching
`vault/<slug>.md` sidecar. Required notice: **CC BY 4.0** — credit the
authors, retain a link to the license, indicate changes if you modify.

| Slug | arXiv | Title (short) |
|------|-------|---------------|
| wei-2022-chain-of-thought | [2201.11903](https://arxiv.org/abs/2201.11903) | Chain-of-Thought Prompting |
| yao-2022-react | [2210.03629](https://arxiv.org/abs/2210.03629) | ReAct |
| rafailov-2023-dpo | [2305.18290](https://arxiv.org/abs/2305.18290) | Direct Preference Optimization |
| bai-2022-constitutional-ai | [2212.08073](https://arxiv.org/abs/2212.08073) | Constitutional AI |
| gu-2023-mamba | [2312.00752](https://arxiv.org/abs/2312.00752) | Mamba |
| dettmers-2023-qlora | [2305.14314](https://arxiv.org/abs/2305.14314) | QLoRA |
| chung-2022-flan | [2210.11416](https://arxiv.org/abs/2210.11416) | FLAN / instruction finetuning |
| touvron-2023-llama | [2302.13971](https://arxiv.org/abs/2302.13971) | LLaMA |
| jiang-2023-mistral-7b | [2310.06825](https://arxiv.org/abs/2310.06825) | Mistral 7B |
| jiang-2024-mixtral | [2401.04088](https://arxiv.org/abs/2401.04088) | Mixtral of Experts |
| roziere-2023-code-llama | [2308.12950](https://arxiv.org/abs/2308.12950) | Code Llama |
| gemma-team-2024-gemma | [2403.08295](https://arxiv.org/abs/2403.08295) | Gemma |
| yao-2023-tree-of-thoughts | [2305.10601](https://arxiv.org/abs/2305.10601) | Tree of Thoughts |
| shinn-2023-reflexion | [2303.11366](https://arxiv.org/abs/2303.11366) | Reflexion |
| leviathan-2023-speculative-sampling | [2302.01318](https://arxiv.org/abs/2302.01318) | Speculative decoding |

License URL (all of the above):  
https://creativecommons.org/licenses/by/4.0/

## Creative Commons Attribution-ShareAlike 4.0 (Wikipedia)

Extracts in `vault/wiki-*.md`. **CC BY-SA 4.0** — attribution + share-alike
if you adapt. Prefer linking the live article for full history.

| Slug | Article |
|------|---------|
| wiki-transformer-architecture | [Transformer (deep learning)](https://en.wikipedia.org/wiki/Transformer_(deep_learning_architecture)) |
| wiki-deep-learning | [Deep learning](https://en.wikipedia.org/wiki/Deep_learning) |
| wiki-bert | [BERT (language model)](https://en.wikipedia.org/wiki/BERT_(language_model)) |
| wiki-large-language-model | [Large language model](https://en.wikipedia.org/wiki/Large_language_model) |
| wiki-attention | [Attention (machine learning)](https://en.wikipedia.org/wiki/Attention_(machine_learning)) |
| wiki-cnn | [Convolutional neural network](https://en.wikipedia.org/wiki/Convolutional_neural_network) |
| wiki-rlhf | [RLHF](https://en.wikipedia.org/wiki/Reinforcement_learning_from_human_feedback) |
| wiki-prompt-engineering | [Prompt engineering](https://en.wikipedia.org/wiki/Prompt_engineering) |
| wiki-foundation-model | [Foundation model](https://en.wikipedia.org/wiki/Foundation_model) |
| wiki-rag | [Retrieval-augmented generation](https://en.wikipedia.org/wiki/Retrieval-augmented_generation) |

License URL: https://creativecommons.org/licenses/by-sa/4.0/

## Explicitly excluded (do not re-add without re-audit)

| Category | Why |
|----------|-----|
| arXiv **nonexclusive-distrib/1.0** only (e.g. Attention, BERT, LoRA, FlashAttention, GPT-3/4, ResNet, RAG paper, …) | Not a free redistribution grant for third parties |
| Personal blogs (Karpathy, Weng, Willison, Alammar, …) | Typically all-rights-reserved unless stated |
| APS / publisher HTML (e.g. Behler–Parrinello PRL) | Publisher copyright |
| Materials-chemistry PDF set from projects-test | Mixed / not re-audited for this sample |
| Synthetic smoke / ingest fixtures | Not product content |

## CC BY candidates audited but not included (optional later)

Still **CC BY 4.0** on arXiv as of 2026-07-24; omitted only for size /
walkthrough focus: AgentBench, CodeAct, StreamingLLM, SWE-agent,
Gemini / Gemini-1.5, Gemma-2, PaLM, Qwen, phi-1.5, ChatGLM, survey on
LLM agents, LIMA, MemGPT, Scaling o1 roadmap, etc. Safe to add with the
same sidecar pattern.
