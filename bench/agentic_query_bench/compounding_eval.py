"""Compounding eval — the readout half of the compounding study.

`compounding_run.py` grows a curated wiki tranche-by-tranche and drops a frozen
snapshot per checkpoint k (`<out-dir>/wiki-snapshots/k<k>/`, each a
wiki+vault+.curator triple). THIS module scores those snapshots: for every frozen
synthesis query it runs three arms on the material available at k —

  • CE  — vector RAG over the *curated wiki*      (retrievers.retrieve_bprime)
  • RAG — hybrid+rerank over the *raw vault*      (retrievers.retrieve_b)
  • CB  — closed-book, no retrieval               (the capability floor)

— generates a single-shot answer with ONE fixed generator (only the context
differs across arms, isolating retrieval), and grades each answer blind with a
two-model non-generator panel on a reference-free quality rubric (the synthesis
queries have no gold). Readout: CE−RAG and CE−CB vs k (design doc H-compound /
H-ceiling).

Resumable: every (k, arm, query) cell is cached in `eval-results.json`; re-running
recomputes only missing cells, then re-derives the per-k means + curves. Not
session-gated — single-shot answers, unlike the heavy curate cycles.

Run:  PYTHONPATH=src:. uv run --no-sync python -m \
        bench.agentic_query_bench.compounding_eval --out-dir bench/results/compounding-v2
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from statistics import pstdev
from typing import Any

from bench import retrievers
from bench.llm import (
    MODEL_OVERRIDE,
    available_providers,
    llm_call,
    provider_model,
)

HERE = Path(__file__).resolve().parent
QUERIES_PATH = HERE / "compounding_queries.json"

# Providers that spawn a subscription CLI and rate-limit mid-run (a mirror of
# bench.llm.SUBSCRIPTION_CLI, inlined so this module imports against any llm.py
# revision — the eval must prefer ungated HTTP providers over these).
_SUBSCRIPTION_CLI = frozenset({"claude-code", "openai-codex", "grok-build"})

# Provider families — judges must sit OUTSIDE the generator's family (charter:
# non-generator judge families), so an arm can't be flattered by its own model.
FAMILY = {
    "claude-code": "claude", "anthropic": "claude",
    "openai-codex": "openai", "openai": "openai",
    "xai": "xai", "grok-build": "xai",
    "gemini": "gemini",
}
# Generator preference. The CE−RAG *difference* is generator-invariant (the same
# generator answers every arm), so the overriding concern is a generator that
# doesn't rate-limit mid-run: prefer ungated HTTP providers over subscription CLIs
# (claude-code/openai-codex gate after a handful of calls — they gate the whole
# eval). Claude-native `anthropic` still leads when API credits exist (the honest
# "CE answers as Claude" story); CLIs are the last resort.
GEN_PREF = ["anthropic", "openai", "xai", "gemini", "claude-code", "openai-codex"]


def _http_first(avail: list[str]) -> list[str]:
    """Order providers HTTP (ungated) before subscription CLIs (gate mid-run)."""
    return [p for p in avail if p not in _SUBSCRIPTION_CLI] + \
           [p for p in avail if p in _SUBSCRIPTION_CLI]

ARMS = ("CE", "RAG", "CB")
GEN_MAX_TOKENS = 700

_GEN_SYS_GROUNDED = (
    "You are a careful research assistant. Answer the QUESTION by synthesising "
    "ONLY the provided CONTEXT — connect ideas across the sources rather than "
    "listing them. If the context does not support part of the answer, say what "
    "is missing; never invent facts or citations."
)
_GEN_SYS_CLOSED = (
    "You are a careful research assistant. Answer the QUESTION from your own "
    "knowledge, synthesising across the relevant sub-topics. Be precise; if you "
    "are unsure, say so rather than inventing specifics."
)
_JUDGE_SYS = (
    "You are a strict, impartial grader of answers to machine-learning synthesis "
    "questions. You do NOT know which system produced the answer — judge only the "
    "text."
)


def _mid(p: str) -> str:
    return MODEL_OVERRIDE.get(p) or provider_model(p) or p


# ── query set ────────────────────────────────────────────────────────────────
def load_queries(limit: int | None = None) -> tuple[list[dict], str]:
    data = json.loads(QUERIES_PATH.read_text(encoding="utf-8"))
    qs = data["queries"]
    if limit:
        qs = qs[:limit]
    h = hashlib.sha256(
        json.dumps([q["q"] for q in qs], ensure_ascii=False).encode()
    ).hexdigest()[:12]
    return qs, h


# ── one arm's context on a snapshot ──────────────────────────────────────────
def arm_context(arm: str, snapshot: Path, query: str) -> tuple[str, list[str]]:
    if arm == "CE":
        return retrievers.retrieve_bprime(snapshot, query)
    if arm == "RAG":
        return retrievers.retrieve_b(snapshot, query)
    return "", []  # CB — closed-book


def generate(generator: str, query: str, arm: str, context: str) -> tuple[str, bool]:
    if arm == "CB":
        return llm_call(generator, f"QUESTION: {query}\n\nANSWER:",
                        system=_GEN_SYS_CLOSED, max_tokens=GEN_MAX_TOKENS)
    return llm_call(generator, f"CONTEXT:\n{context}\n\nQUESTION: {query}\n\nANSWER:",
                    system=_GEN_SYS_GROUNDED, max_tokens=GEN_MAX_TOKENS)


# ── blind reference-free quality judge ───────────────────────────────────────
_JSON_RE = re.compile(r"\{[^{}]*\"score\"[^{}]*\}", re.S)


def judge_quality(judge: str, query: str, answer: str) -> float | None:
    """0..1 overall-quality score for one answer, blind to arm. None on failure."""
    prompt = (
        "Grade the ANSWER to the QUESTION on overall quality:\n"
        "  • accuracy — claims are correct;\n"
        "  • grounding — claims are supported, not fabricated or hedged into vagueness;\n"
        "  • comprehensiveness — covers the relevant sub-topics the question asks to connect;\n"
        "  • synthesis — genuinely relates ideas across sources, not a flat list.\n"
        "Penalise vagueness, unsupported claims, and invented citations.\n\n"
        f"QUESTION:\n{query}\n\nANSWER:\n{answer}\n\n"
        'Output ONLY compact JSON: {"score": <float 0.0-1.0>, "reason": "<=15 words"}'
    )
    # Budget must clear hidden reasoning: thinking judges (gemini-3.5-flash) spend
    # tokens reasoning BEFORE emitting, so a tight cap reads back empty. The JSON
    # itself is ~30 tokens; the rest is headroom the model may or may not use.
    text, ok = llm_call(judge, prompt, system=_JUDGE_SYS, max_tokens=1024)
    if not ok:
        return None
    m = _JSON_RE.search(text)
    if not m:
        return None
    try:
        s = float(json.loads(m.group(0)).get("score"))
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return max(0.0, min(1.0, s))


# ── snapshots ────────────────────────────────────────────────────────────────
def _snapshots(out_dir: Path) -> list[tuple[int, Path]]:
    root = out_dir / "wiki-snapshots"
    found = []
    for d in sorted(root.glob("k*")):
        m = re.fullmatch(r"k(\d+)", d.name)
        if m and (d / "wiki").is_dir():
            found.append((int(m.group(1)), d))
    return sorted(found)


def _cell_key(k: int, arm: str, qid: str) -> str:
    return f"k{k}|{arm}|{qid}"


def _cell_done(cell: dict | None) -> bool:
    return bool(cell and cell.get("answer") and cell.get("judge_scores"))


# ── main eval loop ───────────────────────────────────────────────────────────
def run_eval(out_dir: Path, *, generator: str | None = None,
             judges: list[str] | None = None, limit_q: int | None = None,
             repeats: int = 1, log=print) -> dict[str, Any]:
    repeats = max(1, repeats)
    out_dir = out_dir.expanduser().resolve()
    snaps = _snapshots(out_dir)
    if not snaps:
        raise SystemExit(f"No wiki snapshots under {out_dir}/wiki-snapshots/ — "
                         "run compounding_run first.")
    queries, qhash = load_queries(limit_q)

    # Providers: probe once. Generator = 1 capable model (fixed across arms);
    # judges = 2 available models OUTSIDE the generator's family.
    if generator is None or judges is None:
        avail = _http_first(available_providers())  # ungated HTTP before gating CLIs
        if not avail:
            raise SystemExit("No usable LLM provider (all out of credit/quota).")
        override = os.environ.get("SY_BENCH_GEN")
        if generator is None:
            generator = (override if override in avail
                         else next((p for p in GEN_PREF if p in avail), avail[0]))
        if judges is None:
            # Two-judge panel, priority order: (1) UNGATED (HTTP — a gating CLI judge
            # fails the run just like a gating generator), (2) family-DIVERSE and
            # outside the generator's family, (3) fall back to an ungated same-family
            # judge before ever touching a gating CLI. With only two ungated families
            # up (openai, xai) this yields e.g. grok + gpt; a same-family judge is
            # warned below and is harmless to the difference-based curve.
            gfam = FAMILY.get(generator)
            http = [p for p in avail if p not in _SUBSCRIPTION_CLI]
            cli = [p for p in avail if p in _SUBSCRIPTION_CLI]
            judges, seen = [], set()
            for p in http:  # pass 1: ungated, diverse, non-generator family
                f = FAMILY.get(p)
                if f == gfam or f in seen:
                    continue
                judges.append(p)
                seen.add(f)
                if len(judges) >= 2:
                    break
            for pool in (http, cli):  # pass 2/3: fill from ungated, then gating CLIs
                for p in pool:
                    if len(judges) >= 2:
                        break
                    if p not in judges:
                        judges.append(p)
            judges = judges[:2] or [generator]
    log(f"generator: {generator}={_mid(generator)}")
    log(f"judges:    " + ", ".join(f"{j}={_mid(j)}" for j in judges))
    if len({FAMILY.get(j) for j in judges} & {FAMILY.get(generator)}):
        log("  WARN: a judge shares the generator's family (self-preference risk) — "
            "note in the writeup; the CE−RAG difference still cancels shared bias.")

    results_path = out_dir / "eval-results.json"
    results: dict[str, Any] = {}
    if results_path.is_file():
        try:
            results = json.loads(results_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            results = {}
    cells: dict[str, Any] = results.get("cells", {})
    # Invalidate the cache if the query set, GENERATOR, or judges changed — a valid
    # curve needs ONE fixed generator across every cell, so a generator switch must
    # discard prior cells rather than mix models.
    gen_tag = f"{generator}={_mid(generator)}"
    judge_tags = [f"{j}={_mid(j)}" for j in judges]
    if (results.get("queries_hash") not in (None, qhash)
            or results.get("generator") not in (None, gen_tag)
            or results.get("judges") not in (None, judge_tags)
            or results.get("repeats", 1) != repeats):
        log("  (query set / generator / judges / repeats changed → recomputing all cells)")
        cells = {}

    def _save():
        results.update({
            "queries_hash": qhash,
            "generator": f"{generator}={_mid(generator)}",
            "judges": [f"{j}={_mid(j)}" for j in judges],
            "repeats": repeats,
            "arms": {"CE": "curated wiki (retrieve_bprime)",
                     "RAG": "raw vault hybrid+rerank (retrieve_b)",
                     "CB": "closed-book (no retrieval)"},
            "cells": cells,
        })
        results.update(_derive(cells, snaps, queries))
        results["depth_analysis"] = _depth_analysis(results["per_k"], out_dir)
        results_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    total = len(snaps) * len(ARMS) * len(queries)
    done = 0
    for k, snap in snaps:
        log(f"── snapshot k={k}  ({snap.name}) ──")
        for q in queries:
            for arm in ARMS:
                key = _cell_key(k, arm, q["id"])
                if _cell_done(cells.get(key)):
                    done += 1
                    continue
                ctx, pages = arm_context(arm, snap, q["q"])
                retrieval_failure = arm in ("CE", "RAG") and not ctx.strip()
                # `repeats` independent (generate → judge) samples, averaged, to cut the
                # generation/judge non-determinism that sets the per-cell noise floor.
                samples, last_ans, last_jscores = [], None, None
                for _rep in range(repeats):
                    ans, gok = generate(generator, q["q"], arm, ctx)
                    if not gok or not ans.strip():
                        break
                    jscores = {j: judge_quality(j, q["q"], ans) for j in judges}
                    jvals = [v for v in jscores.values() if v is not None]
                    if not jvals:
                        break
                    samples.append(sum(jvals) / len(jvals))
                    last_ans, last_jscores = ans, jscores
                if not samples:
                    log(f"  {key}: generation/judging FAILED (provider error) — will retry next run")
                    continue
                cell = {
                    "answer": last_ans,
                    "context_chars": len(ctx),
                    "pages": pages[:12],
                    "retrieval_failure": retrieval_failure,
                    "judge_scores": last_jscores,
                    "mean": sum(samples) / len(samples),
                }
                if repeats > 1:
                    cell["samples"] = [round(s, 4) for s in samples]
                    cell["std"] = round(pstdev(samples), 4) if len(samples) > 1 else 0.0
                cells[key] = cell
                done += 1
                flag = " [RETRIEVAL-FAILURE]" if retrieval_failure else ""
                spread = f" ±{cell['std']:.3f}" if repeats > 1 else ""
                log(f"  {key}: mean={cell['mean']:.3f}{spread} "
                    f"(ctx {len(ctx)}c, n={len(samples)}){flag}  [{done}/{total}]")
                _save()  # checkpoint every cell
    _save()
    _write_report(results, out_dir, log)
    return results


# ── per-k means + curves ─────────────────────────────────────────────────────
def _derive(cells: dict, snaps: list, queries: list) -> dict[str, Any]:
    per_k: dict[str, Any] = {}
    for k, _ in snaps:
        row: dict[str, Any] = {}
        for arm in ARMS:
            vals, dropped = [], 0
            for q in queries:
                c = cells.get(_cell_key(k, arm, q["id"]))
                if not _cell_done(c):
                    continue
                if c.get("retrieval_failure"):  # empty-context arm ≈ closed-book → invalid
                    dropped += 1
                    continue
                vals.append(c["mean"])
            row[arm] = round(sum(vals) / len(vals), 4) if vals else None
            row[f"{arm}_n"] = len(vals)
            if dropped:
                row[f"{arm}_retrieval_failures"] = dropped
        ce, rag, cb = row.get("CE"), row.get("RAG"), row.get("CB")
        row["CE_minus_RAG"] = round(ce - rag, 4) if ce is not None and rag is not None else None
        row["CE_minus_CB"] = round(ce - cb, 4) if ce is not None and cb is not None else None
        per_k[str(k)] = row
    ks = [k for k, _ in snaps]
    curves = {
        "k": ks,
        "CE_minus_RAG": [per_k[str(k)].get("CE_minus_RAG") for k in ks],
        "CE_minus_CB": [per_k[str(k)].get("CE_minus_CB") for k in ks],
    }
    return {"per_k": per_k, "curves": curves}


def _depth_analysis(per_k: dict[str, Any], out_dir: Path) -> dict[str, Any] | None:
    """Denoised fixed-corpus readout used by Appendix Q.

    RAG and CB cannot learn during depth because their corpus/model inputs are fixed.
    Pool their checkpoint means into baselines; their checkpoint-to-checkpoint SD is
    the measured stochastic floor. CE's start/end and early/late means then quantify
    persistent improvement from supplementary use without pretending N=8 queries is
    a population-wide significance test.
    """
    cp = Path(out_dir) / "checkpoints.json"
    if not cp.is_file():
        return None
    try:
        checkpoints = json.loads(cp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    depth = sorted((c for c in checkpoints if c.get("regime") == "depth"),
                   key=lambda c: c.get("k", 0))
    breadth = [c for c in checkpoints if c.get("regime") != "depth"]
    if not depth or not breadth:
        return None
    start_k = max(c["k"] for c in breadth)
    depth_ks = [c["k"] for c in depth if str(c.get("k")) in per_k]
    if not depth_ks or str(start_k) not in per_k:
        return None

    def vals(arm: str) -> list[float]:
        return [per_k[str(k)][arm] for k in depth_ks
                if isinstance(per_k[str(k)].get(arm), (int, float))]

    ce, rag, cb = vals("CE"), vals("RAG"), vals("CB")
    if not ce:
        return None
    pool = lambda xs: sum(xs) / len(xs) if xs else None
    rag_pool, cb_pool = pool(rag), pool(cb)
    rag_sd = pstdev(rag) if len(rag) > 1 else 0.0 if rag else None
    cb_sd = pstdev(cb) if len(cb) > 1 else 0.0 if cb else None
    start_ce = per_k[str(start_k)].get("CE")
    end_ce = ce[-1]
    gain = end_ce - start_ce if isinstance(start_ce, (int, float)) else None
    cut = max(1, len(ce) // 2)
    curator = depth[-1].get("curator")
    start_pages = next((c.get("state", {}).get("wiki_pages") for c in breadth
                        if c.get("k") == start_k), None)
    end_pages = depth[-1].get("state", {}).get("wiki_pages")
    noise = max(x for x in (rag_sd, cb_sd) if x is not None) if (rag_sd is not None or cb_sd is not None) else None
    return {
        "curator": curator,
        "start_k": start_k,
        "depth_ks": depth_ks,
        "start_ce": round(start_ce, 4) if isinstance(start_ce, (int, float)) else None,
        "end_ce": round(end_ce, 4),
        "ce_gain": round(gain, 4) if gain is not None else None,
        "ce_early_mean": round(pool(ce[:cut]), 4),
        "ce_late_mean": round(pool(ce[-cut:]), 4),
        "rag_pool": round(rag_pool, 4) if rag_pool is not None else None,
        "cb_pool": round(cb_pool, 4) if cb_pool is not None else None,
        "end_minus_rag_pool": round(end_ce - rag_pool, 4) if rag_pool is not None else None,
        "end_minus_cb_pool": round(end_ce - cb_pool, 4) if cb_pool is not None else None,
        "rag_checkpoint_sd": round(rag_sd, 4) if rag_sd is not None else None,
        "cb_checkpoint_sd": round(cb_sd, 4) if cb_sd is not None else None,
        "max_control_noise_sd": round(noise, 4) if noise is not None else None,
        "gain_exceeds_control_noise_sd": bool(gain is not None and noise is not None and gain > noise),
        "wiki_pages_start": start_pages,
        "wiki_pages_end": end_pages,
        "wiki_pages_added": (end_pages - start_pages
                             if isinstance(start_pages, int) and isinstance(end_pages, int) else None),
    }


def _write_report(results: dict, out_dir: Path, log=print) -> None:
    per_k, curves = results.get("per_k", {}), results.get("curves", {})
    ks = curves.get("k", [])
    L = ["# Compounding eval — CE vs RAG vs closed-book across curation checkpoints", "",
         f"Generator: `{results.get('generator')}` · Judges: "
         + ", ".join(f"`{j}`" for j in results.get("judges", []))
         + f" · queries_hash `{results.get('queries_hash')}`", "",
         "Arms: **CE** = curated wiki · **RAG** = raw-vault hybrid+rerank · "
         "**CB** = closed-book. Blind reference-free quality rubric (0–1). "
         "Retrieval-failure cells (empty context) are excluded from that arm's mean.", "",
         "## Per-checkpoint means", "",
         "| k | CE | RAG | CB | CE−RAG | CE−CB | n |",
         "|--:|:--:|:--:|:--:|:------:|:-----:|:-:|"]
    def _f(x):
        return f"{x:.3f}" if isinstance(x, (int, float)) else "—"
    for k in ks:
        r = per_k.get(str(k), {})
        L.append(f"| {k} | {_f(r.get('CE'))} | {_f(r.get('RAG'))} | {_f(r.get('CB'))} | "
                 f"{_f(r.get('CE_minus_RAG'))} | {_f(r.get('CE_minus_CB'))} | {r.get('CE_n','—')} |")
    L += ["", "## Curves (the readout)", "",
          "```", f"k              : {ks}",
          f"CE − RAG       : {[round(x,3) if isinstance(x,(int,float)) else None for x in curves.get('CE_minus_RAG', [])]}",
          f"CE − closed-bk : {[round(x,3) if isinstance(x,(int,float)) else None for x in curves.get('CE_minus_CB', [])]}",
          "```", "",
          "**Reading (design doc):** a *rising* CE−RAG with k is the compounding "
          "result (H-compound); flat/shrinking sharpens the capability-boundary "
          "finding. CE−CB bounds how much retrieval of any kind can add (H-ceiling). "
          "Small-N: treat as directional, not significant.", ""]
    da = results.get("depth_analysis")
    if da:
        L += ["## Fixed-corpus depth readout (pooled controls)", "",
              f"Curator: `{da.get('curator')}` · depth k: `{da.get('depth_ks')}`", "",
              "| CE start | CE end | CE gain | early CE | late CE | RAG pool (σ) | CB pool (σ) |",
              "|:--------:|:------:|:-------:|:--------:|:-------:|:------------:|:-----------:|",
              f"| {_f(da.get('start_ce'))} | {_f(da.get('end_ce'))} | "
              f"{_f(da.get('ce_gain'))} | {_f(da.get('ce_early_mean'))} | "
              f"{_f(da.get('ce_late_mean'))} | {_f(da.get('rag_pool'))} "
              f"({_f(da.get('rag_checkpoint_sd'))}) | {_f(da.get('cb_pool'))} "
              f"({_f(da.get('cb_checkpoint_sd'))}) |", "",
              f"End CE − pooled RAG: **{_f(da.get('end_minus_rag_pool'))}** · "
              f"End CE − pooled CB: **{_f(da.get('end_minus_cb_pool'))}** · "
              f"pages added: **{da.get('wiki_pages_added', '—')}**.", "",
              "The CE gain " + ("exceeds" if da.get("gain_exceeds_control_noise_sd") else "does not exceed")
              + " the larger checkpoint SD of the two fixed controls. This is the "
              "measured stochastic-floor comparison used by Appendix Q; query-level "
              "generalisation remains small-N.", ""]
    # crude monotonicity note when ≥3 real points
    cr = [x for x in curves.get("CE_minus_RAG", []) if isinstance(x, (int, float))]
    if len(cr) >= 3:
        trend = ("rising" if cr[-1] > cr[0] + 0.02 else
                 "flat" if abs(cr[-1] - cr[0]) <= 0.02 else "shrinking")
        L.append(f"_Observed CE−RAG trend across {len(cr)} checkpoints: **{trend}** "
                 f"({cr[0]:.3f} → {cr[-1]:.3f})._")
    path = out_dir / "eval-report.md"
    path.write_text("\n".join(L), encoding="utf-8")
    log(f"wrote {path}")
    log(f"wrote {out_dir / 'eval-results.json'}")


def main():
    ap = argparse.ArgumentParser(description="Compounding eval: CE/RAG/CB curves across snapshots")
    ap.add_argument("--out-dir", type=Path, default=Path("bench/results/compounding-v2"))
    ap.add_argument("--generator", default=None, help="force generator provider id")
    ap.add_argument("--judges", default=None, help="comma-separated judge provider ids")
    ap.add_argument("--limit-queries", type=int, default=None)
    ap.add_argument("--repeats", type=int, default=1,
                    help="independent (generate→judge) samples per cell, averaged, to cut "
                         "the noise floor (e.g. 3). Changing this recomputes all cells.")
    args = ap.parse_args()
    judges = args.judges.split(",") if args.judges else None
    run_eval(args.out_dir, generator=args.generator, judges=judges,
             limit_q=args.limit_queries, repeats=args.repeats)


if __name__ == "__main__":
    main()
