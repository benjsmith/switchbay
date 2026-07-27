"""File-operation primitives used by the BROWSER column.

Step E ships: delete, duplicate, reveal-in-OS, stat. Drag-and-drop and
the `+` upload-as-ingest-agent flow land in step E.1 / step J.1.

All paths arrive as workspace-relative strings. We re-resolve under the
workspace and refuse anything that escapes it OR lands inside a system
directory (`.git`, `.workbench`, `.venv`, `node_modules`). The daemon's
SKIP_DIRS already hides those from `/api/tree` so the UI cannot point
at them, but we belt-and-brace the API.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Refuse to mutate paths whose first component is one of these. The
# bigger guard below also rejects ANY dotted top-level component so
# .curator, .obsidian, .claude, .DS_Store, etc. are protected even
# though the UI never surfaces them. This is defense-in-depth — if a
# caller hits the API directly with one of these paths, we still say no.
PROTECTED_TOP = {"node_modules", "venv", "__pycache__", "dist", "build"}


class FileOpError(Exception):
    """Raised for any user-visible failure (bad path, missing file, etc.)."""


def _resolve(workspace: Path, rel: str) -> Path:
    if not rel or rel.startswith("/") or "\x00" in rel:
        raise FileOpError("invalid path")
    try:
        target = (workspace / rel).resolve()
    except (OSError, ValueError) as e:
        raise FileOpError(f"resolve failed: {e}") from e
    try:
        relative = target.relative_to(workspace)
    except ValueError:
        raise FileOpError("path escapes workspace")
    if not relative.parts:
        raise FileOpError("refusing to touch the workspace root")
    top = relative.parts[0]
    if top.startswith("."):
        raise FileOpError(f"refusing to touch hidden path {top}/")
    if top in PROTECTED_TOP:
        raise FileOpError(f"refusing to touch {top}/")
    return target


def stat(workspace: Path, rel: str) -> dict:
    target = _resolve(workspace, rel)
    if not target.exists():
        raise FileOpError("not found")
    s = target.stat()
    return {
        "path": rel,
        "size": s.st_size,
        "mtime": s.st_mtime,
        "kind": "dir" if target.is_dir() else "file",
    }


def delete(workspace: Path, rel: str) -> str:
    """Delete-to-trash (D5): move the file to the OS trash so a wrong
    click is always recoverable — macOS `/usr/bin/trash` (ships since
    Sonoma), Linux `gio trash`, else a workspace-local
    `.workbench/trash/` fallback (also used when the OS tool fails,
    e.g. a volume without .Trashes). Returns a human-readable
    destination for the UI toast."""
    target = _resolve(workspace, rel)
    if not target.exists():
        raise FileOpError("not found")
    if target.is_dir():
        # Step E only deletes files; directory delete needs a recursive-confirm
        # UX which lands later.
        raise FileOpError("delete: directories not supported in step E")
    cmd: list[str] | None = None
    if sys.platform == "darwin" and os.path.exists("/usr/bin/trash"):
        cmd = ["/usr/bin/trash", str(target)]
    elif sys.platform.startswith("linux") and shutil.which("gio"):
        cmd = ["gio", "trash", str(target)]
    if cmd is not None:
        try:
            res = subprocess.run(
                cmd, capture_output=True, timeout=10, check=False,
            )
            if res.returncode == 0:
                return "the system Trash"
        except (OSError, subprocess.TimeoutExpired):
            pass  # fall through to the workspace-local bin
    bin_dir = workspace / ".workbench" / "trash"
    bin_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = bin_dir / f"{stamp}-{target.name}"
    n = 2
    while dest.exists():
        dest = bin_dir / f"{stamp}-{n}-{target.name}"
        n += 1
    shutil.move(str(target), str(dest))
    return f".workbench/trash/{dest.name}"


def duplicate(workspace: Path, rel: str) -> str:
    """Copy `rel` to a sibling with a unique " copy" suffix; return new rel."""
    src = _resolve(workspace, rel)
    if not src.is_file():
        raise FileOpError("source must be a file")
    stem = src.stem
    suffix = src.suffix
    parent = src.parent
    candidate = parent / f"{stem} copy{suffix}"
    n = 2
    while candidate.exists():
        candidate = parent / f"{stem} copy {n}{suffix}"
        n += 1
    shutil.copy2(src, candidate)
    # Re-validate (the copy must still be inside workspace).
    return str(candidate.relative_to(workspace))


async def reveal(workspace: Path, rel: str) -> None:
    """Open the file in the OS file manager (Finder/Explorer/xdg)."""
    target = _resolve(workspace, rel)
    if not target.exists():
        raise FileOpError("not found")
    if sys.platform == "darwin":
        argv = ["open", "-R", str(target)]
    elif sys.platform == "win32":
        argv = ["explorer", "/select,", str(target)]
    else:
        # Linux fallback: open the containing directory.
        argv = ["xdg-open", str(target.parent)]
    proc = await asyncio.create_subprocess_exec(*argv)
    await proc.wait()


async def open_external(workspace: Path, rel: str) -> None:
    """Hand the file off to the OS default app — `open <path>` on
    macOS, `xdg-open` on Linux, `start` shell on Windows. Used by
    the file browser's "Open" context-menu item so vault PDFs go
    to Preview, PNGs to the image viewer, etc., instead of trying
    to render them in a switchbay tab."""
    target = _resolve(workspace, rel)
    if not target.exists():
        raise FileOpError("not found")
    if sys.platform == "darwin":
        argv = ["open", str(target)]
    elif sys.platform == "win32":
        # `start` is a shell builtin — invoke via cmd.exe so the
        # current process doesn't pin the launched app.
        argv = ["cmd", "/c", "start", "", str(target)]
    else:
        argv = ["xdg-open", str(target)]
    proc = await asyncio.create_subprocess_exec(*argv)
    await proc.wait()


# Path components hidden from /api/tree and /api/fs/inventory (parallels
# daemon._walk_tree). Kept here too so the inventory endpoint can re-use it.
_SKIP_DIRS = {
    ".git", ".workbench", "node_modules", ".venv", "venv",
    "__pycache__", "dist", "build", ".vite", ".cache",
    ".idea", ".vscode", ".pytest_cache",
}


_EXT_RE = re.compile(r"^[A-Za-z0-9]{1,8}$")


def _clean_ext(p: Path) -> str:
    """Pythons `Path.suffix` reports the last dotted segment, which for
    `foo.md.bak.20260421-223541` is `.20260421-223541` — useless as a
    file-type label. Treat as an extension only if it matches a short
    alphanumeric pattern; otherwise return "" (caller groups under
    "(no ext)").
    """
    if not p.suffix:
        return ""
    raw = p.suffix.lstrip(".").lower()
    return raw if _EXT_RE.match(raw) else ""


def inventory(workspace: Path) -> list[dict]:
    """Walk the workspace and return [{path, size, mtime, ext}] for every
    visible file. Mirrors the visibility rules of /api/tree (skips
    dotted dirs/files) so the DuckDB tab sees the same world as the
    Browser. Done in one pass to avoid N+1 HTTP round-trips for stat.
    """
    # Prune hidden + skip dirs in place (os.walk) so we don't descend
    # into .git / .venv / .curator / node_modules. rglob visited all of
    # them — 150k+ files on a CE workspace — before discarding by the
    # dotfile check, which is the bulk of a multi-second inventory.
    out: list[dict] = []
    ws = str(workspace)
    for root, dirnames, filenames in os.walk(workspace):
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".") and d not in _SKIP_DIRS
        ]
        for fn in filenames:
            if fn.startswith("."):
                continue
            full = os.path.join(root, fn)
            try:
                s = os.stat(full)
            except OSError:
                continue
            out.append({
                "path": os.path.relpath(full, ws),
                "size": s.st_size,
                "mtime": s.st_mtime,
                "ext": _clean_ext(Path(fn)),
            })
    out.sort(key=lambda d: d["path"])
    return out
