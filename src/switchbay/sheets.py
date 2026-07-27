"""Per-workspace Univer workbook persistence.

MVP: one workbook per workspace, stored at
  <workspace>/.workbench/state/sheet.json

The blob is whatever Univer's `workbook.save()` produces — opaque to
us; we just round-trip it. Multiple workbooks per workspace land
later (path will become `.workbench/sheets/<id>.json`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from . import atomicio


def _path(workspace: Path) -> Path:
    return workspace / ".workbench" / "state" / "sheet.json"


def load(workspace: Path) -> dict[str, Any] | None:
    p = _path(workspace)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def save(workspace: Path, snapshot: dict[str, Any]) -> None:
    p = _path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(p, snapshot)
