"""Model-free product preflight (staged-authorization step 1).

Proves the deterministic invariants the product pilot depends on, WITHOUT
launching a generator/judge or building the (download-heavy) RAG index:

  1. modern-RAG calibration set is disjoint from the four scored scenarios
     (review B3), and its absent probes avoid the scored absent topic;
  2. the installed CE query scripts exist and hash stably;
  3. the tool-matched baseline provisions with hash-equal read-only script copies
     and a hash-verified-absent skill tree (on a scratch snapshot);
  4. the mutation-contract auditor accepts an append-only ``.curator/log.md`` and
     rejects an out-of-contract wiki edit (dry-run on scratch copies).

Exit 0 on pass. It never spends model quota.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bench.agentic_query_bench import baseline_provision as BP
from bench.agentic_query_bench import product_arms as PA
from bench.agentic_query_bench import rag_calibration as RC
from bench.agentic_query_bench.mutation_contract import CURATOR_LOG, audit_dirs
from bench.agentic_query_bench.rag_modern import PINNED, config_hash


def _script_hashes(scripts_dir: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for name in BP.CANONICAL_SCRIPTS:
        p = scripts_dir / name
        if p.is_file():
            out[name] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _check_disjointness() -> dict[str, Any]:
    try:
        info = RC.assert_disjoint()
        return {"ok": True, **info}
    except AssertionError as e:  # pragma: no cover - exercised via unit test
        return {"ok": False, "error": str(e)}


def _check_ce_scripts(scripts_dir: Path) -> dict[str, Any]:
    hashes = _script_hashes(scripts_dir)
    missing = [n for n in ("graph.py", "query_router.py") if n not in hashes]
    return {"ok": not missing, "scripts_dir": str(scripts_dir), "hashes": hashes, "missing": missing}


def _check_tool_matched(scripts_dir: Path) -> dict[str, Any]:
    """Provision a scratch snapshot that carries a fake CE skill + the REAL
    scripts, then assert hash-equality + skill-absent."""
    with tempfile.TemporaryDirectory(prefix="aqb-preflight-tm-") as td:
        snap = Path(td) / "snap"
        skill = snap / PA.CE_SKILL_REL
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("# curiosity-engine\n", encoding="utf-8")
        # a scripts subtree inside the skill (product layout) + copy real scripts
        (snap / "CLAUDE.md").write_text("# CE project instructions\n", encoding="utf-8")
        rep = BP.provision_tool_matched_snapshot(
            snap, product_scripts_dir=scripts_dir, skill_rel=PA.CE_SKILL_REL
        )
        return {"ok": rep.ok, **rep.to_dict()}


def _check_mutation_contract() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="aqb-preflight-mc-") as td:
        before = Path(td) / "before"
        after_ok = Path(td) / "after_ok"
        after_bad = Path(td) / "after_bad"
        for root in (before, after_ok, after_bad):
            (root / "wiki").mkdir(parents=True)
            (root / "wiki" / "p.md").write_text("page\n", encoding="utf-8")
            (root / ".curator").mkdir(parents=True)
            (root / CURATOR_LOG).write_text("l1\n", encoding="utf-8")
        # allowed: append to the curator log
        (after_ok / CURATOR_LOG).write_text("l1\nl2\n", encoding="utf-8")
        # forbidden: edit a wiki page
        (after_bad / "wiki" / "p.md").write_text("tampered\n", encoding="utf-8")
        allowed = audit_dirs(before, after_ok, mode="ordinary")
        forbidden = audit_dirs(before, after_bad, mode="ordinary")
        ok = allowed.allowed and not forbidden.allowed
        return {
            "ok": ok,
            "append_allowed": allowed.allowed,
            "wiki_edit_rejected": not forbidden.allowed,
            "forbidden_violations": forbidden.violations,
        }


def run_preflight(
    workspace: Path,
    *,
    scripts_dir: Path | None = None,
) -> dict[str, Any]:
    scripts_dir = Path(scripts_dir) if scripts_dir else PA.product_scripts_dir()
    checks = {
        "calibration_disjointness": _check_disjointness(),
        "ce_scripts": _check_ce_scripts(scripts_dir),
        "tool_matched_provision": _check_tool_matched(scripts_dir),
        "mutation_contract_dryrun": _check_mutation_contract(),
    }
    status = "pass" if all(c.get("ok") for c in checks.values()) else "fail"
    return {
        "schema_version": 1,
        "status": status,
        "workspace": str(workspace),
        "modern_rag_pinned": PINNED,
        "modern_rag_config_hash": config_hash(),
        "checks": checks,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", type=Path, required=True)
    ap.add_argument("--ce-scripts-dir", type=Path, default=None)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    report = run_preflight(
        args.workspace.expanduser().resolve(), scripts_dir=args.ce_scripts_dir
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "out": str(args.out),
                      "checks": {k: v.get("ok") for k, v in report["checks"].items()}}, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
