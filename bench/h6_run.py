"""H6 — semantic dissonance / homonym disambiguation: runner.

Reuses the H5 harness (same haystack workspace, retrieval arms, end-to-end
generator). Adds the collision corpus into the already-curated H5 workspace,
curates incrementally, and scores correct-sense accuracy + CONFLATION rate.

  make bench ARGS="-m bench.h6_run setup"
  make bench ARGS="-m bench.h6_run curate"
  make bench ARGS="-m bench.h6_run embed"
  make bench ARGS="-m bench.h6_run score"
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from bench import h6_dissonance
from bench.h5_run import WS, CE, ARMS, GEN, ANSWER_TMPL, _uv_env, _norm, cmd_curate, cmd_embed

# For AMBIGUOUS queries the model must ENUMERATE each distinct sense with its
# context — not emit a bare figure — so attribution is observable.
AMBIG_TMPL = (
    'Using ONLY the context below, list every distinct thing referred to as '
    '"{term}". For EACH one, on its own line, give its project/context and its '
    'figure. If the context contains none, reply exactly: NOT FOUND.\n\n'
    "CONTEXT:\n{ctx}\n\nTERM: {term}\nList:")

QFILE = WS / "h6_questions.json"
RESULTS = Path("bench/results/h6.json")


def cmd_setup(args) -> int:
    """Add the collision corpus to the existing curated H5 haystack workspace
    (ML + H5 needles serve as distractors) and ingest it. No clone/wipe."""
    if not (WS / "vault").is_dir():
        print(f"{WS} has no vault — run bench.h5_run setup first", file=sys.stderr)
        return 1
    raw = WS / "vault" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    for p in raw.glob("*.md"):  # clear inbox (H5 docs were already moved into vault/)
        p.unlink()
    qs = h6_dissonance.build_corpus(raw)
    QFILE.write_text(json.dumps(qs, indent=2), encoding="utf-8")
    print(f"wrote {len(qs)} queries, {len(list(raw.glob('*.md')))} collision docs")
    r = subprocess.run(
        ["uv", "run", "--no-project", "python3", str(CE / "local_ingest.py"),
         "vault/raw", "--exts", "md"],
        cwd=str(WS), env=_uv_env(), capture_output=True, text=True, timeout=600)
    sys.stdout.write(r.stdout[-500:])
    return r.returncode


def _score_ambig(ans: str, gA: str, mA: str, gB: str, mB: str):
    """For an ambiguous (no-context) query, did the answer SEPARATE the two
    senses (each figure attributed to its own project marker) or blend /
    mis-attribute them? Sentence-level co-occurrence, deterministic."""
    import re as _re
    # split on newlines / semicolons / sentence-ending periods — but NOT the
    # period inside a decimal figure ("88.4", "3.8"), or attribution breaks.
    sents = _re.split(r"[;\n]+|\.\s+", ans)

    def has(s, g):
        return _norm(g) in _norm(s)

    covA, covB = _norm(gA) in _norm(ans), _norm(gB) in _norm(ans)
    pairA = any(has(s, gA) and mA.lower() in s.lower() for s in sents)
    pairB = any(has(s, gB) and mB.lower() in s.lower() for s in sents)
    misA = any(has(s, gA) and mB.lower() in s.lower() and mA.lower() not in s.lower() for s in sents)
    misB = any(has(s, gB) and mA.lower() in s.lower() and mB.lower() not in s.lower() for s in sents)
    coverage = covA and covB
    disambig = pairA and pairB and not (misA or misB)
    return {"coverage": coverage, "disambig": disambig,
            "misattrib": coverage and not disambig}


def cmd_score(args) -> int:
    from bench.llm import llm_call
    qs = json.loads(QFILE.read_text())
    arms = args.arms.split(",") if args.arms else list(ARMS)
    rows = []
    for j, q in enumerate(qs):
        rec = {"kind": q["kind"], "term": q["term"], "arms": {}}
        for arm in arms:
            ctx, _ = ARMS[arm](WS, q["query"], k=args.k)
            # Ambiguous queries need an enumeration answer (both senses + their
            # context) — gemini-2.5-flash is a thinking model, so give it enough
            # budget to reason AND emit both lines, or it truncates to one sense.
            if q["kind"] == "ambiguous":
                prompt, mt = AMBIG_TMPL.format(term=q["term"], ctx=ctx[:8000]), 800
            else:
                prompt, mt = ANSWER_TMPL.format(ctx=ctx[:8000], q=q["query"]), 200
            ans, _ok = llm_call(GEN, prompt, max_tokens=mt, temperature=0.0)
            if q["kind"] == "ambiguous":
                m = _score_ambig(ans, q["goldA"], q["markerA"], q["goldB"], q["markerB"])
                m["ans"] = ans[:140]
                rec["arms"][arm] = m
            else:
                na = _norm(ans)
                correct = _norm(q["gold"]) in na
                conflated = (q["conflation_gold"] is not None
                             and _norm(q["conflation_gold"]) in na)
                rec["arms"][arm] = {"correct": correct,
                                    "conflated": conflated and not correct, "ans": ans[:50]}
        rows.append(rec)
        if q["kind"] == "ambiguous":
            got = " ".join(f"{a}:{'◆' if rec['arms'][a]['disambig'] else ('✗' if rec['arms'][a]['misattrib'] else '·')}" for a in arms)
        else:
            got = " ".join(f"{a}:{'✓' if rec['arms'][a]['correct'] else ('✗' if rec['arms'][a]['conflated'] else '·')}" for a in arms)
        print(f"  [{j+1:2}/{len(qs)}] {q['kind']:9} {q['term'][:10]:10} {got}")

    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps({"rows": rows}, indent=2))

    def rate(subset, key):
        return {a: sum(1 for r in subset if r["arms"][a].get(key)) / max(1, len(subset)) for a in arms}

    coll = [r for r in rows if r["kind"] == "collision"]
    sing = [r for r in rows if r["kind"] == "single"]
    ambi = [r for r in rows if r["kind"] == "ambiguous"]
    print(f"\n=== H6 homonym disambiguation ===\n{'':26}" + "".join(f"{a:>7}" for a in arms))
    for label, sub, key in [
        ("single-ctx acc (control)", sing, "correct"),
        ("H6a  in-context correct", coll, "correct"),
        ("H6a  in-context conflate ↓", coll, "conflated"),
        ("H6b  ambiguous coverage", ambi, "coverage"),
        ("H6b  ambiguous separated ◆", ambi, "disambig"),
        ("H6b  ambiguous mis-attrib ↓", ambi, "misattrib"),
    ]:
        r = rate(sub, key)
        print(f"  {label:24}" + "".join(f"{r[a]:>7.2f}" for a in arms))
    print(f"\nwrote {RESULTS}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="h6_run")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("setup"); p.set_defaults(fn=cmd_setup)
    p = sub.add_parser("curate"); p.add_argument("--timeout", type=int, default=2400)
    p.add_argument("--poll", type=int, default=30); p.set_defaults(fn=cmd_curate)
    p = sub.add_parser("embed"); p.set_defaults(fn=cmd_embed)
    p = sub.add_parser("score"); p.add_argument("--arms", default=None)
    p.add_argument("--k", type=int, default=8); p.set_defaults(fn=cmd_score)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
