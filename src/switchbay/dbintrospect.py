"""Daemon-side SQLite introspection.

DuckDB-WASM's sqlite extension can ATTACH a SQLite file but its catalog
scan loads `PRAGMA table_info` for every table — virtual tables backed
by missing extensions (sqlite-vec's `vec0`, FTS5's `fts5_*`, R*Tree,
etc.) crash the whole ATTACH. Stock Python `sqlite3` reads the
`sqlite_master` catalog without loading those modules, so we ask the
daemon for the table list instead. Counts are best-effort: virtual
tables that need missing modules report `null` rows.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


SYS_PREFIXES = ("sqlite_",)


def introspect(db_path: Path) -> dict[str, Any]:
    """Return {tables: [{name, type, rows}], note}. `rows` is None for
    tables we couldn't COUNT (typically virtual tables backed by an
    extension that's not loaded). Caller should treat that as "schema
    known, contents not introspectable from here."""
    if not db_path.is_file():
        raise FileNotFoundError(db_path)

    notes: list[str] = []
    out: list[dict[str, Any]] = []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)
    try:
        cur = conn.execute(
            "SELECT name, type FROM sqlite_master "
            "WHERE type IN ('table', 'view') ORDER BY name"
        )
        rows = cur.fetchall()
        for name, kind in rows:
            if any(name.startswith(p) for p in SYS_PREFIXES):
                continue
            entry: dict[str, Any] = {"name": name, "type": kind, "rows": None}
            try:
                # Quote the identifier to handle reserved words / hyphens.
                n = conn.execute(
                    f'SELECT COUNT(*) FROM "{name.replace(chr(34), chr(34) * 2)}"'
                ).fetchone()[0]
                entry["rows"] = int(n)
            except sqlite3.OperationalError as e:
                msg = str(e)
                # "no such module: vec0" / similar — record without
                # blocking the rest of the listing.
                entry["note"] = msg[:120]
                if "no such module" in msg and msg not in notes:
                    notes.append(msg)
            out.append(entry)
    finally:
        conn.close()

    note: str | None = None
    if notes:
        modules = sorted({n.split("module:")[-1].strip() for n in notes})
        note = (
            f"Some virtual tables need SQLite extensions not loaded by "
            f"the daemon ({', '.join(modules)}). Their schema is listed "
            f"but row counts are unavailable."
        )

    return {"tables": out, "note": note}


def run_query(db_path: Path, sql: str, max_rows: int = 1000) -> dict[str, Any]:
    """Execute `sql` read-only against `db_path` and return rows. Caps
    output at `max_rows`. Used as a fallback for DBs whose virtual
    tables DuckDB-WASM can't query."""
    if not db_path.is_file():
        raise FileNotFoundError(db_path)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = conn.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchmany(max_rows)
        truncated = len(rows) >= max_rows
        return {
            "columns": cols,
            "rows": [list(r) for r in rows],
            "truncated": truncated,
        }
    finally:
        conn.close()
