"""Cross-tab selection layer.

A "selection" is the user's current focal item — initially a wiki
`page`, eventually also `file`, `rows` (DuckDB), `range` (Univer), etc.
Sidebar/Graph clicks write into it; tabs subscribe (via WS broadcast)
and re-render. Persisted to `<workspace>/.workbench/state/selection.json`
so it survives daemon restarts and reloads.

The shape is duck-typed (a free dict with `kind` + payload) — protocol
.py owns the canonical TypedDict declarations; this module just
serialises them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from . import atomicio


def _path(workspace: Path) -> Path:
    return workspace / ".workbench" / "state" / "selection.json"


def load(workspace: Path) -> dict[str, Any] | None:
    p = _path(workspace)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def save(workspace: Path, selection: dict[str, Any] | None) -> None:
    p = _path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    if selection is None:
        p.unlink(missing_ok=True)
        return
    atomicio.write_json_atomic(p, selection)
