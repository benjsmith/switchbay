---
title: "[tab] Table p.29 — Table 11: Multilingual HumanEval (MultiPL-E) detailed pass@1 results per language across FIM/LCFT ablation configurations — roziere-2023-code-llama-open"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230737-local-roziere-2023-code-llama.pdf.extracted.md"]
extracted_from: roziere-2023-code-llama-open
table_index: 11
row_count: 20
is_snapshot: false
db_table: tab_roziere_2023_code_llama_open_t11
extraction_sha: 05ed05d2d76c420b6af4a1afe6e1dec99939ccf62c5a0c0a258b09cbe1889346
extraction_method: multimodal-sonnet
source_pages: ["29"]
numeric_review_done: 2026-08-01T07:24:38Z
verdict: ok
---

Extracted from [[roziere-2023-code-llama-open]] (vault:20260728-230737-local-roziere-2023-code-llama.pdf.extracted.md), source pages [29], original: vault/roziere-2023-code-llama.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

> **The paper disagrees with itself here.** This table (p.29, Table 11) and
> [[tab-roziere-2023-code-llama-open-t4]] (p.9, Table 4) report different
> MultiPL-E values for the same models: Llama-v2 70B Java is **31.6%** here and
> **31.7%** there (average **24.8** vs **24.4**); Code Llama 13B C# is **27.2%**
> here and **27.3%** there. Both transcriptions were verified against their page
> images. Cite by table, not just by paper.

<!-- cross-table-conflicts -->
> **This source reports conflicting values for these cells in more than one of its own tables.** Both transcriptions were verified against the source page; the disagreement is the paper's, not a transcription error. Check the source before citing either number.
>
> - `code llama` / `average`: **28.6%** here, **26.3%** in [[tab-roziere-2023-code-llama-open-t4]]
> - `code llama` / `bash`: **13.3%** here, **12.0%** in [[tab-roziere-2023-code-llama-open-t4]]
> - `code llama` / `c#`: **21.5%** here, **25.3%** in [[tab-roziere-2023-code-llama-open-t4]]
> - `code llama` / `c++`: **31.1%** here, **28.6%** in [[tab-roziere-2023-code-llama-open-t4]]
> - `code llama` / `java`: **36.1%** here, **34.2%** in [[tab-roziere-2023-code-llama-open-t4]]
> - `code llama` / `php`: **30.4%** here, **24.2%** in [[tab-roziere-2023-code-llama-open-t4]]
> - `code llama - python` / `bash`: **11.4%** here, **16.5%** in [[tab-roziere-2023-code-llama-open-t4]]
> - `code llama - python` / `c#`: **21.5%** here, **24.7%** in [[tab-roziere-2023-code-llama-open-t4]]
> - `code llama - python` / `java`: **32.3%** here, **35.4%** in [[tab-roziere-2023-code-llama-open-t4]]
> - `code llama - python` / `php`: **29.2%** here, **32.3%** in [[tab-roziere-2023-code-llama-open-t4]]
<!-- /cross-table-conflicts -->

| Model | Size | FIM | LCFT | Python | C++ | Java | PHP | TypeScript | C# | Bash | Average |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Llama 2 | 7B | ✗ | ✗ | 14.3% | 6.8% | 10.8% | 9.9% | 12.6% | 6.3% | 3.2% | 8.3% |
| Llama 2 | 13B | ✗ | ✗ | 19.9% | 13.7% | 15.8% | 13.0% | 13.2% | 9.5% | 3.2% | 12.6% |
| Llama 2 | 34B | ✗ | ✗ | 24.2% | 23.6% | 22.2% | 19.9% | 21.4% | 17.1% | 3.8% | 18.9% |
| Llama 2 | 70B | ✗ | ✗ | 27.3% | 30.4% | 31.6% | 34.2% | 15.1% | 25.9% | 8.9% | 24.8% |
| Code Llama | 7B | ✗ | ✗ | 37.3% | 31.1% | 36.1% | 30.4% | 30.4% | 21.5% | 13.3% | 28.6% |
| Code Llama | 7B | ✓ | ✗ | 29.2% | 29.8% | 38.0% | 24.8% | 35.8% | 26.6% | 8.2% | 26.3% |
| Code Llama | 7B | ✗ | ✓ | 34.2% | 31.1% | 36.7% | 31.7% | 27.7% | 25.3% | 13.9% | 28.6% |
| Code Llama | 7B | ✓ | ✓ | 30.4% | 28.6% | 34.2% | 24.2% | 33.3% | 25.3% | 12.0% | 26.9% |
| Code Llama | 13B | ✗ | ✗ | 38.5% | 40.4% | 43.0% | 39.1% | 34.0% | 28.5% | 15.8% | 34.2% |
| Code Llama | 13B | ✓ | ✗ | 36.6% | 43.5% | 43.0% | 40.4% | 38.4% | 25.9% | 12.7% | 33.7% |
| Code Llama | 13B | ✗ | ✓ | 36.6% | 38.5% | 38.6% | 34.2% | 34.0% | 27.8% | 16.5% | 32.3% |
| Code Llama | 13B | ✓ | ✓ | 33.5% | 39.1% | 38.0% | 34.2% | 29.6% | 27.2% | 15.2% | 31.0% |
| Code Llama | 34B | ✗ | ✗ | 48.4% | 45.3% | 46.2% | 39.8% | 26.4% | 29.7% | 18.4% | 37.3% |
| Code Llama | 34B | ✗ | ✓ | 42.9% | 47.8% | 45.6% | 44.1% | 33.3% | 30.4% | 17.1% | 37.3% |
| Code Llama - Python | 7B | ✗ | ✗ | 40.4% | 32.3% | 32.3% | 29.2% | 25.2% | 21.5% | 11.4% | 27.5% |
| Code Llama - Python | 7B | ✗ | ✓ | 40.4% | 32.3% | 35.4% | 32.3% | 23.9% | 24.7% | 16.5% | 29.4% |
| Code Llama - Python | 13B | ✗ | ✗ | 50.3% | 44.1% | 46.8% | 43.5% | 42.1% | 33.5% | 16.5% | 39.6% |
| Code Llama - Python | 13B | ✗ | ✓ | 48.4% | 39.1% | 37.3% | 33.5% | 35.2% | 29.7% | 13.9% | 33.9% |
| Code Llama - Python | 34B | ✗ | ✗ | 59.0% | 42.9% | 39.9% | 44.1% | 23.9% | 29.7% | 18.4% | 36.8% |
| Code Llama - Python | 34B | ✗ | ✓ | 54.0% | 42.2% | 44.9% | 42.9% | 34.3% | 31.6% | 14.6% | 37.8% |
