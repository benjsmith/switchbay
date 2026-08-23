# CE QUERY secondary analysis — interim material read (2026-08-02)

**Directional, opus-4-8 only, zero-quota** (a close read of the generated
material, no judges yet). opus-5 generation hit the weekly Claude limit (8/12
units `<synthetic>`/limit-blocked); the 4-judge scoring + self-preference t-test
are also Claude-quota-blocked. So this is an early read of the *material*, not the
scored Stage-2 result — exactly the "more insight than the stats" the material can
give on its own.

## Stage-1 material generated (native protocol)

12/12 opus-4-8 units complete (synthesis reply + off-leash answer for CE / tool /
RAG × 4 topics). CE native-analysis outcomes:

| topic | CE native offer? | page authored? | note |
|---|---|---|---|
| ap (tech debt) | **yes (turn 0)** | ✅ 9.9k, 26 cites | fully native |
| rp (fairness) | no | ✅ 6.4k, 12 cites | filed on the judgment-deferring accept, not a spontaneous offer |
| mp (privacy, poisoned) | no | ✗ declined | did not crystallize the poisoned synthesis |
| nc (absent quantum) | no | ✗ declined | correct — nothing to crystallize |

CE authored a page on **2 of 4** topics, and **declined** where it should (nc
absent; mp poisoned) — the honest native distribution, no forcing.

## Q1 — is the analysis PAGE richer than the reply? **Directionally yes**

Same topic, CE page vs CE conversational reply:
- **Citation density up sharply** — ap page **26 vault cites vs the reply's 4**
  (similar length); the page is a tightly-grounded artifact, the reply is looser
  prose.
- **Durable structure** — the page organises as a reference: *"What the corpus
  establishes, and what it does not" → "the one mechanism it describes directly:
  entanglement" → "kinds it grounds indirectly" → "how the kinds interrelate: a
  systems-thinking lens" → "Open questions and next steps."*
- **A real generative section** — the page's *Open questions and next steps*
  carries a **specific source request** ("ingest Sculley et al. 2015, NeurIPS
  pp. 2503–2511 … only the paper can ground glue code, pipeline jungles, …") and a
  **testable hypothesis** ("recurrence predicts debt"). The reply gestures at "the
  gap"; the page operationalises it.

So the page adds grounding density + durable synthesis + an explicit
source-request/hypothesis layer over the reply. Matches the expectation.

## Q2 — off-leash generativity across the three arms? **A wash when prompted**

Given the identical off-leash follow-up, **all three arms** produce comparable
generativity — ~6–9k chars, each ends with open questions/hypotheses, each flags
closed-book use (5–7 flags). CE carries more wikilinks (references the wiki
structure), but the *generative* content is not CE-unique when explicitly elicited
— consistent with the primary finding (the doctrine's teaching/generativity shows
up behaviourally but isn't a measurable quality edge).

## Q3/Q4 — CE conservatism + closed-book calibration? **Supported**

On the absent topic (quantum), CE opens with a prominent upfront disclaimer:
> *"Everything substantive below is **my own background knowledge**, not our
> corpus — because our corpus contributes zero quantum content."*

Tool-matched flags too, but as inline per-item tags (`[own-knowledge] — …`). Both
do the correct "cautious where off-corpus" thing; **CE's flagging is more
prominent/upfront** — the "conservative, tightly grounded" quality the blind
adjudicator noticed, now visible in the material.

## What's still pending (Claude-quota-blocked)

- **opus-5 material** — 8/12 units limit-blocked (`<synthetic>`); resume when the
  weekly Claude limit resets (the run is resumable — re-runs only the hard-errored
  units).
- **Stage 2 — the 4-judge blind pass (grok + gpt + opus-4-8 + opus-5) + the
  self-preference t-test.** The non-Claude judges (grok/gpt) could score the
  opus-4-8 material now, but the t-test needs the Claude judges, and the material
  is incomplete without opus-5 — so hold for the reset.

**Net (interim):** the material substantiates that CE's crystallised **pages** are
richer than its **replies** (denser grounding + durable synthesis + a
source-request/hypothesis layer), while off-leash generativity is a wash across
arms and CE's distinctive trait is conservative, well-flagged grounding — coherent
with the primary verdict.

## Stage 2 — 4-judge blind pass on the synthesis replies (2026-08-02)

Full 24-unit material (opus-5 generation re-run after the transient throttle).
Blind reply packs scored by **grok-4.5 + gpt-5.5 + opus-4-8 + opus-5**. (The
opus-5 *judge* itself hit the same transient rate-limit — 10–11/24 — so the
powered stats below use opus-4-8 as the Claude representative and report opus-5
descriptively.)

### Self-preference test — NO Claude self-preference (fully powered, n=24)
All answers are Claude-authored, so a Claude judge scoring them above the
non-Claude judges would be bias. (The anthropic HTTP API ran out of credits
mid-run; the opus-5 judge column was completed via the claude-code subscription.)

**Full test — mean(opus-4-8, opus-5 judges) − mean(grok, gpt), n=24:** Δ **+0.005**,
sd 0.067, **t = 0.39 → not significant**. Judge overall means are flat: grok 0.573,
gpt 0.599, opus-4-8 0.610, opus-5 0.573. **No Claude self-preference** — including
Claude judges would not have distorted the primary verdict.

**Incisive own-model cut** (does opus-N-judge favour opus-N-*authored*?): opus-4-8
judge rates opus-4-8-authored answers **+0.11 higher**, but opus-5 judge rates its
*own*-authored answers **−0.10 *lower*** — the opposite of self-preference. What
both Claude judges agree on is that **opus-4-8's answers grade better than opus-5's**
(a generator-quality signal, consistent with the primary), not a judge bias.

### Per-arm synthesis-reply score — CE is more competitive on synthesis framing
Pooled over the three stable judges (grok, gpt, opus-4-8):

| arm | synthesis-reply score | vs primary (task prompts) |
|---|---|---|
| **ce_product** | **0.624** | reverses — CE ≳ others here |
| rag_modern | 0.589 | |
| tool_matched | 0.569 | primary had tool ≳ CE |

So when the query is framed as a **synthesis** (CE's native mode), CE's replies
grade **at or above** tool-matched — the opposite of the primary's task-prompt
ordering. **But small-n + model-dependent:** by model — opus-4-8 tool 0.70 ≈ ce
0.69 (tool a hair higher); opus-5 ce 0.56 > tool 0.44 (but tool oddly low). With
~4 answers per model/arm cell, treat this as **directional, not a verdict**: it
says CE's advantage is framing-sensitive (shows up on synthesis queries, not task
prompts), consistent with the primary finding that CE's value is in *how* it
retrieves/structures, surfaced when the task rewards synthesis.

## Consolidated read (secondary analysis)

1. **Pages > replies** — CE's crystallised analysis pages are denser-cited, durably
   structured, and carry an explicit source-request/hypothesis layer the chat
   replies lack. The compounding artifact is real (Q1: supported).
2. **Framing matters** — CE grades ≥ tool-matched on *synthesis* queries (secondary)
   but not on *task* prompts (primary); directional given small n.
3. **Off-leash generativity is a wash** across arms when explicitly elicited (Q2).
4. **CE is the conservative, well-flagged one** — heaviest closed-book flagging,
   upfront "this is my knowledge, not the corpus" (Q3/Q4: supported).
5. **No judge self-preference** — Claude judges do not inflate Claude-authored
   answers (opus-4-8 n.s.; opus-5 stingiest), validating the primary's panel design.
6. **Per-model divergence persists** — opus-5 CE crystallised more pages (3 vs 2),
   including on the poisoned mp topic where opus-4-8 declined (flag for a targeted
   look at whether that page repeats or rejects the poison).
