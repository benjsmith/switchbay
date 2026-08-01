"""Freeze the product-pilot config before the smoke.

Stamps the exact hashes + versions the smoke/matrix run against into a frozen
copy of the prereg (`real_pilot_preregistration.frozen.json`, status
``frozen``): CE skill-tree hash, Claude Code version, corpus/index hashes,
modern-RAG config hash + calibration record hash, dossier hashes, and the pinned
model IDs. Deterministic; no model calls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bench.agentic_query_bench import product_arms as PA

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]


def _tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(x for x in Path(root).rglob("*") if x.is_file()):
        parts = p.relative_to(root).parts
        if ".git" in parts or "__pycache__" in parts or p.suffix == ".pyc":
            continue
        h.update(p.relative_to(root).as_posix().encode())
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def _file_hash(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def _claude_version() -> str:
    try:
        out = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=15)
        return out.stdout.strip() or out.stderr.strip()
    except Exception as e:  # noqa: BLE001
        return f"unavailable: {e}"


def freeze(*, skill_dir: Path | None = None, calibration: Path, index_dir: Path,
           out: Path, host_model: str = "claude-opus-4-8") -> dict[str, Any]:
    skill_dir = Path(skill_dir) if skill_dir else PA.product_skill_dir()
    prereg = json.loads((ROOT / "real_pilot_preregistration.draft.json").read_text("utf-8"))
    calib = json.loads(Path(calibration).read_text("utf-8"))
    index_meta = json.loads((Path(index_dir) / "meta.json").read_text("utf-8"))

    dossiers = {p.stem: _file_hash(p)
                for p in sorted((ROOT / "evidence_dossiers").glob("*.json"))}
    scenarios = {p.stem: _file_hash(p)
                 for p in sorted((ROOT / "scenarios").glob("*.json"))}

    frozen = dict(prereg)
    frozen["status"] = "frozen_for_smoke"
    frozen["frozen_at_utc"] = datetime.now(timezone.utc).isoformat()
    frozen["scope"] = {
        **prereg.get("scope", {}),
        "skill_dir": str(skill_dir),
        "skill_tree_hash": _tree_hash(skill_dir),
        "claude_code_version": _claude_version(),
        "host_model": host_model,
        "corpus_hash": index_meta.get("corpus_hash"),
        "modern_rag_config_hash": index_meta.get("config_hash"),
        "modern_rag_index_meta_hash": _file_hash(Path(index_dir) / "meta.json"),
        "calibration_record_hash": hashlib.sha256(
            json.dumps(calib, sort_keys=True).encode()).hexdigest(),
        "calibration_chosen": calib["selection"]["chosen_variant"],
        "no_answer_threshold": calib["selection"]["no_answer_threshold"],
    }
    frozen["frozen_artifacts"] = {
        "dossier_hashes": dossiers,
        "scenario_hashes": scenarios,
        "neutral_map_hash": _file_hash(ROOT / "tool_matched_neutral_map.md"),
        "mutation_contract_module_hash": _file_hash(ROOT / "mutation_contract.py"),
        "product_run_module_hash": _file_hash(ROOT / "product_run.py"),
        "rag_modern_module_hash": _file_hash(ROOT / "rag_modern.py"),
    }
    frozen["judges_pinned"] = {
        "generator": host_model,
        "task_panel": ["xai/grok-4.5", "openai-codex/gpt-5.5"],
        "third_adjudicator": "human",
    }
    Path(out).write_text(json.dumps(frozen, indent=2), encoding="utf-8")
    return frozen


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--calibration", type=Path,
                    default=REPO / "bench/results/rag-modern-calibration/calibration.json")
    ap.add_argument("--index-dir", type=Path, default=REPO / "bench/results/rag-modern-index")
    ap.add_argument("--out", type=Path, default=ROOT / "real_pilot_preregistration.frozen.json")
    ap.add_argument("--host-model", default="claude-opus-4-8")
    args = ap.parse_args(argv)
    frozen = freeze(calibration=args.calibration, index_dir=args.index_dir, out=args.out,
                    host_model=args.host_model)
    print(json.dumps({
        "status": frozen["status"],
        "skill_tree_hash": frozen["scope"]["skill_tree_hash"][:16],
        "claude_code_version": frozen["scope"]["claude_code_version"],
        "corpus_hash": frozen["scope"]["corpus_hash"],
        "out": str(args.out),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
