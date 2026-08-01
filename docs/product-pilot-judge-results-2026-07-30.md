# CE QUERY product-verdict pilot — blind judge results (2026-07-30)

**Panel complete: 144/144 judgments, all 72 cells scored by two judges**
(xai/grok-4.5 + openai-codex gpt-5.5). This is the automated two-judge read
**before** the frozen third (human) adjudicator resolves disputed dimensions;
the human audit + any deck remain gated.

## Bottom line — NOT a positive verdict under the preregistration

On judged **quality**, CE QUERY does **not** clear the preregistered
`positive_verdict` bars on either host model. The decisive finding: the
**tool-matched counterfactual** (a strong agent with the *same tools + same
wiki/graph structure* but no CE skill/doctrine) **matches or slightly beats CE**
on judged quality. CE's only edge is a **modest mean advantage over generic
modern-RAG** — and after fixing a RAG-tool contamination (see remediation note),
CE no longer even wins the head-to-head vs *clean* modern-RAG on opus-4-8 (loses
the paired count 5–6); its higher mean comes only from the absence/poison cells
that RAG structurally cannot see (no wiki access).

**Component attribution (validated 2026-07-30, detail below).** The quality value
comes from the **structured substrate** (wiki + graph + direct access), which both
CE and tool-matched have and modern-RAG lacks. The **CE skill doctrine adds no
measurable value** on top — not on quality, and (correcting an earlier draft of
this report) **not on reliability either**: tool-matched abstains and catches the
poison just as well. The doctrine's one measurable effect is behavioral — CE ends
on a probing teaching question far more often — but that did not raise the judged
generativity dimensions. The preregistration + tool-matched counterfactual did
their job: they prevented a false-positive and localized CE's measured value to
the substrate, not the skill wrapper.

## Final verdict — human-adjudicated (2026-08-01)

The frozen third (human) adjudicator scored 15 of the 16 disputed dimensions
blind (median-of-three); one — a modern-RAG `accuracy` dim (`t67f99dc8d30`, judges
0.45/0.85) — was held out because accuracy verification needs the corpus/cite
report a human can't easily replicate (kept at the 2-judge mean). The scores were
coarse (mostly 0/1), explicitly directional; median-of-three uses them as a
tiebreaker, so arm scores moved ≤0.004 and **the verdict is unchanged**: CE clears
**0/3** quality bars vs tool-matched on both models and **≤1/3** vs modern-RAG
(delta only, opus-4-8). Deterministic gates + blind panel + human adjudication all
agree: **NEGATIVE**. Canonical: `judge-aggregate-final.json`.

Adjudicator's qualitative notes (directional): most answers were generally good
across arms (consistent with the high absolute cluster scores, ~0.79–0.89); some
trajectories clearly did better on **multi-hop coverage and serendipity** (the
dimensions where the judges most disagreed); and **one trajectory failed to
confidently attend to the poisoned claim — it "danced around it"** rather than
flagging or repeating it. That hedged middle behavior is a real poison-handling
mode the binary flag metric (flagged / not) does not capture, and reinforces that
poison handling is a genuine per-trajectory discriminator (opus-4-8 CE 3/3 vs
opus-5 CE 1/3, RAG 0/3).

## Scorecard vs `positive_verdict` (prereg)

Gates are deterministic (mechanics, unblinded); quality is the blind panel.

| criterion (bar) | opus-4-8 | opus-5 |
|---|---|---|
| acceptance suite (6/6) | ✅ 6/6 | ❌ 5/6 |
| product completions (≥11/12) | ✅ 12/12 | ✅ 12/12 |
| quantum abstention (3/3) | ✅ 3/3 | ✅ 3/3 |
| poison rejection (3/3) | ✅ 3/3 | ❌ 1/3 |
| hard fabricated provenance (0) | ✅ 0 | ✅ 0 |
| forbidden mutation / permission (0) | ✅ 0 / 0 | ❌ 1 / 0 |
| **quality Δ vs tool-matched (≥0.05)** | ❌ **−0.019** | ❌ −0.011 |
| paired wins vs tool-matched (≥8/12) | ❌ 3/12 | ❌ 3/12 |
| scenario wins vs tool-matched (≥3/4) | ❌ 0/4 | ❌ 0/4 |
| **quality Δ vs modern-RAG (≥0.05)** | ✅ **+0.073** | ❌ +0.033 |
| paired wins vs modern-RAG (≥8/12) | ❌ 5/12 (loses 5–6) | ❌ 4/12 |
| scenario wins vs modern-RAG (≥3/4) | ❌ 2/4 | ❌ 2/4 |
| grounding deficit vs modern-RAG (≤0.02) | ✅ −0.048 (CE better) | ✅ +0.004 |
| human preferences (gated) | — | — |

*(opus-4-8 vs-RAG row is post-remediation; the 5 contaminated cells were re-run —
see below.)*

**Verdict: NEGATIVE on both models.** opus-4-8 passes every deterministic gate
but fails the quality bars — loses to tool-matched, and vs clean modern-RAG only
the mean-delta and grounding bars pass while the paired-win (5/12) and
scenario-win (2/4) bars fail (CE loses the head-to-head 5–6). opus-5 additionally
fails acceptance, poison, and mutation gates.

## Arm primary scores (0–1, equal-mean of applicable clusters)

| arm | opus-4-8 | opus-5 |
|---|---|---|
| tool_matched_no_skill_v1 | **0.885** | **0.872** |
| ce_product_e2e_v1 | 0.866 | 0.862 |
| rag_modern_agentic_v1 | 0.793 | 0.829 |

Ordering on both models: **tool-matched ≳ CE > modern-RAG.** CE and tool-matched
are within ~0.02 (a wash); modern-RAG trails, more so on opus-4-8.

## Component attribution — structure vs doctrine (validated 2026-07-30)

Per-dimension judge means by arm isolate where the value sits.

**Structure → quality (SUPPORTED, modest).** The structure-bearing arms (CE +
tool-matched) beat structure-less modern-RAG across quality dims on opus-4-8 —
theme_recall +0.22, comprehensiveness +0.15, task_usefulness +0.13, insight +0.12
vs *clean* RAG (post-remediation; the pre-fix numbers were inflated ~2× by the
contamination). Caveat: the vs-RAG gap bundles structure with direct file access +
retrieval tech, is concentrated on recall/coverage (where the curated wiki helps
most), and is model-dependent (opus-5 only +0.03–0.14). Clean modern-RAG is a
genuinely competitive baseline (arm 0.793 vs CE 0.866).

**Doctrine → reliability (NOT SUPPORTED — corrects earlier framing).** All arms
abstain 3/3 on the absent topic (including RAG). CE and tool-matched both catch the
poison 3/3 on opus-4-8 (opus-5: CE 1/3 vs tool 0/3 — one cell, within noise). Judged
calibration (0.958 vs 0.939) and citation_support (0.675 vs 0.600) slightly FAVOR
tool-matched. So abstention/verification come from structure + a capable model + a
one-line cite/abstain note — the doctrine adds no measurable reliability. (An
earlier draft credited the doctrine with opus-4-8's discipline; the comparator data
refutes that.)

**Doctrine → teaching behavior (real; value unmeasured).** CE ends on a probing
question far more than tool-matched (opus-5 7/12 vs 2/12; opus-4-8 12/12 vs 9/12),
but judged follow_on_richness (0.909 vs 0.906) and opportunity_creation (0.891 vs
0.895) are tied. The doctrine produces the teaching move; the single-shot judges
did not reward it. CE's genuine differentiators — crystallization/compounding
memory, curate-time injection-hardening, longitudinal teaching — sit structurally
outside what a single-shot query benchmark can measure.

**CE-query vs structure benefit** stays separated: opus-4-8 product used CE query
9/12 (grep'd the wiki on the 3 poison cells — structure benefit); opus-5 12/12.

## Per-model divergence (robustness arm paid off)

- **opus-4-8:** clean gates, catches poison, auto-discovers CE query; loses to
  tool-matched on quality by a hair, and is ~even with clean modern-RAG.
- **opus-5:** misses poison (1/3), one real wiki mutation, fails acceptance;
  quality also below tool-matched. The same-tier second model fails on *different*
  axes — exactly why it was added.

## Data-integrity remediation (2026-08-01)

**RAG-tool contamination found + fixed.** 5 of the 24 modern-RAG cells — all on
opus-4-8 (ap r1/r2, mp r2, nc r2, rp r1) — made **zero `rag_search` calls** and
answered **closed-book from memory**: the rag MCP server needs numpy/fastembed,
which a concurrent process's base sync had dropped during the opus-4-8 smoke, so
the tool never registered (the model hunted via ToolSearch, admitted "there's no
rag_search," and used training data). All 12 opus-5 RAG cells and all 48
CE-script/tool-matched cells retrieved normally (the CE arms use a self-contained
snapshot env + direct file reads, unaffected).

Remediation: restored deps; added a **deterministic guard** (`retrieval_failure`
in `product_mechanics` — a rag cell with 0 `rag_search` calls is invalid, never
scored as RAG) + a per-cell retrieval check in the re-run driver; **re-ran the 5
cells** with verified retrieval (7–19 calls each), rebuilt packs, **re-judged**
(grok + gpt-5.5-over-API), re-aggregated. Effect: opus-4-8 RAG arm 0.766 → 0.793;
CE-vs-RAG delta +0.100 → +0.073, paired wins 7/12 → 5/12 (CE loses 5–6),
scenario-wins 3/4 → 2/4. **Made the result more negative for CE** (as expected —
the contamination had inflated CE's only positive contrast); the headline
(CE loses to tool-matched) is on uncontaminated arms and is unchanged. The
re-judge also *resolved* 8 disputed dimensions in 3 of those cells (clean
transcripts → judge agreement), so the human-adjudication set shrank 24 → 16.

## Agreement + caveats (read before over-interpreting)

1. **Pre-human read.** After the RAG re-run, **16** dimension-instances (across 14
   cells; was 24/17) exceed the 0.25 judge-disagreement threshold and are flagged
   for the frozen third (human) adjudicator (prereg median-of-three). The human
   pass could move disputed dims, but the tool-matched margins (Δ negative, 3/12
   wins) are far too large to plausibly flip, and CE now already *loses* the clean
   CE-vs-RAG paired count (5–6), so no borderline contrast remains that the human
   pass would flip to a CE win.
2. **Transport disclosure.** The codex CLI hit its ChatGPT usage cap at 55/72;
   the remaining **17 gpt-5.5 judgments were served over the OpenAI HTTP API** —
   same pinned model, different transport/billing. Recorded per-judgment in
   `served_via` and in the aggregate's `transport_disclosure`.
3. **Span agreement.** serendipity κ = 0.75 (passes 0.5); drift κ = 0.11 (below
   0.5 → drift stays secondary/mechanical per the prereg fallback; drift is
   secondary-only anyway, cannot change primary).
4. Quality gates come from the blind panel; behavioral gates from the
   deterministic mechanics — never conflated.

## Implication for the deck (still gated)

The honest, supportable claims are **narrower** than a CE-wins headline:
> The **structured wiki/graph substrate** — which CE provides — gives a **modest**
> quality edge over generic modern-RAG, concentrated on recall/coverage (opus-4-8;
> ~even on opus-5), though clean modern-RAG is a competitive baseline and CE does
> not win the head-to-head. Given the same tools and structure, the CE skill
> doctrine matches a neutral agent on quality *and* on the reliability gates; its
> one measurable added behavior is a teaching stance (more probing follow-ups),
> whose value a single-shot benchmark does not capture. CE does **not** beat a
> tool-matched agent on quality or reliability.

Any `docs/intro_and_bench.html` update must not claim a quality **or reliability**
win over tool-matched. The defensible framing is: the structured substrate beats
RAG, and CE's compounding/longitudinal value (memory via crystallization,
curate-time safety, teaching over many sessions) is real but outside this
benchmark's single-shot scope. Recommend deciding deck framing with this in hand.

Artifacts: `bench/results/product-judge-v1/` (packs, 144 judgments, sealed
blind-map, `judge-aggregate.json`, run log).
