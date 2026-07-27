# License audit method (2026-07-24)

1. Listed primary vault files from
   `the source vault` (no
   `.extracted.md`, no smoke/synth fixtures).
2. Parsed titles + `source_url` from frontmatter.
3. For arXiv ids, fetched `https://arxiv.org/abs/<id>` and recorded the
   abs-page license link:
   - `creativecommons.org/licenses/by/…` → **include** (BY-NC/ND → reject)
   - `arxiv.org/licenses/nonexclusive-distrib/1.0` → **exclude** from
     redistributable sample
4. Wikipedia: site-wide **CC BY-SA 4.0**; extracts via MediaWiki API with
   revid + attribution block.
5. Blogs / Medium / personal sites: **exclude** (no open license found
   without per-site legal review).

This sample only contains sources that cleared step 3–4.
