---
title: "[tab] Table p.39 — Table 25: BOLD profession-domain sentiment scores across 18 profession subgroups (Metal-working, Sewing, Healthcare, Computer, Film & television, Artistic, Scientific, Entertainer, Dance, Nursing specialties, Writing, Professional driver types, Engineering branches, Mental health, Theatre personnel, Corporate titles, Industrial, Railway industry) for pretrained and instruct models — roziere-2023-code-llama-open"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230737-local-roziere-2023-code-llama.pdf.extracted.md"]
extracted_from: roziere-2023-code-llama-open
table_index: 25
row_count: 19
is_snapshot: false
db_table: tab_roziere_2023_code_llama_open_t25
extraction_sha: 05ed05d2d76c420b6af4a1afe6e1dec99939ccf62c5a0c0a258b09cbe1889346
extraction_method: multimodal-sonnet
source_pages: ["39"]
numeric_review_done: 2026-08-01T07:36:27Z
verdict: wrong
review_required: true
flagged_cells_count: 2
backup_id: bk-c55ce446
---

Extracted from [[roziere-2023-code-llama-open]] (vault:20260728-230737-local-roziere-2023-code-llama.pdf.extracted.md), source pages [39], original: vault/roziere-2023-code-llama.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

> **Unresolved — human spot-check wanted.** The `Llama 2 Chat 13B` row's
> `Artistic` / `Scientific` pair was corrected from `0.294 / 0.448` to
> `0.448 / 0.294` at **medium** confidence only. Two readers agreed against the
> 900 dpi page render, but both saw this page before the image, so priming
> cannot be excluded, and the vault text extraction carries no appendix table
> text to corroborate against. Every other cell in this table (305 of 306) was
> verified without dispute. If you cite that pair, check the printed paper.
> Reversible: `tables.py restore-backup tab-roziere-2023-code-llama-open-t25 bk-c55ce446`.

| Model | Metal-working | Sewing | Healthcare | Computer | Film & television | Artistic | Scientific | Entertainer | Dance | Nursing specialties | Writing | Professional driver types | Engineering branches | Mental health | Theatre personnel | Corporate titles | Industrial | Railway industry |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Pretrained models |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| Falcon 7B | 0.223 | 0.227 | 0.345 | 0.424 | 0.350 | 0.319 | 0.215 | 0.303 | 0.262 | 0.457 | 0.310 | 0.229 | 0.200 | 0.322 | 0.374 | 0.515 | 0.190 | 0.259 |
| MPT 7B | 0.239 | 0.283 | 0.377 | 0.532 | 0.348 | 0.364 | 0.235 | 0.326 | 0.334 | 0.532 | 0.320 | 0.127 | 0.217 | 0.288 | 0.426 | 0.592 | 0.355 | 0.382 |
| StarCoder (Python) 15.5B | 0.200 | 0.172 | 0.250 | 0.457 | 0.287 | 0.308 | 0.241 | 0.238 | 0.234 | 0.457 | 0.290 | 0.142 | 0.216 | 0.253 | 0.352 | 0.482 | 0.254 | 0.245 |
| Llama 2 7B | 0.283 | 0.255 | 0.287 | 0.497 | 0.364 | 0.367 | 0.209 | 0.338 | 0.320 | 0.497 | 0.283 | 0.192 | 0.259 | 0.319 | 0.445 | 0.509 | 0.299 | 0.250 |
| Llama 2 13B | 0.245 | 0.255 | 0.347 | 0.501 | 0.415 | 0.361 | 0.241 | 0.388 | 0.351 | 0.479 | 0.310 | 0.179 | 0.269 | 0.339 | 0.463 | 0.663 | 0.351 | 0.283 |
| Llama 2 34B | 0.270 | 0.241 | 0.333 | 0.563 | 0.411 | 0.364 | 0.262 | 0.332 | 0.361 | 0.534 | 0.334 | 0.069 | 0.259 | 0.297 | 0.454 | 0.560 | 0.256 | 0.351 |
| Code Llama 7B | 0.109 | 0.098 | 0.209 | 0.321 | 0.174 | 0.218 | 0.123 | 0.208 | 0.191 | 0.305 | 0.187 | 0.101 | 0.127 | 0.204 | 0.283 | 0.333 | 0.141 | 0.213 |
| Code Llama 13B | 0.109 | 0.119 | 0.176 | 0.349 | 0.136 | 0.184 | 0.112 | 0.097 | 0.132 | 0.312 | 0.190 | 0.106 | 0.110 | 0.212 | 0.225 | 0.424 | 0.171 | 0.245 |
| Code Llama 34B | 0.140 | 0.175 | 0.213 | 0.283 | 0.252 | 0.237 | 0.167 | 0.249 | 0.229 | 0.364 | 0.208 | 0.137 | 0.132 | 0.188 | 0.346 | 0.438 | 0.259 | 0.180 |
| Instruct (aligned) |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| Falcon-instruct 7B | 0.356 | 0.305 | 0.483 | 0.623 | 0.483 | 0.455 | 0.309 | 0.466 | 0.400 | 0.571 | 0.428 | 0.195 | 0.295 | 0.562 | 0.474 | 0.627 | 0.495 | 0.480 |
| MPT-instruct 7B | 0.221 | 0.192 | 0.282 | 0.443 | 0.270 | 0.256 | 0.188 | 0.281 | 0.302 | 0.545 | 0.244 | 0.048 | 0.196 | 0.391 | 0.332 | 0.484 | 0.198 | 0.187 |
| Llama 2 Chat 7B | 0.441 | 0.416 | 0.452 | 0.707 | 0.542 | 0.537 | 0.332 | 0.544 | 0.533 | 0.545 | 0.619 | 0.295 | 0.357 | 0.582 | 0.531 | 0.607 | 0.362 | 0.374 |
| Llama 2 Chat 13B | 0.368 | 0.371 | 0.414 | 0.520 | 0.438 | 0.448 | 0.294 | 0.459 | 0.493 | 0.500 | 0.480 | 0.288 | 0.310 | 0.576 | 0.413 | 0.583 | 0.331 | 0.400 |
| Llama 2 Chat 34B | 0.400 | 0.370 | 0.428 | 0.586 | 0.545 | 0.492 | 0.318 | 0.483 | 0.501 | 0.576 | 0.532 | 0.254 | 0.336 | 0.601 | 0.495 | 0.626 | 0.442 | 0.404 |
| Code Llama - Instruct 7B | 0.384 | 0.333 | 0.382 | 0.543 | 0.490 | 0.436 | 0.272 | 0.482 | 0.347 | 0.547 | 0.481 | 0.135 | 0.297 | 0.513 | 0.438 | 0.555 | 0.347 | 0.410 |
| Code Llama - Instruct 13B | 0.331 | 0.255 | 0.362 | 0.493 | 0.404 | 0.355 | 0.232 | 0.347 | 0.424 | 0.535 | 0.401 | 0.214 | 0.245 | 0.496 | 0.393 | 0.559 | 0.292 | 0.358 |
| Code Llama - Instruct 34B | 0.400 | 0.333 | 0.463 | 0.625 | 0.458 | 0.455 | 0.293 | 0.452 | 0.482 | 0.597 | 0.447 | 0.213 | 0.327 | 0.498 | 0.475 | 0.614 | 0.394 | 0.333 |

## Numeric review (wrong)

Reviewed 2026-08-01T07:36:27Z. 2 cells flagged.
Auto-overwrite applied; previous rows backed up under `bk-c55ce446` in `_extracted_table_backups`. Rewind: `tables.py restore-backup <stem> bk-c55ce446`.

Notes: One transposed pair in 306 cells. Held at medium confidence: both readers saw the page before the image, so priming toward the swapped reading cannot be excluded, and no independent corroboration was available — the vault text extraction carries no appendix table text. Flagged for human spot-check against the printed paper.

- Row 15 / 'Artistic' — claimed `0.294`, suggested `0.448` (medium) — Adjacent-pair transposition in the Llama 2 Chat 13B row. Second reviewer re-rendered p39 at 900 dpi and calibrated ordinal column position against four undisputed rows (Falcon 7B, Llama 2 Chat 7B, Llama 2 Chat 34B, Code Llama Instruct 34B), all of which matched the page exactly; the 13B row then read 0.448 before 0.294 on two separate passes.
- Row 15 / 'Scientific' — claimed `0.448`, suggested `0.294` (medium) — Other half of the same transposition. Bracketing cells (Film & television 0.438, Entertainer 0.459) agree between page and image, so this is an order swap, not a column offset.
