---
title: "[tab] Table p.3 — Related work on reasoning and decision-making: feature comparison of Self-refine, Beam search, and Reflexion (checkmark/cross table, top table under Figure 1) — shinn-2023-reflexion-language-agents"
type: extracted-table
created: 2026-07-28
updated: 2026-07-28
sources: ["20260728-230739-local-shinn-2023-reflexion.pdf.extracted.md"]
extracted_from: shinn-2023-reflexion-language-agents
table_index: 1
row_count: 3
is_snapshot: false
db_table: tab_shinn_2023_reflexion_language_agents_t1
extraction_sha: 6059b6f89fea9959bd3dab553fbb97756a3dfb1b15e3cbab2fbf3ab6664333bd
extraction_method: multimodal-sonnet
source_pages: ["3"]
numeric_review_done: 2026-08-01T07:36:14Z
verdict: wrong
review_required: true
flagged_cells_count: 1
backup_id: bk-29cbfa53
---

Extracted from [[shinn-2023-reflexion-language-agents]] (vault:20260728-230739-local-shinn-2023-reflexion.pdf.extracted.md), source pages [3], original: vault/shinn-2023-reflexion.pdf. Numeric values are literal transcriptions — do not derive or unit-convert when citing this page.

| Approach | Self refine | Hidden constraints | Decision making | Binary reward | Memory |
|---|---|---|---|---|---|
| Self-refine [15] | ✓ | ✗ | ✗ | ✗ | ✗ |
| Beam search [27] | ✓ | ✓ | ✓ | ✓ | ✗ |
| Reflexion (ours) | ✓ | ✓ | ✓ | ✓ | ✓ |

## Numeric review (wrong)

Reviewed 2026-08-01T07:36:14Z. 1 cells flagged.
Auto-overwrite applied; previous rows backed up under `bk-29cbfa53` in `_extracted_table_backups`. Rewind: `tables.py restore-backup <stem> bk-29cbfa53`.

Notes: Single-cell glyph substitution in the top related-work checklist. Memory column reads ✗/✗/✓ top to bottom; all other 14 cells verified correct.

- Row 2 / 'Memory' — claimed `✓`, suggested `✗` (high) — Two independent reviewers read the p3 image as a red cross, not a check. Second reviewer re-rendered at 900 dpi and confirmed the glyph is unambiguously ✗ by colour and stroke shape. As transcribed, Beam search matched Reflexion on all five features, erasing the only distinction the table exists to draw.
