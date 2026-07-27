"""Per-workspace SQL starter pills for the Table (DuckDB-WASM) tab.

A starter is just `{label, sql}`. The user edits them via the "Edit
starters" dialog in the tab; we round-trip the list through this
module so they survive reloads and are easy to back up / commit.

File: `<workspace>/.workbench/state/duckdb-starters.json`
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from . import atomicio


DEFAULTS: list[dict[str, str]] = [
    {
        "label": "files (top 20 biggest)",
        "sql": "SELECT path, size, ext\nFROM files\nORDER BY size DESC\nLIMIT 20;",
    },
    {
        "label": "pages by type",
        "sql": (
            "SELECT type, COUNT(*) AS n, AVG(degree)::INT AS avg_degree\n"
            "FROM pages\nGROUP BY type\nORDER BY n DESC;"
        ),
    },
    {
        "label": "most-connected pages",
        "sql": "SELECT title, type, degree\nFROM pages\nORDER BY degree DESC\nLIMIT 20;",
    },
    {
        "label": "files modified this week",
        # `now()` is TIMESTAMPTZ; cast to plain TIMESTAMP so subtraction
        # against INTERVAL works in older DuckDB-WASM versions.
        "sql": (
            "SELECT path, size, mtime\nFROM files\n"
            "WHERE mtime > now()::TIMESTAMP - INTERVAL 7 DAY\n"
            "ORDER BY mtime DESC;"
        ),
    },
    {
        "label": "read a workspace CSV",
        "sql": (
            "-- replace the path with one that actually exists in your workspace.\n"
            "-- Easiest way: find the file in the BROWSER's FILES tree on the\n"
            "-- left, right-click → Copy path, paste it after `path=` below.\n"
            "-- DuckDB-WASM streams it via the daemon's /api/fs/raw endpoint.\n"
            "SELECT * FROM read_csv_auto('/api/fs/raw?path=vault/raw/your-file.csv') LIMIT 50;"
        ),
    },
]


def _path(workspace: Path) -> Path:
    return workspace / ".workbench" / "state" / "duckdb-starters.json"


def load(workspace: Path) -> list[dict[str, Any]]:
    p = _path(workspace)
    if not p.is_file():
        return [dict(s) for s in DEFAULTS]
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [dict(s) for s in DEFAULTS]
    if not isinstance(data, list):
        return [dict(s) for s in DEFAULTS]
    out: list[dict[str, Any]] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("label", "")).strip()
        sql = str(entry.get("sql", "")).strip()
        if label and sql:
            out.append({"label": label, "sql": sql})
    return out or [dict(s) for s in DEFAULTS]


def save(workspace: Path, starters: list[dict[str, Any]]) -> None:
    cleaned: list[dict[str, str]] = []
    for entry in starters:
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("label", "")).strip()
        sql = str(entry.get("sql", "")).strip()
        if label and sql:
            cleaned.append({"label": label, "sql": sql})
    p = _path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(p, cleaned)
