"""Workspace merge (D2, stage 5) — a daemon-side DETERMINISTIC pipeline.

Design decision (2026-07-05): the merge deliberately involves no LLM
and no agent. curiosity-merge's `merge.py` is a scripted stage →
audit → apply pipeline (trust gates, quarantine, unmerge manifests),
so the daemon can orchestrate it as subprocesses:

    1. seed: copy source #1 → <workspaces-home>/<name>
       (minus .git — a published source's remote must not leak into
       the merged workspace — and minus .workbench/state + trash:
       rail history and trashed files are per-workspace, not
       knowledge)
    2. for each remaining source:  merge.py <src> --as-origin <slug>
       --workspace <target>   then   merge.py --apply <slug>

This keeps the single-workspace agent scoping rule fully intact and
is SAFER than a scope exception: sources are only ever read by
audited deterministic code, never by a model. The optional
post-merge reconciliation review can run later as a normal agent
scoped to the TARGET workspace only.

Originals stay on disk and leave the registry (reversible — re-Add
them any time). Completion is a toast with an Open button, never an
auto-switch (D2 detail ruling).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Callable

from . import cebridge

log = logging.getLogger(__name__)

_STEP_TIMEOUT = 1800  # staging/apply rebuild the kuzu graph — allow big wikis


class MergeError(Exception):
    """User-visible merge failure (carries the failing step's tail)."""


def cm_root() -> Path:
    """Locate the curiosity-merge skill bundle (scripts/merge.py).
    Same resolution posture as cebridge: env override, then the
    installed first-party skill, then the dev checkout."""
    candidates: list[Path] = []
    env = os.environ.get("SWITCHBAY_CM_ROOT")
    if env:
        candidates.append(Path(env).expanduser())
    candidates.append(Path.home() / ".claude" / "skills" / "curiosity-merge")
    candidates.append(Path.home() / "Dev" / "curiosity-merge")
    for c in candidates:
        if (c / "scripts" / "merge.py").is_file():
            return c
    raise MergeError(
        "curiosity-merge skill not found — expected scripts/merge.py under "
        + " or ".join(str(c) for c in candidates)
    )


def origin_slugs(sources: list[Path]) -> list[str]:
    """One stable, unique --as-origin tag per merged-in source
    (source #1 seeds the target and gets no tag)."""
    out: list[str] = []
    seen: set[str] = set()
    for src in sources[1:]:
        base = re.sub(r"[^a-z0-9-]+", "-", src.name.lower()).strip("-") or "origin"
        slug, n = base, 2
        while slug in seen:
            slug = f"{base}-{n}"
            n += 1
        seen.add(slug)
        out.append(slug)
    return out


def _seed_copy(src: Path, dst: Path) -> None:
    shutil.copytree(
        src, dst,
        ignore=shutil.ignore_patterns(".git"),
        symlinks=False,
    )
    for sub in ("state", "trash"):
        shutil.rmtree(dst / ".workbench" / sub, ignore_errors=True)
    # merge.py refuses a receiving workspace without BOTH wiki/ and
    # vault/ — a source that never ingested anything has no vault dir.
    (dst / "wiki").mkdir(exist_ok=True)
    (dst / "vault").mkdir(exist_ok=True)


def _merge_env() -> dict[str, str]:
    """Subprocess env: CE helper imports resolved, venv leak vars
    scrubbed (the cebridge gotcha)."""
    env = {
        k: v for k, v in os.environ.items()
        if k not in {"VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "PYTHONPATH"}
    }
    env["CURIOSITY_ENGINE_SCRIPTS_DIR"] = str(cebridge.ce_root() / "scripts")
    return env


async def _run_step(argv: list[str], *, cwd: Path) -> str:
    """One merge.py invocation; raises MergeError on failure with the
    output tail (the audit report head is usually the useful part)."""
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(cwd),
        env=_merge_env(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out_b, _ = await asyncio.wait_for(proc.communicate(), _STEP_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        raise MergeError(f"merge step timed out after {_STEP_TIMEOUT}s: {' '.join(argv[-4:])}")
    out = out_b.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        tail = "\n".join(out.strip().splitlines()[-15:])
        raise MergeError(f"{' '.join(argv[-4:])} failed (rc={proc.returncode}):\n{tail}")
    return out


async def merge_workspaces(
    sources: list[Path],
    target: Path,
    progress: Callable[[str], None],
) -> dict:
    """Run the full pipeline. Returns {origins, output_tail}."""
    if len(sources) < 2:
        raise MergeError("need at least two workspaces to merge")
    if target.exists():
        raise MergeError(f"target already exists: {target}")
    merge_py = cm_root() / "scripts" / "merge.py"
    slugs = origin_slugs(sources)

    progress(f"seeding from {sources[0].name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        await asyncio.to_thread(_seed_copy, sources[0], target)
        last_out = ""
        for src, slug in zip(sources[1:], slugs):
            progress(f"staging {src.name}")
            await _run_step(
                [sys.executable, str(merge_py), str(src),
                 "--as-origin", slug, "--workspace", str(target)],
                cwd=target,
            )
            progress(f"applying {src.name}")
            last_out = await _run_step(
                [sys.executable, str(merge_py),
                 "--apply", slug, "--workspace", str(target)],
                cwd=target,
            )
    except Exception:
        # A half-built target must not linger looking like a real
        # workspace — the originals are untouched, so a clean retry
        # is always possible.
        await asyncio.to_thread(shutil.rmtree, target, True)
        raise
    tail = "\n".join(last_out.strip().splitlines()[-8:]) if last_out else ""
    return {"origins": slugs, "output_tail": tail}
