# H5 — alias / synonym resolution: design critique & pre-registration

Status: **DESIGN — not yet run.** Written before the run, deliberately, so the
metric and predictions aren't tuned to a hoped-for result.

## 0. The claim under test

> When a fact is stored under one name for an entity, and a user asks using a
> *different* name (an alias) for the same entity, does a curated knowledge
> wiki/graph (CE) let the system answer, where raw-document RAG cannot?

This is an **alias-resolution** claim. It is NOT the same as "curation is
better" in general — it is specifically about the *name-mismatch* failure of
lexical/embedding retrieval.

## 1. What went wrong before, and why (catalogue of failure modes)

Each previous attempt failed for a concrete, now-understood reason. A robust
design has to defeat all of them at once.

| # | Failure mode | Mechanism | Fix |
|---|---|---|---|
| F1 | **Corpus contamination** | setup left 135 curiosity-test ML sources in `vault/`; curation built ~130 extra pages; A0 returned `deepseek-r1` for "LLM". | Deliberate, *labelled* distractors (see F6) — not accidental ones. |
| F2 | **Query lexical leak** | queries restated the fact's distinctive words ("lift over baseline"), so retrieval matched those, not the alias. | Generic, alias-only queries. |
| F3 | **Metric saturation** | 24-doc corpus, k=5 → arm sees 20% of everything; "in top-k" is ~always true. | Realistic haystack so k is ~1% (F6); report recall *and* answer. |
| F4 | **Alias-length confound** | curated arms do *string* retrieval of the curation-injected alias; 3-char aliases ("LLM","CNN") are swamped by query boilerplate and mis-route. common/rare got confounded with alias length. | Length-balanced aliases; length recorded as a covariate; no bare acronyms. |
| F5 | **Control unmeasurable** | top-k retrieval always returns its nearest neighbour → a "should abstain" control always "hits". | Abstention is a *generation* behaviour → measure end-to-end (F7). |
| F6 | **No distractors → retrieval is trivial** | with everything in-budget, both raw and curated arms "retrieve" the fact; the test can't tell good retrieval from bad. | Embed the needles in the **real 392-page curiosity-test corpus** as a haystack. |
| F7 | **Retrieval-only metric is unfair to raw RAG** | raw RAG's honest path is: retrieve the *definition* ("B is A") **and** the A-fact, then let the generator hop B→A→fact. Scoring "is the gold value in the retrieved context" ignores that the generator can connect two retrieved passages. | Score **end-to-end answer accuracy**, equal budget, plus retrieval recall as a diagnostic. |
| F8 | **Curation non-determinism** | each curate run fragments pages differently (one run unified alias+fact; another split them). Single run = high variance. | Acknowledge; report as single-run; keep the treatment = "the system as curation actually built it". |
| F9 | **Experimenter bias** | hand-tuning the query template until numbers looked right; picking k post-hoc. | Pre-register template, k, metric, and predictions **here**; deterministic scoring; include refutation conditions and a positive control. |

The single most important realisation: **F6 + F7 together**. Without a real
haystack the retrieval task is fake; with retrieval-only scoring the baseline is
handicapped. A fair test needs a realistic corpus *and* an end-to-end metric.

## 2. Design v3

### 2.1 Corpus (needles in a real haystack)
- **Haystack:** the real curiosity-test wiki/vault (392 pages) — a genuine
  distractor set, already curated. Retrieval must discriminate (~1% in-budget).
- **Needles:** ~24 invented entities whose *names and aliases do not occur in
  the ML haystack* (so no accidental collisions like "LLM"). Two families:
  - **real-synonym entities (n≈12):** a real-world thing with a genuine
    synonym the model/embeddings know — but the *fact* is invented. Names are
    outside ML (medical, logistics, etc.): myocardial infarction / heart
    attack, kidney failure / renal failure, …
  - **codename entities (n≈12):** an invented canonical + an invented alias,
    connected only by a glossary doc: "Project Zephyr" / "the customer-churn
    prediction model v3".
  - Each needle = a **fact doc** (canonical name A + one unique numeric value +
    neutral filler) and a **definition doc** ("B is another name for A").
- **Alias-length control:** across BOTH families, aliases are drawn from a
  matched spread of character lengths (short / medium / long). No 3-char
  acronyms. Length is recorded per item and reported as a covariate, so
  "familiar vs codename" is never confounded with "short vs long".

### 2.2 Conditions (within-entity; paired)
Every needle is queried two ways, with the SAME fixed template:

> `"According to the evaluation, what figure is reported for {name}?"`

- **canonical** — `{name}` = A. *Positive control*: every arm should score
  high; if not, retrieval/corpus is broken and the run is void.
- **alias** — `{name}` = B (the real synonym or the codename).

Plus a separate **abstention control**: ~8 look-alike names with no entity and
no definition ("Project Sentry" when only "Project Sentinel" exists). Correct
behaviour = the model declines.

The alias effect is measured **paired, within entity**: `penalty = acc(canonical)
− acc(alias)`. This removes per-entity/per-fact difficulty as a nuisance
variable — the cleanest control we have.

### 2.3 Arms (equal budget)
A0 keyword · B raw-vault RAG · A1 graph · B′ wiki-RAG · R routed. Every arm gets
the **same char budget** (e.g. 6 000 chars) and the same generator. B is the
raw-document baseline; A0/A1/B′/R read the curated wiki.

### 2.4 Metric (end-to-end + diagnostic)
For each (arm, query): retrieve → a fixed cheap generator (low effort) answers
**from the retrieved context only**, instructed to output the figure or exactly
`NOT FOUND`. Two scores, both deterministic (no LLM judge → no judge bias):
- **answer accuracy** (primary): gold value string present in the answer.
- **retrieval recall** (diagnostic): gold value present in the retrieved
  context. `recall − accuracy` isolates "retrieval found it but the generator
  didn't use it" from "retrieval never found it".
- **abstention control:** false-answer rate = fraction where the model emits any
  numeric figure instead of `NOT FOUND` (lower is better).

### 2.5 Analysis
- Per arm: `acc(canonical)`, `acc(alias)`, paired `penalty`, with **bootstrap
  95% CIs** over entities.
- Primary contrast: alias penalty of **B (raw-vault)** vs the curated arms.
- Secondary: real-synonym vs codename penalty, **with alias length as a
  covariate** (report accuracy vs length, not just the regime means).
- Abstention: false-answer rate per arm.

### 2.6 Pre-registered predictions — and how the test can REFUTE the claim
1. **Positive control:** all arms `acc(canonical) ≥ 0.8`. (Else void.)
2. **Claim-supporting:** B shows a large alias penalty on **codenames**
   (retrieves the definition but the A-fact is a needle it can't surface);
   curated arms show a much smaller penalty.
3. **Claim could be REFUTED if:** B's codename penalty is small — i.e. B
   retrieves *both* the definition and the A-fact within budget and the
   generator hops B→A→fact. Then curation adds little for capable generators.
   **We will report this honestly if it happens.**
4. **Real-synonym penalty < codename penalty for B** (embedding proximity
   partly bridges known synonyms); curated arms ≈ flat across both.
5. **No length effect within an arm** once the alias is on the curated page
   (A0/B′/A1/R); a residual length effect would mean the metric is still
   retrieval-precision-bound, not resolution-bound.

## 3. Cost
- One **incremental** curation pass: add ~48 needle docs to a clone of the
  already-curated curiosity-test, curate only the new docs (subscription, not
  API). No re-curation of the 392 existing pages.
- Generation: ~24 entities × 2 query-types × 5 arms + 8 controls × 5 ≈ **280
  cheap-model answer calls** (low effort). Scoring is deterministic (free).

## 4. Open questions for sign-off
- **Generator model** for the answer step (cheapest current mid-tier at low
  effort, per the cost-efficiency finding — e.g. gemini-2.5-flash or a low
  Haiku). Deterministic scoring means the generator only has to be consistent.
- **n per family** (12 proposed → 24 needles). Larger n = tighter CIs but more
  invented facts to author + a longer curate pass.
- Whether to also report a **canonical-only** raw-vault sanity (B should ace
  canonical queries — it's a plain lookup — confirming B isn't just weak).

---

# H6 — semantic dissonance / homonym disambiguation (planned; run after H5)

The **dual** of H5. H5: different names, same entity → curation should *merge*.
H6: **same name, different entities** → curation should *split*. RAG's failure
mode flips from "can't bridge two names" to **"conflates two meanings"**.

**Why it can refute the claim.** H5 tests whether curation merges correctly; H6
tests whether it *over-merges*. A naive one-page-per-name curator collapses "the
Doohickey (a process)" and "the Doohickey (an output)" into one incoherent page
— and then the curated arms do *worse* than RAG. That is the honest risk to
Switch Bay's identity story (typed pages, per-workspace IRIs, curiosity-merge,
provenance): H6 is the test it can fail.

**Corpus.** N collision terms in the same real haystack. Each term T appears in
two contexts with a distinct sense + a distinct invented figure:
  - T = "the Doohickey"; Project Atlas: the nightly *validation step*, "cleared
    3,400 records"; Project Borealis: the exported *ledger file*, "weighed 88 MB".
  - Distinct sense, distinct figure, each tagged by project/context. Figures and
    contexts chosen not to occur in the ML haystack.

**Query.** Disambiguated by CONTEXT, never by the fact:
"In Project Atlas, what figure is reported for the Doohickey?" → correct = 3,400;
wrong-sense = 88 MB; blend = both / neither.

**Metrics (reuse H5's end-to-end harness).**
  - correct-sense accuracy — answer gives the queried sense's figure.
  - **conflation rate** (primary) — answer gives the OTHER sense's figure or
    reports both. RAG should score high here; curated arms low IF curation split
    the entity.
  - retrieval diagnostic — did both senses land in the retrieved context (they
    should, for RAG — that's the conflation trap).

**Controls.**
  - positive: a term used in only one context (no collision) — all arms ace it.
  - honest-negative watch: if curated arms conflate as much as RAG, curation did
    not disambiguate — report it plainly.

**Escalation (realistic Switch Bay angle).** Strongest version puts the two
senses in two DIFFERENT workspaces, exercising cross-workspace identity
(per-workspace IRIs, curiosity-merge) that is supposed to keep them distinct even
when queried together. Start single-corpus/project-tagged; escalate to
two-workspace if the single-corpus signal is clean.

**Caveats up front.** Meaning-difference is a spectrum; claim only the clean
binary cases (process-vs-output), flag the graded middle as out of scope. The
disambiguating cue (project tag) is present in every doc, so it is fair to all
arms.

**Reuse.** ~90% of the H5 harness carries over: same haystack setup, same
end-to-end deterministic scorer. New: the collision-corpus builder and the
conflation metric.
