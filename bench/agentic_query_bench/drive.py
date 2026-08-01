"""Unattended pilot driver: generate → judge → aggregate, limit-robust.

Designed for nohup: every step is checkpointed and idempotent, limit-shaped
provider errors sleep + auto-resume (llm_util), and cells that failed ONLY
because patience ran out are requeued on the next pass. Safe to kill and
rerun at any point with the same --results-dir.

  PYTHONPATH=src:. nohup python -m bench.agentic_query_bench.drive \\
    --workspace ~/.cache/sy-phase2-bench/ws \\
    --results-dir bench/results/agentic-pilot-v1 \\
    > bench/results/agentic-pilot-v1/driver.log 2>&1 &
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from bench.agentic_query_bench import run as runner
from bench.agentic_query_bench.aggregate import build_report, render_md
from bench.agentic_query_bench.judges import judge_pack_file
from bench.agentic_query_bench.llm_util import LimitPatienceExceeded, is_limit_error
from bench.agentic_query_bench.cite_resolver import CITE_RESOLVER_VERSION

DEFAULT_ARMS = "closed_book,rag_std,rag_wiki_text,long_ctx,agentic_plain,ce_retrieve_only,ce_query"
DEFAULT_JUDGES = "xai,openai-codex"


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%m-%d %H:%M:%S')}Z] {msg}", flush=True)


def _requeue_limit_failures(traj_dir: Path) -> int:
    """Delete checkpointed cells whose ONLY failure is a limit error so the
    next generation pass re-runs them. Hard failures stay recorded."""
    n = 0
    for f in traj_dir.glob("*.json"):
        try:
            t = json.loads(f.read_text(encoding="utf-8")).get("trajectory") or {}
        except json.JSONDecodeError:
            f.unlink(missing_ok=True)
            n += 1
            continue
        err = t.get("arm_error") or ""
        if err and ("LimitPatienceExceeded" in err or is_limit_error(err)):
            f.unlink(missing_ok=True)
            n += 1
    return n


def phase_generate(args: argparse.Namespace) -> None:
    traj_dir = args.results_dir / "trajectories"
    traj_dir.mkdir(parents=True, exist_ok=True)
    initial_requeued = _requeue_limit_failures(traj_dir)
    if initial_requeued:
        log(f"{initial_requeued} prior limit-failed cells requeued before generation")
    for gen_pass in range(1, args.max_gen_passes + 1):
        argv = [
            "--workspace", str(args.workspace),
            "--results-dir", str(args.results_dir),
            "--arms", args.arms,
            "--repeats", str(args.repeats),
            "--generate-provider", args.gen_provider,
            "--model", args.gen_model,
            "--limit-sleep", str(args.limit_sleep),
            "--limit-patience-hours", str(args.patience_hours),
        ]
        if args.dry_run:
            argv = [
                "--workspace", str(args.workspace),
                "--results-dir", str(args.results_dir),
                "--arms", args.arms,
                "--repeats", str(args.repeats),
                "--dry-run",
            ]
        log(f"generation pass {gen_pass} starting")
        try:
            runner.main(argv)
        except Exception as e:  # noqa: BLE001 — keep the driver alive
            log(f"generation pass raised {type(e).__name__}: {e} — continuing")
        requeued = _requeue_limit_failures(traj_dir)
        if requeued == 0:
            log("generation complete (no limit-failed cells left)")
            return
        log(f"{requeued} limit-failed cells requeued — sleeping "
            f"{args.limit_sleep}s before next pass")
        time.sleep(args.limit_sleep)
    log("WARNING: max generation passes reached with limit failures remaining")


def phase_judge(args: argparse.Namespace) -> None:
    traj_dir = args.results_dir / "trajectories"
    pack_dir = args.results_dir / "packs"
    judg_dir = args.results_dir / "judgments"
    pack_dir.mkdir(parents=True, exist_ok=True)
    judges = [j.strip() for j in args.judges.split(",") if j.strip()]
    scenarios = runner.load_scenarios([runner.ROOT / "scenarios"])
    scenario_by_id = {str(s.get("id")): s for s in scenarios}
    files = sorted(traj_dir.glob("*.json"))
    log(f"judging {len(files)} trajectories × {len(judges)} judges")
    for f in files:
        initial = json.loads(f.read_text(encoding="utf-8"))
        initial_traj = initial.get("trajectory") or {}
        scenario = scenario_by_id.get(str(initial_traj.get("scenario_id")))
        migrated = False
        if scenario is not None:
            migrated = runner.refresh_checkpoint_file(f, args.workspace, scenario)
        obj = json.loads(f.read_text(encoding="utf-8"))
        pack = obj.get("judge_pack")
        traj = obj.get("trajectory") or {}
        if not pack or traj.get("arm_error"):
            continue  # failed cells are reported in the completion table, not judged
        pack_path = pack_dir / f"{f.stem}.json"
        existing_pack_version = None
        if pack_path.is_file():
            try:
                existing_pack = json.loads(pack_path.read_text(encoding="utf-8"))
                existing_pack_version = (
                    ((existing_pack.get("trajectory") or {}).get("cite_resolver") or {}).get(
                        "resolver_version"
                    )
                )
            except json.JSONDecodeError:
                pass
        if migrated or existing_pack_version != CITE_RESOLVER_VERSION:
            pack_path.write_text(json.dumps(pack, indent=1), encoding="utf-8")
        for judge in judges:
            judgment_path = judg_dir / f"{f.stem}.{judge}.json"
            if judgment_path.is_file():
                try:
                    judgment_version = json.loads(
                        judgment_path.read_text(encoding="utf-8")
                    ).get("cite_resolver_version")
                except json.JSONDecodeError:
                    judgment_version = None
                if judgment_version != CITE_RESOLVER_VERSION:
                    judgment_path.unlink(missing_ok=True)
            if args.dry_run:
                continue
            try:
                out = judge_pack_file(
                    pack_path, judge, judg_dir,
                    limit_sleep_s=args.limit_sleep,
                    limit_patience_h=args.patience_hours,
                    log=log,
                )
                if out is None:
                    log(f"[judge] {judge} failed to produce parseable "
                        f"judgment for {f.stem}")
            except LimitPatienceExceeded as e:
                log(f"[judge] patience exceeded ({e}) — moving on; rerun "
                    "drive to fill the gap")
            except Exception as e:  # noqa: BLE001
                log(f"[judge] {judge} error on {f.stem}: {e}")
    log("judging pass complete")


def phase_aggregate(args: argparse.Namespace) -> None:
    judges = [j.strip() for j in args.judges.split(",") if j.strip()]
    pair = (judges[0], judges[1]) if len(judges) >= 2 else (judges[0], judges[0])
    report = build_report(args.results_dir, pair)
    (args.results_dir / "report.json").write_text(
        json.dumps(report, indent=1), encoding="utf-8"
    )
    md = render_md(report)
    (args.results_dir / "report.md").write_text(md, encoding="utf-8")
    log("report written")
    print(md, flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Agentic bench pilot driver")
    ap.add_argument("--workspace", type=Path,
                    default=Path.home() / ".cache/sy-phase2-bench/ws")
    ap.add_argument("--results-dir", type=Path,
                    default=Path("bench/results/agentic-pilot-v1"))
    ap.add_argument("--arms", default=DEFAULT_ARMS)
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--gen-provider", default="claude-code")
    ap.add_argument("--gen-model", default="claude-opus-4-8",
                    help="User-chosen: latest Opus, burns subscription limits "
                         "slower than the Claude 5 tier")
    ap.add_argument("--judges", default=DEFAULT_JUDGES,
                    help="Non-generator families (prereg separation)")
    ap.add_argument("--limit-sleep", type=int, default=1800)
    ap.add_argument("--patience-hours", type=float, default=12.0)
    ap.add_argument("--max-gen-passes", type=int, default=12)
    ap.add_argument("--phases", default="generate,judge,aggregate")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    args.workspace = args.workspace.expanduser().resolve()
    args.results_dir = args.results_dir.expanduser()
    args.results_dir.mkdir(parents=True, exist_ok=True)

    log(f"driver start: ws={args.workspace} results={args.results_dir}")
    log(f"generator={args.gen_provider}:{args.gen_model} judges={args.judges} "
        f"arms={args.arms} repeats={args.repeats}")
    phases = [p.strip() for p in args.phases.split(",") if p.strip()]
    if "generate" in phases:
        phase_generate(args)
    if "judge" in phases:
        phase_judge(args)
    if "aggregate" in phases:
        phase_aggregate(args)
    log("driver done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
