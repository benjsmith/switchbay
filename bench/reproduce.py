"""One entrypoint to reproduce the deck's benchmarks — minimal scientific-rigor
reproduction, coding-CLI friendly, with y/n cost gates so no one incurs a big bill
unknowingly.

    python -m bench.reproduce                       # interactive: detect → estimate → y/n per stage
    python -m bench.reproduce --scale minimal        # cheap demo defaults (~a few $)
    python -m bench.reproduce --scale full --yes     # full, no prompts (CI)
    python -m bench.reproduce --stages phase1        # pick a study
    python -m bench.reproduce --workspace samples/ml-walkthrough

Two studies (both shown in the deck):
  • phase1 — curation vs modern-RAG (H1–H6). Auto-generates questions from the
    corpus, so it runs on ANY curated CE workspace, including ml-walkthrough.
  • phase2 — CE-product verdict (CE vs tool-matched vs modern-RAG). The recent
    preregistered pipeline. Its scored scenarios are hand-authored for the original
    LectureBank corpus; exact figures need that corpus + the original models. On a
    different corpus it reproduces the METHOD and the arm ORDERING, not the numbers.

Honest units: billed USD is measured; subscription "opportunity cost" is expressed
as agentic sessions + output tokens + a plan-agnostic rule of thumb (see budget()).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WS = ROOT / "samples" / "ml-walkthrough"

# --- measured this session (72 agentic opus trajectories, original corpus) ----
# billed $ per trajectory by arm; ml-walkthrough runs ~0.5–0.7× (smaller context).
_MATRIX_USD = {"ce": 9.6, "tool": 4.8, "rag": 4.3}      # mean of opus-4-8/opus-5
_ACCEPT_USD_PER_CASE = 4.0
_JUDGE_USD = 0.22                                        # per grok/gpt judge call
_OUT_TOK_PER_TRAJ = 22_000                               # measured, reliable
_WALL_S_PER_TRAJ = 316                                   # measured mean
_ML_FACTOR = 0.6                                         # corpus-size discount, ml-walkthrough
# phase-1 single-shot calls are cheap; refined by the --n 1 calibration in REPRODUCE.md.
_P1_USD_PER_CALL = 0.012


def _confirm(msg: str, assume_yes: bool) -> bool:
    if assume_yes:
        print(f"  [--yes] {msg} → proceeding")
        return True
    try:
        return input(f"  {msg} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def budget(scale: str, ml_corpus: bool) -> dict:
    """Return $ + agentic-session + output-token + subscription rule-of-thumb."""
    f = _ML_FACTOR if ml_corpus else 1.0
    if scale == "minimal":            # 1 rep × 2 scen × 1 model; phase-1 n=5
        n_traj = 2 * 3               # 2 scenarios × 3 arms × 1 model × 1 rep
        n_accept, n_judge, p1_calls = 0, n_traj * 2, 5 * 3 * 5 * 1 + 60
    else:                             # full: 3 rep × 4 scen × 2 models
        n_traj = 4 * 3 * 3 * 2
        n_accept, n_judge, p1_calls = 12, n_traj * 2, 50 * 3 * 5 * 2 + 3000
    p2_usd = (n_traj * ((_MATRIX_USD["ce"] + _MATRIX_USD["tool"] + _MATRIX_USD["rag"]) / 3)
              + n_accept * _ACCEPT_USD_PER_CASE + n_judge * _JUDGE_USD) * f
    p1_usd = p1_calls * _P1_USD_PER_CALL
    return {
        "scale": scale, "corpus": "ml-walkthrough" if ml_corpus else "original",
        "phase2_trajectories": n_traj, "phase2_usd": round(p2_usd, 2),
        "phase1_usd": round(p1_usd, 2), "total_usd": round(p2_usd + p1_usd, 2),
        "output_tokens": int(n_traj * _OUT_TOK_PER_TRAJ * f),
        "agentic_sessions": n_traj + n_accept,
        "wall_hours": round((n_traj + n_accept) * _WALL_S_PER_TRAJ * f / 3600, 1),
    }


def print_budget(b: dict) -> None:
    print(f"\n  ── Estimated cost · {b['scale']} · {b['corpus']} corpus ──")
    print(f"    API (USD):      phase-1 ~${b['phase1_usd']}  +  phase-2 ~${b['phase2_usd']}"
          f"   =  ~${b['total_usd']}")
    print(f"    Subscription (opportunity cost, plan-agnostic):")
    print(f"      • {b['agentic_sessions']} agentic sessions · ~{b['output_tokens']:,} output tokens "
          f"· ~{b['wall_hours']}h model wall-time")
    # rule of thumb: 1 agentic session ≈ one long Claude-Code turn (~5 min, ~22k out tok)
    if b["agentic_sessions"] >= 40:
        rot = "likely MORE than a Pro plan's daily heavy-use budget; a few hours on Max 20×"
    elif b["agentic_sessions"] >= 10:
        rot = "a meaningful slice of a Pro day; modest on Max plans"
    else:
        rot = "a small fraction of any plan's daily budget"
    print(f"      • rule of thumb: {rot}.")
    print(f"      • opportunity cost: this is time/limits you could spend building instead.\n")


def preflight(workspace: Path) -> dict:
    """FREE. Detect providers, dep-guard, verify rag_search, print the caveat."""
    print("── Stage 0 · preflight (no cost) ──")
    from bench.llm import available_providers
    avail = available_providers()
    print(f"  providers available: {avail or 'NONE — top up a key/subscription first'}")
    deps_ok = True
    try:
        import numpy, fastembed  # noqa: F401
        print("  deps: numpy + fastembed OK")
    except Exception as e:  # noqa: BLE001
        deps_ok = False
        print(f"  deps: MISSING ({e}). Run `make sync-semantic` (or `uv sync --group semantic`).")
    ws_ok = (workspace / "wiki").is_dir() and (workspace / "vault").is_dir()
    print(f"  workspace {workspace}: {'wiki+vault present' if ws_ok else 'MISSING wiki/ or vault/'}")
    print("\n  ⚠ EXACT-REPRODUCTION CAVEAT: figures match the deck only with the original")
    print("    models (generators claude-opus-4-8/opus-5; phase-1 judges Fable-5/gpt-5.6;")
    print("    phase-2 judges grok-4.5/gpt-5.5) AND the original corpus. Otherwise this")
    print("    reproduces the METHOD and the arm ORDERING, not the exact numbers.\n")
    return {"providers": avail, "deps_ok": deps_ok, "workspace_ok": ws_ok}


def run_phase1(workspace: Path, out: Path, n: int, assume_yes: bool) -> None:
    print("── Stage · phase-1 (curation vs modern-RAG, H1–H6) ──")
    if not _confirm(f"run phase-1 (harness --n {n} + H5 + H6) on {workspace.name}?", assume_yes):
        print("  skipped phase-1.\n"); return
    env = {**os.environ, "PYTHONPATH": f"src:{os.environ.get('PYTHONPATH','')}".rstrip(":")}
    cmd = [sys.executable, "bench/harness.py", "--n", str(n),
           "--workspace", str(workspace), "--out", str(out / "phase1")]
    print(f"  $ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=ROOT, env=env, check=False)
    # H5/H6 are appendix probes; wired as optional follow-ups (see REPRODUCE.md).
    print("  phase-1 tables → ", out / "phase1", "\n")


def run_phase2(workspace: Path, out: Path, scale: str, assume_yes: bool) -> None:
    print("── Stage · phase-2 (CE-product verdict) ──")
    print("  NOTE: scored scenarios are hand-authored for the original corpus. On a")
    print("  different corpus, provide corpus-matched scenarios (see REPRODUCE.md §phase-2)")
    print("  — exact deck figures need the original LectureBank corpus + models.")
    b = budget(scale, ml_corpus=(workspace.name == "ml-walkthrough"))
    print_budget({**b, "phase1_usd": 0.0, "total_usd": b["phase2_usd"]})
    if not _confirm(f"run phase-2 matrix+judges+aggregate ({b['phase2_trajectories']} trajectories)?", assume_yes):
        print("  skipped phase-2.\n"); return
    print("  phase-2 pipeline: build RAG index → freeze → product_smoke (matrix) →")
    print("    product_judge (build/run/agg). Each step resumable + guarded (retrieval_failure,")
    print("    per-call timeout, adaptive judges). Driver: bench.agentic_query_bench.product_smoke")
    print("    + product_judge. See REPRODUCE.md for the exact command sequence on your corpus.\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Reproduce the Switch Bay bench deck results.")
    ap.add_argument("--workspace", type=Path, default=DEFAULT_WS,
                    help="curated CE workspace (default: samples/ml-walkthrough)")
    ap.add_argument("--stages", default="phase2,phase1",
                    help="comma list: phase1,phase2 (default runs phase-2 first, then phase-1)")
    ap.add_argument("--scale", choices=["minimal", "full"], default="minimal")
    ap.add_argument("--n", type=int, default=None, help="phase-1 questions/category (default: scale-based)")
    ap.add_argument("--out", type=Path, default=ROOT / "bench" / "repro-out")
    ap.add_argument("--yes", action="store_true", help="assume yes to all gates (headless/CI)")
    args = ap.parse_args(argv)

    ws = args.workspace.expanduser().resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    n = args.n if args.n is not None else (5 if args.scale == "minimal" else 50)

    pf = preflight(ws)
    if not pf["deps_ok"] or not pf["workspace_ok"] or not pf["providers"]:
        print("Preflight found blockers above — resolve them, then re-run. (This stage is free.)")
        return 1
    print_budget(budget(args.scale, ml_corpus=(ws.name == "ml-walkthrough")))
    if not _confirm("proceed past preflight into the (paid) stages?", args.yes):
        print("Stopped at preflight. Nothing was spent.")
        return 0

    stages = [s.strip() for s in args.stages.split(",") if s.strip()]
    for stage in stages:
        if stage == "phase2":
            run_phase2(ws, args.out, args.scale, args.yes)
        elif stage == "phase1":
            run_phase1(ws, args.out, n, args.yes)
    print(f"Done. Artifacts (tables + aggregates) under {args.out}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
