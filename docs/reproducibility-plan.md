# Switch Bay bench — reproducibility package plan + token/cost budget (2026-08-01)

Goal: let an interested researcher reproduce the results **shown in the deck**
(phase-1 curation-vs-RAG + phase-2 product verdict) on the shippable
`samples/ml-walkthrough` vault, from a coding CLI, with one command + y/n cost
gates, adapting to whatever model APIs they have — minimal scientific-rigor
reproduction, not a polished product feature. This doc is the plan + the budget
estimate (the estimate is calibrated from **real billed cost** of this session's
runs, not a fresh rerun).

## Cost budget — grounded in measured `total_cost_usd`

The phase-2 numbers are **measured** from the 72 agentic trajectories actually run
this session (on the LectureBank corpus). Phase-1 is **estimated** from call
structure (single-shot, context-based — far cheaper per call). All are for the
**original** corpus; on `ml-walkthrough` (25 sources vs 92 vault + 882 wiki)
agentic context is smaller, so expect **~50–70% of these** for phase-2.

| stage | unit cost (measured/est.) | full-repro count | full subtotal |
|---|---|---|---|
| **Phase-2 matrix** (agentic, opus) | CE **$8.7–10.4** · tool $4.1–5.6 · RAG $3.9–4.7 /traj | 72 traj (3 arms×4 scen×3 rep×2 models) | **~$449** (measured) |
| Phase-2 acceptance | ~$4/case | 12 (6×2 models) | ~$49 |
| Phase-2 judges | ~$0.15–0.30/call (grok+gpt) | 144 | ~$30 |
| **Phase-1 harness** (single-shot) | ~$0.005–0.02/call | ~4,500 calls (n=50×3cat×5arm×2gen + judges) | ~$40–90 (est.) |
| Phase-1 H5 synonym + H6 dissonance | cheap (gemini-flash, deterministic score) | ~hundreds | ~$10–25 (est.) |
| **FULL, original corpus** | | | **~$580–650** |
| **FULL, ml-walkthrough** (×0.5–0.7 phase-2) | | | **~$350–480** |

**Minimal-demo config** (validates the method, not the exact numbers): phase-1
`--n 5`, phase-2 **1 repeat × 2 scenarios × cheapest available model**, judges
optional → **~$30–70**. This is the default the one-command runner should offer
first.

Token note: recorded input-token counts undercount agentic context (the stream
driver logs ~63 input tok/traj while output is ~22k — context re-feed isn't
summed), so **billed USD is the honest unit**, not token totals. Output tokens are
reliable (~1.58M output across the 72 matrix trajectories).

## The single most important design consequence

The phase-2 matrix is the whole cost (agentic opus trajectories at $4–10 each).
**The runner must show this estimate and hard-gate (y/n) before the matrix**, and
default to the minimal-demo scale — this is exactly the "don't incur a huge bill
unknowingly" requirement.

## Reproducer design — `reproduce.py` (one entrypoint, staged, gated)

```
python -m bench.reproduce            # interactive: detect models → estimate → y/n per stage
python -m bench.reproduce --yes --scale minimal   # CI/headless minimal
python -m bench.reproduce --scale full --stages phase2   # pick studies/scale
```

- **Stage 0 — preflight (no cost).** Detect available providers (`bench.llm
  available_providers`); import-check numpy/fastembed + build/load the RAG index;
  verify `rag_search` returns hits (the guard that would have caught our
  contamination); check the CLI-driver timeout is set. Print a per-provider table
  + **the exact-reproduction caveat**: results match the deck only with the
  original model versions (opus-4-8/opus-5 generators; Fable-5/gpt-5.6 phase-1
  judges; grok-4.5/gpt-5.5 phase-2 judges) — otherwise it reproduces the *method*
  and *ordering*, not the exact figures.
- **Stage 1 — phase-1** (curation vs RAG): questions → arms → multi-judge →
  tables (H1–H4) + H5/H6. Adapts generator/judges to available providers.
- **Stage 2 — phase-2** (product verdict): freeze → matrix → judges → aggregate →
  scorecard tables. **Behind the loud cost gate.**
- Each stage: prints its estimate, asks **y/n**, is **resumable** (checkpoint per
  cell — kill/rerun safe), emits only the **minimal artifacts** (the summary
  tables + aggregate JSON), writes them to `bench/repro-out/`.

### Pitfalls baked in (from this session)
1. **Dep guard** — hard preflight on numpy/fastembed; fail loud, don't silently
   fall back (caused the RAG contamination).
2. **RAG retrieval-failure guard** — `product_mechanics.retrieval_failure`; a
   0-`rag_search` cell is invalid, never scored.
3. **Per-CLI-call timeout + process-group kill** (`product_judge`) — the grok hang.
4. **Adaptive judges** — if a judge provider is capped/absent, fall back with a
   disclosed note (as we did codex→OpenAI-API); never block the whole run.
5. **Frozen inputs** — corpus hash + skill hash + config pins recorded in the
   output so a run is self-describing.

## Packaging manifest (what moves to switchbay)

INCLUDE (clean code, no artifacts):
- `bench/` **code only**: `harness.py`, `retrievers.py`, `h5_run.py`, `h5_synonym.py`,
  `h6_run.py`, `h6_dissonance.py`, `llm.py`, `make_context_pack.py`, and
  `bench/agentic_query_bench/*.py` (the product pipeline) + the **new** `reproduce.py`.
- `bench/agentic_query_bench/scenarios/`, `evidence_dossiers/`, `fixtures/`,
  `judgment-charter.json`, `real_pilot_preregistration.frozen*.json` (frozen inputs).
- `docs/intro_and_bench.html` (the deck, with appendix J–L).
- A `bench/REPRODUCE.md` (quickstart + the budget table above + caveats).

EXCLUDE (run artifacts / dev-only):
- `bench/results/` (3.9 GB), `~/.cache/sy-phase2-bench/` (7.6 GB), `bench/cache/`,
  `bench/phase2/`, `__pycache__`, `study_sim/`, the `_*.py` scratch scripts,
  `bulk_curate.py`, internal working docs, and this session's `product-secondary-*`.
- Corpus: ship **only** `samples/ml-walkthrough` (already CC-cleared); the runner
  points at it by default.

## Open items before build
1. **Confirm the phase-1 estimate** with 1–2 tiny calibration calls on
   ml-walkthrough (harness `--n 1`) — cheap, tightens the ~$40–90 range.
2. **Minimal-demo defaults** — is 1 repeat × 2 scenarios × 1 model the right cheap
   default for phase-2, or even smaller (1 scenario)?
3. Build order: phase-2 wrapper first (higher value, cost-gated) or phase-1 first?
