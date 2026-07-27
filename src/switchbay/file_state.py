"""Lazy external-edit detection — no watchdog, no polling.

We track every file the daemon has *touched* (read or written) in a
`file_state` table inside the workspace's conversations.db. On each
subsequent read of a tracked file, we stat it: if mtime+size match
the record, no event. If they drift AND the new content hash differs
from the old, we emit a `file_edit_external` rail event and update
the record.

This means we never see external edits that happened to files
switchbay hasn't touched yet — but those files are by definition not
in the user's view, so silence is fine. The first time switchbay
*does* touch them, we record their state; the *second* time we'll
catch any drift since.

Internal writes (page save, fileops.duplicate) bypass the detection
by calling `record_internal_write` immediately after the write, so
the next read sees a record matching the new state and stays silent.
External-edit events are clearly attributed via `last_owner`.

Hashing is sha256 over the whole file. We only hash when stat
indicates a change, so steady-state reads stay cheap (just a stat
call + an indexed lookup).
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

log = logging.getLogger("switchbay.file_state")


def _path(workspace: Path) -> Path:
    # Same DB as the conversations module — resolve through the shared
    # statedir helper so both always agree on its location (roams by
    # default; machine-local when `rail_history_local` is set).
    from . import app_settings, statedir

    return statedir.conversations_db(
        workspace, local=app_settings.get_rail_history_local()
    )


@contextmanager
def _connect(workspace: Path) -> Iterator[sqlite3.Connection]:
    p = _path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    # Shares conversations.db with the conversations module + the
    # daemon's write-serializer; wait for locks rather than erroring.
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        _ensure_schema(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS file_state (
            path           TEXT PRIMARY KEY,
            mtime          REAL NOT NULL,
            size           INTEGER NOT NULL,
            hash           TEXT,                 -- sha256 hex; NULL until first hash
            last_seen      REAL NOT NULL,        -- unix ts of last read/write
            last_seen_via  TEXT NOT NULL,        -- 'read' | 'write' | 'delete'
            last_owner     TEXT                  -- 'editor' | 'fileops' | 'external' | 'unknown'
        );
        """
    )


def _hash_file(p: Path) -> str | None:
    """sha256 hex digest of a file's contents. None on read error."""
    try:
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def get(workspace: Path, rel: str) -> dict[str, Any] | None:
    with _connect(workspace) as conn:
        row = conn.execute(
            "SELECT * FROM file_state WHERE path = ?", (rel,),
        ).fetchone()
    return dict(row) if row else None


def record_internal_write(
    workspace: Path,
    rel: str,
    *,
    owner: str = "editor",
) -> None:
    """Persist the post-write state of a file we just wrote ourselves.
    Hashes the new content so future reads know what 'unchanged' looks
    like. No-ops silently if the file vanished between write and call."""
    p = workspace / rel
    if not p.is_file():
        return
    try:
        st = p.stat()
    except OSError:
        return
    h = _hash_file(p)
    now = time.time()
    with _connect(workspace) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO file_state "
            "(path, mtime, size, hash, last_seen, last_seen_via, last_owner) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (rel, st.st_mtime, st.st_size, h, now, "write", owner),
        )


def check_external(
    workspace: Path, rel: str,
) -> dict[str, Any] | None:
    """Stat `rel` and compare to the last record. Returns a change dict
    (old_size, new_size, old_mtime, new_mtime, old_hash, new_hash) when
    the content actually differs, else None.

    First-time observations (no record yet) silently insert a record
    and return None — that's discovery, not change. mtime/size drift
    with identical content (a `touch` or no-op editor save) updates
    the record but doesn't fire an event."""
    p = workspace / rel
    if not p.is_file():
        return None
    try:
        st = p.stat()
    except OSError:
        return None
    now = time.time()
    record = get(workspace, rel)
    if record is None:
        # First touch — record without firing an event.
        h = _hash_file(p)
        with _connect(workspace) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO file_state "
                "(path, mtime, size, hash, last_seen, last_seen_via, last_owner) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (rel, st.st_mtime, st.st_size, h, now, "read", "unknown"),
            )
        return None
    if record["mtime"] == st.st_mtime and record["size"] == st.st_size:
        # Stat unchanged → content unchanged. Touch last_seen.
        with _connect(workspace) as conn:
            conn.execute(
                "UPDATE file_state SET last_seen = ?, last_seen_via = 'read' WHERE path = ?",
                (now, rel),
            )
        return None
    # Stat differs — hash to see if content also did.
    new_hash = _hash_file(p)
    old_hash = record.get("hash")
    if new_hash and old_hash and new_hash == old_hash:
        # Same bytes, just touched. Update stat record.
        with _connect(workspace) as conn:
            conn.execute(
                "UPDATE file_state SET mtime = ?, size = ?, last_seen = ?, "
                "last_seen_via = 'read' WHERE path = ?",
                (st.st_mtime, st.st_size, now, rel),
            )
        return None
    # Real external change.
    change = {
        "old_size": record["size"],
        "new_size": st.st_size,
        "old_mtime": record["mtime"],
        "new_mtime": st.st_mtime,
        "old_hash": old_hash,
        "new_hash": new_hash,
    }
    with _connect(workspace) as conn:
        conn.execute(
            "UPDATE file_state SET mtime = ?, size = ?, hash = ?, "
            "last_seen = ?, last_seen_via = 'read', last_owner = 'external' "
            "WHERE path = ?",
            (st.st_mtime, st.st_size, new_hash, now, rel),
        )
    return change


def delete_record(workspace: Path, rel: str) -> None:
    with _connect(workspace) as conn:
        conn.execute("DELETE FROM file_state WHERE path = ?", (rel,))


def stats(workspace: Path) -> dict[str, int]:
    """For diagnostics — counts by owner."""
    with _connect(workspace) as conn:
        rows = conn.execute(
            "SELECT last_owner, COUNT(*) AS n FROM file_state GROUP BY last_owner"
        ).fetchall()
    return {(r["last_owner"] or "unknown"): r["n"] for r in rows}
