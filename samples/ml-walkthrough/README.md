# Sample ML walkthrough corpus

Small, **license-clean** machine-learning corpus for Switch Bay’s first-run
/ product walkthrough: the demo workspace that guided tour runs against, so
it has real pages, citations, tables and a populated graph to show rather
than an empty scaffold. Built by curating `vault/` with curiosity-engine —
**not** an excision of an existing test vault.

## What is here

| Kind | Count | License | Notes |
|------|------:|---------|--------|
| arXiv paper PDFs + attribution sidecars | 15 | **CC BY 4.0** | Verified on arXiv abs pages 2026-07-24 |
| Wikipedia plain-text extracts | 10 | **CC BY-SA 4.0** | Attribution + revid in frontmatter |

**No blogs**, Medium posts, or arXiv *nonexclusive-distrib* papers.
Classics such as *Attention Is All You Need*, BERT, LoRA, FlashAttention,
GPT-3/4, ResNet, etc. are **not redistributed as PDFs** here — those abs
pages still use arXiv’s default non-exclusive license, which does not
grant third-party redistribution rights. Coverage for those ideas is via
Wikipedia (CC BY-SA) plus later CC BY papers that build on them.

## Layout

```
samples/ml-walkthrough/
  README.md                 # this file
  ATTRIBUTION.md            # full license + cite table (ship)
  CLAUDE.md                 # short workspace charter for agents
  vault/                    # raw sources + FTS5/embedding index
  wiki/                     # the curated corpus (already built — see below)
  wiki-history.bundle       # wiki git history, restorable (see First run)
  .curator/                 # curator config + the run log
  docs/license-audit.md     # how licenses were checked
```

## What state this arrives in

**The wiki is already curated — do not rebuild it.** It carries 229 pages:
39 content pages (entities, concepts, analyses, evidence), 150
extracted-table pages, plus sources, figures and notes; 629 wikilinks, 251
citations, 0 uncited vault sources, 0 orphans. All 15 PDFs were
table-extracted and all 150 tables numeric-reviewed against their source
page images.

Earlier revisions of this file told you to recurate from an empty
scaffold. That is no longer true and following it would discard the
corpus. Recurate only if you deliberately want a fresh build.

## First run

```
bash <skill_path>/scripts/setup.sh                        # venv, dirs, deps
uv run python3 <skill_path>/scripts/graph.py rebuild wiki # rebuild the graph
```

`vault/vault.db` ships prebuilt, so keyword and semantic search work on the
first query. The graph (`.curator/graph.kuzu`) is excluded from the copy
because it is fully derived, hence the rebuild — needed before any
walkthrough step that shows the graph viewer.

**Requires curiosity-engine v1.1.1 or newer.** This workspace sets
`embedding_enabled: true`, and only v1.1.1+ installs fastembed +
sqlite-vec on a non-interactive `setup.sh`. On older versions setup skips
them silently and the first `vault_index.py` or `graph.py` call fails on a
missing `sqlite_vec`. Fix by installing those two packages, or by setting
`embedding_enabled: false` in `.curator/config.json`.

To inspect how the corpus was built, restore the wiki's git history:

```
git clone wiki-history.bundle wiki-history && git -C wiki-history log
```

One commit per curation wave, each carrying its reasoning. This is build
provenance for maintainers — nothing in the product walkthrough depends on
it, and it is shipped as a bundle because a `.git` directory cannot be
committed inside another git repository.

## Known caveats

Both are recorded on the pages themselves; noted here so nobody is
surprised by a number.

- `wiki/tables/tab-roziere-2023-code-llama-open-t25` carries a corrected
  transposition held at **medium** confidence, flagged for a human
  spot-check against the printed paper. Reversible via
  `tables.py restore-backup <stem> <backup_id>`.
- **Several papers contradict themselves across their own tables.** These
  are transcribed faithfully and never silently reconciled — a citation
  should name the table it came from. The Code Llama pairs (Tables 2/10
  and 4/11) carry a note above the data on both pages. Others — LLaMA
  Tables 9/16, Chain-of-Thought main text vs appendix — are recorded in
  `.curator/log.md` only, because the detector matches row labels and in
  those cases the entity is a column.

## Why not copy curiosity-projects-test?

That vault mixes Wikipedia (OK), blogs (all-rights-reserved), PDFs of
mixed provenance, and many arXiv papers under **nonexclusive-distrib**
only. Shipping it would create legal risk. This sample is rebuilt from
sources that are explicitly free-to-redistribute with attribution.
