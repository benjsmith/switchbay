"""H5 — alias / synonym resolution: runner (v3, end-to-end).

Design + pre-registration: docs/benchmark-h5-prereg.md.

Stages (subcommands, in order):
  setup   Clone a real CURATED workspace (curiosity-test, 392 pages) as the
          distractor HAYSTACK, drop the H5 needle docs into vault/raw, and
          local_ingest them alongside it. (--isolated wipes the haystack for a
          needles-only corpus — the old, retrieval-trivial mode; not for v3.)
  curate  Incrementally curate the new needle docs into the haystack wiki+graph
          (claude -p, Code subscription).
  embed   graph.py embed → rebuild wiki.db over the whole wiki (for B′).
  score   For every (query, arm): retrieve with an EQUAL budget, then a fixed
          cheap generator (gemini-2.5-flash) answers FROM CONTEXT ONLY (figure,
          or NOT FOUND). Deterministic gold-value match → no judge bias.
          Reports per family × query-type accuracy, the paired canonical→alias
          penalty with bootstrap CIs, retrieval recall (diagnostic), and the
          control false-bridge / abstain rates.

  make bench ARGS="-m bench.h5_run setup"
  make bench ARGS="-m bench.h5_run curate"
  make bench ARGS="-m bench.h5_run embed"
  make bench ARGS="-m bench.h5_run score"
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from bench import h5_synonym
from bench import retrievers

TEMPLATE_WS = Path.home() / "Dev" / "curiosity-test"   # curated 392-page haystack
WS = Path.home() / ".cache" / "sy-h5-bench"
RESULTS = Path("bench/results/h5.json")
CE = Path.home() / ".claude" / "skills" / "curiosity-engine" / "scripts"

ARMS = {
    "A0": retrievers.retrieve_a0,      # keyword over wiki
    "A1": retrievers.retrieve_a1,      # vector-seeded graph traversal
    "B":  retrievers.retrieve_b,       # raw-vault RAG (the baseline)
    "B'": retrievers.retrieve_bprime,  # wiki-RAG (curated pages)
    "R":  retrievers.retrieve_routed,  # adaptive routing (shipped)
}
GEN = "gemini"  # gemini-2.5-flash via bench/llm.MODEL_OVERRIDE
ANSWER_TMPL = (
    "Answer strictly from the CONTEXT below. If the context states the figure "
    "the question asks for, reply with just that figure and nothing else. If the "
    "context does not contain it, reply with exactly: NOT FOUND.\n\n"
    "CONTEXT:\n{ctx}\n\nQUESTION: {q}\nANSWER:")


def _uv_env() -> dict:
    return {k: v for k, v in os.environ.items()
            if k not in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "PYTHONPATH")}


def _norm(s: str) -> str:
    """Match figures robustly: lowercase, drop commas/whitespace."""
    return re.sub(r"[,\s]", "", (s or "").lower())


# ── setup ────────────────────────────────────────────────────────────
def cmd_setup(args) -> int:
    if not TEMPLATE_WS.is_dir():
        print(f"template workspace not found: {TEMPLATE_WS}", file=sys.stderr)
        return 1
    if WS.exists():
        if not args.force:
            print(f"{WS} exists — pass --force to re-clone", file=sys.stderr)
            return 1
        shutil.rmtree(WS)
    WS.parent.mkdir(parents=True, exist_ok=True)
    print(f"cloning {TEMPLATE_WS} → {WS} …")
    r = subprocess.run(["cp", "-c", "-R", str(TEMPLATE_WS), str(WS)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        subprocess.run(["cp", "-R", str(TEMPLATE_WS), str(WS)], check=True)

    if args.isolated:
        # needles-only (retrieval-trivial; kept for comparison, not v3).
        for rel in ("vault", "wiki", ".curator/graph.kuzu", ".curator/wiki.db",
                    ".curator/sessions", ".curator/.graph-meta.json",
                    ".curator/derived", ".curator/identifiers"):
            p = WS / rel
            shutil.rmtree(p) if p.is_dir() else (p.unlink() if p.exists() else None)
        (WS / "wiki").mkdir(parents=True, exist_ok=True)
    else:
        # HAYSTACK: keep the curated 392-page corpus as distractors. Only clear
        # the raw inbox so curiosity-test's own raw docs aren't re-ingested.
        raw = WS / "vault" / "raw"
        if raw.is_dir():
            shutil.rmtree(raw)
        for rel in (".curator/sessions",):
            p = WS / rel
            if p.is_dir():
                shutil.rmtree(p)
    (WS / "vault" / "raw").mkdir(parents=True, exist_ok=True)

    questions = h5_synonym.build_corpus(WS / "vault" / "raw")
    (WS / "h5_questions.json").write_text(json.dumps(questions, indent=2), encoding="utf-8")
    docs = list((WS / "vault" / "raw").glob("*.md"))
    hay = len(list((WS / "wiki").rglob("*.md")))
    print(f"wrote {len(questions)} questions, {len(docs)} needle docs; "
          f"haystack wiki pages present: {hay}")

    print("ingesting needles (local_ingest) …")
    r = subprocess.run(
        ["uv", "run", "--no-project", "python3", str(CE / "local_ingest.py"),
         "vault/raw", "--exts", "md"],
        cwd=str(WS), env=_uv_env(), capture_output=True, text=True, timeout=900)
    sys.stdout.write(r.stdout[-800:])
    if r.returncode != 0:
        sys.stderr.write(r.stderr[-2000:])
        return 1
    print("ingest ok" if (WS / "vault" / "vault.db").is_file() else "vault.db MISSING")
    return 0


# ── curate ───────────────────────────────────────────────────────────
def cmd_curate(args) -> int:
    if not (WS / ".curator").is_dir():
        print("run `setup` first", file=sys.stderr)
        return 1
    print("launching CE curate (claude -p, subscription) …")
    subprocess.run(
        ["uv", "run", "--no-project", "python3", str(CE / "curate_launch.py"),
         "--workspace", str(WS)],
        cwd=str(WS), env=_uv_env(), capture_output=True, text=True)
    print("polling curate_status …")
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        time.sleep(args.poll)
        s = subprocess.run(
            ["uv", "run", "--no-project", "python3", str(CE / "curate_status.py"),
             "--workspace", str(WS)],
            cwd=str(WS), env=_uv_env(), capture_output=True, text=True)
        try:
            st = json.loads(s.stdout or "{}")
        except json.JSONDecodeError:
            st = {}
        gone = st.get("status") in ("no-sessions", "not-found")
        pages = len(list((WS / "wiki").rglob("*.md")))
        print(f"  [{int(time.monotonic()-deadline+args.timeout)}s] "
              f"alive={st.get('alive')} gone={gone} wiki_pages={pages}")
        if st.get("alive") is False or gone:
            print("curate session exited")
            return 0
    print("curate still running at timeout", file=sys.stderr)
    return 2


# ── embed ────────────────────────────────────────────────────────────
def cmd_embed(args) -> int:
    print("graph.py embed → wiki.db …")
    r = subprocess.run(
        ["uv", "run", "--no-project", "python3", str(CE / "graph.py"), "embed"],
        cwd=str(WS), env=_uv_env(), capture_output=True, text=True, timeout=1200)
    sys.stdout.write(r.stdout[-800:])
    return r.returncode


# ── score (end-to-end) ───────────────────────────────────────────────
def _boot_ci(vals: list[float], n: int = 2000, seed: int = 0) -> tuple[float, float]:
    if not vals:
        return (0.0, 0.0)
    rng = random.Random(seed)
    m = len(vals)
    means = []
    for _ in range(n):
        s = sum(vals[rng.randrange(m)] for _ in range(m)) / m
        means.append(s)
    means.sort()
    return (round(means[int(0.025 * n)], 3), round(means[int(0.975 * n)], 3))


def cmd_score(args) -> int:
    from bench.llm import llm_call
    qs = json.loads((WS / "h5_questions.json").read_text())
    arms = args.arms.split(",") if args.arms else list(ARMS)
    rows = []
    for j, q in enumerate(qs):
        rec = {"family": q["family"], "query_type": q["query_type"],
               "entity": q["entity"], "gold": q["gold"],
               "alias_len": q["alias_len"], "arms": {}}
        for arm in arms:
            ctx, _src = ARMS[arm](WS, q["query"], k=args.k)
            recall = _norm(q["gold"]) in _norm(ctx)
            ans, ok = llm_call(GEN, ANSWER_TMPL.format(ctx=ctx[:8000], q=q["query"]),
                               max_tokens=200, temperature=0.0)
            acc = _norm(q["gold"]) in _norm(ans)
            rec["arms"][arm] = {"recall": recall, "acc": acc,
                                "abstain": "notfound" in _norm(ans), "ans": ans[:50]}
        rows.append(rec)
        got = " ".join(f"{a}:{'✓' if rec['arms'][a]['acc'] else '·'}" for a in arms)
        print(f"  [{j+1:2}/{len(qs)}] {q['family']:8} {q['query_type']:9} {q['name'][:24]:24} {got}")

    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps({"rows": rows}, indent=2))
    _report(rows, arms)
    return 0


def _report(rows: list[dict], arms: list[str]) -> None:
    fams = ("real_syn", "codename")
    qts = ("canonical", "alias")

    def acc_list(fam, qt, arm):
        return [1.0 if r["arms"][arm]["acc"] else 0.0
                for r in rows if r["family"] == fam and r["query_type"] == qt]

    print("\n=== answer accuracy (gemini-2.5-flash, from retrieved context) ===")
    for fam in fams:
        print(f"\n[{fam}]  {'':11}" + "".join(f"{a:>7}" for a in arms))
        for qt in qts:
            vals = {a: acc_list(fam, qt, a) for a in arms}
            print(f"  {qt:20}" + "".join(f"{sum(vals[a])/len(vals[a]):>7.2f}" for a in arms))
        # paired canonical→alias penalty, per entity, with bootstrap CI
        print(f"  {'penalty (can−ali)':20}", end="")
        ents = sorted({r["entity"] for r in rows if r["family"] == fam})
        for a in arms:
            pen = []
            for e in ents:
                c = [r for r in rows if r["entity"] == e and r["query_type"] == "canonical"]
                al = [r for r in rows if r["entity"] == e and r["query_type"] == "alias"]
                if c and al:
                    pen.append((1.0 if c[0]["arms"][a]["acc"] else 0.0)
                               - (1.0 if al[0]["arms"][a]["acc"] else 0.0))
            lo, hi = _boot_ci(pen)
            print(f"{sum(pen)/len(pen):>7.2f}", end="")
        print()
        for a in arms:  # CIs on a second line to keep columns readable
            pass

    # retrieval recall (diagnostic) on alias queries
    print("\n=== retrieval recall on ALIAS queries (gold value in context) ===")
    print(f"{'':11}" + "".join(f"{a:>7}" for a in arms))
    for fam in fams:
        vals = {a: [1.0 if r["arms"][a]["recall"] else 0.0
                    for r in rows if r["family"] == fam and r["query_type"] == "alias"]
                for a in arms}
        print(f"  {fam:9}" + "".join(f"{sum(vals[a])/len(vals[a]):>7.2f}" for a in arms))

    # control: false-bridge (reported a figure) vs abstain
    ctl = [r for r in rows if r["family"] == "control"]
    if ctl:
        print("\n=== control (look-alike, no entity) — lower false-bridge = better ===")
        print(f"{'':13}" + "".join(f"{a:>7}" for a in arms))
        fb = {a: sum(1 for r in ctl if r["arms"][a]["acc"]) / len(ctl) for a in arms}
        ab = {a: sum(1 for r in ctl if r["arms"][a]["abstain"]) / len(ctl) for a in arms}
        print("  false-bridge" + "".join(f"{fb[a]:>7.2f}" for a in arms))
        print("  abstained   " + "".join(f"{ab[a]:>7.2f}" for a in arms))
    print(f"\nwrote {RESULTS}")


def main() -> int:
    ap = argparse.ArgumentParser(prog="h5_run")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("setup"); p.add_argument("--force", action="store_true")
    p.add_argument("--isolated", action="store_true", help="wipe haystack (needles-only)")
    p.set_defaults(fn=cmd_setup)
    p = sub.add_parser("curate"); p.add_argument("--timeout", type=int, default=2400)
    p.add_argument("--poll", type=int, default=30); p.set_defaults(fn=cmd_curate)
    p = sub.add_parser("embed"); p.set_defaults(fn=cmd_embed)
    p = sub.add_parser("score"); p.add_argument("--arms", default=None)
    p.add_argument("--k", type=int, default=8, help="equal retrieval budget per arm")
    p.set_defaults(fn=cmd_score)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
