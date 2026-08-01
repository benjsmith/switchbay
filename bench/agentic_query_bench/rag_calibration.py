"""Isolated, unscored calibration for ``rag_modern_agentic_v1``.

Mechanically selects the retrieval configuration and the no-answer threshold on
a set that is **disjoint** from the four scored scenarios (review B3), then
freezes the choice. The calibration set is:

  present queries  — turns of the non-matrix pilot scenarios whose gold source
                     families do NOT intersect any scored scenario's gold
                     families (the disjointness gate drops overlaps);
  absent probes    — authored queries on topics absent from this ML corpus and
                     distinct from the scored absent topic (quantum), used only
                     to set the abstention threshold on CORPUS-absence — never on
                     model confidence (review decision C caveat: model-authored
                     probes are still in the host's training distribution, so
                     corpus-absent != parametric-absent).

Selection order: gold-passage recall, then MRR, then lower latency. Contains no
scored-scenario answers. Emits a frozen record with model IDs, config/corpus
hashes, per-variant metrics, and the disjointness proof.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bench.agentic_query_bench.rag_modern import (
    PINNED,
    Embedder,
    ModernRagIndex,
    config_hash,
)

ROOT = Path(__file__).resolve().parent
SCORED_SCENARIOS = [
    "nc-absent-theme-quantum-01",
    "mp-poisoned-analysis-privacy-01",
    "ap-comp599-tech-debt-article-01",
    "rp-comp599-fairness-research-01",
]
# Non-matrix pilot scenarios that MAY seed calibration (subject to disjointness).
CANDIDATE_SCENARIOS = [
    "ep-comp599-privacy-transparency-01",
    "ep-stat453-nesterov-essay-02",
    "lp-stat453-optimizers-lesson-01",
]
EVAL_K = 10

# Authored absent-topic probes. Deliberately NOT quantum (the scored absent
# case) and clearly outside a COMP599/STAT453 ML privacy/optimization corpus.
ABSENT_PROBES = [
    "Explain the light-dependent reactions of photosynthesis in chloroplasts.",
    "How does the CRISPR-Cas9 system achieve targeted gene editing?",
    "Describe the proof-of-stake consensus mechanism used by blockchains.",
    "What were the main causes of the French Revolution of 1789?",
    "Summarize the plot and themes of Shakespeare's Hamlet.",
    "How does a four-stroke internal combustion engine work?",
]


def _scenario(name: str) -> dict[str, Any]:
    return json.loads((ROOT / "scenarios" / f"{name}.json").read_text(encoding="utf-8"))


def _gold_families(scenario: dict[str, Any]) -> set[str]:
    fams: set[str] = set()
    for g in scenario.get("gold_themes", []) or []:
        fams |= set(g.get("source_families", []) or [])
    return fams


def scored_gold_families() -> set[str]:
    fams: set[str] = set()
    for name in SCORED_SCENARIOS:
        fams |= _gold_families(_scenario(name))
    return fams


@dataclass
class CalibrationSet:
    present: list[dict[str, Any]] = field(default_factory=list)   # {query, gold_families, scenario}
    absent: list[dict[str, Any]] = field(default_factory=list)    # {query}
    dropped: list[dict[str, Any]] = field(default_factory=list)   # {scenario, reason}
    scored_families: list[str] = field(default_factory=list)
    used_families: list[str] = field(default_factory=list)


def build_calibration_set() -> CalibrationSet:
    scored = scored_gold_families()
    cs = CalibrationSet(scored_families=sorted(scored))
    used: set[str] = set()
    for name in CANDIDATE_SCENARIOS:
        scen = _scenario(name)
        fams = _gold_families(scen)
        overlap = fams & scored
        if overlap or not fams:
            cs.dropped.append(
                {"scenario": name, "reason": f"gold families overlap scored set: {sorted(overlap)}"
                 if overlap else "no gold families"}
            )
            continue
        used |= fams
        for turn in scen.get("turns", []) or []:
            q = str(turn.get("user_template") or "").strip()
            if q:
                cs.present.append(
                    {"query": q, "gold_families": sorted(fams), "scenario": name}
                )
    cs.used_families = sorted(used)
    for q in ABSENT_PROBES:
        cs.absent.append({"query": q})
    return cs


def assert_disjoint(cs: CalibrationSet | None = None) -> dict[str, Any]:
    """Preflight-grade disjointness assertion (raises on failure)."""
    cs = cs or build_calibration_set()
    scored = set(cs.scored_families)
    used = set(cs.used_families)
    bad = used & scored
    if bad:
        raise AssertionError(f"calibration gold families overlap scored set: {sorted(bad)}")
    # absent probes must not restate the scored absent topic (quantum)
    for item in cs.absent:
        if "quantum" in item["query"].casefold():
            raise AssertionError("absent probe reuses the scored absent topic (quantum)")
    if not cs.present:
        raise AssertionError("no disjoint present queries available for calibration")
    return {
        "disjoint": True,
        "scored_families": sorted(scored),
        "calibration_families": sorted(used),
        "dropped": cs.dropped,
        "n_present": len(cs.present),
        "n_absent": len(cs.absent),
    }


def _chunk_is_gold(path: str, gold_families: list[str]) -> bool:
    p = path.casefold()
    return any(fam.casefold() in p for fam in gold_families)


def _deterministic_rewrites(query: str, *, max_rewrites: int = 3) -> list[str]:
    """Deterministic multi-query expansion (calibration only; the live arm gets
    multi-query from the agent issuing its own rag_search calls)."""
    import re

    out = [query]
    # salient content tokens (drop very common words) as a keyword query
    toks = re.findall(r"[A-Za-z][A-Za-z0-9\-]{3,}", query)
    stop = {"what", "which", "with", "that", "this", "from", "your", "should",
            "before", "using", "prefer", "check", "their", "them", "then",
            "into", "about", "plan", "essay", "lesson"}
    keys = [t for t in toks if t.casefold() not in stop]
    if keys:
        out.append(" ".join(keys[:8]))
    # first clause (before first comma/period) as a focused query
    head = re.split(r"[,.;:]", query, maxsplit=1)[0].strip()
    if head and head != query:
        out.append(head)
    # dedupe preserve order
    seen: set[str] = set()
    uniq = []
    for q in out:
        if q not in seen:
            seen.add(q)
            uniq.append(q)
    return uniq[:max_rewrites]


# variant -> (retrieval mode, apply cross-encoder rerank). "multiquery" is a
# calibration-only expansion; the live agentic arm gets multi-query for free by
# issuing several rag_search calls, so it maps to (hybrid, rerank).
VARIANTS = ["lexical", "dense", "hybrid", "hybrid_rerank", "multiquery_hybrid_rerank"]
VARIANT_LIVE = {
    "lexical": ("lexical", False),
    "dense": ("dense", False),
    "hybrid": ("hybrid", False),
    "hybrid_rerank": ("hybrid", True),
    "multiquery_hybrid_rerank": ("hybrid", True),
}


def _retrieve_topk(index: ModernRagIndex, query: str, variant: str, k: int) -> tuple[list[int], float]:
    """Return top-k chunk indices and the abstention relevance score.

    The abstention score is ALWAYS the top dense cosine (a real, cross-query
    comparable relevance signal), independent of the ranking variant — RRF/rank
    scores are not comparable across queries.
    """
    rel = index.top_dense_score(query)
    if variant == "lexical":
        return index.candidate_indices(query, mode="lexical", pool=k)[:k], rel
    if variant == "dense":
        return index.candidate_indices(query, mode="dense", pool=k)[:k], rel
    if variant == "hybrid":
        return index.candidate_indices(query, mode="hybrid", pool=k)[:k], rel
    if variant == "hybrid_rerank":
        cand = index.candidate_indices(query, mode="hybrid", pool=PINNED["retrieve_pool"])
        ranked = index.rerank_indices(query, cand)
        return [i for i, _ in ranked[:k]], rel
    # multiquery_hybrid_rerank
    pool: list[int] = []
    seen: set[int] = set()
    for rq in _deterministic_rewrites(query):
        for i in index.candidate_indices(rq, mode="hybrid", pool=PINNED["retrieve_pool"]):
            if i not in seen:
                seen.add(i)
                pool.append(i)
    ranked = index.rerank_indices(query, pool)
    return [i for i, _ in ranked[:k]], rel


@dataclass
class VariantMetrics:
    variant: str
    recall: float
    mrr: float
    latency_s: float
    present_top_scores: list[float] = field(default_factory=list)
    absent_top_scores: list[float] = field(default_factory=list)


def evaluate_variant(index: ModernRagIndex, cs: CalibrationSet, variant: str, *, k: int = EVAL_K) -> VariantMetrics:
    hits = 0
    rr_sum = 0.0
    present_tops: list[float] = []
    t0 = time.perf_counter()
    for item in cs.present:
        topk, top = _retrieve_topk(index, item["query"], variant, k)
        present_tops.append(top)
        first_rank = None
        for rank, ci in enumerate(topk):
            if _chunk_is_gold(index.chunks[ci].path, item["gold_families"]):
                first_rank = rank
                break
        if first_rank is not None:
            hits += 1
            rr_sum += 1.0 / (first_rank + 1)
    absent_tops: list[float] = []
    for item in cs.absent:
        _, top = _retrieve_topk(index, item["query"], variant, k)
        absent_tops.append(top)
    latency = time.perf_counter() - t0
    n = max(1, len(cs.present))
    return VariantMetrics(
        variant=variant,
        recall=hits / n,
        mrr=rr_sum / n,
        latency_s=latency,
        present_top_scores=present_tops,
        absent_top_scores=absent_tops,
    )


def _select_threshold(present_tops: list[float], absent_tops: list[float]) -> dict[str, Any]:
    """Pick a no-answer threshold on CORPUS-absence: maximize balanced accuracy
    (answer present, abstain absent). Ties → the most conservative (higher)."""
    grid = sorted(set(present_tops + absent_tops))
    if not grid:
        return {"threshold": 0.0, "balanced_accuracy": 0.0}
    best = {"threshold": grid[0], "balanced_accuracy": -1.0}
    P = max(1, len(present_tops))
    A = max(1, len(absent_tops))
    lo, hi = grid[0] - 1e-6, grid[-1] + 1e-6
    for thr in [lo] + grid + [hi]:
        tp = sum(1 for s in present_tops if s >= thr) / P   # answered present
        tn = sum(1 for s in absent_tops if s < thr) / A     # abstained absent
        bacc = 0.5 * (tp + tn)
        if bacc > best["balanced_accuracy"] or (
            bacc == best["balanced_accuracy"] and thr > best["threshold"]
        ):
            best = {"threshold": float(thr), "balanced_accuracy": float(bacc),
                    "present_answer_rate": float(tp), "absent_abstain_rate": float(tn)}
    return best


def select_config(index: ModernRagIndex, cs: CalibrationSet) -> dict[str, Any]:
    metrics = [evaluate_variant(index, cs, v) for v in VARIANTS]
    # winner by recall, then MRR, then lower latency
    winner = max(metrics, key=lambda m: (round(m.recall, 6), round(m.mrr, 6), -m.latency_s))
    thr = _select_threshold(winner.present_top_scores, winner.absent_top_scores)
    live_mode, live_rerank = VARIANT_LIVE[winner.variant]
    return {
        "chosen_variant": winner.variant,
        "live_mode": live_mode,
        "live_rerank": live_rerank,
        "no_answer_threshold": thr["threshold"],
        "threshold_selection": thr,
        "per_variant": [
            {"variant": m.variant, "recall": m.recall, "mrr": m.mrr, "latency_s": m.latency_s}
            for m in metrics
        ],
    }


def run_calibration(
    workspace: Path,
    *,
    out: Path,
    embedder: Embedder | None = None,
) -> dict[str, Any]:
    cs = build_calibration_set()
    disjoint = assert_disjoint(cs)
    index = ModernRagIndex(Path(workspace), embedder=embedder).build()
    selection = select_config(index, cs)
    record = {
        "schema_version": 1,
        "arm": PINNED["arm"],
        "status": "calibration_result_unscored",
        "pinned": PINNED,
        "config_hash": config_hash(),
        "corpus_hash": index.corpus_hash,
        "n_chunks": len(index.chunks),
        "disjointness": disjoint,
        "calibration_set": {
            "present": cs.present,
            "absent": cs.absent,
            "dropped": cs.dropped,
        },
        "selection": selection,
    }
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    rec = run_calibration(args.workspace.expanduser().resolve(), out=args.out)
    print(json.dumps({
        "chosen_variant": rec["selection"]["chosen_variant"],
        "no_answer_threshold": rec["selection"]["no_answer_threshold"],
        "n_chunks": rec["n_chunks"],
        "dropped": [d["scenario"] for d in rec["calibration_set"]["dropped"]],
        "out": str(args.out),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
