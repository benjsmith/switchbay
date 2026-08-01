---
title: "[tab] Table p.9 — Table 4: Multi-Lingual HE Pass@1 scores across C++, Java, PHP, TS, C#, Bash using MultiPL-E, zero-shot greedy decoding — roziere-2023-code-llama-open"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230737-local-roziere-2023-code-llama.pdf.extracted.md"]
extracted_from: roziere-2023-code-llama-open
table_index: 4
row_count: 21
is_snapshot: false
db_table: tab_roziere_2023_code_llama_open_t4
extraction_sha: 05ed05d2d76c420b6af4a1afe6e1dec99939ccf62c5a0c0a258b09cbe1889346
extraction_method: multimodal-sonnet
source_pages: ["9"]
numeric_review_done: 2026-08-01T07:24:27Z
verdict: ok
---

Extracted from [[roziere-2023-code-llama-open]] (vault:20260728-230737-local-roziere-2023-code-llama.pdf.extracted.md), source pages [9], original: vault/roziere-2023-code-llama.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

> **The paper disagrees with itself here.** This table (p.9, Table 4) and
> [[tab-roziere-2023-code-llama-open-t11]] (p.29, Table 11) report different
> MultiPL-E values for the same models: Llama-v2 70B Java is **31.7%** here and
> **31.6%** there (average **24.4** vs **24.8**); Code Llama 13B C# is **27.3%**
> here and **27.2%** there. Both transcriptions were verified against their page
> images. Cite by table, not just by paper.

<!-- cross-table-conflicts -->
> **This source reports conflicting values for these cells in more than one of its own tables.** Both transcriptions were verified against the source page; the disagreement is the paper's, not a transcription error. Check the source before citing either number.
>
> - `code llama` / `average`: **26.3%** here, **28.6%** in [[tab-roziere-2023-code-llama-open-t11]]
> - `code llama` / `bash`: **12.0%** here, **13.3%** in [[tab-roziere-2023-code-llama-open-t11]]
> - `code llama` / `c#`: **25.3%** here, **21.5%** in [[tab-roziere-2023-code-llama-open-t11]]
> - `code llama` / `c++`: **28.6%** here, **31.1%** in [[tab-roziere-2023-code-llama-open-t11]]
> - `code llama` / `java`: **34.2%** here, **36.1%** in [[tab-roziere-2023-code-llama-open-t11]]
> - `code llama` / `php`: **24.2%** here, **30.4%** in [[tab-roziere-2023-code-llama-open-t11]]
> - `code llama - python` / `bash`: **16.5%** here, **11.4%** in [[tab-roziere-2023-code-llama-open-t11]]
> - `code llama - python` / `c#`: **24.7%** here, **21.5%** in [[tab-roziere-2023-code-llama-open-t11]]
> - `code llama - python` / `java`: **35.4%** here, **32.3%** in [[tab-roziere-2023-code-llama-open-t11]]
> - `code llama - python` / `php`: **32.3%** here, **29.2%** in [[tab-roziere-2023-code-llama-open-t11]]
<!-- /cross-table-conflicts -->

| Model | Size | C++ | Java | PHP | TS | C# | Bash | Average |
|---|---|---|---|---|---|---|---|---|
| CodeGen-Multi | 16B | 21.0% | 22.2% | 8.4% | 20.1% | 8.2% | 0.6% | 13.4% |
| CodeGeeX | 13B | 16.9% | 19.1% | 13.5% | 10.1% | 8.5% | 2.8% | 11.8% |
| code-cushman-001 | 12B | 30.6% | 31.9% | 28.9% | 31.3% | 22.1% | 11.7% | 26.1% |
| StarCoder Base | 15.5B | 30.6% | 28.5% | 26.8% | 32.2% | 20.6% | 11.0% | 25.0% |
| StarCoder Python | 15.5B | 31.6% | 30.2% | 26.1% | 32.3% | 21.0% | 10.5% | 25.3% |
| Llama-v2 | 7B | 6.8% | 10.8% | 9.9% | 12.6% | 6.3% | 3.2% | 8.3% |
| Llama-v2 | 13B | 13.7% | 15.8% | 13.1% | 13.2% | 9.5% | 3.2% | 11.4% |
| Llama-v2 | 34B | 23.6% | 22.2% | 19.9% | 21.4% | 17.1% | 3.8% | 18.0% |
| Llama-v2 | 70B | 30.4% | 31.7% | 34.2% | 15.1% | 25.9% | 8.9% | 24.4% |
| Code Llama | 7B | 28.6% | 34.2% | 24.2% | 33.3% | 25.3% | 12.0% | 26.3% |
| Code Llama | 13B | 39.1% | 38.0% | 34.2% | 29.6% | 27.3% | 15.2% | 30.6% |
| Code Llama | 34B | 47.8% | 45.6% | 44.1% | 33.3% | 30.4% | 17.1% | 36.4% |
| Code Llama | 70B | 52.8% | 51.9% | 50.9% | 49.1% | 38.0% | 29.1% | 45.3% |
| Code Llama - Instruct | 7B | 31.1% | 30.4% | 28.6% | 32.7% | 21.6% | 10.1% | 25.8% |
| Code Llama - Instruct | 13B | 42.2% | 40.5% | 32.3% | 39.0% | 24.0% | 13.9% | 32.0% |
| Code Llama - Instruct | 34B | 45.3% | 43.7% | 36.6% | 40.3% | 31.0% | 19.6% | 36.1% |
| Code Llama - Instruct | 70B | 53.4% | 58.2% | 58.4% | 39.0% | 36.7% | 29.7% | 45.9% |
| Code Llama - Python | 7B | 32.3% | 35.4% | 32.3% | 23.9% | 24.7% | 16.5% | 27.5% |
| Code Llama - Python | 13B | 39.1% | 37.3% | 33.5% | 35.2% | 29.8% | 13.9% | 31.5% |
| Code Llama - Python | 34B | 42.2% | 44.9% | 42.9% | 34.3% | 31.7% | 14.6% | 35.1% |
| Code Llama - Python | 70B | 54.7% | 57.6% | 53.4% | 44.0% | 34.8% | 25.3% | 45.0% |
