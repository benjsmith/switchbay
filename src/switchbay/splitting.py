"""Workspace split (D4, stage 5) — switchbay orchestrates, CM exports.

Revised ruling (2026-07-05): split is NOT a curiosity-merge verb.
The graph review surface decides WHAT leaves and with which policy;
this module then composes:

  1. curiosity-merge `subgraph_export.py --pages-file` (v0.7.0)
     copies the selected pages + transitive vault citations + wiki-
     relative figure assets into the target — headless via the
     audited `--no-preflight --force` combination.
  2. Workspace-root `figures/` and `.workbench/sketches/` carry —
     switchbay-side by necessity: CM resolves figures wiki-relative
     and never touches `.workbench/`.
  3. `_split-manifest` records on BOTH sides (`.curator/splits/`),
     mapping each moved page to its destination so an async curator
     pass can heal dangling wikilinks — prose is never rewritten
     automatically.
  4. Source pruning: MOVE pages go to the OS trash (fileops.delete)
     — recoverable; COPY pages stay (that IS the duplicate-to-both
     boundary policy: copy = export + keep, move = export + trash).

No agent, no scope exception — same posture as merge.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

from . import cebridge, fileops
from .merging import cm_root

log = logging.getLogger(__name__)

_EXPORT_TIMEOUT = 900

_FIGURE_REF_RE = re.compile(r"figures/[A-Za-z0-9_.\-/]+")
_SLIDES_INLINE_RE = re.compile(r"^slides:\s*\[(.*?)\]", re.MULTILINE)
_SLIDES_DASH_RE = re.compile(
    r"^slides:\s*\n((?:\s*-\s*.+\n?)+)", re.MULTILINE,
)


class SplitError(Exception):
    """User-visible split failure."""


def _page_file(workspace: Path, ref: str) -> Path:
    return workspace / "wiki" / f"{ref}.md"


def validate_refs(workspace: Path, refs: list[str]) -> list[str]:
    """Refs that don't resolve to a wiki page file (graph ids are
    wiki-relative stems, so this is a direct check)."""
    return [r for r in refs if not _page_file(workspace, r).is_file()]


async def _run_export(
    workspace: Path, target: Path, refs: list[str],
) -> str:
    export_py = cm_root() / "scripts" / "subgraph_export.py"
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8",
    ) as f:
        json.dump(refs, f)
        pages_file = f.name
    env = {
        k: v for k, v in os.environ.items()
        if k not in {"VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "PYTHONPATH"}
    }
    env["CURIOSITY_ENGINE_SCRIPTS_DIR"] = str(cebridge.ce_root() / "scripts")
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(export_py),
            "--pages-file", pages_file,
            "--to", str(target),
            "--no-preflight", "--force",
            "--include-vault", "all",
            "--include-non-native",
            cwd=str(workspace),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            out_b, _ = await asyncio.wait_for(proc.communicate(), _EXPORT_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            raise SplitError(f"export timed out after {_EXPORT_TIMEOUT}s")
    finally:
        try:
            os.unlink(pages_file)
        except OSError:
            pass
    out = out_b.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        tail = "\n".join(out.strip().splitlines()[-12:])
        raise SplitError(f"subgraph export failed (rc={proc.returncode}):\n{tail}")
    return out


def _carry_assets(workspace: Path, target: Path) -> dict:
    """Copy workspace-root figures + referenced sketches for every
    exported page. CM's export handles wiki-relative figure paths;
    switchbay's figures/ lives at the workspace ROOT and sketches
    under .workbench/ — both invisible to CM by design."""
    figures = 0
    sketches = 0
    missing: list[str] = []
    for page in (target / "wiki").rglob("*.md"):
        try:
            text = page.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for ref in set(_FIGURE_REF_RE.findall(text)):
            # Post-migration refs are wiki-relative (CM's export
            # collects those itself — the dst.exists() check makes
            # this a no-op then); legacy workspace-root refs are ours
            # to carry. Try both roots.
            pairs = (
                (workspace / "wiki" / ref, target / "wiki" / ref),
                (workspace / ref, target / ref),
            )
            hit = next(((s, d) for s, d in pairs if s.is_file()), None)
            if hit is None:
                if not any(d.exists() for _, d in pairs):
                    missing.append(ref)
                continue
            src, dst = hit
            if dst.exists():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            figures += 1
        # Deck pages: carry the sketch sources their slides: list names.
        ids: list[str] = []
        m = _SLIDES_INLINE_RE.search(text)
        if m:
            ids = [s.strip().strip("\"'") for s in m.group(1).split(",") if s.strip()]
        else:
            m = _SLIDES_DASH_RE.search(text)
            if m:
                ids = [
                    line.strip().lstrip("-").strip().strip("\"'")
                    for line in m.group(1).splitlines() if line.strip()
                ]
        for sid in ids:
            src_dir = workspace / ".workbench" / "sketches"
            if not src_dir.is_dir():
                break
            for src in src_dir.glob(f"{sid}.*"):
                dst = target / ".workbench" / "sketches" / src.name
                if dst.exists():
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                sketches += 1
    return {"figures": figures, "sketches": sketches, "missing_figures": missing}


def _write_manifests(
    workspace: Path, target: Path, name: str,
    move: list[str], copy: list[str],
) -> None:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    body = {
        "name": name,
        "created": stamp,
        "source": str(workspace),
        "target": str(target),
        "moved": move,
        "copied": copy,
    }
    for side, extra in ((workspace, {"role": "source"}), (target, {"role": "target"})):
        d = side / ".curator" / "splits"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{stamp}-{name}.json").write_text(
            json.dumps({**body, **extra}, indent=2) + "\n", encoding="utf-8",
        )


async def split_workspace(
    workspace: Path,
    target: Path,
    move: list[str],
    copy: list[str],
    progress: Callable[[str], None],
) -> dict:
    """Full pipeline. Returns stats. On export/carry failure the
    half-built target is removed and the SOURCE is untouched; pruning
    (the only source mutation) runs LAST and uses the trash."""
    refs = list(dict.fromkeys(move + copy))
    if not refs:
        raise SplitError("nothing selected")
    if target.exists():
        raise SplitError(f"target already exists: {target}")
    bad = validate_refs(workspace, refs)
    if bad:
        raise SplitError("not wiki pages: " + ", ".join(bad[:8]))
    try:
        progress(f"exporting {len(refs)} pages")
        await _run_export(workspace, target, refs)
        progress("carrying figures + sketches")
        assets = await asyncio.to_thread(_carry_assets, workspace, target)
        progress("writing split manifests")
        await asyncio.to_thread(
            _write_manifests, workspace, target, target.name, move, copy,
        )
    except Exception:
        await asyncio.to_thread(shutil.rmtree, target, True)
        raise
    # Prune LAST — the target is complete before the source changes.
    progress(f"moving {len(move)} pages to the trash")
    pruned: list[str] = []
    prune_errors: list[str] = []
    for ref in move:
        try:
            await asyncio.to_thread(
                fileops.delete, workspace, f"wiki/{ref}.md",
            )
            pruned.append(ref)
        except fileops.FileOpError as e:
            prune_errors.append(f"{ref}: {e}")
    return {
        "exported": len(refs),
        "moved": len(pruned),
        "copied": len(copy),
        "prune_errors": prune_errors,
        **assets,
    }
