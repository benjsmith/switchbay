"""Benchmark orchestrator: generate questions grounded in the corpus,
answer them through each retrieval arm (identical generator), and score
with a multi-judge, position-bias-controlled panel.

Run:  PYTHONPATH=src uv run --no-sync python bench/harness.py --n 5
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from switchbay import tools
from bench import retrievers as R
from bench.llm import llm_call, available_providers

MAX_WORKERS = 8                  # bounded concurrency across the 4 providers
GENERATOR = "anthropic"          # fixed per-run; reset to an AVAILABLE provider in main()
GEN_PREF = ["anthropic", "openai", "xai", "gemini"]  # preference order for the generator
CORPUS = Path.home() / "Dev" / "curiosity-test"
random.seed(1234)


def _provider_failed(ans: str) -> bool:
    """A generator/judge infrastructure failure (credit/quota/network) — the
    arm's answer is missing through no fault of retrieval, so exclude from
    scoring rather than count it wrong. '[no context retrieved]' is NOT
    this — that's a legit retrieval miss and is graded normally."""
    return bool(ans) and ans.startswith("[") and ("Error" in ans or "credit" in ans or "quota" in ans)


def _json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _pages_by_type(ws: Path, types: set[str]) -> list[str]:
    out = []
    for rel, p in tools._iter_wiki_pages(ws):
        try:
            _t, typ = tools._page_meta(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if (typ or "").casefold() in types:
            out.append(rel)
    return out


# ── Question generation ──────────────────────────────────────────────
def gen_single_hop(ws: Path, n: int) -> list[dict]:
    pool = _pages_by_type(ws, {"concept", "entity", "fact", "evidence"})
    random.shuffle(pool)
    qs = []
    for page in pool:
        if len(qs) >= n:
            break
        _rel, txt = R._read_page_text(ws, page)
        if len(txt) < 300:
            continue
        out, ok = llm_call(GENERATOR, (
            "From the wiki page below, write ONE specific factual question "
            "answerable SOLELY from this page, plus its concise answer. "
            "Avoid yes/no. Return JSON {\"question\":...,\"answer\":...}.\n\n"
            f"PAGE {page}:\n{txt}"), max_tokens=400)
        j = _json(out) if ok else None
        if j and j.get("question") and j.get("answer"):
            qs.append({"category": "single_hop", "question": j["question"],
                       "gold_answer": j["answer"], "gold_pages": [page]})
    return qs


def gen_multi_hop(ws: Path, n: int) -> list[dict]:
    idx = tools._graph_index(ws)
    seeds = [p for p in idx.out if idx.out[p] and idx.ptype.get(p) in ("concept", "entity", "analysis")]
    random.shuffle(seeds)
    qs = []
    for a in seeds:
        if len(qs) >= n:
            break
        nbrs = [b for b in idx.out[a] if idx.ptype.get(b) != "source"]
        if not nbrs:
            continue
        b = random.choice(nbrs)
        _r1, ta = R._read_page_text(ws, a)
        _r2, tb = R._read_page_text(ws, b)
        if len(ta) < 250 or len(tb) < 250:
            continue
        out, ok = llm_call(GENERATOR, (
            "Write ONE question that REQUIRES a fact from BOTH pages A and B "
            "to answer — neither page alone is sufficient — plus the concise "
            "answer. Return JSON {\"question\":...,\"answer\":...}.\n\n"
            f"PAGE A ({a}):\n{ta}\n\nPAGE B ({b}):\n{tb}"), max_tokens=400)
        j = _json(out) if ok else None
        if j and j.get("question") and j.get("answer"):
            qs.append({"category": "multi_hop", "question": j["question"],
                       "gold_answer": j["answer"], "gold_pages": [a, b]})
    return qs


def gen_global(ws: Path, n: int) -> list[dict]:
    analyses = _pages_by_type(ws, {"analysis", "concept"})
    random.shuffle(analyses)
    qs = []
    for seed in analyses[: n * 2]:
        if len(qs) >= n:
            break
        _r, txt = R._read_page_text(ws, seed)
        topic = tools._graph_index(ws).ptitle.get(seed, seed)
        out, ok = llm_call(GENERATOR, (
            "Below is one page from a knowledge base about machine-learning "
            "research. Write ONE broad 'sensemaking' question about the main "
            "themes, trade-offs, or how ideas relate ACROSS the whole corpus "
            f"(not just this page), anchored on the topic '{topic}'. Return "
            "JSON {\"question\":...}.\n\n" + txt[:1200]), max_tokens=200)
        j = _json(out) if ok else None
        if j and j.get("question"):
            qs.append({"category": "global", "question": j["question"],
                       "gold_answer": None, "gold_pages": [seed]})
    return qs


# ── Answering ────────────────────────────────────────────────────────
ANSWER_SYS = (
    "You answer questions using ONLY the provided context passages. Be "
    "concise, factual, and specific. Cite the relevant passage titles. If "
    "the context is insufficient to answer, say exactly what is missing.")


def answer(question: str, context: str) -> tuple[str, bool]:
    if not context.strip():
        return "[no context retrieved]", True
    return llm_call(GENERATOR, f"CONTEXT:\n{context}\n\nQUESTION: {question}\n\nANSWER:",
                    system=ANSWER_SYS, max_tokens=500)


# ── Retrieval recall (diagnostic) ────────────────────────────────────
def retrieval_recall(ws: Path, arm: str, retrieved: list[str], gold_pages: list[str]) -> float:
    if not gold_pages:
        return float("nan")
    idx = tools._graph_index(ws)
    ret = set()
    for s in retrieved:
        ret.add(s.removeprefix("wiki/").removesuffix(".md"))
        ret.add(s)
    hit = 0
    for g in gold_pages:
        gnorm = g.removeprefix("wiki/").removesuffix(".md")
        covered = gnorm in ret or g in ret
        if not covered:
            # An arm that retrieved a vault source the gold page CITES also
            # "covers" it (applies to B and the hybrid, which pull vault
            # sources; a no-op for pure wiki-page arms).
            cites = idx.cites.get(g, set())
            covered = any(any(c in r for c in cites) for r in retrieved)
        hit += 1 if covered else 0
    return hit / len(gold_pages)


# ── Judging ──────────────────────────────────────────────────────────
def judge_correctness(judge: str, q: str, gold: str, cand: str) -> float | None:
    out, ok = llm_call(judge, (
        "Grade the candidate answer against the reference. Return JSON "
        "{\"verdict\":\"correct\"|\"partial\"|\"incorrect\"}.\n\n"
        f"QUESTION: {q}\nREFERENCE: {gold}\nCANDIDATE: {cand}"), max_tokens=300)
    j = _json(out) if ok else None
    if not j:
        return None
    return {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}.get(str(j.get("verdict")).lower())


def judge_pairwise(judge: str, q: str, ans1: str, ans2: str) -> str | None:
    """Which answer is more comprehensive + diverse (global Qs). Returns
    'A'/'B'/'tie' where A is ans1."""
    out, ok = llm_call(judge, (
        "Two answers to a sensemaking question. Judge which is more "
        "comprehensive (covers more relevant themes) AND diverse (varied "
        "perspectives), for a reader wanting to understand the topic "
        "broadly. Return JSON {\"winner\":\"1\"|\"2\"|\"tie\"}.\n\n"
        f"QUESTION: {q}\n\nANSWER 1:\n{ans1}\n\nANSWER 2:\n{ans2}"), max_tokens=300)
    j = _json(out) if ok else None
    if not j:
        return None
    w = str(j.get("winner")).lower()
    return {"1": "A", "2": "B", "tie": "tie"}.get(w)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5, help="questions per category")
    ap.add_argument("--out", default="bench/results")
    ap.add_argument("--workspace", type=Path, default=None,
                    help="curated CE workspace (wiki+vault+.curator) to benchmark; "
                         "defaults to the dev CORPUS. Point at samples/ml-walkthrough to reproduce.")
    ap.add_argument("--reuse", default=None,
                    help="load questions+answers from a prior results JSON and only "
                         "compute/judge arms not already present (adds new arms apples-to-apples)")
    args = ap.parse_args()

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    ws = (args.workspace.expanduser().resolve() if args.workspace else CORPUS)
    print(f"Corpus: {ws}  ({sum(1 for _ in tools._iter_wiki_pages(ws))} pages)")
    print("Probing providers…")
    avail = available_providers()
    if not avail:
        raise SystemExit("No usable LLM provider (all out of credit/quota). Top up a key and retry.")
    global GENERATOR
    # SY_BENCH_GEN forces a generator (the cheap probe passes even when a
    # provider is out of credit for real answering — e.g. anthropic depleted).
    override = os.environ.get("SY_BENCH_GEN")
    GENERATOR = override if override in avail else next((p for p in GEN_PREF if p in avail), avail[0])
    # Judges = all available (multi-judge). Robustness caveat when only one
    # is up is noted in the report.
    judges = avail
    # Confirm the exact model IDs before running (charter: latest-gen only).
    from bench.llm import MODEL_OVERRIDE, provider_model
    def _mid(p):
        return MODEL_OVERRIDE.get(p) or provider_model(p)
    print(f"Generator: {GENERATOR}={_mid(GENERATOR)} | Judges: "
          + ", ".join(f"{j}={_mid(j)}" for j in judges) + "\n")

    # 1. Questions — fresh, or reused from a prior run (to add arms on the
    #    IDENTICAL question set, apples-to-apples).
    if args.reuse:
        questions = json.loads(Path(args.reuse).read_text())
        print(f"Reusing {len(questions)} questions from {args.reuse}; "
              f"computing arms not already present: "
              f"{[a for a in R.ARMS if a not in (questions[0].get('arms') or {})]}")
    else:
        print("Generating questions…")
        questions = (gen_single_hop(ws, args.n) + gen_multi_hop(ws, args.n)
                     + gen_global(ws, args.n))
        print(f"  {len(questions)} questions "
              f"({sum(q['category']=='single_hop' for q in questions)} single, "
              f"{sum(q['category']=='multi_hop' for q in questions)} multi, "
              f"{sum(q['category']=='global' for q in questions)} global)")

    # Pre-warm shared indices (built once, then read concurrently) so the
    # thread pool below doesn't race to build them.
    tools._graph_index(ws)
    R._wiki_vector_index(ws)

    # 2. Answer through each arm (question-level concurrency)
    print(f"Answering through arms ({MAX_WORKERS} workers)…")

    def _answer_one(q):
        q.setdefault("arms", {})
        for arm, fn in R.ARMS.items():
            if arm in q["arms"]:      # reuse mode: keep prior arms, add new ones
                continue
            ctx, srcs = fn(ws, q["question"], category=q["category"])
            ans, _ok = answer(q["question"], ctx)
            q["arms"][arm] = {"answer": ans, "sources": srcs,
                              "recall": retrieval_recall(ws, arm, srcs, q["gold_pages"])}
        return q

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for i, _ in enumerate(ex.map(_answer_one, questions)):
            if (i + 1) % 10 == 0:
                print(f"  answered {i+1}/{len(questions)}")

    # 3. Judge (question-level concurrency)
    print(f"Judging ({MAX_WORKERS} workers)…")

    def _judge_one(q):
        if q["category"] in ("single_hop", "multi_hop"):
            for arm, a in q["arms"].items():
                if "correctness" in a:     # reuse mode: don't re-judge prior arms
                    continue
                if _provider_failed(a["answer"]):
                    a["correctness"] = None
                    continue
                scores = [judge_correctness(j, q["question"], q["gold_answer"], a["answer"]) for j in judges]
                scores = [s for s in scores if s is not None]
                a["correctness"] = sum(scores) / len(scores) if scores else None
                a["per_judge"] = scores
        else:
            base = q["arms"]["B"]["answer"]
            if _provider_failed(base):
                return q
            for arm, a in q["arms"].items():
                if arm == "B" or "global_winrate_vs_B" in a or _provider_failed(a["answer"]):
                    continue
                wins = []
                for j in judges:
                    r1 = judge_pairwise(j, q["question"], a["answer"], base)   # arm as A
                    r2 = judge_pairwise(j, q["question"], base, a["answer"])   # swapped
                    # normalise: count arm-wins across both orderings
                    if r1 == "A":
                        wins.append(1)
                    elif r1 == "B":
                        wins.append(0)
                    if r2 == "B":
                        wins.append(1)
                    elif r2 == "A":
                        wins.append(0)
                a["global_winrate_vs_B"] = sum(wins) / len(wins) if wins else None
        return q

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for i, _ in enumerate(ex.map(_judge_one, questions)):
            if (i + 1) % 10 == 0:
                print(f"  judged {i+1}/{len(questions)}")

    # 4. Aggregate + write
    ts = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    (outdir / f"pilot-{ts}.json").write_text(json.dumps(questions, indent=2))
    _summarize(questions, judges, outdir / f"pilot-{ts}.md")
    print(f"\nWrote {outdir}/pilot-{ts}.json + .md")


def _mean(xs):
    xs = [x for x in xs if x is not None and x == x]
    return sum(xs) / len(xs) if xs else None


def _summarize(questions, judges, path: Path):
    arms = ["A0", "A1", "A1P", "B", "Bp", "H", "HA", "R", "Bwc", "Bww", "Bwd"]
    lines = ["# CE-vs-RAG pilot", "",
             f"Judges: {', '.join(judges)} · generator: {GENERATOR} · both-ordering pairwise", ""]
    for cat in ("single_hop", "multi_hop"):
        qs = [q for q in questions if q["category"] == cat]
        if not qs:
            continue
        lines += [f"## {cat} — answer correctness (0–1) + retrieval recall", "",
                  "| arm | correctness | recall |", "|---|---|---|"]
        for arm in arms:
            corr = _mean([q["arms"][arm].get("correctness") for q in qs])
            rec = _mean([q["arms"][arm].get("recall") for q in qs])
            lines.append(f"| {arm} | {corr:.2f} | {rec:.2f} |" if corr is not None else f"| {arm} | – | – |")
        lines.append("")
    gq = [q for q in questions if q["category"] == "global"]
    if gq:
        lines += ["## global — comprehensiveness/diversity win-rate vs B (RAG)", "",
                  "| arm | win-rate vs B |", "|---|---|"]
        for arm in ("A0", "A1", "A1P", "Bp", "H", "HA", "R", "Bwc", "Bww", "Bwd"):
            wr = _mean([q["arms"][arm].get("global_winrate_vs_B") for q in gq])
            lines.append(f"| {arm} | {wr:.2f} |" if wr is not None else f"| {arm} | – |")
        lines.append("\n(0.5 = parity with vector RAG; >0.5 = better.)")
    path.write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
