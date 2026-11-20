"""Append-only audit log for mounts, captures, and refusals.

Records live under the machine-local state root. They store ids and
reasons, not page bodies or source payloads.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .. import statedir


def _path(workspace: Path) -> Path:
    digest = hashlib.sha256(str(workspace.resolve()).encode("utf-8")).hexdigest()[:16]
    return statedir.state_root() / "audit" / digest / "audit.jsonl"


def record(workspace: Path, event: str, **fields: Any) -> dict[str, Any]:
    row = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": event,
        "workspace": str(workspace.resolve()),
    }
    for key, value in fields.items():
        if value is not None:
            row[key] = value
    path = _path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
    return row


def read(workspace: Path) -> list[dict[str, Any]]:
    path = _path(workspace)
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows
