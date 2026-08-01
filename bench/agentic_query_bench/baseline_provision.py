"""Provision + verify the tool-matched (no-skill) baseline substrate.

The ``tool_matched_no_skill_v1`` arm must be identical to the product arm in
its read/query *capability* and differ only in *policy*. Concretely:

1. Read-only copies of the exact shipped CE query scripts live under
   ``<snapshot>/.bench-tools/ce-read/``, and their hashes equal the product
   skill's corresponding scripts (so neither arm has a stronger tool).
2. The CE project skill tree and CE-specific ``CLAUDE.md`` are removed and
   hash-verified absent, replaced by the frozen neutral workspace map
   (``tool_matched_neutral_map.md``) which names the commands but gives no
   retrieval/conversation/crystallization policy.

This module builds that substrate deterministically and verifies both halves.
No model calls.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Scripts whose hash-equality is contractually required. Others are copied for
# import completeness but only these are asserted equal to the product skill.
CANONICAL_SCRIPTS = ("query_router.py", "graph.py", "vault_search.py", "entity_gate.py")

CE_READ_REL = ".bench-tools/ce-read"
DEFAULT_SKILL_REL = ".claude/skills/curiosity-engine"
NEUTRAL_MAP_REL = "CLAUDE.md"

ROOT = Path(__file__).resolve().parent


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy_ignore(_dir: str, names: list[str]) -> set[str]:
    return {n for n in names if n == "__pycache__" or n.endswith(".pyc")}


def provision_ce_read(
    scripts_dir: Path,
    snapshot_root: Path,
    *,
    make_read_only: bool = True,
) -> dict[str, Any]:
    """Copy the shipped CE script tree into ``<snapshot>/.bench-tools/ce-read``.

    The whole tree is copied (so intra-tree imports resolve when the model runs
    ``uv run python3 .bench-tools/ce-read/graph.py …``); every copied file's
    hash is verified equal to its source. Returns a manifest with the canonical
    script hashes and a pass/fail verdict.
    """
    scripts_dir = Path(scripts_dir).expanduser().resolve()
    dest = Path(snapshot_root).expanduser().resolve() / CE_READ_REL
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(scripts_dir, dest, ignore=_copy_ignore)

    all_files: dict[str, str] = {}
    copy_mismatches: list[str] = []
    for path in sorted(p for p in dest.rglob("*") if p.is_file()):
        rel = path.relative_to(dest).as_posix()
        src = scripts_dir / rel
        digest = _sha256_file(path)
        all_files[rel] = digest
        if not src.is_file() or _sha256_file(src) != digest:
            copy_mismatches.append(rel)

    canonical_hashes: dict[str, str] = {}
    missing_canonical: list[str] = []
    for name in CANONICAL_SCRIPTS:
        p = dest / name
        if p.is_file():
            canonical_hashes[name] = _sha256_file(p)
        else:
            missing_canonical.append(name)

    if make_read_only:
        # Only files are made read-only. Directories stay writable so the
        # disposable snapshot's rmtree cleanup (and any re-provision) works;
        # a model dropping a *new* file under ce-read is caught by the
        # mutation-contract auditor (out-of-contract create), not relied on here.
        for path in dest.rglob("*"):
            if path.is_file():
                path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)

    return {
        "dest": str(dest),
        "source_scripts_dir": str(scripts_dir),
        "file_count": len(all_files),
        "canonical_hashes": canonical_hashes,
        "missing_canonical": missing_canonical,
        "copy_mismatches": copy_mismatches,
        "read_only": make_read_only,
        "ok": not copy_mismatches and not missing_canonical,
    }


def verify_script_hash_equality(
    product_scripts_dir: Path,
    ce_read_dir: Path,
) -> dict[str, Any]:
    """Assert the canonical query scripts match between product skill and copy."""
    product_scripts_dir = Path(product_scripts_dir).expanduser().resolve()
    ce_read_dir = Path(ce_read_dir).expanduser().resolve()
    hashes: dict[str, dict[str, str | None]] = {}
    mismatches: list[str] = []
    for name in CANONICAL_SCRIPTS:
        prod = product_scripts_dir / name
        copy = ce_read_dir / name
        prod_h = _sha256_file(prod) if prod.is_file() else None
        copy_h = _sha256_file(copy) if copy.is_file() else None
        hashes[name] = {"product": prod_h, "copy": copy_h}
        # Only canonical scripts that exist in the product are required to match.
        if prod_h is not None and prod_h != copy_h:
            mismatches.append(name)
    return {"equal": not mismatches, "mismatches": mismatches, "hashes": hashes}


def verify_skill_absent(
    snapshot_root: Path,
    *,
    skill_rel: str = DEFAULT_SKILL_REL,
    neutral_map_rel: str = NEUTRAL_MAP_REL,
) -> dict[str, Any]:
    """Verify the CE skill tree is gone and the neutral map is installed."""
    snapshot_root = Path(snapshot_root).expanduser().resolve()
    skill_path = snapshot_root / skill_rel
    neutral_path = snapshot_root / neutral_map_rel

    # Any residual skill directory that names curiosity-engine is a leak.
    residual_skills: list[str] = []
    skills_dir = snapshot_root / ".claude" / "skills"
    if skills_dir.is_dir():
        for child in sorted(skills_dir.iterdir()):
            if "curiosity" in child.name.casefold():
                residual_skills.append(child.relative_to(snapshot_root).as_posix())

    skill_present = skill_path.exists()
    neutral_present = neutral_path.is_file()
    return {
        "skill_absent": not skill_present and not residual_skills,
        "skill_path_checked": skill_rel,
        "residual_skill_dirs": residual_skills,
        "neutral_map_present": neutral_present,
        "neutral_map_hash": _sha256_file(neutral_path) if neutral_present else None,
        "ok": (not skill_present and not residual_skills and neutral_present),
    }


def install_neutral_map(
    snapshot_root: Path,
    *,
    neutral_map_src: Path | None = None,
    neutral_map_rel: str = NEUTRAL_MAP_REL,
) -> dict[str, Any]:
    """Replace the snapshot's CE-specific CLAUDE.md with the frozen neutral map."""
    src = Path(neutral_map_src) if neutral_map_src else ROOT / "tool_matched_neutral_map.md"
    dest = Path(snapshot_root).expanduser().resolve() / neutral_map_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return {"path": str(dest), "hash": _sha256_file(dest), "source": str(src)}


@dataclass
class BaselineProvisionReport:
    ce_read: dict[str, Any] = field(default_factory=dict)
    hash_equality: dict[str, Any] = field(default_factory=dict)
    skill_check: dict[str, Any] = field(default_factory=dict)
    neutral_map: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(
            self.ce_read.get("ok")
            and self.hash_equality.get("equal")
            and self.skill_check.get("ok")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "ce_read": self.ce_read,
            "hash_equality": self.hash_equality,
            "skill_check": self.skill_check,
            "neutral_map": self.neutral_map,
        }


def provision_tool_matched_snapshot(
    snapshot_root: Path,
    *,
    product_scripts_dir: Path,
    skill_rel: str = DEFAULT_SKILL_REL,
    neutral_map_src: Path | None = None,
    make_read_only: bool = True,
) -> BaselineProvisionReport:
    """End-to-end: remove the skill, install the neutral map, copy + verify the
    read-only CE scripts, and assert hash-equality against the product skill.

    Assumes ``snapshot_root`` is a disposable copy that already contains the CE
    skill tree at ``skill_rel`` (so removing it here is the treatment removal).
    """
    snapshot_root = Path(snapshot_root).expanduser().resolve()
    product_scripts_dir = Path(product_scripts_dir).expanduser().resolve()

    skill_path = snapshot_root / skill_rel
    if skill_path.exists():
        shutil.rmtree(skill_path)

    report = BaselineProvisionReport()
    report.neutral_map = install_neutral_map(snapshot_root, neutral_map_src=neutral_map_src)
    report.ce_read = provision_ce_read(
        product_scripts_dir, snapshot_root, make_read_only=make_read_only
    )
    report.hash_equality = verify_script_hash_equality(
        product_scripts_dir, snapshot_root / CE_READ_REL
    )
    report.skill_check = verify_skill_absent(snapshot_root, skill_rel=skill_rel)
    return report


def default_product_scripts_dir() -> Path:
    """Resolve the installed CE scripts dir the same way ProductionCeBackend does."""
    configured = os.environ.get("CURIOSITY_ENGINE_SCRIPTS_DIR")
    return Path(
        configured or Path.home() / ".agents/skills/curiosity-engine/scripts"
    ).expanduser().resolve()
