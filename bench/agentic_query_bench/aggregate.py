"""Aggregate trajectories + judgments into the preregistered report.

Applies: provenance gate (headline exclusion), agreement gate (kappa < 0.5
drops judge drift + serendipity from composite use), 5-cluster primary,
paired bootstrap by scenario (prereg test), completion/failure tables.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

from bench.agentic_query_bench.judges import compute_span_kappa
from bench.agentic_query_bench.scoring import load_charter, primary_score

KAPPA_MIN = 0.5


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _sd(xs: list[float]) -> float | None:
    if len(xs) < 2:
        return None
    m = _mean(xs) or 0.0
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


def load_results(results_dir: Path) -> tuple[list[dict], dict, dict]:
    """Return (trajectories, packs_by_stem, judgments_by_stem)."""
    trajs: list[dict] = []
    packs: dict[str, dict] = {}
    for f in sorted((results_dir / "trajectories").glob("*.json")):
        obj = json.loads(f.read_text(encoding="utf-8"))
        obj["_stem"] = f.stem
        trajs.append(obj["trajectory"] if "trajectory" in obj else obj)
        if "judge_pack" in obj:
            packs[f.stem] = obj["judge_pack"]
        trajs[-1]["_stem"] = f.stem
    judgments: dict[str, dict[str, dict]] = defaultdict(dict)
    jdir = results_dir / "judgments"
    if jdir.is_dir():
        for f in sorted(jdir.glob("*.json")):
            stem, _, judge = f.stem.rpartition(".")
            try:
                judgments[stem][judge] = json.loads(f.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
    return trajs, packs, dict(judgments)


def mean_judge_scores(judgs: dict[str, dict]) -> dict[str, float]:
    acc: dict[str, list[float]] = defaultdict(list)
    for j in judgs.values():
        for k, v in (j.get("scores") or {}).items():
            acc[k].append(float(v))
    return {k: sum(v) / len(v) for k, v in acc.items()}


def paired_bootstrap(
    per_scenario_a: dict[str, float],
    per_scenario_b: dict[str, float],
    iters: int = 2000,
    seed: int = 7,
) -> dict[str, Any] | None:
    """Bootstrap the mean(a-b) over shared scenarios. Positive = a wins."""
    shared = sorted(set(per_scenario_a) & set(per_scenario_b))
    if len(shared) < 3:
        return None
    diffs = [per_scenario_a[s] - per_scenario_b[s] for s in shared]
    rng = random.Random(seed)
    n = len(diffs)
    boots = []
    for _ in range(iters):
        sample = [diffs[rng.randrange(n)] for _ in range(n)]
        boots.append(sum(sample) / n)
    boots.sort()
    lo = boots[int(0.025 * iters)]
    hi = boots[int(0.975 * iters)]
    p_gt = sum(1 for b in boots if b > 0) / iters
    return {
        "n_scenarios": n,
        "mean_diff": sum(diffs) / n,
        "ci95": [lo, hi],
        "frac_boot_gt_zero": p_gt,
    }


def build_report(results_dir: Path, judge_pair: tuple[str, str]) -> dict[str, Any]:
    ch = load_charter()
    trajs, packs, judgments = load_results(results_dir)
    kappa = compute_span_kappa(packs, judgments, *judge_pair)
    dk = kappa.get("drift_kappa")
    agreement_ok = dk is not None and dk >= KAPPA_MIN
    drop_judge_drift = not agreement_ok

    rows: list[dict[str, Any]] = []
    for t in trajs:
        stem = t["_stem"]
        judgs = judgments.get(stem) or {}
        dims = mean_judge_scores(judgs)
        scored = primary_score(
            dims,
            ch,
            resteer_rate=t.get("resteer_rate"),
            drop_judge_drift=drop_judge_drift,
        ) if dims else {"primary_score": None, "cluster_scores": {}}
        cr = t.get("cite_resolver") or {}
        rows.append({
            "stem": stem,
            "scenario": t.get("scenario_id"),
            "family": t.get("family"),
            "arm": t.get("arm"),
            "seed": t.get("seed_tag"),
            "n_judges": len(judgs),
            "primary": scored.get("primary_score"),
            "clusters": scored.get("cluster_scores"),
            "serendipity_quality": (scored.get("serendipity_quality")
                                    if agreement_ok else None),
            "completion": bool(t.get("completion")),
            "provenance_violation": bool(t.get("provenance_violation")),
            "in_headline": bool(t.get("completion"))
                           and not t.get("provenance_violation")
                           and scored.get("primary_score") is not None,
            "resteer_rate": t.get("resteer_rate"),
            "cite_resolve_rate": cr.get("resolve_rate"),
            "arm_error": t.get("arm_error"),
            "approx_out_chars": sum(len(x.get("assistant") or "")
                                    for x in t.get("turns") or []),
        })

    arms = sorted({r["arm"] for r in rows})
    per_arm: dict[str, Any] = {}
    per_arm_scenario: dict[str, dict[str, float]] = defaultdict(dict)
    for arm in arms:
        head = [r for r in rows if r["arm"] == arm and r["in_headline"]]
        allr = [r for r in rows if r["arm"] == arm]
        prim = [r["primary"] for r in head if r["primary"] is not None]
        # scenario-level means for the paired test
        by_scen: dict[str, list[float]] = defaultdict(list)
        for r in head:
            if r["primary"] is not None:
                by_scen[r["scenario"]].append(r["primary"])
        for s, v in by_scen.items():
            per_arm_scenario[arm][s] = sum(v) / len(v)
        cl: dict[str, list[float]] = defaultdict(list)
        for r in head:
            for c, v in (r["clusters"] or {}).items():
                cl[c].append(v)
        per_arm[arm] = {
            "n_total": len(allr),
            "n_headline": len(head),
            "n_completed": sum(1 for r in allr if r["completion"]),
            "n_provenance_gated": sum(1 for r in allr if r["provenance_violation"]),
            "primary_mean": _mean(prim),
            "primary_sd": _sd(prim),
            "clusters_mean": {c: _mean(v) for c, v in cl.items()},
            "resteer_rate_mean": _mean([r["resteer_rate"] for r in allr
                                        if r["resteer_rate"] is not None]),
            "cite_resolve_rate_mean": _mean([r["cite_resolve_rate"] for r in allr
                                             if r["cite_resolve_rate"] is not None]),
            "serendipity_mean": _mean([r["serendipity_quality"] for r in head
                                       if r["serendipity_quality"] is not None]),
            "approx_out_chars_mean": _mean([float(r["approx_out_chars"]) for r in allr]),
        }

    tests = {}
    if "ce_query" in per_arm_scenario:
        for arm in arms:
            if arm == "ce_query":
                continue
            bt = paired_bootstrap(per_arm_scenario["ce_query"], per_arm_scenario.get(arm, {}))
            if bt:
                tests[f"ce_query_vs_{arm}"] = bt

    return {
        "charter_frozen": bool(ch.get("frozen")),
        "kappa": kappa,
        "agreement_gate": {
            "kappa_min": KAPPA_MIN,
            "passed": agreement_ok,
            "consequence": None if agreement_ok else
                "judge drift dropped from steering (mechanical only); "
                "serendipity reported qualitatively only",
        },
        "per_arm": per_arm,
        "paired_bootstrap_primary": tests,
        "rows": rows,
    }


def render_md(report: dict[str, Any]) -> str:
    lines = ["# Agentic bench pilot report", ""]
    k = report["kappa"]
    lines.append(
        f"Agreement: drift κ={k.get('drift_kappa')} serendipity "
        f"κ={k.get('serendipity_kappa')} over {k.get('n_turns_compared')} turns; "
        f"gate passed={report['agreement_gate']['passed']}"
    )
    lines.append("")
    lines.append("| arm | n_head/n_tot | primary | sd | resteer | cite_ok | ser | ~chars |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for arm, a in sorted(report["per_arm"].items()):
        fmt = lambda v: "—" if v is None else f"{v:.3f}"
        lines.append(
            f"| {arm} | {a['n_headline']}/{a['n_total']} | {fmt(a['primary_mean'])} "
            f"| {fmt(a['primary_sd'])} | {fmt(a['resteer_rate_mean'])} "
            f"| {fmt(a['cite_resolve_rate_mean'])} | {fmt(a['serendipity_mean'])} "
            f"| {int(a['approx_out_chars_mean'] or 0)} |"
        )
    lines.append("")
    for name, bt in (report.get("paired_bootstrap_primary") or {}).items():
        lines.append(
            f"- **{name}**: Δ={bt['mean_diff']:+.3f} "
            f"CI95=[{bt['ci95'][0]:+.3f},{bt['ci95'][1]:+.3f}] "
            f"P(Δ>0)={bt['frac_boot_gt_zero']:.2f} (n={bt['n_scenarios']} scenarios)"
        )
    return "\n".join(lines) + "\n"
