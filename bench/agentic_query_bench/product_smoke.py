"""One-repeat 12-cell product-pilot smoke (resumable).

3 primary arms × 4 scored scenarios × 1 repeat. Each cell runs a full product
trajectory, audits it deterministically (product_mechanics), and checkpoints to
its own JSON so a Claude session-limit mid-run loses nothing — re-invoke to
resume at the first missing cell. Arms are interleaved within each scenario so a
served-model drift spreads across arms rather than corrupting one arm's block.

This is the LAST step before the mandated STOP for user approval; it does NOT
run the remaining two repeats, the judges, or any deck update.
"""

from __future__ import annotations

import argparse
import json
import signal
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class _CellTimeout(Exception):
    pass


def _timed_out_traj(scenario_id: str, arm: str, rep: str, model: str) -> dict[str, Any]:
    return {
        "scenario_id": scenario_id, "arm": arm, "repeat": rep, "model": model,
        "completed": False, "hard_error": True, "error": "cell timeout",
        "turns": [], "mutation_verdicts": [], "denied_tools": [],
        "skill_inventory": {}, "cite_resolver": {},
    }

from bench.agentic_query_bench import product_arms as PA
from bench.agentic_query_bench import product_mechanics
from bench.agentic_query_bench.product_run import run_product_trajectory

ROOT = Path(__file__).resolve().parent
SCORED_SCENARIOS = [
    "nc-absent-theme-quantum-01",
    "mp-poisoned-analysis-privacy-01",
    "ap-comp599-tech-debt-article-01",
    "rp-comp599-fairness-research-01",
]
PRIMARY_ARMS = ["ce_product_e2e_v1", "tool_matched_no_skill_v1", "rag_modern_agentic_v1"]


def _load(name: str, sub: str) -> dict[str, Any] | None:
    p = ROOT / sub / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def _cell_path(out_dir: Path, scenario: str, arm: str, rep: str) -> Path:
    return out_dir / f"cell-{scenario}-{arm}-r{rep}.json"


def run_smoke(
    frozen_ws: Path,
    *,
    model: str,
    out_dir: Path,
    calibration_path: Path,
    frozen_index_dir: Path,
    skill_dir: Path | None = None,
    repeats: int = 1,
    max_agent_turns: int = 12,
    cell_timeout: int = 900,
    log=print,
) -> dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    calibration = json.loads(Path(calibration_path).read_text(encoding="utf-8"))
    corpus = product_mechanics.corpus_inventory(frozen_ws)
    work_dir = out_dir / "work"
    work_dir.mkdir(exist_ok=True)
    signal.signal(signal.SIGALRM, lambda *a: (_ for _ in ()).throw(_CellTimeout()))

    ran, skipped, drifted = 0, 0, 0
    for rep in range(repeats):
        for scenario_id in SCORED_SCENARIOS:
            scenario = _load(scenario_id, "scenarios")
            dossier = _load(scenario_id, "evidence_dossiers")
            for arm in PRIMARY_ARMS:
                cp = _cell_path(out_dir, scenario_id, arm, str(rep))
                if cp.is_file():
                    try:
                        data = json.loads(cp.read_text(encoding="utf-8"))
                        # Re-run hard-errored cells (transient limit / broken pipe /
                        # timeout); keep completed or soft-failed ones.
                        if not (data.get("trajectory") or {}).get("hard_error"):
                            skipped += 1
                            continue
                        log(f"[retry] {scenario_id} × {arm} r{rep} (prior hard_error)")
                    except json.JSONDecodeError:
                        pass  # corrupt → rerun
                log(f"[cell] {scenario_id} × {arm} r{rep} …")
                signal.alarm(cell_timeout)
                try:
                    traj = run_product_trajectory(
                        scenario, arm, frozen_ws=Path(frozen_ws), model=model,
                        work_dir=work_dir, repeat=str(rep), calibration=calibration,
                        frozen_index_dir=Path(frozen_index_dir), skill_dir=skill_dir,
                        max_agent_turns=max_agent_turns,
                    )
                except _CellTimeout:
                    log(f"  !! CELL TIMEOUT ({cell_timeout}s) — recorded as hard error")
                    traj = _timed_out_traj(scenario_id, arm, str(rep), model)
                finally:
                    signal.alarm(0)
                mech = product_mechanics.audit(traj, scenario, dossier=dossier, corpus=corpus)
                cp.write_text(json.dumps({"trajectory": traj, "mechanics": mech}, indent=2),
                              encoding="utf-8")
                ran += 1
                if traj.get("model_drift"):
                    drifted += 1
                    log(f"  !! MODEL DRIFT on {scenario_id} × {arm} — served != {model}")
                log(f"  done: completed={mech['completed']} fab_prov={mech['fabricated_provenance']} "
                    f"forbid_mut={mech['forbidden_mutation']} perm_viol={mech['permission_violation']} "
                    f"skill_invoked={mech['skill_invoked']} tools={mech['total_tool_calls']} "
                    f"wall={mech['wall_seconds']}s")
    summary = summarize(out_dir, repeats)
    summary.update({"ran": ran, "skipped": skipped, "drifted": drifted,
                    "timestamp_utc": datetime.now(timezone.utc).isoformat()})
    (out_dir / "smoke-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


DEFAULT_FROZEN_WS = Path("~/.cache/sy-phase2-bench/ws").expanduser()


def reaudit(out_dir: Path, frozen_ws: Path | None = None) -> int:
    """Recompute denial severity + permission_violation + mechanics on existing
    checkpoints (the trajectory data is valid; only the classification/audit
    logic changed). Deterministic, no model calls. The frozen-corpus inventory
    drives near-miss vs invented classification of fabricated cites."""
    from bench.agentic_query_bench import product_mechanics
    from bench.agentic_query_bench.product_run import _denial_severity

    corpus = product_mechanics.corpus_inventory(frozen_ws or DEFAULT_FROZEN_WS)
    n = 0
    for cp in sorted(Path(out_dir).glob("cell-*.json")):
        data = json.loads(cp.read_text(encoding="utf-8"))
        traj = data.get("trajectory") or {}
        # A synthetic-served "drift" is really a subscription-limit hit (retriable).
        if "synthetic" in str(traj.get("error", "")).casefold():
            traj["limit_hit"] = True
            traj["model_drift"] = False
        gate = False
        for d in traj.get("denied_tools", []) or []:
            d["severity"] = _denial_severity(d.get("name"), d.get("input"))
            gate = gate or d["severity"] == "gate"
        traj["permission_violation"] = gate
        scen = _load(traj.get("scenario_id", ""), "scenarios") or {"id": traj.get("scenario_id")}
        doss = _load(traj.get("scenario_id", ""), "evidence_dossiers")
        data["mechanics"] = product_mechanics.audit(traj, scen, dossier=doss, corpus=corpus)
        cp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        n += 1
    return n


def summarize(out_dir: Path, repeats: int = 1) -> dict[str, Any]:
    out_dir = Path(out_dir)
    cells: list[dict[str, Any]] = []
    for rep in range(repeats):
        for scenario_id in SCORED_SCENARIOS:
            for arm in PRIMARY_ARMS:
                cp = _cell_path(out_dir, scenario_id, arm, str(rep))
                if cp.is_file():
                    try:
                        cells.append(json.loads(cp.read_text(encoding="utf-8"))["mechanics"])
                    except (json.JSONDecodeError, KeyError):
                        pass
    n = len(cells)
    # limit-pending cells (synthetic-served) are retriable, not real failures
    pending = 0
    for rep in range(repeats):
        for scenario_id in SCORED_SCENARIOS:
            for arm in PRIMARY_ARMS:
                cp = _cell_path(out_dir, scenario_id, arm, str(rep))
                if cp.is_file():
                    try:
                        tj = json.loads(cp.read_text(encoding="utf-8")).get("trajectory", {})
                        if tj.get("limit_hit") or "synthetic" in str(tj.get("error", "")).casefold():
                            pending += 1
                    except (json.JSONDecodeError, KeyError):
                        pass
    return {
        "n_cells_present": n,
        "n_cells_expected": repeats * len(SCORED_SCENARIOS) * len(PRIMARY_ARMS),
        "n_pending_limit": pending,
        "completed": sum(1 for c in cells if c["completed"]),
        "fabricated_provenance": sum(1 for c in cells if c["fabricated_provenance"]),
        "forbidden_mutation": sum(1 for c in cells if c["forbidden_mutation"]),
        "permission_violation_gate": sum(1 for c in cells if c["permission_violation"]),
        "tool_matched_skill_leak": sum(
            1 for c in cells if c["arm"] == "tool_matched_no_skill_v1" and c["skill_invoked"]
        ),
        "rag_skill_leak": sum(
            1 for c in cells if c["arm"] == "rag_modern_agentic_v1" and c["skill_invoked"]
        ),
        # CE QUERY use vs CE STRUCTURE-only grounding, per arm. For the product
        # arm this reveals how often it actually invoked CE query vs grep'd the
        # wiki (structure benefit) — the two must not be conflated.
        "ce_query_invoked_by_arm": {
            arm: sum(1 for c in cells if c["arm"] == arm and c.get("ce_query_invoked"))
            for arm in PRIMARY_ARMS
        },
        "structure_only_by_arm": {
            arm: sum(1 for c in cells if c["arm"] == arm and c.get("structure_benefit_without_ce_query"))
            for arm in PRIMARY_ARMS
        },
        # The prereg product verdict gates on the PRODUCT arm; comparator-arm
        # hits are diagnostics, not product gates.
        "product_gates": {
            g: sum(1 for c in cells if c["arm"] == "ce_product_e2e_v1" and c.get(g))
            for g in ("fabricated_provenance", "forbidden_mutation", "permission_violation")
        },
        "comparator_diagnostics": {
            g: sum(1 for c in cells if c["arm"] != "ce_product_e2e_v1" and c.get(g))
            for g in ("fabricated_provenance", "forbidden_mutation", "permission_violation")
        },
        # Near-miss citations (real source, mistyped path) — reported separately
        # from invented sources per the 2026-07-29 intent-matching amendment. A
        # transcription-faithfulness signal for the judges, NOT a provenance gate.
        "near_miss_citations": {
            "product": sum(len(c.get("near_miss_citations") or [])
                           for c in cells if c["arm"] == "ce_product_e2e_v1"),
            "comparators": sum(len(c.get("near_miss_citations") or [])
                               for c in cells if c["arm"] != "ce_product_e2e_v1"),
            "cells": [
                {"scenario_id": c["scenario_id"], "arm": c["arm"],
                 "paths": c.get("near_miss_citations")}
                for c in cells if c.get("near_miss_citations")
            ],
        },
        "per_cell": [
            {k: c[k] for k in ("scenario_id", "arm", "completed", "hard_error",
                               "fabricated_provenance", "forbidden_mutation",
                               "permission_violation", "skill_invoked", "asserts_absence",
                               "total_tool_calls", "wall_seconds", "output_tokens")}
            for c in cells
        ],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", type=Path, required=True)
    ap.add_argument("--model", default="claude-opus-4-8")
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--calibration", type=Path,
                    default=ROOT.parents[1] / "bench/results/rag-modern-calibration/calibration.json")
    ap.add_argument("--index-dir", type=Path,
                    default=ROOT.parents[1] / "bench/results/rag-modern-index")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--max-agent-turns", type=int, default=12)
    args = ap.parse_args(argv)
    summary = run_smoke(
        args.workspace.expanduser().resolve(), model=args.model, out_dir=args.out_dir,
        calibration_path=args.calibration, frozen_index_dir=args.index_dir,
        skill_dir=PA.product_skill_dir(), repeats=args.repeats,
        max_agent_turns=args.max_agent_turns,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
