"""Atomic file writes for durable state.

A plain ``path.write_text(...)`` truncates the target to zero and then
streams the new bytes. If the process is killed (crash, ``kill -9`` of a
wedged daemon, power loss), the disk fills, or a cloud-sync service grabs
the file mid-write, the file is left truncated or empty — and for our
JSON registries that means the user loses their workspace list, tab
layout, pending proposals, etc.

The fix is the standard write-temp-then-rename dance: write the full
payload to a sibling temp file, ``fsync`` it, then ``os.replace`` it over
the target. ``os.replace`` is atomic on POSIX and Windows, so a reader
(or an interrupted writer) sees either the old file or the new one, never
a half-written one. The temp lives in the SAME directory as the target so
the rename stays on one filesystem (cross-device rename fails).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_text_atomic(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Atomically write ``text`` to ``path`` (parents must already exist,
    matching ``write_text`` semantics for our callers, which mkdir first)."""
    path = Path(path)
    directory = path.parent
    fd, tmp = tempfile.mkstemp(
        dir=str(directory), prefix=f".{path.name}.", suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        # Best-effort cleanup of the temp on any failure; never mask the
        # original error.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json_atomic(path: Path, obj: Any, *, indent: int = 2) -> None:
    """Atomically write ``obj`` as pretty JSON + trailing newline — the
    exact shape our state writers used with ``write_text(json.dumps(...))``."""
    write_text_atomic(path, json.dumps(obj, indent=indent) + "\n")
