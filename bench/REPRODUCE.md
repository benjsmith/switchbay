# Reproducing the Switch Bay benchmarks

## Prerequisites (read first)

1. **Install the curiosity-engine skill** — `bench/retrievers.py` and the phase-2
   arms call its scripts (`~/.claude/skills/…` / `~/.agents/skills/…`). Without it,
   CE / tool-matched retrieval fails. Install once globally:

   ```bash
   npx skills add -g -y benjsmith/curiosity-engine
   ```

   The compounding runner detects both `~/.agents/skills/curiosity-engine` and
   `~/.claude/skills/curiosity-engine`. For another location, set
   `CURIOSITY_ENGINE_SKILL_DIR` to the skill root (the directory containing
   `scripts/`).

2. **Phase-2 scenarios are corpus-specific.** The shipped scenarios under
   `bench/agentic_query_bench/scenarios/` were authored for the original
   LectureBank corpus. On `samples/ml-walkthrough`, phase-2 reproduces the
   **method** and the **arm ordering**, not the deck's exact numbers. Supply
   corpus-matched scenarios (same JSON shape: gold themes, an absent topic, an
   optional poison fixture) for a meaningful phase-2 run on another vault.
   See § [The two studies](#the-two-studies) below.

---

This package lets you reproduce the three studies and the secondary analysis in the intro deck
(`docs/intro_and_bench.html`) on the bundled, CC-licensed `samples/ml-walkthrough`
vault — **minimal scientific-rigor reproduction**, run from a coding CLI, with
y/n cost gates so you never incur a large bill unknowingly.

> **Exact figures need the originals.** The deck numbers were produced on a private
> LectureBank-derived corpus with specific model versions. This package reproduces
> the **method** and the **arm ordering** on a shippable corpus; it matches the
> deck's exact numbers only with the original corpus **and** the original models
> (generators `claude-opus-4-8`/`opus-5`; phase-1 judges Fable-5/gpt-5.6; phase-2
> judges grok-4.5/gpt-5.5). The runner prints this caveat every time.

> **Public null result.** Phase-2 (Appendices J–K–L of the intro deck) is a
> **negative** product verdict on single-shot skill-layer quality: structure
> carried the value; the CE skill did not improve judged quality vs a tool-matched
> agent in this test. Publishing that result is intentional scientific integrity.

## Quickstart

```bash
uv sync --group semantic          # numpy + fastembed (required; hard-checked)
python -m bench.reproduce         # detect models → show budget → y/n per stage
```

- `--scale minimal` (default): a cheap demo that validates the method.
- `--scale full`: matches the deck's run size (expensive — see budget).
- `--stages phase1` / `phase2` / `followup`: select an earlier study.
- `--stages compound`: reproduce the five-checkpoint breadth run and the
  eight-round Sonnet repeated-use run in Appendices O–Q.
- `--stages compound-opus`: after `compound`, rewind to the same k=5 state and
  reproduce the four-round Opus curator comparison in Appendix Q.
- `--yes`: headless/CI (assumes yes to every gate — only with `--scale minimal`
  unless you really mean it).
- `--workspace PATH`: benchmark a different curated CE workspace.

Stage 0 (preflight) is **free**: it detects your providers, hard-checks
numpy/fastembed, verifies the RAG tool actually returns hits, and prints the
caveat. Nothing is spent until you answer `y` past it.

## What it will cost

Grounded in **measured** billed cost of the original 72 agentic trajectories;
`ml-walkthrough` runs ~0.6× (smaller context). Billed USD is the honest unit —
the agentic input context isn't fully token-metered.

| scale | phase-1 | phase-2 | **total (API $)** | subscription opportunity cost |
|---|---|---|---|---|
| **minimal** | ~$1.6 | ~$24 | **~$26** | 6 agentic sessions · ~80k output tok · ~0.3h — a small fraction of any plan's day |
| **full** | ~$54 | ~$317 | **~$371** | 84 sessions · ~950k output tok · ~4.4h — likely **> a Pro day**; a few hours on Max 20× |

**Subscription users:** limits are opaque and plan-dependent, so treat the run as
*N agentic sessions* (one long Claude-Code turn each). The full run is ~84 such
sessions over ~4–5 hours of model time — the opportunity cost is roughly **a day
of heavy building** you'd trade for the reproduction. The **minimal** demo is a
few minutes and a small slice of any plan.

The phase-2 agentic matrix is essentially all the cost (CE/tool/RAG trajectories
at $4–10 each) — which is why the runner **hard-gates before it**.

## Studies represented in the deck

- **phase-1 — curation vs modern-RAG (H1–H6).** Auto-generates questions from the
  corpus, so it runs on `ml-walkthrough` out of the box. Produces the correctness /
  recall / win-rate tables and the H5 (synonym) + H6 (dissonance) appendix probes.
- **phase-2 — CE-product verdict (CE vs tool-matched vs modern-RAG).** The
  preregistered pipeline (freeze → matrix → blind judges → aggregate → scorecard).
  Its scored scenarios (`bench/agentic_query_bench/scenarios/`) are hand-authored
  for the original corpus (absent-topic, poisoned-analysis, task prompts). **To run
  phase-2 meaningfully on a different corpus, supply corpus-matched scenarios**
  (same JSON shape — gold themes, an absent topic, an optional poison fixture); the
  shipped ones reproduce exactly only on the original LectureBank corpus.
- **followup — controlled secondary analysis (Appendices M–N).** Poses identical
  synthesis and off-the-leash questions to all three product arms, records CE's
  native crystallisation behavior, and runs a four-judge self-preference control.
- **compounding — breadth and repeated-use depth (Appendices O–Q).** Rebuilds the
  bundled 15-paper corpus in five chronological tranches, then holds the corpus
  fixed while supplementary questions drive eight additional CE curation rounds.
  Every checkpoint is evaluated against both raw-vault RAG and closed-book (CB).
  Those controls cannot absorb curation or use; CE can update its structured wiki.

## Exact Appendix O–Q reproduction

Run from the repository root. These commands are resumable, but expensive: the
full sequence performs five breadth curation sessions, eight Sonnet depth sessions,
and four Opus depth sessions, plus repeated generation and judging.

```bash
# 1. Five breadth checkpoints, then eight fixed-corpus Sonnet depth checkpoints.
#    The eval uses 8 held-out questions × CE/RAG/CB × 13 checkpoints × 3 repeats.
python -m bench.reproduce --scale full --stages compound

# 2. Archive the Sonnet curve, rewind to the identical k=5 workspace, and run
#    four fixed-corpus depth rounds with claude-opus-4-8.
python -m bench.reproduce --scale full --stages compound-opus
```

The exact direct commands used by those two stages are:

```bash
PYTHONPATH=src:. python -m bench.agentic_query_bench.compounding_run \
  --src-ws samples/ml-walkthrough \
  --out-dir bench/repro-out/compounding-v2 \
  --tranches 5 --wave-cap 4 --patience-h 20 \
  --curate-model claude-sonnet-5 --no-eval

PYTHONPATH=src:. python -m bench.agentic_query_bench.compounding_run \
  --out-dir bench/repro-out/compounding-v2 \
  --depth --depth-rounds 8 --wave-cap 2 --patience-h 20 \
  --curate-model claude-sonnet-5 \
  --generator xai --judges xai,gemini --repeats 3

PYTHONPATH=src:. python -m bench.agentic_query_bench.compounding_run \
  --out-dir bench/repro-out/compounding-v2 --rewind

PYTHONPATH=src:. python -m bench.agentic_query_bench.compounding_run \
  --out-dir bench/repro-out/compounding-v2 \
  --depth --depth-rounds 4 --wave-cap 2 --patience-h 20 \
  --curate-model claude-opus-4-8 \
  --generator xai --judges xai,gemini --repeats 3
```

Frozen inputs:

- `compounding_queries.json`: eight held-out evaluation questions, never shown to
  the curator.
- `compounding_explore_queries.json`: sixteen supplementary questions split into
  eight contiguous rounds for Sonnet, or four rounds for Opus. They are a proxy
  for repeated use and are distinct from the held-out questions; adjacency is
  explicitly annotated in the file.
- one fixed generator (`xai`, grok-4.5 in the reported run) and two fixed judges
  (`xai`/grok-4.5 and `gemini`/gemini-3.5-flash) across CE, RAG, CB, and checkpoints.

Key artifacts under `bench/repro-out/compounding-v2/`:

- `checkpoints.json` and `wiki-snapshots/k*/`: the auditable state at every k;
- `eval-results.json`: raw per-cell answers, judges, repeated samples, and means;
- `eval-report.md`: current per-checkpoint CE/RAG/CB table and difference curves;
- `eval-results.depth-claude-sonnet-5.json` and the matching report: automatically
  archived by `--rewind` before the Opus rerun.

The CB arm is not optional bookkeeping: it shows the no-retrieval capability
floor, while RAG shows what the same raw sources provide without curation. Neither
can improve through the supplementary-question rounds. CE combines model knowledge,
retrieval, and its persistent structured wiki, so only CE can compound through use.
Three repeats reduce the generation/judge noise floor enough to assess changes above
that noise; they do not turn the small held-out set into a broad population claim.

## Appendix M–N secondary-analysis commands

After producing the frozen phase-2 workspace, modern-RAG index, and calibration:

```bash
PYTHONPATH=src:. python -m bench.agentic_query_bench.product_secondary \
  --workspace ~/.cache/sy-phase2-bench/ws \
  --out-dir bench/results/product-secondary-v1 \
  --calibration bench/results/rag-modern-calibration/calibration.json \
  --index-dir bench/results/rag-modern-index

PYTHONPATH=src:. python -m bench.agentic_query_bench.product_secondary_judge all \
  --units-dir bench/results/product-secondary-v1/units \
  --out-dir bench/results/product-secondary-judge
```

## Pitfall guards (baked in — from hard-won experience)

1. **Dep guard** — numpy/fastembed are hard-checked at preflight; the runner fails
   loudly rather than letting the RAG arm silently answer closed-book.
2. **Retrieval-failure guard** — a modern-RAG cell that makes 0 `rag_search` calls
   is marked invalid, never scored as RAG.
3. **Per-CLI-call timeout + process-group kill** — a hung judge/generator CLI can't
   stall the run.
4. **Adaptive judges** — if a judge provider is capped/absent, it falls back with a
   disclosed note; the run doesn't block.
5. **Frozen inputs recorded** — corpus + skill + config hashes are written into the
   output so a run is self-describing.

## Providers

The runner uses whatever is configured (`claude-code`, `openai-codex`, `anthropic`,
`openai`, `xai`, `gemini`) and adapts generator + judges to what's available. With
**no** model access it stops cleanly at the free preflight. See `bench/llm.py` for
provider/key configuration.
