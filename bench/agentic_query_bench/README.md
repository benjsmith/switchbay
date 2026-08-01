# Agentic QUERY vs RAG bench (Phase 2 rethink)

Multi-turn knowledge-work bench (essay / article / lesson / research planning).

| Doc | Role |
|-----|------|
| `docs/phase2-agentic-query-bench-design.md` | Design |
| `docs/ce-query-intent-taxonomy.md` | QUERY intents |
| `docs/reorientation-review-2026-07-21.md` | External review (A1–A7) |
| `judgment-charter.json` | **Canonical** rubric (schema_version 2) |
| `preregistration.json` | Directional claims, n, arms |
| `judge_fewshot_hard_negatives.md` | Drift/serendipity calibration |

## Arms

| Arm | Mandatory |
|-----|-----------|
| `ce_query` | yes — harness-internal simulation (`ce_query_sim_v2`) behind the shared QUERY orchestrator |
| `ce_query_real` | proposed small pilot — installed CE classifier + graph retrieval on a fail-on-diff workspace snapshot |
| `agentic_plain` | yes (same loop budget, vault only) |
| `rag_std` | yes |
| `ce_retrieve_only` | yes |
| `closed_book` | yes |
| `long_ctx` | pilot |
| `rag_wiki_text` | pilot |
| `rag_graph` | optional stub |

## Corpus

```text
~/.cache/sy-phase2-bench/ws
```

No densify redo for v1. The poison fixture is injected for M-path cards at
the card's `poisoned_analysis.relative_path` (default
`wiki/analyses/_privacy-utility-tradeoffs.md` — innocuous name on purpose;
paths leak into retrieval context) and **deleted again in a `finally` after
each trajectory**. If a run is SIGKILLed mid-trajectory, grep the wiki for
leading-underscore analyses before the next run.

## Scenarios (pilot)

| Id | Family / note |
|----|----------------|
| `ep-comp599-privacy-transparency-01` | essay |
| `ep-stat453-nesterov-essay-02` | essay |
| `ap-comp599-tech-debt-article-01` | article + user_contribution |
| `lp-stat453-optimizers-lesson-01` | lesson |
| `rp-comp599-fairness-research-01` | research + examiner side-path fork |
| `nc-absent-theme-quantum-01` | negative control |
| `mp-poisoned-analysis-privacy-01` | poisoned analysis M-path |

## Run (after implementation review — not yet a scored experiment)

Note: the offline stub deliberately emits unresolvable cites, so **every
dry-run trajectory reports `provenance_violation=true`** — that exercises
the gate; it is not a harness failure. Prefer a scratch **copy** of the
workspace for dry-runs.

```bash
# Stub generator, offline
PYTHONPATH=src:. python -m bench.agentic_query_bench.run \
  --workspace ~/.cache/sy-phase2-bench/ws --dry-run

# Live (example)
PYTHONPATH=src:. python -m bench.agentic_query_bench.run \
  --workspace ~/.cache/sy-phase2-bench/ws \
  --arms closed_book,rag_std,agentic_plain,ce_query \
  --generate-provider xai --repeats 2
```

## Gates & primary score

- **Cite-resolver v5** separates malformed/abbreviated citation conformance,
  unresolved semantic wikilinks, and fully specified nonexistent provenance.
  Only the last class sets `provenance_violation` and excludes the trajectory.
- **Primary** = mean of clusters coverage/grounding/writing/generativity/steering.
- **serendipity_quality** reported separately; card-anchored.
- **Drift** primary signal = examiner re-steer rate.

## Proposed real-QUERY pilot (not authorized)

The model-free preflight must pass before any smoke:

```bash
PYTHONPATH=src:. python -m bench.agentic_query_bench.preflight_real_ce \
  --workspace ~/.cache/sy-phase2-bench/ws \
  --out bench/results/real-ce-query-preflight.json
```

It runs the deterministic installed classifier/retriever against temporary
copies only. It proves zero workspace diffs and captures corpus/script hashes;
it does not call a generator or judge. See
`real_pilot_preregistration.draft.json` and
`docs/real-ce-query-pilot-plan-2026-07-23.md`.

## Status

| Piece | State |
|-------|--------|
| Design + charter v2 + prereg | yes |
| Harness modules | yes |
| Pilot scenarios | 7 |
| Live gen/judge run | **not run** (awaiting external code review) |
| Intro claims | **forbidden** |
