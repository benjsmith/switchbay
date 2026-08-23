# Benchmark design — CE knowledge graph vs. vector RAG

> **Headline (matches the `docs/intro_and_bench.html` deck — the canonical
> visual summary).** On **two frontier models cross-judged** (claude-fable-5 +
> gpt-5.6, each judging both answer sets):
> - **Curation + graph beat raw-vault RAG on facts & multi-hop.** Curated-wiki
>   vector (B′) and light routing (R) topped single-hop correctness (≈0.93
>   Fable / 0.81 gpt) and multi-hop (0.68 / 0.54); raw-vault RAG (B) and keyword
>   (A0) lagged. The ordering held from the older sonnet-4.6/gpt-4.1 run.
> - **Sensemaking was mostly answer length.** The global "win" flipped by
>   generator because the metric tracked verbosity; length-controlled, both
>   models only *modestly* favour curation — a soft, judge-noisy edge, not the
>   old 0.91.
> - **Retrieval recall:** raw-vault RAG *finds* sources (0.84/0.76) but doesn't
>   synthesise; routing keeps recall high and wins correctness; keyword lowest.
> - **PPR rejected** at this graph scale (worse global, hub concentration).
> - **H5 (alias resolution):** end-to-end, raw-vault RAG can't answer an
>   invented-codename alias (0.00 — it retrieves the definition but the fact is
>   an unreachable needle); every curated-wiki arm resolves it (1.00). Real
>   synonyms 0.67 (embedding half-bridges) vs curated 1.00. (A validated
>   entity-resolution abstention gate → look-alike false-bridge 0.12 → 0.00;
>   see `docs/ce-handoff-h5-identity-gate.md`.)
> - **H6 (semantic dissonance / homonyms):** curation *splits* a same-named
>   term into two provenanced pages (no over-merge). On an ambiguous query,
>   raw-vault RAG collapses to one sense (0.20) while curated retrieval surfaces
>   *and* separates both (B′ 1.00, routed 0.90).
> - **Cost-efficient config:** retrieve locally (free); answer with a mid-tier
>   current model at low effort (quality saturates; ordering held across model
>   generations); reserve the strong model for the propose→review curate gate.
>   A local 9B (Ornith) was insufficient for the hard agentic path — good only
>   as a cheap fan-out worker.

**Status: finalized (2026-07-15); the deck is the canonical summary.** The
frontier re-run + length-controlled global retest are complete; three ≤80-word
answer repairs on the strict length-control remain a caveat (below). Goal: establish
whether querying a curiosity-engine (CE) knowledge graph reaches **parity
with vector RAG on ordinary factoid retrieval**, and whether it **wins in
the areas RAG is known to be weak** — multi-hop reasoning and global/
sensemaking questions.

> **Correction — global/sensemaking result is provisional.** The original
> pairwise judge controlled answer *order* but not answer *length*. A later
> two-generator, two-judge cross-evaluation reversed the global result when the
> generator reversed which arm produced longer answers. Fable's curated-arm
> answers were longer than B and scored 0.79–0.92; GPT's B answers were longer
> than the curated arms and those arms scored 0.41–0.49. This is a scoring
> confound, not evidence that either generator establishes the true retrieval
> ordering.
>
> **Nominal rerun complete (2026-07-14), strict length control pending.** The 50
> global questions were cross-judged with the common context budget, and the
> reversal disappeared in the nominal averages: Fable A0/A1/B′/R =
> 0.68/0.78/0.75/0.79 and GPT-5.6 = 0.59/0.59/0.58/0.59 (win-rate vs B,
> averaging the two judges). However, an output audit found three Fable answers
> outside the ≤80-word cap (global-8/A1: 82; global-9/A0: 85; global-9/R: 82).
> The required fixed length-only rewrite and rejudge have not been run, so these
> numbers are a **sensitivity result, not a strict length-controlled conclusion**.
> Inter-judge disagreement is also large (about |Δ|=0.53); the Phase 2 atomic-
> theme metric remains the only confirmatory global outcome.

## 0. Results (n=50/category, curiosity-test corpus)

Run 2026-07-12. Generator: Claude (`claude-sonnet-4-6`, fixed across arms;
openai `gpt-4.1`, xai `grok-4.5`, gemini `2.5-flash` used where noted). Judges:
**all four — OpenAI, Anthropic, Gemini, xAI** — each pairwise judgement scored
in **both orderings** (position-bias control). **Inter-judge agreement is
tight** (mean per-item score std **0.047**, 0=perfect), so the numbers
are panel-robust, not one judge's artifact. 95% CIs are bootstrap (2000×).

*Model-currency check (2026-07-13).* The main run used `claude-sonnet-4-6`; a
small `claude-sonnet-5` spot-check (n=4/cat, generated + judged on sonnet-5)
**preserved the headline**: on single-hop, all curated/graph arms scored 1.00
vs raw-vault RAG (B) 0.88 — curated/graph still beats raw-vault RAG on factoids.
So the newer model does not invert the conclusions. (Multi/global at n=4 are
too small to read; the powered granularity signal is below.)

Arms: **A0** switchbay-as-shipped (keyword `search_wiki`), **A1**
GraphRAG (semantic seed + multi-hop **BFS** graph expansion), **A1P** the
same but ranked by **Personalized PageRank** instead of BFS, **B** vector-RAG
over raw vault sources, **B′** vector-RAG over the curated wiki pages,
**H** hybrid (curated-wiki graph context ~65% of budget + raw-vault
vector recall), **HA** adaptive hybrid (query-routed: global → graph-only,
else → graph + vault). A1P/HA were run on the *identical* question set as
the rest (apples-to-apples `--reuse`).

| category | metric | A0 | A1 | A1P | B | B′ | H | HA |
|---|---|---|---|---|---|---|---|---|
| **single-hop** | correctness | 0.60 | 0.92 | 0.90 | 0.68 | **0.97** | 0.90 | 0.92 |
| **single-hop** | retrieval recall | 0.30 | 0.72 | 0.68 | 0.84 | 0.88 | **0.94** | 0.90 |
| **multi-hop** | correctness | 0.68 | 0.75 | **0.76** | 0.53 | 0.74 | 0.74 | 0.74 |
| **multi-hop** | retrieval recall | 0.30 | 0.57 | 0.51 | 0.76 | 0.54 | **0.77** | 0.76 |
| **global** | win-rate vs B | 0.78 | **0.91** | 0.83 | — | 0.87 | 0.80 | 0.81 |

*(n=50/cat; 95% CIs bootstrap-paired — e.g. multi-hop correctness
A1 0.75 [.65,.85], H 0.74 [.64,.83]; multi-hop recall B 0.76 [.67,.84],
H 0.77 [.70,.85].)*

**PPR did NOT beat BFS (A1P vs A1) — reject at this corpus scale.** Paired
deltas are neutral-to-negative everywhere and **significantly worse on
global** (Δ −0.079, 95% CI [−0.149, −0.019], excludes 0); recall trends
down (single −0.04, multi −0.06). At 392 pages BFS distance-ranking wins;
PPR's teleport concentrates mass on high-degree hubs, which *costs
diversity* — exactly what the global/sensemaking metric rewards. PPR is a
*scale* play (HippoRAG's setting is much larger graphs / single-shot
multi-hop); it does not pay off here. **Keep BFS; revisit PPR only if CE
graphs grow orders of magnitude larger.**

**Adaptive-as-built (HA) tied fixed hybrid (H) — every paired CI crosses
0.** The routing added nothing *because it was wired over PPR* (its
global branch used PPR-graph-only, inheriting PPR's global weakness → 0.81,
not A1's 0.91).

**The candidate router (R) — adaptive routing over BFS — was then built and
measured on the identical n=50 set. Its single-hop and multi-hop evidence is
strong; its global branch remains provisional because of the length confound.** R sends each
question type to the retriever the benchmark shows is best for it:
single→B′, multi→hybrid (H), global→graph-only (A1). Measured:

| task | metric | R | best other | note |
|---|---|---|---|---|
| single-hop | correctness | **0.97** | B′ 0.97 | top (ties B′) |
| single-hop | recall | 0.88 | H 0.94 | B′-level |
| multi-hop | correctness | **0.76** | A1 0.75 | top |
| multi-hop | recall | **0.77** | H 0.77 | top (ties H) |
| global | win-rate | 0.90 | A1 0.91 | recovers A1 (vs H 0.80) |

R is top or tied-top on every factoid/multi-hop metric. The reported recovery
of A1's global score (0.90) is historical and under retest; **do not yet infer
that dropping the vault on global questions is optimal.** The non-global
routing result and the rejection of PPR remain supported.

**The hybrid (H) validates the "best of both" hypothesis.** On multi-hop
it is the **only** arm that is top-tier on *both* correctness (0.74, tying
A1/B′) **and** recall (0.77, tying B) — where A1 trades away recall (0.57)
and B trades away correctness (0.53). It also has the **best single-hop
recall** (0.94) with strong correctness (0.90). Its one weakness: on
**global/sensemaking it drops to 0.80** (vs A1 0.91) — the raw-vault chunks
dilute the comprehensiveness that pure curated content gives. **Implication:
an adaptive/query-routed hybrid** — curated-graph for sensemaking, blend in
vault-vector recall for factoid/multi-hop — is the optimal design.

**Findings:**
- **H1 (factoid parity) — holds for the semantic arms.** A1 (0.92) ≈ B′
  (0.97); both clearly beat the *shipped keyword* A0 (0.60, CIs
  non-overlapping). CE-graph retrieval reaches parity with vector RAG on
  simple factoids — but Switch Bay's current keyword `search_wiki` is the
  weak link.
- **H2 (multi-hop) — graph + curated content win the *answers*.** A1
  (0.75) and B′ (0.74) top correctness; raw-vault RAG (B) is worst (0.53).
- **B has the best multi-hop *recall* (0.76) but the worst *correctness*
  (0.53)** — it retrieves the right raw papers but can't synthesise the
  multi-hop answer across the raw sources. **This is the hybrid signal:** vault-vector
  *recall* + graph/curated *synthesis* (HippoRAG-style) is the clear next
  step.
- **H3 (global/sensemaking) — unresolved after bias audit.** The first run
  favored every curated-wiki arm, but global answers were not length-matched.
  Cross-generation scoring then tracked which side was more verbose and
  reversed direction. Position balancing alone was insufficient. H3 is being
  rerun with every answer capped at 80 words / approximately 500 characters;
  until that lands, neither a CE win nor a RAG win is established.
- **H4 (the Switch Bay gap) — large and real.** A0 (shipped keyword) trails
  badly on single-hop (0.60 vs A1 0.92) and recall (0.30 vs 0.72). The
  shipped graph-retrieval fix + a semantic seed closes it. **Product action:
  give `search_wiki` a semantic mode; default the agent to the graph tools.**
- **Honest nuance:** B′ (plain vector RAG over the *curated wiki*) is
  extremely strong across the board — so much of CE's value is the
  *curation* (distilled, linked pages), retrievable by simple embeddings.
  The graph's *marginal* lift over B′ is real but modest (global 0.91 vs
  0.87; multi-hop tied) — it matters most for connective/global questions
  and for giving the agent a structure to traverse.

*Caveats:* one corpus (ML/AI research), one generator in the original run, and
LLM grading. Four-judge agreement did not protect against a shared
answer-length preference, so judge-panel agreement alone is not sufficient.
H5 (synonym resolution) and the
LectureBank study-notes phase are separate, still to run.

### 0.1 Global length-control audit and corrective run (2026-07-13)

The frontier cross-run generated answers independently with Fable 5 and GPT
5.6, then had both models judge both answer sets. It revealed a
generator×arm interaction that follows answer length:

| generator | curated-arm mean words | B mean words | panel global range vs B |
|---|---:|---:|---:|
| Fable 5 | 181–194 | 146 | 0.79–0.92 |
| GPT 5.6 | 118–120 | 164 | 0.41–0.49 |

This does not identify the better retriever; it identifies a broken global
comparison. The corrective pack (`context_pack_global.json`) holds the
model-visible retrieval budget approximately constant and caps all answers at
80 words / ~500 characters. Both generators completed all 50 questions, and
both judges graded both answer sets in both orderings. An audit found three
Fable answers outside the 80-word cap, so the required fixed length-only
rewrite/rejudge remains open. The nominal averages are recorded in the
correction box above as a sensitivity result, not a strict length-controlled
claim or the Phase 2 atomic-theme outcome.

Phase 2 will go further: global evaluation's primary metric will be a
pre-registered atomic-theme coverage score with penalties for unsupported
claims and redundancy. Pairwise preference becomes secondary. Actual context
and answer lengths will always be reported by arm and generator. The frozen
design is in [`benchmark-ce-vs-rag-phase2-prereg.md`](benchmark-ce-vs-rag-phase2-prereg.md).
The semantic arms and the new chunked raw baseline now share a SHA-pinned CE
embedding lock with fail-closed backend/model and index-rebuild checks; only
the shipped keyword control is lexical.

**Methodological note — arm B is whole-document RAG, not chunked RAG.**
CE's `vault_index.py` embeds each source as a *single* whole-document vector
(`model.encode(text[:8000])`, default MiniLM ~512-token window) and FTS5
indexes the full body — there is **no chunking**. So arm B is *not* the
chunked passage-retrieval baseline most production RAG uses; it is a
conservative — and on long documents weaker — RAG. On this corpus the effect
is small (median source 1,536 chars; only 16% exceed the ~2k-char embedding
window, 6% exceed the 8k cap), so B is a fair baseline here, but a chunked
baseline could narrow B's multi-hop-recall lead (0.76) on long-document
corpora. CE's planned fix is *not* chunking but a curator distillation pass
over over-long sources (retrieval-optimized semantic compression layered on
the lossless FTS index) — see the roadmap.

**Wiki-embedding granularity experiment (2026-07-13) — inconclusive on this
corpus; defer to Phase 2.** Three wiki-retrieval arms holding the fed context
constant (all feed whole pages) and varying only the ranking surface: `Bwc`
900-char chunks (CE's current `.curator/wiki.db`), `Bww` one whole-page vector
(truncates the 34% of pages over the ~512-tok window), `Bwd` a compressed
LLM retrieval-descriptor for over-window pages. gpt-4.1, n=50/cat: **no
dominant winner** — chunk best on global (0.95 win-rate), whole-page best on
multi-hop correctness (0.90 — it did *not* regress as the truncation worry
predicted), descriptor best on multi-hop recall (0.59); single-hop tied ~0.96.
Small, traded differences (single-hop hits a ceiling — a strong model answers
factoids from any reasonable curated context). **Takeaway:** at this doc length
the granularity choice barely matters, so CE's chunking isn't hurting and
shouldn't change on aesthetics. The distinction should bite on **long, thematic
documents** — settle it in the LectureBank study-notes phase (§10) before
touching CE's live index. Arms live in `bench/wiki_gran.py`.

## 1. What the literature says (grounds the hypotheses)

Recent head-to-head studies converge on a consistent split:

- **RAG wins / ties on single-hop, detail-oriented factoid** questions
  (e.g. 71.7% vs 69.5% precision on Natural Questions). Neither method
  wins outright on a unified task set — "RAG took the single-hop and
  detail-oriented questions." ([RAG vs GraphRAG systematic eval](https://arxiv.org/html/2502.11371v3))
- **Graph methods win on multi-hop**: +27 avg over dense retrieval across
  HotpotQA / 2Wiki / MuSiQue; on some enterprise multi-hop sets 86% vs
  32%. The failure is **structural disconnection**, not lexical mismatch —
  hybrid RAG ≈ naive RAG on MuSiQue because the docs share no lexical
  overlap but are logically linked. ([systematic eval](https://arxiv.org/html/2502.11371v3), [MultiHop-RAG](https://arxiv.org/abs/2401.15391))
- **Graph methods win on global/sensemaking**: +50–70% comprehensiveness,
  ~72% comprehensiveness win-rate and ~62% diversity win-rate over vector
  RAG on corpus-level "what are the main themes" questions. ([Microsoft GraphRAG, Local→Global](https://arxiv.org/html/2404.16130v2))
- **Evaluation caveat:** LLM-as-judge has strong **position bias** — you
  must test both answer orderings and average. ([systematic eval](https://arxiv.org/html/2502.11371v3))

**Our hypotheses (what we're testing).** Systems: **A0** = Switch Bay as
shipped, **A1** = CE full graph, **B** = vector RAG (see §2).
- **H1 (parity):** CE (A1, and ideally A0) ≈ vector RAG on single-hop
  factoid (within a small margin; not significantly worse).
- **H2 (multi-hop):** A1 > B on multi-hop questions whose supporting facts
  live on different, linked pages.
- **H3 (global):** A1 > B on global/sensemaking (comprehensiveness +
  diversity), because CE distils + types + links.
- **H4 (the Switch Bay gap):** A1 > A0 on multi-hop/global — quantifies
  the retrieval quality Switch Bay forgoes by not exposing CE's kuzu
  multi-hop queries to the agent. If A0 already ties B on factoid but
  trails A1 on multi-hop, the product action is clear: wire `graph.py`
  into the agent tools.
- **H5 (synonym/alias resolution):** CE resolves "different names for the
  same thing" better than vector RAG — **but only where the resolution is
  learned, not trained-in.** Split into three regimes (see §9):
  - *Common synonyms* (in the model's training corpus): expect **parity**
    — RAG's embeddings already bridge them (heart-attack ≈ myocardial
    infarction because the corpus co-uses them).
  - *Rare/internal synonyms* (codenames, org-specific terms NOT in
    training): expect **CE > RAG** — but conditional on CE's *curator*
    having resolved the alias into the graph (wikilinking both surface
    forms to one canonical page). This is the open question you raised;
    we measure whether curation actually does it, and whether it improves
    over successive curation passes ("over time").
  - *Negative controls* (look-alikes that are NOT synonyms): measures
    over-merging (CE) and wrong-entity retrieval (RAG).
- **H0 (cost):** tokens/latency per answer — CE's agentic traversal may
  cost more; quantify the trade.

## 2. What CE actually is here — and a load-bearing finding

CE is genuinely a **typed, multi-hop property graph**, but **Switch Bay's
shipped agent tools use almost none of it.** Two distinct graph surfaces
exist:

- **CE's real graph (`graph.kuzu`)** — a kuzu property graph with typed
  node tables (`WikiPage / VaultSource / DataRow / Note`) and typed edges
  (`WikiLink`, `Cites` = page→vault citation, `DataRef` = table-column
  links, `Depicts` = figure `relates_to`, `AppearsIn` = note→page). Edges
  come from three sources: `[[wikilinks]]`, `(vault:…)` citations, and
  structured frontmatter/columns. CE ships graph-query commands:
  `neighbors --hops N` (**true multi-hop**), `path` (shortest wikilink
  path), `shared-sources`, `bridge-candidates` (co-citation). This is the
  "real GraphRAG" surface.
- **Switch Bay's agent tools (what users get today)** — a **degenerate**
  view: `search_wiki` is a keyword scorer (no vectors, no FTS,
  `tools.py:1239`); `wiki_neighbors` is **1-hop wikilinks only, re-derived
  from page text**, ignoring kuzu entirely (`tools.py:1312`);
  `read_wiki_page` (12k cap), `list_wiki_pages`. It **never calls kuzu** —
  the rich `graph.py` queries above are unused by the agent (kuzu today
  only feeds the visual graph tab). `recall_rail`'s vector index is over
  rail *history*, not the wiki.

**This gap is itself a headline product finding**, so the benchmark tests
**two CE arms**:

| Arm | Retrieval | Represents |
|---|---|---|
| **A0 — switchbay-as-shipped** | agent loop with `search_wiki` (keyword) + 1-hop `wiki_neighbors` + `read_wiki_page` | what users actually get **today** |
| **A1 — CE full graph** | CE's kuzu queries (`neighbors --hops N`, `path`, `shared-sources`, `bridge-candidates`) → read the linked curated pages | CE's graph at **full power** (upper bound) |

The **A1 − A0 gap** quantifies how much retrieval quality Switch Bay is
leaving on the table by not wiring `graph.py`'s multi-hop/typed queries
into the agent tools — a concrete, actionable result.

**System B — vector RAG (baseline, mostly already built).** CE's
`vault/vault.db` already holds a `source_embeddings` sqlite-vec index
(MiniLM 384-dim) over the raw sources, with `vault_search.py --mode
hybrid` giving FTS5 + cosine RRF **for free**. So the classic RAG baseline
= top-k over `source_embeddings` (one whole-doc vector per source) → stuff
the retrieved sources → same generator. Almost
nothing to build.

**Fairness — the apples-to-apples pivot:** both A (graph) and B (vector)
draw from the **same underlying vault documents** — CE distils+types+links
them into `wiki/` + `graph.kuzu`; RAG embeds them raw in `source_embeddings`.
Identical generator model + prompt + retrieval token budget across arms.
Optional **third diagnostic arm B′** = vector RAG over the *curated wiki
pages* (embed them with the in-repo fastembed encoder), to separate "graph
structure helps" from "CE's distillation of the text helps."

## 3. Corpora — confirmed scientific/technical, indexes already built

Three real workspaces exist, **domain = LLM/ML research + computational
science** (concept pages incl. Attention Mechanism, Scaling Laws,
Chain-of-Thought, Constitutional AI, Diffusion Models, DFT, Active
Learning) — exactly the scientific/technical target. Both live corpora
already have `graph.kuzu` **and** `vault.db` (`source_embeddings`) built,
so both retrieval surfaces are ready:

| Workspace | wiki pages | vault sources | both indexes built |
|---|---|---|---|
| `~/Dev/curiosity-test` | **392** | 230 | ✅ kuzu + vault.db |
| `~/Documents/curiosity-projects-test` | 336 | 233 | ✅ (6 projects) |
| `~/.cache/sy-smoke-ws` | 6 | 0 | smoke only |

Type mix (curiosity-test): analyses 75 · sources 113 · evidence 50 ·
concepts 48 · facts 32 · entities 26 · figures 21 · tables 17.

Plan:
- **Primary run on a COPY of `curiosity-test`** (392 pages, richest;
  copied off iCloud per charter — there's precedent, `log.md:4069`).
  Ecological validity + it already has both indexes.
- **Controlled corpus (for rigorous multi-hop gold):** ingest a fixed
  30–50 arXiv/ML-paper set through CE's `local_ingest.py → curate →
  graph.py rebuild` pipeline. This builds `source_embeddings` (RAG
  baseline) **and** `graph.kuzu` (graph) from the **same documents**, so
  gold multi-hop questions have known supporting pages. This is what makes
  H2 scoring airtight; the real workspace is the realism check.

## 4. Question set (the corpus has no gold Q&A — we generate + verify)

Three categories, ~50–80 questions each (mirrors the taxonomy in the
systematic-eval and MultiHop-RAG papers):

1. **Single-hop factoid** — answer on one page. Auto-generated by an LLM
   from a randomly sampled page + verified (answer string present on that
   page). Tests H1.
2. **Multi-hop** — answer requires ≥2 wikilinked pages. Generated by:
   pick a page, follow a wikilink to a neighbour, author a question whose
   answer needs a fact from each; record the supporting page set as gold.
   Tests H2. (This is where "structural disconnection" bites RAG.)
3. **Global / sensemaking** — "what are the main themes / how do X and Y
   relate across the corpus". Generated GraphRAG-style from community/
   type clusters; **no single gold answer** → judged on comprehensiveness
   + diversity. Tests H3.

All generated questions pass a **human-in-the-loop spot check** (you
review a sample) before the scored run, so we're not grading against a
model's hallucinated premise.

## 5. Metrics

Per the reference-free RAG-eval standard (RAGAS) + the systematic-eval
paper, scored by an LLM judge (strong model), with controls:

- **Retrieval quality** (diagnostic, separates retrieval from generation):
  - *Context precision / recall* vs the gold supporting-page set
    (multi-hop especially) — did the system surface the right pages/chunks?
- **Answer quality:**
  - *Correctness / F1 / exact-match* where a gold answer exists
    (single-hop, multi-hop).
  - *Faithfulness* (RAGAS: fraction of answer claims entailed by the
    retrieved context — catches hallucination).
  - *Comprehensiveness + Diversity* (LLM-judge win-rate, GraphRAG-style)
    for global questions.
- **Cost:** tokens (retrieval + generation) and wall-clock per question.
- **Judge rigor:** every pairwise judgement run in **both orderings**
  (A-first / B-first) and averaged to defuse position bias; a fixed judge
  model distinct from the generator; a subset human-verified to calibrate
  the judge.

Report per-category tables (A vs B vs B′) with win-rates, mean scores, and
95% bootstrap CIs, plus the cost trade-off.

## 6. What we build (much of it already exists)

All under a scratch `bench/` harness (not shipped). Effort ranked:

1. **Corpus prep** — copy `curiosity-test` off-sync; both indexes are
   already built. (Controlled corpus: run CE's `local_ingest.py → curate
   → graph.py rebuild` on a fixed paper set.) — *little/no build.*
2. **System B (vector RAG)** — reuse CE's `vault_search.py --mode
   hybrid/semantic` over the existing `source_embeddings`; thin wrapper to
   retrieve top-k whole sources and hand them to the generator. Optional
   B′: embed the wiki pages with the in-repo fastembed encoder
   (`conversations.py`). — *small.*
3. **A0 runner (Switch Bay as shipped)** — drive the real agent loop over
   the workspace with only its wiki tools, via the daemon on an isolated
   port (the exact harness pattern used for the Sheet/Zen live tests this
   session). — *small; infra reused.*
4. **A1 runner (CE full graph)** — a retriever that calls CE's `graph.py`
   (`neighbors --hops N`, `path`, `shared-sources`, `bridge-candidates`)
   to expand from seed pages, then reads the linked curated pages. Seeds
   from `search_wiki`/vault hits. — *the main new piece* (a few hundred
   lines; CE commands already exist, we orchestrate them).
5. **Question generator + verifier** — LLM generates per-category
   questions grounded in sampled pages / kuzu paths (multi-hop questions
   built by walking `path`, recording gold supporting pages); verifier
   checks answerability; you spot-check a sample. — *medium.*
6. **Judge harness + report** — runs every arm per question, scores the
   metric suite (both orderings), writes a results table + a self-
   contained HTML report (reuse the `create_report` artifact path). —
   *medium.*

Everything is offline/local except generator + judge LLM calls (strong
provider; bounded run — ~150–200 questions × up to 4 arms).

## 7. Deliverable + decision

A report answering, per category:
- **Parity on factoid?** (H1) — is CE within a small margin of B?
- **Multi-hop lift?** (H2) — magnitude of A1 > B + the retrieval-recall
  story behind it.
- **Global lift?** (H3) — comprehensiveness/diversity win-rates.
- **The Switch Bay gap** (H4) — A1 − A0: is the product under-using CE's
  graph, and would wiring `graph.py` into the agent tools close it?
- **At what cost?** (H0) — tokens/latency delta.
- **A1 vs B′** — how much of any lift is *graph structure* vs *CE's
  distillation of the source text*.

This tells us (a) where CE genuinely earns its keep vs. where plain RAG
does as well for less — product positioning; and (b) whether Switch Bay
should surface CE's kuzu multi-hop queries to the agent — a concrete
roadmap item.

## 8. Scope / cost knobs for your review (decisions to make)

- **Arms:** minimum is **A1 (CE full graph) vs B (vector RAG)**. Include
  **A0 (switchbay-as-shipped)** to measure the product gap (H4) —
  strongly recommended, cheap. Include **B′ (RAG-over-wiki)** for the
  structure-vs-distillation diagnosis (optional).
- **Corpus:** the real `curiosity-test` copy only (fast, both indexes
  ready), or also the controlled arXiv corpus (rigorous multi-hop gold,
  more setup)?
- **Question volume:** ~50/category (fast, ~1–2h of LLM spend) vs
  ~150/category (tighter CIs, more spend).
- **Judge/generator model:** which provider (cost vs quality) — you have
  OpenAI, Gemini, Anthropic/Claude-Code, xAI keys.
- **Multi-hop gold:** LLM-generated from kuzu `path` walks + verified
  (fast) vs a small hand-authored gold set (most rigorous, slower).

## 9. Synonym / alias resolution experiment (H5) — controlled, simulated

This is a **separate, fully-controlled corpus** because we must know the
ground-truth synonym pairs and guarantee which are/aren't in training.

**Why the graph might win — grounded in the code + literature.** CE has a
**general identity layer**, not just wikilink aliasing. `identifier_cache.py`
is a *generalised IRI registry that any entity class can mint into* —
`ce:<class>:<workspace>:<slug>`, workspace-stable, deterministic, **no
network** — so reconciliation keys on identity, not slug. `same_as` merges
across mints from the same page, and `curiosity-merge` reconciles pages
sharing an IRI (or overlapping `same_as`) across workspaces regardless of
slug. (The chem/gene PubChem/MyGene network resolver that *optionally*
populates `same_as` is **off by default** — `config.json enabled:false` —
so there's no data leakage; general minting is local-only.) On top of that,
the curator also wikilinks surface-form mentions to one canonical page.
Together these give CE a *persistent, identity-based* resolution of "same
thing, different name." RAG has none of this: it relies on **embedding
proximity** (bridges common synonyms the training corpus co-uses; fails
for rare ones) or on coincidentally retrieving a chunk that states the
equivalence. The GraphRAG-entity-resolution literature is explicit that
"*what is the same thing under a different name*" is **not** a
semantic-similarity question — graphs solve it by merging, vectors don't.
([entity-resolved GraphRAG](https://odsc.medium.com/entity-resolved-knowledge-graphs-the-foundation-for-effective-graphrag-e19e2d4779f9), [Denoising KGs for RAG](https://arxiv.org/html/2510.14271v1))

*Open point the experiment settles:* whether entity-IRI minting runs
automatically in the default curate loop or is the opt-in "U1" tier — the
"resolution-created?" diagnostic below inspects whether curation actually
minted a shared IRI / `same_as` / merged the pair; the CE arm runs with
identity minting enabled (testing CE's real designed capability).

**Corpus (simulated, ~60–90 fact docs).** For each synonym pair (A, B):
- a **fact document** stating a distinctive, checkable fact using form
  **A** only (e.g. "⟨A⟩'s error rate dropped to 3.2% in the March run");
- a **defining document** stating the equivalence ("⟨B⟩ is our name for
  ⟨A⟩") — realistic (glossary / onboarding page); include an **ablation
  without it** to establish the floor (if the equivalence is stated
  nowhere, neither system can resolve it);
- **queries phrased with form B** asking for the fact.

Three regimes:
| Regime | Pairs | Prediction |
|---|---|---|
| **S1 common** (in training) | MI/heart attack · renal/kidney · LLM/large language model · CNN/convolutional net | RAG bridges via embeddings → **parity** |
| **S2 rare/internal** (invented, NOT in training) | Project Zephyr = churn-model-v3 · "Bluewidget" = settlement-reconciliation-service · made-up drug/gene codenames | **CE > RAG**, *iff* curation resolved it |
| **S3 negative control** | Zephyr vs Zenith (distinct) · jaguar animal/car | over-merge (CE) / wrong-entity (RAG) |

**Pipeline (this is the point):** ingest the docs → **run CE's curator**
→ query. Because S2 hinges on curation, we:
- **inspect** whether the curator created the resolution (did a wikilink /
  alias / merged page connect B→A?) — a structural diagnostic that
  *explains* the accuracy, not just scores it;
- run curation **once vs several passes** to test "does it resolve over
  time?" — the exact uncertainty you raised.

**Metrics:** *alias-bridge accuracy* (query in form B → correct fact
retrieved+answered; exact, ground-truth-controlled); *false-merge rate*
(S3); and the CE *resolution-created?* diagnostic. Run across the same
four arms (A0/A1/B/B′). Expected shape: A0≈A1≈B on S1; A1>B on S2 when
curation resolves (and A1≈B when it doesn't — which itself is the finding).

## 10. Study notes across years/courses (RAG's weak spot)

**Real data:** there is **no public dataset of personal, multi-year
student notes** — that material is private and unreleased. The strong
public proxies:
- **LectureBank** — 1,352 lecture PDFs across **60 courses** (CS), with
  annotated topic + **prerequisite relations** (a built-in cross-course
  dependency graph). This is exactly "source material across many
  courses" with the connective structure RAG struggles on. ([LectureBank])
- **EduScopeQA** — multi-subject, multi-scope QA that *already* compares
  vector-RAG vs graph-RAG in classroom QA — a ready question set + a
  precedent for our exact comparison.
- **EDU-RAG** — education-domain RAG benchmark (middle-school science).

**Proposed design:** use **LectureBank as the corpus** (multi-course, with
a real prerequisite graph → perfect for cross-course multi-hop where RAG
fails), ingest it through CE, and either reuse EduScopeQA-style questions
or generate cross-course questions ("this technique from course X builds
on which prerequisite from course Y?"). Optionally **simulate the personal
-notes layer** by generating fragmented, informal student-note summaries
(evolving terminology across "years") from LectureBank content — which
also feeds the synonym experiment (terminology drift = internal synonyms).
This is a **phase 2** once the core H1–H4 + H5 runs land; flagging it now
so the corpus choice is deliberate.

---

### Sources
- [RAG vs GraphRAG: A Systematic Evaluation (arXiv 2502.11371)](https://arxiv.org/html/2502.11371v3)
- [From Local to Global: A GraphRAG Approach to Query-Focused Summarization (arXiv 2404.16130)](https://arxiv.org/html/2404.16130v2)
- [MultiHop-RAG: Benchmarking RAG for Multi-Hop Queries (arXiv 2401.15391)](https://arxiv.org/abs/2401.15391)
- [Ragas: Automated Evaluation of RAG (arXiv 2309.15217)](https://arxiv.org/pdf/2309.15217)
- KG-construction benchmarks (scientific): [SciERC](https://arxiv.org/pdf/1808.09602), [SciREX](https://www.emergentmind.com/topics/scirex-dataset), [SciER (arXiv 2410.21155)](https://arxiv.org/html/2410.21155v1)
- Entity resolution / synonyms for GraphRAG: [Entity-Resolved KGs = foundation for GraphRAG](https://odsc.medium.com/entity-resolved-knowledge-graphs-the-foundation-for-effective-graphrag-e19e2d4779f9), [Denoising KGs for RAG (arXiv 2510.14271)](https://arxiv.org/html/2510.14271v1)
- Education corpora (study-notes proxy): LectureBank (60 CS courses, prerequisite graph), [EduScopeQA / EDU-RAG (OpenReview)](https://openreview.net/forum?id=a2rSx6t4EV), [Aligning LLMs for the Classroom: a comparative RAG study (arXiv 2509.07846)](https://arxiv.org/html/2509.07846)
