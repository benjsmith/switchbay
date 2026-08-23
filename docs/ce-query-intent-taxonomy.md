# CE QUERY intent taxonomy

**Status:** design freeze for product routing + agentic bench (2026-07-21 reorientation;
amended 2026-07-22 after `docs/reorientation-review-2026-07-21.md`).
**Audience:** CE skill maintainers, Switch Bay bench, QUERY implementers.
**Companion:** `docs/phase2-agentic-query-bench-design.md`.
**Bench rubric (canonical):** `bench/agentic_query_bench/judgment-charter.json`.

---

## 1. Product north star (reorientation)

CE cheapens a **Zettelkasten-like** network whose **apex is well-cited analyses**.

- **Atoms** (facts, figures, evidence, entities, concepts) are material.
- **Links** make multi-hop structure walkable and fixable.
- **Analyses** synthesize atoms into knowledge greater than the sum of parts,
  with back-references into the graph and vault.
- **Humans** mostly steer with **sources, notes/ideas, and insightful questions**
  (and sometimes hypotheses/tests). Direct wiki authorship is preserved but
  is usually the lesser intervention.
- **QUERY** often *answers by writing or updating an analysis* (and proposing
  next questions / docs / hypotheses), not only by packing a one-shot context
  window. That agentic loop is the primary capability surface for knowledge work.

**Plumbing still matters:** needles must not drown in the wrong page type;
entity look-alikes must abstain. Those are specialized paths, not the mission.

**Do not** treat “always demote analyses” as CE philosophy. Demotion is
**needle-mode only**. For matched synthesis, analyses are rich multi-hop starting
material. For unmatched synthesis, **compose** an analysis.

---

## 2. Intent classes

Classify each user turn (heuristic + optional LLM assist; fail open to
`compose_analysis` when unsure).

| ID | Intent | Typical user jobs | Signal heuristics (non-exhaustive) |
|----|--------|-------------------|-------------------------------------|
| **N** | `needle` | Exam fact, caption, quote, number, “what does Fig. N say” | Fig/Table/caption/verbatim; short closed question; single named atom |
| **L** | `locate` | Which lecture/source introduced X; find locus | “which lecture/source/file”, “where does”, “who said” |
| **C** | `compare` | Contrast two ideas/methods/eras | “vs”, “versus”, “difference between”, two named entities |
| **M** | `matched_analysis` | Multi-hop / theme where a good analysis already covers it | Semantic hit on `type: analysis` (or dense concept hub) above threshold |
| **S** | `compose_analysis` | Essay/article/lesson/research **planning**; open synthesis; no good analysis hit | Planning verbs; “outline”, “curriculum”, “angle”, “framework”; low analysis match |
| **X** | `explore` | Serendipitous / curious expansion from a pin | User accepts branch; “what else connects”; “surprise me / related” *after* a base answer |

Notes:

- **N** and **L** optimize precision and honesty (short path to atoms/vault).
- **M** and **S** are the high-leverage knowledge-work paths.
- **X** is desired; it must be **distinguishable from unproductive drift**
  (see §5 and bench design).

---

## 3. Default retrieve + write behaviour by intent

Each path returns: **working set** (pages + vault spans), **answer artifact**,
**graph deltas** (optional), **steering surface** (gaps, next questions).

### N — `needle`

| Step | Behaviour |
|------|-----------|
| Retrieve | Prefer `facts` / `figures` / `tables` / `evidence` / `sources`; **demote analyses**; chunked vault residual if atoms underfill |
| Write | Short answer + citations; **do not** invent an analysis unless user asks |
| Graph delta | Optional: promote span → fact if missing (propose only) |
| Steering | If missing: “insufficient; would need type Y from source Z” |

### L — `locate`

| Step | Behaviour |
|------|-----------|
| Retrieve | `sources` + vault phrase/FTS boost; entities as pins; light facts |
| Write | Document id + locus paraphrase/quote + confidence |
| Graph delta | None required |
| Steering | Alternate candidate sources if ambiguous |

### C — `compare`

| Step | Behaviour |
|------|-----------|
| Retrieve | Pin both poles (entity_gate / title match); ≥1 fact or concept per pole; existing compare-style analysis if any |
| Write | Structured contrast (2–4 bullets); cite both sides |
| Graph delta | Propose link between poles if missing |
| Steering | “Shared parent concept?” / “where they disagree in sources” |

### M — `matched_analysis`

| Step | Behaviour |
|------|-----------|
| Retrieve | **Seed analysis (or hub concept)** first; **descend** into its `[[wikilinks]]` and `(vault:…)` cites (atoms + sources); fill residual with type-aware wiki |
| Write | Synthesize using analysis as map; verify claims against cited atoms; note conflicts |
| Graph delta | Patch analysis only if user wants update; else answer + optional patch proposal |
| Steering | Gaps in analysis coverage; next questions that deepen the same spine |

### S — `compose_analysis`

| Step | Behaviour |
|------|-----------|
| Retrieve | Coverage-oriented multi-pass: themes/modules → atoms per theme → sources; provisional bridges; **do not** fill budget with one long weak analysis |
| Write | **Draft or update analysis** (or project brief): outline, claims with cites, explicit **gaps**, **hypotheses**, **next questions**, optional source requests |
| Graph delta | Propose analysis page + links (ratchet/review path in full CE; bench may capture proposal JSON) |
| Steering | **Primary product:** avenues for human refinement without rephrasing from zero |

### X — `explore` (serendipity mode)

| Step | Behaviour |
|------|-----------|
| Retrieve | Neighbors / provisional bridges / co-citation **off the current pin**, labeled as **side paths** |
| Write | Separate “spine” (honours prior intent) vs “side paths” (novel, still grounded) |
| Graph delta | Optional provisional → link candidates |
| Steering | Human accepts/rejects branch; accepted branch can become new spine |

---

## 4. What we measure (per intent)

| Intent | Primary metrics | Secondary |
|--------|-----------------|-----------|
| **N** | Answer correctness; atom/source precision@k; verbatim/caption hit when applicable | Abstention when unsupported |
| **L** | Gold document hit; locus support | Ambiguity honesty |
| **C** | Both poles covered; contrast accuracy | Proposed bridge quality |
| **M** | Claim support from analysis+atoms; multi-hop fact recall; no false bridges | Compactness; conflict surfacing |
| **S** | Theme/module **recall & precision**; multi-hop inclusion; synthesis quality (see bench charter); **follow-on richness**; low **unproductive drift** | Novelty of synthesis (grounded); usefulness for stated task |
| **X** | Serendipity: grounded novelty + human would keep; **not** scored as drift if labeled side-path | Spine fidelity still required |

Global (all intents):

- **Calibration:** weak evidence → hedge / abstain / show alternatives (enterprise failure mode).
- **Citation integrity:** mechanical resolve; invented provenance is a **gate**, not a soft score.
- **Cost:** tokens/latency (report; not primary product gate alone).

**Bench primary score** is five **cluster** means (coverage / grounding / writing /
generativity / steering) — see judgment-charter.json. `serendipity_quality` is
**outside** the primary composite and **card-anchored** in the agentic bench.

---

## 5. Drift vs serendipity (definitions for routing + judges)

| | **Unproductive drift** | **Serendipitous discovery** |
|--|------------------------|-------------------------------|
| Relation to user intent | Displaces the spine; user must re-steer | Extends or reframes productively **while spine remains available** |
| Grounding | Weak or off-corpus | Grounded in vault/wiki (or explicit “model hypothesis, uncited”) |
| Structure | Blended into main answer as if primary | Labeled **side path** / “optional avenue” |
| Follow-on | Dead-end or thrash | Clear next question or test the human would want |
| Multi-turn | Forces repeated rephrase to recover intent | Deepens synthesis toward a sharper concept |
| Bench scoring | Primary signal = mechanical **re-steer** rate | Only matches card `fruitful_directions`; labeled-but-unlisted = 0; unlabeled off-spine = drift |

Routing/UX requirement: never mix unlabeled drift into the main answer for **S/M**.
Serendipity is allowed when structured as **X** or side-paths; product UX may
reward it, but the **agentic bench does not put it in the primary composite**
(avoids designed-in CE advantage vs RAG-std).

---

## 6. Human-in-the-loop (leverage order)

| Rank | Human action | System response |
|------|----------------|-----------------|
| 1 | Insightful **question** | Intent classify → M/S/N… path; often compose/update analysis |
| 2 | **Source** curation (ingest) | Vault + later bootstrap/curate |
| 3 | **Notes / ideas / hypotheses** | Steer next QUERY/CURATE; attach to project/analysis |
| 4 | Strong **tests** of hypotheses | Optional; model may propose tests too |
| 5 | Direct wiki edit | Always allowed; not the default loop |

Product should optimize (1–3), not rail-approve every link.

---

## 7. Implementation map

| Layer | Owner | Notes |
|-------|--------|------|
| Intent classify | CE `query_router` / QUERY skill | Advisory; log intent on every turn |
| Needle demotion | CE `graph.py retrieve` type priority | **Only** for N (and L as appropriate) |
| Analysis seed + descend | CE retrieve / QUERY | M path; cite expansion mandatory |
| Compose analysis | CE QUERY agentic loop | S path; primary knowledge-work surface |
| Bench arms | Switch Bay | CE agentic QUERY vs standard RAG vs graph-RAG (e.g. HippoRAG-class) |
| One-shot study-sim SH | Switch Bay | **Plumbing regression** for atoms; not product gate |

---

## 8. Non-goals

- Using extractive Phase-2 denser scores as product proof.
- Shipping vault-first T2 as default (rejected by pilot assembly failure).
- Claiming intro wins from un-rebased suites or n=12 study-sim.
- Treating human wiki micro-edits as the main HITL story.

---

## 9. One-screen cheat sheet

```
needle/locate  → atoms + vault; demote analyses; short honest answer
compare        → pin both poles; structured contrast
matched synth  → analysis hub → descend cites → verify
compose synth  → multi-pass coverage → WRITE analysis + gaps + next Qs
explore        → labeled side-paths; spine preserved
human          → sources, notes, questions (not mainly link-approver)
measure        → coverage, multi-hop, synthesis quality, follow-on richness,
                 serendipity vs drift, calibration — not only exam SH
```
