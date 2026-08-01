"""Blind task-judge panel for the CE QUERY product-verdict pilot.

Turns the completed product matrix cells (both host models) into arm-blind judge
packs, runs the two-judge panel (xai/grok-4.5 + openai-codex/gpt-5.5) over them,
and aggregates into the preregistered product verdict — as TWO paired contrasts,
one per host model (opus-4-8, opus-5), never pooled.

Blinding: packs contain only the normalized transcript + frozen evidence dossier
+ mechanical reports; system self-identifiers (CE / curiosity-engine / rag_search
/ script names / arm ids) are scrubbed to neutral phrases, tool_uses are dropped,
and each cell is keyed by a hash blind_code. The blind_code→(model,arm,repeat)
map is sealed in a separate file the judges never see.

Resumable + limit-robust (one JSON per pack×judge). No numpy dependency.

  PYTHONPATH=. python -m bench.agentic_query_bench.product_judge build --out-dir bench/results/product-judge-v1
  PYTHONPATH=. python -m bench.agentic_query_bench.product_judge run   --out-dir bench/results/product-judge-v1
  PYTHONPATH=. python -m bench.agentic_query_bench.product_judge agg   --out-dir bench/results/product-judge-v1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bench.agentic_query_bench.judges import (
    DEFAULT_JUDGES,
    compute_span_kappa,
    judge_pack_file,
)
from bench.agentic_query_bench.scoring import load_charter

ROOT = Path(__file__).resolve().parent

# host model → completed 36-cell matrix dir
MATRIX_DIRS = {
    "claude-opus-4-8": ROOT.parents[1] / "bench/results/product-smoke-v1",
    "claude-opus-5": ROOT.parents[1] / "bench/results/product-matrix-opus5",
}
PRODUCT_ARM = "ce_product_e2e_v1"
COMPARATORS = ["tool_matched_no_skill_v1", "rag_modern_agentic_v1"]

# Preregistered 3-cluster primary (real_pilot_preregistration.frozen.json).
CLUSTERS = {
    "task_fulfilment": ["theme_recall", "theme_precision", "multi_hop_coverage",
                        "comprehensiveness", "spine_fidelity"],
    "evidence_fidelity": ["citation_support", "accuracy"],
    "calibration": ["calibration"],
}
DISAGREEMENT_THRESHOLD = 0.25  # > this on a dimension → frozen third (human) adjudicator
CELL_TIE = 0.01                # |paired delta| below this = CE non-win
BLIND_SALT = "ce-product-verdict-2026-07-29"  # fixed; deterministic blinding

# Extra product-arm de-blinding scrub (assistant prose only). build_judge_pack's
# normalizer misses the product vocabulary, so add it here. All arms pass through
# the SAME scrub so it cannot itself leak treatment.
_SCRUB = [
    (re.compile(r"(?i)\bcuriosity[\s_-]*engine\b"), "the system"),
    (re.compile(r"(?i)/curiosity-engine\b"), "the system"),
    (re.compile(r"(?i)\bCE[\s_-]*(query|structure|skill|action)\b"), "the system"),
    # distinctive CE script names — scrub bare (no .py needed); keep generic
    # "graph" suffix-gated so the ordinary word "graph" survives.
    (re.compile(r"(?i)\b(query_router|vault_search|entity_gate)\b(\.py)?"), "a retrieval script"),
    (re.compile(r"(?i)\bgraph\.py\b"), "a retrieval script"),
    (re.compile(r"(?i)\bentity[\s_-]gate\b"), "the retrieval filter"),
    (re.compile(r"(?i)\bmcp__rag__rag_search\b|\brag_search\b"), "the retrieval tool"),
    (re.compile(r"(?i)\b(ce_product_e2e_v1|tool_matched_no_skill_v1|rag_modern_agentic_v1)\b"), "the system"),
    (re.compile(r"(?i)\.curator/"), "the index/"),
]


def _scrub(text: str) -> str:
    value = text or ""
    for pat, repl in _SCRUB:
        value = pat.sub(repl, value)
    return value


def _load_json(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _blind_code(model: str, scenario: str, arm: str, repeat: str) -> str:
    h = hashlib.sha1(f"{model}|{scenario}|{arm}|{repeat}|{BLIND_SALT}".encode()).hexdigest()
    return "t" + h[:11]


def _applicable_dimensions(scenario: dict[str, Any], traj: dict[str, Any],
                           dossier: dict[str, Any] | None) -> dict[str, bool]:
    themes = scenario.get("gold_themes") or []
    applicable = {
        "theme_recall": any(not t.get("absent_from_corpus") for t in themes),
        "multi_hop_coverage": any(t.get("multi_hop") and not t.get("absent_from_corpus") for t in themes),
        "citation_support": bool(((traj.get("cite_resolver") or {}).get("n_presented") or 0)),
    }
    if dossier:
        applicable.update(dossier.get("applicable_dimensions") or {})
    return applicable


def _dossier_diagnostics(traj: dict[str, Any], dossier: dict[str, Any] | None) -> dict[str, Any]:
    canonical = set((dossier or {}).get("canonical_sources") or [])
    cited: list[str] = []
    covered: list[str] = []
    for turn in ((traj.get("cite_resolver") or {}).get("per_turn") or []):
        for cite in ((turn.get("report") or {}).get("cites") or []):
            resolved = cite.get("resolved_path")
            if not resolved or not cite.get("presented_as_citation"):
                continue
            cited.append(str(resolved))
            if resolved in canonical:
                covered.append(str(resolved))
    uc, uv = list(dict.fromkeys(cited)), list(dict.fromkeys(covered))
    return {"cited_sources": uc, "covered_sources": uv,
            "citation_coverage_rate": (len(uv) / len(uc) if uc else 1.0),
            "minimum_required_for_matrix": 0.9}


def build_product_pack(scenario: dict[str, Any], traj: dict[str, Any],
                       dossier: dict[str, Any] | None, blind_code: str) -> dict[str, Any]:
    """Arm-blind judge pack: normalized transcript + frozen gold only."""
    applicable = _applicable_dimensions(scenario, traj, dossier)
    return {
        "scenario": {
            "id": scenario.get("id"), "family": scenario.get("family"),
            "task_intent": scenario.get("task_intent"),
            "spine_must_hold": scenario.get("spine_must_hold"),
            "gold_themes": scenario.get("gold_themes"),
            "gold_anti_themes": scenario.get("gold_anti_themes"),
            "serendipity": scenario.get("serendipity"),
            "final_artifact": scenario.get("final_artifact"),
            "negative_control": scenario.get("negative_control"),
            "poisoned_analysis": scenario.get("poisoned_analysis"),
            "applicable_dimensions": applicable,
        },
        "evidence_dossier": dossier,
        "evidence_dossier_diagnostics": _dossier_diagnostics(traj, dossier),
        "trajectory": {
            "blind_code": blind_code,
            "turns": [
                {"id": t.get("turn_id") or t.get("id"),
                 "user": _scrub(str(t.get("user") or "")),
                 "assistant": _scrub(str(t.get("assistant") or ""))}
                for t in traj.get("turns") or []
            ],
            "resteer_rate": traj.get("resteer_rate"),
            "cite_resolver": traj.get("cite_resolver"),
            "provenance_violation": bool((traj.get("cite_resolver") or {}).get("provenance_violation")),
            "completion": bool(traj.get("completed")),
        },
        "instructions": (
            "Score using judgment-charter.json. citation_support must use "
            "cite_resolver plus the frozen evidence dossier. Omit every dimension "
            "marked false in applicable_dimensions. serendipity_quality is "
            "card-anchored and outside the primary composite."
        ),
    }


def _cell_valid(traj: dict[str, Any]) -> bool:
    return bool(traj.get("completed")) and not traj.get("hard_error") \
        and not traj.get("limit_hit") and not traj.get("model_drift")


def build_packs(out_dir: Path, log=print) -> dict[str, Any]:
    """Build blind packs for every valid cell across both models. Writes packs/ +
    a SEALED blind-map. Idempotent."""
    out_dir = Path(out_dir)
    packs_dir = out_dir / "packs"
    packs_dir.mkdir(parents=True, exist_ok=True)
    sealed: dict[str, dict[str, Any]] = {}
    n_valid = n_invalid = 0
    invalid: list[dict[str, Any]] = []
    for model, mdir in MATRIX_DIRS.items():
        for cp in sorted(Path(mdir).glob("cell-*.json")):
            cell = _load_json(cp) or {}
            traj = cell.get("trajectory") or {}
            sid, arm, rep = traj.get("scenario_id"), traj.get("arm"), str(traj.get("repeat"))
            code = _blind_code(model, sid, arm, rep)
            sealed[code] = {"model": model, "scenario_id": sid, "arm": arm,
                            "repeat": rep, "valid": _cell_valid(traj),
                            "source_cell": str(cp.relative_to(ROOT.parents[1]))}
            if not _cell_valid(traj):
                n_invalid += 1
                invalid.append({"blind_code": code, "model": model, "scenario_id": sid, "arm": arm})
                continue
            scenario = _load_json(ROOT / "scenarios" / f"{sid}.json") or {"id": sid}
            dossier = _load_json(ROOT / "evidence_dossiers" / f"{sid}.json")
            pack = build_product_pack(scenario, traj, dossier, code)
            (packs_dir / f"{code}.json").write_text(json.dumps(pack, indent=1, ensure_ascii=False),
                                                    encoding="utf-8")
            n_valid += 1
    (out_dir / "sealed_blindmap.json").write_text(json.dumps(sealed, indent=1), encoding="utf-8")
    summary = {"n_packs": n_valid, "n_invalid_cells": n_invalid, "invalid": invalid,
               "models": list(MATRIX_DIRS), "salt": BLIND_SALT}
    (out_dir / "packs-summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    log(f"[build] {n_valid} blind packs, {n_invalid} invalid cells → {packs_dir}")
    return summary


# A single judge CLI call can HANG with no timeout (observed: the grok CLI stuck
# >2h inside one stream). So each call runs in its own subprocess/process-group
# and is killed as a GROUP on timeout — which also kills the spawned CLI. The
# outer loop makes several passes so timed-out/failed calls get retried.
CALL_TIMEOUT_S = 600  # generous: a valid grok call can take ~7min when degraded
MAX_PASSES = 4
MAX_WORKERS = 4       # independent CLI subprocesses; overlaps slow calls


def _missing(out_dir: Path, judges: list[str]) -> list[tuple[Path, str]]:
    jdir = out_dir / "judgments"
    miss = []
    for pack in sorted((out_dir / "packs").glob("*.json")):
        for judge in judges:
            if not (jdir / f"{pack.stem}.{judge}.json").is_file():
                miss.append((pack, judge))
    return miss


def _one_call(pack_path: Path, judge: str, out_dir: Path,
              limit_sleep_s: int, limit_patience_h: float) -> None:
    """Judge exactly one pack with one judge (subprocess entrypoint)."""
    judge_pack_file(Path(pack_path), judge, Path(out_dir) / "judgments",
                    limit_sleep_s=limit_sleep_s, limit_patience_h=limit_patience_h)


def _spawn_one(pack: Path, judge: str, out_dir: Path, env: dict, log) -> bool:
    """Run one (pack, judge) call in an isolated process group; kill the GROUP
    (and its CLI subprocess) on timeout. Returns True if the judgment landed."""
    import os
    import signal
    import subprocess
    import sys

    cmd = [sys.executable, "-m", "bench.agentic_query_bench.product_judge", "_one",
           "--pack", str(pack), "--judge", judge, "--out-dir", str(out_dir),
           "--limit-sleep-s", "120", "--limit-patience-h", "0.08"]
    p = subprocess.Popen(cmd, env=env, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        p.wait(timeout=CALL_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass
        p.wait()
        log(f"[run] TIMEOUT {pack.stem} × {judge} — killed group after {CALL_TIMEOUT_S}s")
    return (out_dir / "judgments" / f"{pack.stem}.{judge}.json").is_file()


def run_judges(out_dir: Path, judges: list[str] | None = None,
               limit_sleep_s: int = 1800, limit_patience_h: float = 8.0,
               max_workers: int = MAX_WORKERS, log=print) -> dict[str, Any]:
    """Judge every pack with every judge; resumable, hang-proof, concurrent.

    Each (pack, judge) call is an isolated subprocess in its own session, killed
    at the process-group level on timeout (taking the CLI with it) and retried on
    a later pass. A small worker pool overlaps slow calls (grok can take ~7min
    when degraded), so one slow provider no longer starves the other."""
    import os
    from concurrent.futures import ThreadPoolExecutor, as_completed

    out_dir = Path(out_dir)
    judges = judges or list(DEFAULT_JUDGES)
    (out_dir / "judgments").mkdir(parents=True, exist_ok=True)
    n_expected = len(list((out_dir / "packs").glob("*.json"))) * len(judges)
    env = {**os.environ, "PYTHONPATH": f"src:{os.environ.get('PYTHONPATH', '')}".rstrip(":")}

    for pass_i in range(1, MAX_PASSES + 1):
        miss = _missing(out_dir, judges)
        if not miss:
            break
        log(f"[run] pass {pass_i}/{MAX_PASSES}: {len(miss)} of {n_expected} calls "
            f"remaining ({max_workers} workers)", flush=True)
        progressed = False
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = {ex.submit(_spawn_one, pack, judge, out_dir, env, log): (pack, judge)
                    for pack, judge in miss}
            for fut in as_completed(futs):
                if fut.result():
                    progressed = True
        if not progressed:
            log(f"[run] pass {pass_i}: no progress, stopping", flush=True)
            break

    remaining = _missing(out_dir, judges)
    done = n_expected - len(remaining)
    log(f"[run] judgments {done}/{n_expected} done; {len(remaining)} missing", flush=True)
    return {"n_expected": n_expected, "n_done": done, "n_missing": len(remaining),
            "missing": [f"{p.stem}.{j}" for p, j in remaining], "judges": judges}


def resume_missing_via(out_dir: Path, judge_label: str = "openai-codex",
                       provider: str = "openai", model: str = "gpt-5.5",
                       max_workers: int = 4, log=print) -> dict[str, Any]:
    """Fill missing <judge_label> judgments by serving the SAME pinned model over
    a DIFFERENT transport (codex CLI capped → OpenAI HTTP API). Writes into the
    same judge slot so the panel is unchanged except for transport, which is
    recorded in `served_via` on each filled judgment and disclosed in the report."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from bench.agentic_query_bench.judges import build_judge_prompt, parse_judgment
    from bench.agentic_query_bench.llm_util import robust_llm_call

    out_dir = Path(out_dir)
    jdir = out_dir / "judgments"
    jdir.mkdir(parents=True, exist_ok=True)
    missing = [p for p in sorted((out_dir / "packs").glob("*.json"))
               if not (jdir / f"{p.stem}.{judge_label}.json").is_file()]
    log(f"[resume] {len(missing)} {judge_label} judgments to fill via {provider}/{model}")

    def _fill(pack_path: Path) -> bool:
        pack = json.loads(pack_path.read_text(encoding="utf-8"))
        prompt = build_judge_prompt(pack)
        applicable = (pack.get("scenario") or {}).get("applicable_dimensions") or {}
        for _ in range(2):
            try:
                text = robust_llm_call(provider, prompt, model=model, max_tokens=3000,
                                       limit_sleep_s=300, limit_patience_h=1.0, log=log)
            except Exception as e:  # noqa: BLE001
                log(f"[resume] {pack_path.stem} error: {str(e)[:160]}")
                return False
            parsed = parse_judgment(text, applicable_dimensions=applicable)
            if parsed:
                parsed["judge"] = judge_label
                parsed["pack"] = pack_path.name
                parsed["served_via"] = {"provider": provider, "model": model,
                    "note": "pinned gpt-5.5 served over OpenAI HTTP API (codex CLI "
                            "usage-capped 2026-07-30); transport change, same model"}
                parsed["cite_resolver_version"] = (
                    ((pack.get("trajectory") or {}).get("cite_resolver") or {}).get("resolver_version"))
                (jdir / f"{pack_path.stem}.{judge_label}.json").write_text(
                    json.dumps(parsed, indent=1), encoding="utf-8")
                return True
            prompt += "\n\nREMINDER: reply with STRICT JSON only."
        return False

    filled = 0
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for fut in as_completed({ex.submit(_fill, p): p for p in missing}):
            if fut.result():
                filled += 1
    log(f"[resume] filled {filled}/{len(missing)}")
    return {"requested": len(missing), "filled": filled, "provider": provider, "model": model}


# --------------------------- aggregation ---------------------------------- #

def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _cluster_scores(dim_means: dict[str, float]) -> dict[str, float]:
    out = {}
    for cname, dims in CLUSTERS.items():
        vals = [dim_means[d] for d in dims if d in dim_means]
        if vals:
            out[cname] = sum(vals) / len(vals)
    return out


def _trajectory_score(clusters: dict[str, float]) -> float | None:
    # equal mean of applicable clusters; calibration + >=1 other required
    if "calibration" not in clusters or len(clusters) < 2:
        return None
    return sum(clusters.values()) / len(clusters)


def aggregate(out_dir: Path, log=print,
              dim_overrides: dict[tuple[str, str], float] | None = None,
              out_name: str = "judge-aggregate.json") -> dict[str, Any]:
    """Fuse judgments → per-cell/arm/paired verdict. `dim_overrides` maps
    (blind_code, dimension) → a resolved value (e.g. median-of-three after human
    adjudication) that replaces the 2-judge mean for that cell/dimension."""
    out_dir = Path(out_dir)
    overrides = dim_overrides or {}
    sealed = _load_json(out_dir / "sealed_blindmap.json") or {}
    charter = load_charter()
    valid_dims = set((charter.get("dimensions") or {}).keys())
    jdir = out_dir / "judgments"

    # blind_code -> judge -> judgment
    judgments: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for jf in jdir.glob("*.json"):
        # filename: <blind_code>.<judge>.json  (judge may contain no dots)
        stem = jf.name[:-5]
        code, _, judge = stem.partition(".")
        judgments[code][judge] = _load_json(jf) or {}

    packs = {p.stem: _load_json(p) for p in (out_dir / "packs").glob("*.json")}

    # per cell: fuse the two judges → dim_means + disputes; then cluster + traj score
    cells: dict[str, dict[str, Any]] = {}
    disputed_total = 0
    for code, js in judgments.items():
        if len(js) < 2:
            continue
        names = sorted(js)
        dim_means: dict[str, float] = {}
        disputes: list[str] = []
        all_dims = set()
        for jn in names:
            all_dims |= set((js[jn].get("scores") or {}).keys())
        for d in all_dims & valid_dims:
            vals = [js[jn]["scores"][d] for jn in names if d in (js[jn].get("scores") or {})]
            if not vals:
                continue
            if (code, d) in overrides:
                dim_means[d] = overrides[(code, d)]  # human-resolved (median-of-three)
            else:
                dim_means[d] = sum(vals) / len(vals)
            if len(vals) == 2 and abs(vals[0] - vals[1]) > DISAGREEMENT_THRESHOLD:
                disputes.append(d)
        disputed_total += len(disputes)
        clusters = _cluster_scores(dim_means)
        cells[code] = {
            **sealed.get(code, {}),
            "dim_means": dim_means, "clusters": clusters,
            "trajectory_score": _trajectory_score(clusters),
            "disputed_dimensions": disputes,
            "evidence_fidelity": clusters.get("evidence_fidelity"),
        }

    # group by (model, arm) and (model, scenario, repeat)
    by_arm: dict[tuple[str, str], list[float]] = defaultdict(list)
    ef_by_arm: dict[tuple[str, str], list[float]] = defaultdict(list)
    traj_by_key: dict[tuple[str, str, str, str], float | None] = {}
    for code, c in cells.items():
        if not c.get("valid"):
            continue
        m, arm, sid, rep = c.get("model"), c.get("arm"), c.get("scenario_id"), c.get("repeat")
        ts = c.get("trajectory_score")
        traj_by_key[(m, arm, sid, rep)] = ts
        if ts is not None:
            by_arm[(m, arm)].append(ts)
        if c.get("evidence_fidelity") is not None:
            ef_by_arm[(m, arm)].append(c["evidence_fidelity"])

    arm_scores = {f"{m}|{arm}": _mean(v) for (m, arm), v in by_arm.items()}

    # paired contrasts per model: CE vs each comparator
    scenarios = sorted({c["scenario_id"] for c in cells.values() if c.get("scenario_id")})
    contrasts: dict[str, Any] = {}
    for model in MATRIX_DIRS:
        contrasts[model] = {}
        ce_arm_score = _mean(by_arm.get((model, PRODUCT_ARM), []))
        for comp in COMPARATORS:
            wins = losses = ties_or_invalid = 0
            scen_wins = 0
            for sid in scenarios:
                s_ce, s_cp = [], []
                for rep in ("0", "1", "2"):
                    ce = traj_by_key.get((model, PRODUCT_ARM, sid, rep))
                    cp = traj_by_key.get((model, comp, sid, rep))
                    if ce is None or cp is None:
                        ties_or_invalid += 1  # invalid cell = CE non-win
                        if ce is not None:
                            s_ce.append(ce)
                        if cp is not None:
                            s_cp.append(cp)
                        continue
                    s_ce.append(ce); s_cp.append(cp)
                    if ce - cp >= CELL_TIE:
                        wins += 1
                    elif cp - ce >= CELL_TIE:
                        losses += 1
                    else:
                        ties_or_invalid += 1
                m_ce, m_cp = _mean(s_ce), _mean(s_cp)
                if m_ce is not None and m_cp is not None and m_ce - m_cp >= CELL_TIE:
                    scen_wins += 1
            comp_arm_score = _mean(by_arm.get((model, comp), []))
            delta = (ce_arm_score - comp_arm_score) if (ce_arm_score is not None and comp_arm_score is not None) else None
            entry = {
                "ce_arm_score": ce_arm_score, "comparator_arm_score": comp_arm_score,
                "primary_delta": delta, "paired_wins": wins, "paired_losses": losses,
                "paired_ties_or_invalid": ties_or_invalid, "paired_denominator": 12,
                "scenario_mean_wins": scen_wins, "scenario_denominator": len(scenarios),
                "meets_delta_0.05": (delta is not None and delta >= 0.05),
                "meets_paired_8of12": wins >= 8,
                "meets_scenario_3of4": scen_wins >= 3,
            }
            if comp == "rag_modern_agentic_v1":
                ce_ef = _mean(ef_by_arm.get((model, PRODUCT_ARM), []))
                rag_ef = _mean(ef_by_arm.get((model, comp), []))
                deficit = (rag_ef - ce_ef) if (ce_ef is not None and rag_ef is not None) else None
                entry["evidence_fidelity_ce"] = ce_ef
                entry["evidence_fidelity_rag"] = rag_ef
                entry["grounding_deficit_vs_rag"] = deficit
                entry["meets_grounding_<=0.02"] = (deficit is not None and deficit <= 0.02)
            contrasts[model][comp] = entry

    # agreement gate (span kappa) across the two judges, pooled over packs
    kappa = None
    if len(DEFAULT_JUDGES) == 2:
        pk = {code: p for code, p in packs.items() if p}
        jm = {code: js for code, js in judgments.items()}
        kappa = compute_span_kappa(pk, jm, DEFAULT_JUDGES[0], DEFAULT_JUDGES[1])

    n_expected = len(packs) * len(DEFAULT_JUDGES)
    n_have = sum(len(js) for js in judgments.values())
    # transport disclosure: judgments served via an alternate transport (same model)
    alt_transport = []
    for jf in jdir.glob("*.json"):
        j = _load_json(jf) or {}
        if j.get("served_via"):
            alt_transport.append({"file": jf.name, **j["served_via"]})
    report = {
        "generated_utc": None,  # stamped by caller (no Date.now in-script)
        "judges": list(DEFAULT_JUDGES),
        "judgments_present": n_have, "judgments_expected": n_expected,
        "n_cells_scored": len(cells), "disputed_dimension_instances": disputed_total,
        "disagreement_threshold": DISAGREEMENT_THRESHOLD,
        "span_kappa": kappa, "min_span_kappa": 0.5,
        "transport_disclosure": {
            "n_alt_transport": len(alt_transport),
            "detail": ("openai-codex CLI hit its usage cap at 55/72; the remaining "
                       "gpt-5.5 judgments were served over the OpenAI HTTP API "
                       "(same pinned model, different transport/billing)."),
            "judgments": alt_transport,
        } if alt_transport else None,
        "arm_scores": arm_scores,
        "paired_contrasts": contrasts,
        "note": ("Automated 2-judge pass. Dimensions with >0.25 disagreement are "
                 "flagged for the frozen third (human) adjudicator; human contrasts "
                 "+ deck remain gated. Product gate inputs (acceptance, mutations, "
                 "fabrication, poison, abstention) come from the deterministic "
                 "mechanics, not the judges."),
    }
    (out_dir / out_name).write_text(json.dumps(report, indent=1), encoding="utf-8")
    log(f"[agg] {n_have}/{n_expected} judgments, {len(cells)} cells, kappa={kappa}")
    return report


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2.0


def apply_human_adjudication(out_dir: Path, human_scores: dict[str, dict[str, float]],
                             log=print) -> dict[str, Any]:
    """Resolve disputed dimensions with the human third adjudicator: for each
    (blind_code, dimension) the human scored, final = median(judge_a, judge_b,
    human). Re-aggregates with those overrides → judge-aggregate-final.json, and
    reports how each disputed dimension resolved + any verdict deltas."""
    out_dir = Path(out_dir)
    jdir = out_dir / "judgments"
    judgments: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for jf in jdir.glob("*.json"):
        code, _, judge = jf.name[:-5].partition(".")
        judgments[code][judge] = _load_json(jf) or {}

    overrides: dict[tuple[str, str], float] = {}
    resolved: list[dict[str, Any]] = []
    for code, dims in (human_scores or {}).items():
        js = judgments.get(code, {})
        for dim, h in dims.items():
            jvals = [js[n]["scores"][dim] for n in sorted(js) if dim in (js[n].get("scores") or {})]
            if len(jvals) < 2:
                log(f"[adj] skip {code}/{dim}: <2 judge scores")
                continue
            med = _median(jvals + [float(h)])
            overrides[(code, dim)] = med
            resolved.append({"blind_code": code, "dimension": dim, "judge_scores": jvals,
                             "human": float(h), "median_of_three": med,
                             "prev_2judge_mean": sum(jvals) / len(jvals)})
    before = _load_json(out_dir / "judge-aggregate.json") or {}
    after = aggregate(out_dir, log=log, dim_overrides=overrides, out_name="judge-aggregate-final.json")
    summary = {"n_resolved": len(resolved), "resolved": resolved,
               "arm_scores_before": before.get("arm_scores"),
               "arm_scores_after": after.get("arm_scores"),
               "paired_before": before.get("paired_contrasts"),
               "paired_after": after.get("paired_contrasts")}
    (out_dir / "adjudication-result.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    log(f"[adj] resolved {len(resolved)} disputed dims → judge-aggregate-final.json")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "run", "agg", "all", "_one"])
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--judges", default=",".join(DEFAULT_JUDGES))
    ap.add_argument("--limit-sleep-s", type=int, default=1800)
    ap.add_argument("--limit-patience-h", type=float, default=8.0)
    ap.add_argument("--pack", type=Path)  # _one only
    ap.add_argument("--judge", type=str)  # _one only
    args = ap.parse_args(argv)
    judges = [j for j in args.judges.split(",") if j]
    if args.cmd == "_one":
        _one_call(args.pack, args.judge, args.out_dir, args.limit_sleep_s, args.limit_patience_h)
        return 0
    if args.cmd in ("build", "all"):
        build_packs(args.out_dir)
    if args.cmd in ("run", "all"):
        run_judges(args.out_dir, judges, args.limit_sleep_s, args.limit_patience_h)
    if args.cmd in ("agg", "all"):
        rep = aggregate(args.out_dir)
        rep["generated_utc"] = datetime.now(timezone.utc).isoformat()
        (args.out_dir / "judge-aggregate.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
        print(json.dumps({k: rep[k] for k in ("judgments_present", "judgments_expected",
              "n_cells_scored", "span_kappa", "arm_scores")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
