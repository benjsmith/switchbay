"""Model-free preflight for the real CE QUERY pilot.

This is intentionally separate from the four-cell smoke. It invokes only the
installed deterministic CE classifier/retriever against isolated copies,
proves zero workspace diff, and emits the hashes that must be frozen before the
matrix. It is not run automatically.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bench.agentic_query_bench.query_orchestrator import ProductionCeBackend

ROOT = Path(__file__).resolve().parent


def run_preflight(
    workspace: Path,
    *,
    scripts_dir: Path | None = None,
) -> dict[str, Any]:
    prereg = json.loads(
        (ROOT / "real_pilot_preregistration.draft.json").read_text(encoding="utf-8")
    )
    checks: list[dict[str, Any]] = []
    corpus_hashes: set[str] = set()
    script_manifests: list[dict[str, str]] = []
    for scenario_id in prereg["scenarios"]:
        scenario = json.loads(
            (ROOT / "scenarios" / f"{scenario_id}.json").read_text(encoding="utf-8")
        )
        question = str(scenario["turns"][0]["user_template"])
        backend = ProductionCeBackend(workspace, scripts_dir=scripts_dir)
        try:
            result = backend.retrieve(question, k=6)
            corpus_hashes.add(backend.corpus_hash)
            script_manifests.append(backend.script_hashes)
            checks.append(
                {
                    "scenario_id": scenario_id,
                    "question": question,
                    "corpus_hash": backend.corpus_hash,
                    "script_hashes": backend.script_hashes,
                    "sources": result.sources,
                    "trace": result.trace,
                    "zero_diff": all(
                        item["workspace_hash_before"] == item["workspace_hash_after"]
                        for item in backend.trace
                    ),
                }
            )
        finally:
            backend.close()
    stable_scripts = all(
        manifest == script_manifests[0] for manifest in script_manifests
    )
    return {
        "schema_version": 1,
        "status": "pass"
        if len(corpus_hashes) == 1
        and stable_scripts
        and all(check["zero_diff"] for check in checks)
        else "fail",
        "corpus_hash": next(iter(corpus_hashes)) if len(corpus_hashes) == 1 else None,
        "script_hashes": script_manifests[0] if stable_scripts else None,
        "checks": checks,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--ce-scripts-dir", type=Path, default=None)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    report = run_preflight(
        args.workspace.expanduser().resolve(),
        scripts_dir=args.ce_scripts_dir,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "out": str(args.out)}))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
