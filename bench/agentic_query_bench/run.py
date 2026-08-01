"""Multi-turn agentic_query_bench runner.

Does not invoke live LLMs unless --generate-provider is set.
Default: --dry-run validates scenarios + cite_resolver + examiner branches
with a stub generator (no network).

  PYTHONPATH=src:. python -m bench.agentic_query_bench.run \\
    --workspace ~/.cache/sy-phase2-bench/ws --dry-run

  PYTHONPATH=src:. python -m bench.agentic_query_bench.run \\
    --workspace ~/.cache/sy-phase2-bench/ws \\
    --scenarios scenarios/ep-comp599-privacy-transparency-01.json \\
    --arms closed_book,rag_std --generate-provider xai
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from bench.agentic_query_bench.arms import ArmResult, blind_code, build_arm
from bench.agentic_query_bench.cite_resolver import (
    CITE_RESOLVER_VERSION,
    resolve_trajectory,
)
from bench.agentic_query_bench.examiner import (
    load_scenario,
    next_user_message,
    resteer_rate,
    validate_turn_against_templates,
)
from bench.agentic_query_bench.scoring import apply_provenance_gate, mechanical_resteer_rate

ROOT = Path(__file__).resolve().parent
DEFAULT_WS = Path.home() / ".cache/sy-phase2-bench/ws"


def _stub_generate(question: str, context: str) -> str:
    """Deterministic offline generator for dry-run / unit paths."""
    ctx_note = f"(context_chars={len(context or '')})"
    # Emit a resolvable-looking cite only if context contains vault/ or wiki/
    cite = ""
    if "vault/" in (context or "") or "(vault:" in (context or ""):
        cite = " (vault:example-not-checked-in-stub)"
    if "wiki/" in (context or ""):
        cite = " wiki/facts/stub.md"
    return (
        f"STUB PLAN for: {question[:200]}\n"
        f"- Point A{cite}\n"
        f"- Point B\n"
        f"**Side path:** fairness-harms-contrast (optional)\n"
        f"Gaps: need more on X.\n"
        f"Next questions: What about Y?\n"
        f"{ctx_note}\n"
    )


def _llm_generate(
    provider: str,
    *,
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.0,
    limit_sleep_s: int = 1800,
    limit_patience_h: float = 12.0,
) -> Callable[[str, str], str]:
    from bench.agentic_query_bench.llm_util import robust_llm_call

    def gen(question: str, context: str) -> str:
        # Arms enforce their own context budgets (long_ctx legitimately sends
        # ~100k chars) — this cap is only a runaway safety net (review RB7).
        prompt = (
            "You are answering a multi-turn knowledge-work planning task.\n"
            "Use ONLY the CONTEXT for corpus claims. Cite (vault:relpath) or wiki paths "
            "when possible. Label optional digressions as **Side path:** name.\n\n"
            f"CONTEXT:\n{context[:200_000]}\n\nUSER:\n{question}\n"
        )
        # Limit-shaped errors sleep + auto-resume inside; hard errors raise
        # and surface as ArmResult.error → completion/failure table.
        return robust_llm_call(
            provider, prompt, model=model, max_tokens=max_tokens,
            temperature=temperature,
            limit_sleep_s=limit_sleep_s, limit_patience_h=limit_patience_h,
        )

    return gen


def cell_stem(scenario_id: str, arm: str, seed: str | int) -> str:
    return f"{scenario_id}--{arm}--s{seed}"


def load_scenarios(paths: list[Path]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in paths:
        if p.is_dir():
            for f in sorted(p.glob("*.json")):
                if f.name.startswith("_"):
                    continue
                out.append(json.loads(f.read_text(encoding="utf-8")))
        else:
            out.append(json.loads(p.read_text(encoding="utf-8")))
    return out


def _maybe_inject_poison(workspace: Path, scenario: dict[str, Any]) -> list[Path]:
    """Copy poisoned fixtures into the workspace if the card requests them.

    Returns the paths written (wiki analysis and/or raw-vault variant), for
    retrieve-time context only. Caller must delete them in a ``finally`` (RB4).

    The vault variant (``poisoned_vault``) exists so raw-vault-only comparators
    (``rag_modern_agentic_v1``) face the same false claim CE meets in the wiki
    analysis; without it the poison paired cell is biased against CE — see
    docs/rag-modern-comparator-independent-review-2026-07-23.md (B2).
    """
    written: list[Path] = []
    # Paths must look organic (underscore prefix is for ops grep only):
    # retrieval context includes paths, so "poison"/"bench" in a name would give
    # the descend-and-verify test away (review RB3).
    pa = scenario.get("poisoned_analysis") or {}
    if pa.get("inject"):
        rel = pa.get("relative_path") or "wiki/analyses/_privacy-utility-tradeoffs.md"
        src = ROOT / "fixtures/poisoned" / Path(rel).name
        if not src.is_file():
            src = ROOT / "fixtures/poisoned/_privacy-utility-tradeoffs.md"
        dest = workspace / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        written.append(dest)
    pv = scenario.get("poisoned_vault") or {}
    if pv.get("inject") and pv.get("relative_path"):
        rel = pv["relative_path"]
        src = ROOT / "fixtures/poisoned/vault" / Path(rel).name
        if src.is_file():
            dest = workspace / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            written.append(dest)
    return written


def run_trajectory(
    scenario: dict[str, Any],
    arm_name: str,
    workspace: Path,
    generate: Callable[[str, str], str],
    *,
    max_tool_calls: int = 8,
    seed_tag: str = "0",
    ce_scripts_dir: Path | None = None,
) -> dict[str, Any]:
    poison_paths = _maybe_inject_poison(workspace, scenario)
    try:
        return _run_trajectory_inner(
            scenario, arm_name, workspace, generate,
            max_tool_calls=max_tool_calls, seed_tag=seed_tag,
            poison_paths=poison_paths,
            ce_scripts_dir=ce_scripts_dir,
        )
    finally:
        # RB4: never leave a poison fixture in the live workspace — it would
        # contaminate later scenarios in this run and any re-embed afterwards.
        for p in poison_paths:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass


def _run_trajectory_inner(
    scenario: dict[str, Any],
    arm_name: str,
    workspace: Path,
    generate: Callable[[str, str], str],
    *,
    max_tool_calls: int,
    seed_tag: str,
    poison_paths: list[Path],
    ce_scripts_dir: Path | None,
) -> dict[str, Any]:
    arm = build_arm(
        arm_name,
        workspace,
        generate,
        max_tool_calls=max_tool_calls,
        ce_scripts_dir=ce_scripts_dir,
    )
    state = load_scenario(scenario)
    history: list[dict[str, str]] = []
    turns_out: list[dict[str, Any]] = []
    last_assistant: str | None = None
    t0 = time.time()
    arm_error: str | None = None

    while not state.done:
        umsg = next_user_message(state, last_assistant=last_assistant)
        if umsg is None:
            break
        user_text = umsg["user"]
        template_ok = bool(umsg.get("synthesized")) or validate_turn_against_templates(
            scenario, user_text, umsg["id"]
        )
        # Scenario cards carry preregistered intent labels. CE arms consume
        # them as their QUERY policy; all other arms simply ignore the field.
        setattr(arm, "expected_intent", umsg.get("expected_intent") or "")
        try:
            result: ArmResult = arm.respond(user_text, history)
        except Exception as e:  # noqa: BLE001
            result = ArmResult(answer="", error=f"{type(e).__name__}: {e}")
        if result.error:
            arm_error = result.error
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": result.answer or ""})
        last_assistant = result.answer or ""
        turns_out.append({
            "id": umsg["id"],
            "examiner_goal": umsg.get("examiner_goal"),
            "branch_used": umsg.get("branch_used"),
            "is_resteer": umsg.get("is_resteer"),
            "template_ok": template_ok,
            "expected_intent": umsg.get("expected_intent"),
            "user": user_text,
            "assistant": result.answer,
            "sources": result.sources,
            "context_chars": result.context_chars,
            "tool_calls": result.tool_calls,
            "arm_meta": result.meta,
            "error": result.error,
        })
        if arm_error and not result.answer:
            break

    cite_rep = resolve_trajectory(workspace, turns_out, answer_key="assistant")
    rr = mechanical_resteer_rate(turns_out)
    # also from examiner state
    rr = max(rr, resteer_rate(state))

    traj = {
        "scenario_id": scenario.get("id"),
        "family": scenario.get("family"),
        "arm": arm_name,
        "blind_code": blind_code(arm_name),
        "seed_tag": seed_tag,
        "workspace": str(workspace),
        "poison_injected": str(poison_paths[0]) if poison_paths else None,
        "poison_injected_paths": [str(p) for p in poison_paths],
        "turns": turns_out,
        "n_turns": len(turns_out),
        "resteer_count": state.resteer_count,
        "resteer_rate": rr,
        "accept_count": state.accept_count,
        "cite_resolver": cite_rep,
        "provenance_violation": cite_rep.get("provenance_violation", False),
        "completion": arm_error is None and len(turns_out) == len(scenario.get("turns") or []),
        "arm_error": arm_error,
        "elapsed_s": round(time.time() - t0, 3),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    arm.close()
    return apply_provenance_gate(traj, provenance_violation=traj["provenance_violation"])


def build_judge_pack(scenario: dict[str, Any], trajectory: dict[str, Any]) -> dict[str, Any]:
    """Pack for judges: frozen evidence, no live tools, mechanical pre-pass."""
    dossier_path = ROOT / "evidence_dossiers" / f"{scenario.get('id')}.json"
    dossier: dict[str, Any] | None = None
    if dossier_path.is_file():
        dossier = json.loads(dossier_path.read_text(encoding="utf-8"))

    applicable = {
        "theme_recall": any(
            not t.get("absent_from_corpus")
            for t in (scenario.get("gold_themes") or [])
        ),
        "multi_hop_coverage": any(
            t.get("multi_hop") and not t.get("absent_from_corpus")
            for t in (scenario.get("gold_themes") or [])
        ),
        "citation_support": bool(
            ((trajectory.get("cite_resolver") or {}).get("n_presented") or 0)
        ),
    }
    if dossier:
        applicable.update(dossier.get("applicable_dimensions") or {})

    canonical = set((dossier or {}).get("canonical_sources") or [])
    cited: list[str] = []
    covered: list[str] = []
    workspace = Path(str(trajectory.get("workspace") or "."))
    for turn in ((trajectory.get("cite_resolver") or {}).get("per_turn") or []):
        for cite in ((turn.get("report") or {}).get("cites") or []):
            resolved = cite.get("resolved_path")
            if not resolved or not cite.get("presented_as_citation"):
                continue
            cited.append(str(resolved))
            if resolved in canonical:
                covered.append(str(resolved))
                continue
            if str(resolved).startswith("wiki/"):
                try:
                    page = (workspace / str(resolved)).read_text(
                        encoding="utf-8", errors="replace"
                    )
                except OSError:
                    page = ""
                if any(source.removeprefix("vault/") in page for source in canonical):
                    covered.append(str(resolved))
    unique_cited = list(dict.fromkeys(cited))
    unique_covered = list(dict.fromkeys(covered))
    dossier_coverage = (
        len(unique_covered) / len(unique_cited) if unique_cited else 1.0
    )

    def normalize(text: str) -> str:
        # Remove system self-identifiers without touching evidence, citations,
        # or substantive prose. All arms pass through the same function.
        value = text or ""
        value = re.sub(
            r"(?i)\b(?:ce[\s_-]*query(?:[\s_-]*(?:real|sim))?|"
            r"ce_query_real_bench_v1|ce_query_sim_v2|"
            r"rag_wiki_text|agentic_plain|closed_book)\b",
            "the system",
            value,
        )
        return value

    return {
        "scenario": {
            "id": scenario.get("id"),
            "family": scenario.get("family"),
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
        "evidence_dossier_diagnostics": {
            "cited_sources": unique_cited,
            "covered_sources": unique_covered,
            "citation_coverage_rate": dossier_coverage,
            "minimum_required_for_matrix": 0.9,
        },
        "trajectory": {
            "blind_code": trajectory.get("blind_code"),
            "turns": [
                {
                    "id": t.get("id"),
                    "user": t.get("user"),
                    "assistant": normalize(str(t.get("assistant") or "")),
                    "branch_used": t.get("branch_used"),
                    "is_resteer": t.get("is_resteer"),
                }
                for t in trajectory.get("turns") or []
            ],
            "resteer_rate": trajectory.get("resteer_rate"),
            "cite_resolver": trajectory.get("cite_resolver"),
            "provenance_violation": trajectory.get("provenance_violation"),
            "completion": trajectory.get("completion"),
        },
        "instructions": (
            "Score using judgment-charter.json. citation_support must use "
            "cite_resolver plus the frozen evidence dossier. Omit every "
            "dimension marked false in applicable_dimensions. "
            "serendipity_quality is card-anchored and outside primary composite."
        ),
    }


def _atomic_write_json(path: Path, obj: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1), encoding="utf-8")
    tmp.replace(path)


def refresh_checkpoint_file(
    path: Path,
    workspace: Path,
    scenario: dict[str, Any],
) -> bool:
    """Recompute resolver-derived fields without regenerating model output.

    Returns True when an old checkpoint was migrated. Poison fixtures are
    present during recomputation so saved poisoned-scenario citations resolve
    against the same workspace state as generation.
    """
    cell = json.loads(path.read_text(encoding="utf-8"))
    traj = cell.get("trajectory") or {}
    old = traj.get("cite_resolver") or {}
    if old.get("resolver_version") == CITE_RESOLVER_VERSION:
        return False

    poison_paths = _maybe_inject_poison(workspace, scenario)
    try:
        cite_rep = resolve_trajectory(
            workspace, traj.get("turns") or [], answer_key="assistant"
        )
    finally:
        for p in poison_paths:
            p.unlink(missing_ok=True)

    traj["cite_resolver"] = cite_rep
    traj = apply_provenance_gate(
        traj, provenance_violation=cite_rep.get("provenance_violation", False)
    )
    cell["trajectory"] = traj
    cell["judge_pack"] = build_judge_pack(scenario, traj)
    _atomic_write_json(path, cell)
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Agentic QUERY vs RAG multi-turn bench")
    ap.add_argument("--workspace", type=Path, default=DEFAULT_WS)
    ap.add_argument(
        "--scenarios",
        type=Path,
        nargs="*",
        default=[ROOT / "scenarios"],
        help="Scenario JSON files or directories",
    )
    ap.add_argument(
        "--arms",
        default="closed_book,rag_std,agentic_plain,ce_retrieve_only,ce_query",
        help="Comma-separated arm names",
    )
    ap.add_argument("--generate-provider", default="", help="If set, use bench.llm provider")
    ap.add_argument("--model", default="", help="Model override for the generator provider")
    ap.add_argument("--generator-max-tokens", type=int, default=4096)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--dry-run", action="store_true", help="Stub generator; no network")
    ap.add_argument("--max-tool-calls", type=int, default=8)
    ap.add_argument(
        "--ce-scripts-dir",
        type=Path,
        default=None,
        help="Installed curiosity-engine scripts directory for ce_query_real",
    )
    ap.add_argument("--repeats", type=int, default=1, help="Trajectories per scenario-arm")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument(
        "--results-dir", type=Path, default=None,
        help="Checkpoint mode: one JSON per (scenario, arm, seed) under "
             "<dir>/trajectories/; existing cells are skipped (resume)",
    )
    ap.add_argument("--limit-sleep", type=int, default=1800)
    ap.add_argument("--limit-patience-hours", type=float, default=12.0)
    ap.add_argument("--limit-scenarios", type=int, default=0)
    ap.add_argument(
        "--migrate-checkpoints",
        action="store_true",
        help="Explicitly rewrite old resolver-derived checkpoint fields. "
        "Off by default so frozen experiments remain immutable.",
    )
    args = ap.parse_args(argv)

    ws = args.workspace.expanduser().resolve()
    scen_paths = [p.expanduser() for p in args.scenarios]
    scenarios = load_scenarios(scen_paths)
    if args.limit_scenarios:
        scenarios = scenarios[: args.limit_scenarios]
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    if "ce_query_real" in arms and not (args.dry_run or args.model):
        ap.error("ce_query_real requires an explicit --model pin")
    if not 0.0 <= args.temperature <= 2.0:
        ap.error("--temperature must be between 0 and 2")

    if args.dry_run or not args.generate_provider:
        generate = _stub_generate
        mode = "dry_run_stub"
        resolved_model = "stub"
    else:
        from bench import llm as _llm
        resolved_model = (
            args.model
            or _llm.MODEL_OVERRIDE.get(args.generate_provider)
            or _llm.provider_model(args.generate_provider)
            or "provider-default"
        )
        generate = _llm_generate(
            args.generate_provider, model=args.model or None,
            max_tokens=args.generator_max_tokens,
            temperature=args.temperature,
            limit_sleep_s=args.limit_sleep,
            limit_patience_h=args.limit_patience_hours,
        )
        mode = f"llm:{args.generate_provider}"
    # Charter directive: print the resolved generator model before the run.
    print(f"GENERATOR: provider={args.generate_provider or 'stub'} "
          f"model={resolved_model}", flush=True)

    traj_dir: Path | None = None
    if args.results_dir:
        traj_dir = args.results_dir.expanduser() / "trajectories"
        traj_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for sc in scenarios:
        for arm in arms:
            for r in range(args.repeats):
                stem = cell_stem(sc.get("id", "unknown"), arm, r)
                if traj_dir is not None and (traj_dir / f"{stem}.json").is_file():
                    migrated = False
                    if args.migrate_checkpoints:
                        migrated = refresh_checkpoint_file(
                            traj_dir / f"{stem}.json", ws, sc
                        )
                    if migrated:
                        print(
                            f"migrate {stem} (cite resolver v{CITE_RESOLVER_VERSION})",
                            flush=True,
                        )
                    print(f"skip {stem} (already done)", flush=True)
                    continue
                print(f"run {sc.get('id')} × {arm} seed={r} …", flush=True)
                traj = run_trajectory(
                    sc, arm, ws, generate,
                    max_tool_calls=args.max_tool_calls,
                    seed_tag=str(r),
                    ce_scripts_dir=args.ce_scripts_dir,
                )
                traj["generator"] = {
                    "mode": mode,
                    "model": resolved_model,
                    "max_tokens": args.generator_max_tokens,
                    "temperature_requested": args.temperature,
                    "temperature_note": (
                        "Some subscription CLI providers reject temperature; "
                        "the gateway then uses their provider default."
                    ),
                }
                pack = build_judge_pack(sc, traj)
                cell = {"trajectory": traj, "judge_pack": pack}
                if traj_dir is not None:
                    _atomic_write_json(traj_dir / f"{stem}.json", cell)
                results.append(cell)
                print(
                    f"  turns={traj['n_turns']} resteer={traj['resteer_rate']:.2f} "
                    f"prov_viol={traj['provenance_violation']} "
                    f"complete={traj['completion']} err={traj.get('arm_error')}",
                    flush=True,
                )

    out = {
        "schema_version": 1,
        "mode": mode,
        "workspace": str(ws),
        "n_trajectories": len(results),
        "charter": "bench/agentic_query_bench/judgment-charter.json",
        "preregistration": "bench/agentic_query_bench/preregistration.json",
        "results": results,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    out_path = args.out or (
        Path("bench/results") / f"agentic-query-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json"
    )
    out_path = out_path.expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"wrote {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
