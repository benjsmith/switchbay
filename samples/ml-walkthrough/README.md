# Sample ML walkthrough corpus

Small, **license-clean** machine-learning source pack for Switch Bay’s
first-run / product walkthrough. Intended to be registered as a workspace,
curated with curiosity-engine, and used as the demo wiki — **not** an
excision of an existing test vault.

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
  vault/                    # raw sources only (curate from these)
  wiki/                     # empty scaffold — recurate, do not paste old wiki
  docs/license-audit.md     # how licenses were checked
```

## How to use

1. Copy or symlink this directory somewhere under `$HOME` (e.g.
   `~/Workspaces/ml-walkthrough`).
2. Add it as a Switch Bay workspace; run CE `setup` if needed.
3. **Recurate** with `/curate` (or the CE skill) from `vault/` — do **not**
   copy wiki pages from `curiosity-projects-test` or other test wikis.
4. After curation, rebuild the graph viewer so walkthrough graph steps
   have real nodes/edges.

## Why not copy curiosity-projects-test?

That vault mixes Wikipedia (OK), blogs (all-rights-reserved), PDFs of
mixed provenance, and many arXiv papers under **nonexclusive-distrib**
only. Shipping it would create legal risk. This sample is rebuilt from
sources that are explicitly free-to-redistribute with attribution.
