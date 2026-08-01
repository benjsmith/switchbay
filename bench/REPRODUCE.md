# Reproducing the Switch Bay benchmarks

## Prerequisites (read first)

1. **Install the curiosity-engine skill** — `bench/retrievers.py` and the phase-2
   arms call its scripts (`~/.claude/skills/…` / `~/.agents/skills/…`). Without it,
   CE / tool-matched retrieval fails. Install once globally:

   ```bash
   npx skills add -g -y benjsmith/curiosity-engine
   ```

2. **Phase-2 scenarios are corpus-specific.** The shipped scenarios under
   `bench/agentic_query_bench/scenarios/` were authored for the original
   LectureBank corpus. On `samples/ml-walkthrough`, phase-2 reproduces the
   **method** and the **arm ordering**, not the deck's exact numbers. Supply
   corpus-matched scenarios (same JSON shape: gold themes, an absent topic, an
   optional poison fixture) for a meaningful phase-2 run on another vault.
   See § [The two studies](#the-two-studies) below.

---

This package lets you reproduce the two studies in the intro deck
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
- `--stages phase1` / `--stages phase2`: run one study.
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

## The two studies

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
