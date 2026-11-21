"""Owner-only files for caches, captures, and tokens.

These live under the per-OS-user state root. The directories are
mode 0700 and the files are mode 0600. Nothing here is encrypted.
"""

from __future__ import annotations

import os
from pathlib import Path


def owner_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path


def owner_write(path: Path, text: str) -> None:
    owner_dir(path.parent)
    path.write_text(text, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def is_private(path: Path) -> bool:
    """True when other users have no permission bits, on POSIX."""
    if os.name == "nt":
        return True
    try:
        mode = path.stat().st_mode
    except OSError:
        return False
    return (mode & 0o077) == 0


EXPORT_SKIP_PARTS = frozenset({
    ".workbench", ".grok", ".git", "captures", "graph-cache", "graph-tokens",
    "audit", "mounts",
})


def export_excluded(rel: str) -> bool:
    """True when a workspace-relative path must not leave in an export."""
    parts = [part for part in rel.replace("\\", "/").split("/") if part]
    return any(part in EXPORT_SKIP_PARTS for part in parts)
