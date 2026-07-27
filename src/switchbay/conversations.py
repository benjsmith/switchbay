"""Per-workspace rail event log.

Every decision, action, or observation that happens inside a workspace
lands here as a row in `events`. Today that means rail chat (user
prose, assistant prose, tool_use, tool_result) — but the schema is
deliberately broader so off-rail sources (file edits, exec/sql/slash
commands, CE curation runs, mode/workspace changes) can stream into
the same timeline. Storage path:
`<workspace>/.workbench/state/conversations.db`.

Tiering (see log.md):
  1. Working set — last N chat events sent verbatim. THIS MODULE.
  2. Block summaries — tried (438ba57) and dropped (9fc6dcc) in
     favor of stronger system prompt + on-demand recall.
  3. Vector recall — sqlite-vec + a pluggable local embedder
     (384-dim): fastembed/ONNX (default, no PyTorch) or
     sentence-transformers/PyTorch, auto-selected by what's installed.
     Optional: if neither backend nor sqlite-vec is present, semantic
     queries return [] and FTS is the only path. The vector *space* is
     labelled per row so a backend/model switch triggers a clean
     re-embed; the sentence-transformers/MiniLM path stays byte-exact
     with a curiosity-engine vault index.

A "thread" (Workspace → Thread → Run → Turn; see charter 2026-07-03)
is the durable, switchable unit of work — what this module called a
"conversation" before the AG-UI alignment. POST /api/llm/reset opens
a new one, as does workspace switch (which gets its own DB file, so
the new thread always starts empty there). A thread has a `kind`:
`structured-agent` (AG-UI event stream, transcript render) or
`interactive-pty` (PTY via terminals.py, xterm render).

NAMING NOTE — deliberately unrenamed: the module file stays
`conversations.py` and the on-disk DB stays `conversations.db`
(renaming the file would orphan every user's history / churn every
import; see work-plan Step 0 trap 4). Only the table (`threads`),
column (`events.thread_id`) and code identifiers use the new word.
`_migrate_conv_to_thread` rolls existing DBs forward in place.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import json
import logging
import os
import shutil
import sqlite3
import re
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

log = logging.getLogger("switchbay.conversations")

WORKING_SET_TURNS = 20
RECALL_SNIPPET_CHARS = 240

THREAD_KIND_DEFAULT = "structured-agent"


def _path(workspace: Path) -> Path:
    # Rail history roams by default (lives in the synced workspace); the
    # `rail_history_local` setting moves it to the machine-local state
    # root. See statedir.py for the cloud-sync rationale.
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
    # Multiple connections touch this DB within the one daemon process
    # (the write-serializer worker + offloaded reads like working_set /
    # list_events, plus file_state). Wait for a lock instead of erroring
    # with "database is locked". We deliberately do NOT switch to WAL —
    # its -wal/-shm sidecars sync independently and risk corruption when
    # the DB roams on a cloud-sync service (see statedir.py).
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        _ensure_schema(conn, p)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_schema(conn: sqlite3.Connection, db_path: Path) -> None:
    # The conversations→threads migration MUST run before the CREATE
    # block below — otherwise a fresh empty `threads` table would block
    # the rename on existing DBs (work-plan Step 0 trap 2).
    _migrate_conv_to_thread(conn, db_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS threads (
            id           TEXT PRIMARY KEY,
            created_at   REAL NOT NULL,
            updated_at   REAL NOT NULL,
            title        TEXT,
            summary      TEXT,
            kind         TEXT NOT NULL DEFAULT 'structured-agent',
                                                    -- 'structured-agent' |
                                                    -- 'interactive-pty'
            archived_at  REAL,                      -- soft delete: hidden from
                                                    -- the switcher, events stay
                                                    -- searchable (rail philosophy)
            project      TEXT                       -- D8 binding: captures in this
                                                    -- thread inherit the project.
                                                    -- NULL = workspace-level.
        );
        CREATE TABLE IF NOT EXISTS events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id       TEXT NOT NULL REFERENCES threads(id),
            created_at      REAL NOT NULL,
            kind            TEXT NOT NULL,         -- user/assistant/tool_use/tool_result/
                                                    -- exec/sql/slash/file_edit_internal/
                                                    -- file_edit_external/curation/…
            source          TEXT NOT NULL DEFAULT 'rail',
            actor           TEXT,                  -- user/assistant/system/<tool>
            summary         TEXT NOT NULL,         -- short text for FTS + working set
            payload_json    TEXT,                  -- structured details (JSON)
            ref_id          TEXT,                  -- groups related events
                                                    -- (tool_use ↔ tool_result, edit batch)
            block_summary   TEXT,                  -- tier-2 fill-in, NULL today
            needs_embedding INTEGER NOT NULL DEFAULT 1,
                                                    -- tier-3 drain flag: 1 = pending
                                                    -- vector embedding, 0 = embedded
            run_id          TEXT                   -- groups events from a single
                                                    -- LLM dispatch (the agent
                                                    -- dashboard's transcript
                                                    -- expander filters by this)
        );
        CREATE INDEX IF NOT EXISTS events_thread_idx ON events(thread_id, id);
        CREATE INDEX IF NOT EXISTS events_kind_idx ON events(thread_id, kind, id);
        CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
            summary, kind, thread_id UNINDEXED, event_id UNINDEXED,
            tokenize='unicode61 remove_diacritics 2'
        );
        """
    )
    _migrate_legacy(conn)
    _migrate_columns(conn)
    # Indexes that reference columns added by `_migrate_columns` MUST
    # run AFTER the migration, not inside the executescript above —
    # SQLite aborts an executescript on first failure and the next
    # connect would never reach the column-add. Was the cause of
    # `OperationalError: no such column: needs_embedding` on DBs
    # that predated the column.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS events_pending_embed_idx "
        "ON events(needs_embedding) WHERE needs_embedding = 1"
    )


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def _col_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def _conv_to_thread_pending(conn: sqlite3.Connection) -> bool:
    """True if any piece of the pre-thread schema is still present."""
    tables = _table_names(conn)
    if "conversations" in tables:
        return True
    if "events" in tables and "conversation_id" in _col_names(conn, "events"):
        return True
    if "events_fts" in tables and "conversation_id" in _col_names(conn, "events_fts"):
        return True
    return False


def _migrate_conv_to_thread(conn: sqlite3.Connection, db_path: Path) -> None:
    """One-shot in-place migration: `conversations`→`threads` table,
    `events.conversation_id`→`thread_id`, and `events_fts` rebuilt with
    the new column name (FTS5 can't rename a column — DROP + recreate +
    reindex from `events`). Idempotent: detection is by table/column
    presence, so a migrated (or fresh) DB is a no-op on every connect.

    Runs BEFORE the CREATE-IF-NOT-EXISTS block in `_ensure_schema`.
    On an *ancient* pre-`events` DB (`turns` schema) only the
    `conversations` table exists — the column/FTS branches skip and
    `_migrate_legacy` later copies `turns` into the new-name schema.
    """
    if not _conv_to_thread_pending(conn):
        return
    # File-level backup, once, before the first rename ever touches the
    # DB. Pure insurance for the user's rail history — a failed copy
    # logs and proceeds rather than blocking the migration.
    bak = db_path.with_name(db_path.name + ".pre-thread.bak")
    if db_path.exists() and not bak.exists():
        try:
            shutil.copy2(db_path, bak)
        except OSError as e:
            log.warning("pre-thread backup of %s failed: %s", db_path, e)
    # BEGIN IMMEDIATE serialises concurrent connections racing this
    # migration (write-serializer vs offloaded reads): the loser waits
    # on busy_timeout, re-checks, and no-ops.
    conn.execute("BEGIN IMMEDIATE")
    try:
        if not _conv_to_thread_pending(conn):
            conn.execute("COMMIT")
            return
        log.info("migrating conversations→threads schema in %s", db_path)
        tables = _table_names(conn)
        if "conversations" in tables:
            if "threads" not in tables:
                conn.execute("ALTER TABLE conversations RENAME TO threads")
            else:
                # Interrupted half-migration left both — fold the old
                # rows in (id-keyed, so replays are safe) and drop.
                conn.execute(
                    "INSERT OR IGNORE INTO threads "
                    "(id, created_at, updated_at, title, summary) "
                    "SELECT id, created_at, updated_at, title, summary "
                    "FROM conversations"
                )
                conn.execute("DROP TABLE conversations")
        if "events" in tables and "conversation_id" in _col_names(conn, "events"):
            conn.execute(
                "ALTER TABLE events RENAME COLUMN conversation_id TO thread_id"
            )
            # The rename auto-rewrites index definitions but keeps the
            # old index name; drop it so the CREATE block's
            # `events_thread_idx` doesn't leave a duplicate behind.
            conn.execute("DROP INDEX IF EXISTS events_conv_idx")
        if "events_fts" in tables and "conversation_id" in _col_names(
            conn, "events_fts"
        ):
            conn.execute("DROP TABLE events_fts")
            conn.execute(
                "CREATE VIRTUAL TABLE events_fts USING fts5("
                "summary, kind, thread_id UNINDEXED, event_id UNINDEXED, "
                "tokenize='unicode61 remove_diacritics 2')"
            )
            if "events" in tables:
                conn.execute(
                    "INSERT INTO events_fts (event_id, thread_id, summary, kind) "
                    "SELECT id, thread_id, summary, kind FROM events"
                )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def _migrate_columns(conn: sqlite3.Connection) -> None:
    """Roll forward additive column changes on existing DBs. Each
    branch is idempotent and gated on `PRAGMA table_info` so this is
    safe to call on every connect."""
    cols = _col_names(conn, "events")
    if "needs_embedding" not in cols:
        # Existing rows pre-tier-3: mark them all as pending embedding
        # (default 1) so the next drain pass back-fills them.
        conn.execute(
            "ALTER TABLE events ADD COLUMN needs_embedding INTEGER "
            "NOT NULL DEFAULT 1"
        )
    if "run_id" not in cols:
        # Pre-existing events from before per-run grouping landed —
        # NULL is fine; the dashboard expander filters with `run_id =`
        # so unrelated rows are simply not returned.
        conn.execute("ALTER TABLE events ADD COLUMN run_id TEXT")
    tcols = _col_names(conn, "threads")
    if "kind" not in tcols:
        # Threads renamed from `conversations` predate the kind column;
        # everything before Foundation B is a structured-agent thread.
        conn.execute(
            "ALTER TABLE threads ADD COLUMN kind TEXT "
            "NOT NULL DEFAULT 'structured-agent'"
        )
    if "archived_at" not in tcols:
        # Session 18: thread deletion = archive (hide from the
        # switcher, keep the events searchable). NULL = live.
        conn.execute("ALTER TABLE threads ADD COLUMN archived_at REAL")
    if "project" not in tcols:
        # Session 19 (D8): thread→project binding. NULL = unbound
        # (captures land at workspace level).
        conn.execute("ALTER TABLE threads ADD COLUMN project TEXT")


def _migrate_legacy(conn: sqlite3.Connection) -> None:
    """One-shot migration from the old `turns` schema (chat-only).
    Idempotent: detects the old table, copies rows into `events`, drops
    `turns` + `turns_fts`. Newly-created DBs skip this entirely.

    NOTE: the *source* column here is the ancient schema's
    `turns.conversation_id` — that name must stay even though the
    *target* is now `events.thread_id` (work-plan Step 0 trap 1)."""
    has_old = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='turns'"
    ).fetchone()
    if not has_old:
        return
    log.info("migrating legacy `turns` table → `events`")
    # role='tool' rows in the old schema were always tool_result-shaped
    # (we never stored tool_use blocks). Nothing else needs translation.
    conn.execute(
        """
        INSERT INTO events
            (thread_id, created_at, kind, source, actor, summary,
             block_summary)
        SELECT
            conversation_id,
            created_at,
            CASE role WHEN 'tool' THEN 'tool_result' ELSE role END,
            'rail',
            COALESCE(tool_name, role),
            content,
            block_summary
        FROM turns
        ORDER BY id
        """
    )
    conn.execute(
        """
        INSERT INTO events_fts (event_id, thread_id, summary, kind)
        SELECT id, thread_id, summary, kind FROM events
        """
    )
    conn.executescript("DROP TABLE turns_fts; DROP TABLE turns;")


# Placeholder titles for freshly-created chat threads ("New thread 3").
# They make a brand-new thread visible in the switcher immediately and
# are REPLACEABLE: the first-user-turn excerpt backfill and the LLM
# auto-titler both treat them like an unset title.
_PLACEHOLDER_RE = re.compile(r"New thread \d+")


def is_placeholder_title(title: str | None) -> bool:
    return bool(title) and _PLACEHOLDER_RE.fullmatch(title) is not None


def next_new_thread_title(workspace: Path) -> str:
    """The next free "New thread N" placeholder — numbered against the
    placeholders still present (auto-titled threads free their number,
    which is fine: numbers only disambiguate concurrent blanks)."""
    with _connect(workspace) as conn:
        rows = conn.execute(
            "SELECT title FROM threads WHERE title LIKE 'New thread %'"
        ).fetchall()
    highest = 0
    for r in rows:
        if is_placeholder_title(r["title"]):
            highest = max(highest, int(r["title"].rsplit(" ", 1)[1]))
    return f"New thread {highest + 1}"


def new_thread(
    workspace: Path,
    title: str | None = None,
    kind: str = THREAD_KIND_DEFAULT,
) -> str:
    tid = uuid.uuid4().hex
    now = time.time()
    with _connect(workspace) as conn:
        conn.execute(
            "INSERT INTO threads (id, created_at, updated_at, title, kind) "
            "VALUES (?, ?, ?, ?, ?)",
            (tid, now, now, title, kind),
        )
    return tid


def append_event(
    workspace: Path,
    thread_id: str,
    kind: str,
    summary: str,
    *,
    source: str = "rail",
    actor: str | None = None,
    payload: Any = None,
    ref_id: str | None = None,
    run_id: str | None = None,
) -> int:
    """Append one row to the rail log. `summary` should be a compact
    line suitable for the FTS index and for the working-set window;
    bulky details (full diffs, full tool output, etc.) belong in
    `payload`, which is JSON-encoded and not loaded into chat context."""
    if not kind:
        raise ValueError("kind is required")
    if summary is None:
        summary = ""
    payload_json = json.dumps(payload) if payload is not None else None
    if actor is None:
        # Sensible defaults for chat events; off-rail callers should
        # pass actor explicitly.
        if kind in ("user", "assistant"):
            actor = kind
        elif kind == "system":
            actor = "system"
    now = time.time()
    with _connect(workspace) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO threads (id, created_at, updated_at) VALUES (?, ?, ?)",
            (thread_id, now, now),
        )
        cur = conn.execute(
            "INSERT INTO events "
            "(thread_id, created_at, kind, source, actor, summary, "
            " payload_json, ref_id, run_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (thread_id, now, kind, source, actor, summary,
             payload_json, ref_id, run_id),
        )
        event_id = cur.lastrowid
        conn.execute(
            "INSERT INTO events_fts (event_id, thread_id, summary, kind) VALUES (?, ?, ?, ?)",
            (event_id, thread_id, summary, kind),
        )
        conn.execute(
            "UPDATE threads SET updated_at = ? WHERE id = ?",
            (now, thread_id),
        )
        if kind == "user":
            # Backfill an untitled (or placeholder-titled) thread's
            # title from its first user prose — every dispatch path
            # (rail, rules, fan-out, headless) gets a usable switcher
            # label for free. GLOB keeps real "New thread ..." user
            # titles safe (only "New thread <digits>" matches).
            title = " ".join(summary.split())[:80]
            if title:
                conn.execute(
                    "UPDATE threads SET title = ? "
                    "WHERE id = ? AND (title IS NULL "
                    "  OR title GLOB 'New thread [0-9]*')",
                    (title, thread_id),
                )
    return int(event_id or 0)


def thread_exists(workspace: Path, thread_id: str) -> bool:
    with _connect(workspace) as conn:
        row = conn.execute(
            "SELECT 1 FROM threads WHERE id = ?", (thread_id,)
        ).fetchone()
    return row is not None


def thread_kind(workspace: Path, thread_id: str) -> str | None:
    """The thread's kind ('structured-agent' | 'interactive-pty'), or
    None when the thread doesn't exist — doubles as an existence
    check for handlers that need both."""
    with _connect(workspace) as conn:
        row = conn.execute(
            "SELECT kind FROM threads WHERE id = ?", (thread_id,)
        ).fetchone()
    return row["kind"] if row else None


def events_since(
    workspace: Path, since_ts: float, limit: int = 500,
) -> list[dict[str, Any]]:
    """Events newer than `since_ts` across every thread — the
    away-digest's feed. Ascending, capped."""
    with _connect(workspace) as conn:
        rows = conn.execute(
            "SELECT id, thread_id, created_at, kind, source, actor, summary "
            "FROM events WHERE created_at > ? ORDER BY id ASC LIMIT ?",
            (since_ts, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def thread_title(workspace: Path, thread_id: str) -> str | None:
    """The thread's display title, or None when unset / unknown."""
    with _connect(workspace) as conn:
        row = conn.execute(
            "SELECT title FROM threads WHERE id = ?", (thread_id,)
        ).fetchone()
    return row["title"] if row else None


def thread_project(workspace: Path, thread_id: str) -> str | None:
    """The thread's bound project name (D8), or None when unbound /
    unknown. Captures in a bound thread inherit this project."""
    with _connect(workspace) as conn:
        row = conn.execute(
            "SELECT project FROM threads WHERE id = ?", (thread_id,)
        ).fetchone()
    return row["project"] if row else None


def set_project(workspace: Path, thread_id: str, project: str | None) -> bool:
    """Bind (or unbind, project=None) a thread to a project. Returns
    False for an unknown thread. Validation against the CE project
    registry is the caller's job — this layer only stores the name."""
    with _connect(workspace) as conn:
        cur = conn.execute(
            "UPDATE threads SET project = ? WHERE id = ?",
            (project, thread_id),
        )
    return bool(cur.rowcount)


def list_threads(
    workspace: Path, *, limit: int = 100, include_empty: bool = False,
) -> list[dict[str, Any]]:
    """Threads for the switcher, most-recently-active first. By default
    threads with no chat events AND no title are hidden — /llm-reset +
    workspace switches lazily create system-only threads (the "daemon
    started" breadcrumbs land somewhere), and those would flood the
    picker with untitled rows. `interactive-pty` threads are exempt:
    they never have chat events, but each one is a deliberate user
    action (a shell) that must stay reachable — an invisible pty thread
    can't be focused, so its shell can't even be exited."""
    with _connect(workspace) as conn:
        rows = conn.execute(
            "SELECT t.id, t.title, t.kind, t.project, t.created_at, t.updated_at, "
            "  (SELECT COUNT(*) FROM events e WHERE e.thread_id = t.id "
            "     AND e.kind IN ('user', 'assistant')) AS chat_count, "
            "  (SELECT e2.summary FROM events e2 WHERE e2.thread_id = t.id "
            "     AND e2.kind IN ('user', 'assistant') "
            "     ORDER BY e2.id DESC LIMIT 1) AS last_summary "
            "FROM threads t WHERE t.archived_at IS NULL "
            "ORDER BY t.updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        if (
            not include_empty and not r["chat_count"] and not r["title"]
            and r["kind"] != "interactive-pty"
        ):
            continue
        out.append({
            "thread_id": r["id"],
            "title": r["title"],
            "kind": r["kind"],
            "project": r["project"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "chat_count": int(r["chat_count"]),
            "last_summary": (r["last_summary"] or "")[:120],
        })
    return out


def first_user_summary(workspace: Path, thread_id: str) -> str | None:
    """The first user turn's summary — the auto-titler's input, and the
    reference for deciding whether the current title was user-set."""
    with _connect(workspace) as conn:
        row = conn.execute(
            "SELECT summary FROM events WHERE thread_id = ? "
            "AND kind = 'user' ORDER BY id LIMIT 1",
            (thread_id,),
        ).fetchone()
    return row["summary"] if row else None


def set_auto_title(workspace: Path, thread_id: str, title: str) -> bool:
    """Set an LLM-authored title, but never clobber a user-chosen one.
    A title counts as auto when it is NULL, a "New thread N"
    placeholder, or exactly the deterministic excerpt backfill of the
    first user turn (see append_event) — those checks are how we avoid
    a schema column for title provenance. Returns True when the title
    was applied."""
    title = " ".join(title.split()).strip()
    if not title:
        return False
    with _connect(workspace) as conn:
        row = conn.execute(
            "SELECT title FROM threads WHERE id = ?", (thread_id,)
        ).fetchone()
        if row is None:
            return False
        current = row["title"]
        if current is not None and not is_placeholder_title(current):
            first = conn.execute(
                "SELECT summary FROM events WHERE thread_id = ? "
                "AND kind = 'user' ORDER BY id LIMIT 1",
                (thread_id,),
            ).fetchone()
            backfill = " ".join(((first["summary"] if first else "") or "").split())[:80]
            if current != backfill:
                return False  # user-set (or already LLM-titled)
        conn.execute(
            "UPDATE threads SET title = ? WHERE id = ?",
            (title[:80], thread_id),
        )
    return True


def archive_thread(workspace: Path, thread_id: str) -> bool:
    """Soft-delete: hide the thread from the switcher. Its events stay
    in the log, searchable via recall_rail — per the rail philosophy,
    deleting a thread should not delete the memory. Hard removal is
    the purge path below. Returns False for an unknown thread."""
    with _connect(workspace) as conn:
        cur = conn.execute(
            "UPDATE threads SET archived_at = ? "
            "WHERE id = ? AND archived_at IS NULL",
            (time.time(), thread_id),
        )
        if cur.rowcount:
            return True
        row = conn.execute(
            "SELECT 1 FROM threads WHERE id = ?", (thread_id,)
        ).fetchone()
    return row is not None  # already archived counts as success


def purge_candidates(workspace: Path, *, before: float | None = None) -> list[dict[str, Any]]:
    """Every thread (live + archived) as purge-preview material:
    id, title, kind, archived flag, time bounds, event count, and a
    first-user-summary hook for the topic matcher. `before` filters to
    threads whose LAST activity predates the cutoff — a thread active
    since the cutoff is never a candidate."""
    with _connect(workspace) as conn:
        rows = conn.execute(
            "SELECT t.id, t.title, t.kind, t.created_at, t.updated_at, "
            "  t.archived_at, "
            "  (SELECT COUNT(*) FROM events e WHERE e.thread_id = t.id) AS event_count, "
            "  (SELECT e2.summary FROM events e2 WHERE e2.thread_id = t.id "
            "     AND e2.kind = 'user' ORDER BY e2.id LIMIT 1) AS first_user, "
            "  (SELECT e3.summary FROM events e3 WHERE e3.thread_id = t.id "
            "     ORDER BY e3.id DESC LIMIT 1) AS last_summary "
            "FROM threads t ORDER BY t.updated_at DESC",
        ).fetchall()
    out = []
    for r in rows:
        if before is not None and r["updated_at"] >= before:
            continue
        out.append({
            "thread_id": r["id"],
            "title": r["title"],
            "kind": r["kind"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "archived": r["archived_at"] is not None,
            "event_count": int(r["event_count"]),
            "first_user": (r["first_user"] or "")[:200],
            "last_summary": (r["last_summary"] or "")[:200],
        })
    return out


def purge_threads(workspace: Path, thread_ids: list[str]) -> dict[str, int]:
    """HARD-delete threads and every trace of their events: rows, FTS
    entries, and vector embeddings. This is the explicit opt-out from
    the keep-the-log default — rare, destructive, driven from the
    Settings purge panel only. Returns counts for the confirmation."""
    if not thread_ids:
        return {"threads": 0, "events": 0}
    placeholders = ",".join("?" for _ in thread_ids)
    with _connect(workspace) as conn:
        event_ids = [
            r["id"] for r in conn.execute(
                f"SELECT id FROM events WHERE thread_id IN ({placeholders})",
                thread_ids,
            )
        ]
        if event_ids:
            ev_ph = ",".join("?" for _ in event_ids)
            conn.execute(
                f"DELETE FROM events_fts WHERE event_id IN ({ev_ph})", event_ids,
            )
            # Vector rows only exist when sqlite-vec is installed; the
            # meta table maps event → vec rowid.
            if _ensure_vec_schema(conn):
                vec_rowids = [
                    r["vec_rowid"] for r in conn.execute(
                        f"SELECT vec_rowid FROM event_embeddings_meta "
                        f"WHERE event_id IN ({ev_ph})", event_ids,
                    )
                ]
                if vec_rowids:
                    vr_ph = ",".join("?" for _ in vec_rowids)
                    conn.execute(
                        f"DELETE FROM event_embeddings WHERE rowid IN ({vr_ph})",
                        vec_rowids,
                    )
                    conn.execute(
                        f"DELETE FROM event_embeddings_meta "
                        f"WHERE event_id IN ({ev_ph})", event_ids,
                    )
            conn.execute(
                f"DELETE FROM events WHERE id IN ({ev_ph})", event_ids,
            )
        cur = conn.execute(
            f"DELETE FROM threads WHERE id IN ({placeholders})", thread_ids,
        )
    return {"threads": cur.rowcount, "events": len(event_ids)}


def chat_event_count(workspace: Path, thread_id: str) -> int:
    """How many user+assistant events exist for this thread.
    Useful for the rail UI's load-older affordance and for any future
    "is this getting long?" hints to the agent."""
    with _connect(workspace) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM events "
            "WHERE thread_id = ? AND kind IN ('user', 'assistant')",
            (thread_id,),
        ).fetchone()
    return int(row["n"]) if row else 0


def working_set(
    workspace: Path,
    thread_id: str,
    *,
    limit: int = WORKING_SET_TURNS,
) -> list[dict[str, Any]]:
    """Return the last `limit` chat-shaped events as a chronological
    list of {role, content} dicts — the format providers consume.

    Today only kind in (user, assistant) flows back into the working
    set. tool_use / tool_result events are persisted for recall but
    the in-memory agent loop already maintains them across turns; we
    don't double-feed. Off-rail event kinds (file_edit, exec, sql,
    curation, …) are *not* injected here — they're surfaced to the
    agent via recall_rail when the user references them. This keeps
    token cost bounded and predictable."""
    with _connect(workspace) as conn:
        rows = conn.execute(
            "SELECT kind, summary FROM events "
            "WHERE thread_id = ? AND kind IN ('user', 'assistant') "
            "ORDER BY id DESC LIMIT ?",
            (thread_id, limit),
        ).fetchall()
    rows.reverse()
    return [{"role": r["kind"], "content": r["summary"]} for r in rows]


# ── Tier-3: semantic recall via sqlite-vec ───────────────────────────


# Pluggable local embedder. Two backends, auto-selected by what's
# installed (see `_load_embedder`):
#   · fastembed (ONNX, no PyTorch — the light default). Model
#     BAAI/bge-small-en-v1.5: 384-dim, stronger retrieval than MiniLM at
#     the same size; overridable via SY_EMBED_MODEL.
#   · sentence-transformers (PyTorch). Model all-MiniLM-L6-v2, 384-dim —
#     byte-exact with a curiosity-engine vault index.
# BOTH emit L2-normalised 384-dim vectors, so the vec0 schema and blob
# layout are identical; only the vector *space* differs, which is why
# `event_embeddings_meta.model` labels each vector and a backend/model
# switch triggers a clean re-embed (`_reconcile_embed_model`).
_FASTEMBED_MODEL = os.environ.get("SY_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
_ST_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_DIM = 384

# Opt-in VENDOR embedding backends (app_settings.embedding_backend). Each
# requests EMBED_DIM output dimensions so the vec0 schema is unchanged,
# and reuses the provider's configured API key. Text is sent to the
# vendor — the local-privacy trade the user explicitly opts into. Pure
# stdlib (urllib), so this path needs NO local ML deps at all.
_VENDOR_EMBED: dict[str, dict[str, Any]] = {
    "openai": {
        "provider": "openai",
        "model": "text-embedding-3-small",
        "url": "https://api.openai.com/v1/embeddings",
    },
    "gemini": {
        "provider": "gemini",
        "model": "text-embedding-004",
        "url": ("https://generativelanguage.googleapis.com/v1beta/"
                "models/text-embedding-004:batchEmbedContents"),
    },
}


def _vendor_key(provider: str) -> str | None:
    from . import secrets
    key = secrets.get(provider)
    if key:
        return key
    envs = {
        "openai": ("OPENAI_API_KEY",),
        "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    }.get(provider, ())
    for e in envs:
        if os.environ.get(e):
            return os.environ[e]
    return None


def _l2norm(v: list[float]) -> list[float]:
    import math
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _vendor_embed(backend: str, texts: list[str]) -> list[list[float]]:
    """Synchronous vendor embeddings call (runs in the embed executor /
    to_thread, NEVER on the event loop). Requests EMBED_DIM dims and L2-
    normalises so the results drop into the existing 384-dim vec0 schema.
    Pure stdlib — no numpy/torch/onnx needed."""
    import json as _json
    import urllib.request

    cfg = _VENDOR_EMBED[backend]
    key = _vendor_key(cfg["provider"])
    if not key:
        raise RuntimeError(f"no API key for embedding backend {backend!r}")

    if backend == "openai":
        body = {"model": cfg["model"], "input": texts, "dimensions": EMBED_DIM}
        req = urllib.request.Request(
            cfg["url"], data=_json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            data = _json.loads(r.read())
        raw = [d["embedding"] for d in data["data"]]
    elif backend == "gemini":
        body = {"requests": [
            {"model": f"models/{cfg['model']}",
             "content": {"parts": [{"text": t}]},
             "outputDimensionality": EMBED_DIM} for t in texts]}
        req = urllib.request.Request(
            cfg["url"], data=_json.dumps(body).encode(),
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            data = _json.loads(r.read())
        raw = [e["values"] for e in data["embeddings"]]
    else:  # pragma: no cover — guarded by _load_embedder
        raise RuntimeError(f"unknown vendor backend {backend!r}")

    # Reduced-dim OpenAI + truncated Gemini vectors aren't unit-length.
    return [_l2norm([float(x) for x in v]) for v in raw]

_embedder: Any = None  # singleton; False = tried-and-missing
# Dedicated single-thread executor for embedding work (model load +
# encode). Kept OFF asyncio's shared default thread pool so the
# first-run SentenceTransformer download/load (~80 MB, tens of seconds)
# can't starve request-handler offloads. That head-of-line blocking was
# the real cause of the Table tab hanging ~30s on a fresh daemon: the
# pool's 14 workers were tied up warming the model while /api/duckdb/
# starters et al. queued behind it. Serialised (max_workers=1) is fine —
# there's one model and the drain runs on a 30s timer.
_EMBED_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="sy-embed",
)
_vec_loaded_paths: set[str] = set()  # connections where load() succeeded


def _try_load_vec(conn: sqlite3.Connection) -> bool:
    """Load the sqlite-vec extension on this connection. Returns True
    if available, False (silently) if `sqlite_vec` isn't installed or
    extension loading is disabled in this Python's sqlite3 build.
    Caching is per-call (cheap), but `sqlite_vec.load` itself
    re-registers virtual-table modules safely on repeat calls."""
    try:
        import sqlite_vec
    except ImportError:
        return False
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except (sqlite3.OperationalError, AttributeError) as e:
        log.debug("sqlite-vec load failed: %s", e)
        return False


def _ensure_vec_schema(conn: sqlite3.Connection) -> bool:
    """Create the vec0 virtual table + meta table if absent. Returns
    True if vec is loaded and the schema is in place, False otherwise.
    No-op when sqlite-vec isn't available, so tier-1 stays unaffected."""
    if not _try_load_vec(conn):
        return False
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS event_embeddings "
        f"USING vec0(embedding float[{EMBED_DIM}])"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS event_embeddings_meta ("
        "  vec_rowid  INTEGER PRIMARY KEY,"
        "  event_id   INTEGER NOT NULL UNIQUE REFERENCES events(id),"
        "  model      TEXT NOT NULL,"
        "  created_at REAL NOT NULL"
        ")"
    )
    return True


async def _aload_embedder():
    """Async wrapper around _load_embedder() that runs the
    model-load in a thread. SentenceTransformer's constructor reads
    weights / tokenizer config from disk (and on first launch
    downloads ~80 MB from huggingface) — both block the asyncio
    event loop for several seconds, freezing every other HTTP
    request the daemon was serving. Off-thread keeps the daemon
    responsive while the model warms up. Uses the dedicated embedding
    executor (not asyncio's shared default pool) so the load can't
    starve request-handler offloads."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_EMBED_EXECUTOR, _load_embedder)


class _Embedder:
    """Uniform interface over the two local backends. Both produce
    L2-normalised 384-dim vectors as plain `list[float]` (ready for
    `sqlite_vec.serialize_float32`). `model_id` labels the vector space.

    bge/arctic-style models are asymmetric — passages and queries embed
    differently (the query carries a retrieval instruction) — so we keep
    `embed_passages` / `embed_query` distinct. For the symmetric MiniLM
    (sentence-transformers) path they're the same call."""

    def __init__(self, backend: str, model_id: str, *, st=None, fe=None, vendor=None):
        self.backend = backend
        self.model_id = model_id
        self._st = st
        self._fe = fe
        self._vendor = vendor  # vendor backend key ("openai"/"gemini")

    @staticmethod
    def _normed(vec) -> list[float]:
        import numpy as np
        n = float(np.linalg.norm(vec))
        return (vec / n if n else vec).astype("float32").tolist()

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        if self.backend == "vendor":
            return _vendor_embed(self._vendor, list(texts))
        if self.backend == "fastembed":
            return [self._normed(v) for v in self._fe.embed(list(texts))]
        vecs = self._st.encode(list(texts), normalize_embeddings=True)
        return [v.tolist() for v in vecs]

    def embed_query(self, text: str) -> list[float]:
        if self.backend == "vendor":
            return _vendor_embed(self._vendor, [text])[0]
        if self.backend == "fastembed":
            return self._normed(next(iter(self._fe.query_embed([text]))))
        return self._st.encode(text, normalize_embeddings=True).tolist()


def _load_embedder():
    """Lazy singleton embedder. Prefers **fastembed** (ONNX, no PyTorch —
    the light path); falls back to **sentence-transformers** (PyTorch) if
    that's what's installed; returns None if neither is present (callers
    fall back to FTS-only). First load pulls the model (~30–90 MB) and
    takes a couple of seconds; after that encoding is fast.

    Synchronous; the embed_pending drain calls _aload_embedder() which
    wraps this in the dedicated executor so the loop stays free."""
    global _embedder
    if _embedder is False:
        return None
    if _embedder is not None:
        return _embedder
    # 0. Vendor API backend, if the user explicitly opted in (never auto —
    #    it sends rail text off-machine). Fail-soft to FTS-only if the
    #    key is missing rather than silently falling back to a local model.
    from . import app_settings
    backend = app_settings.get_embedding_backend()
    if backend in _VENDOR_EMBED:
        if _vendor_key(_VENDOR_EMBED[backend]["provider"]) is None:
            log.warning(
                "embedding_backend=%r but no API key for it — recall stays "
                "FTS-only until a key is added", backend,
            )
            _embedder = False
            return None
        model_id = f"{backend}:{_VENDOR_EMBED[backend]['model']}@{EMBED_DIM}"
        log.info(
            "using VENDOR embedding backend %s (%s) — rail text is sent to "
            "the provider for embedding", backend, model_id,
        )
        _embedder = _Embedder("vendor", model_id, vendor=backend)
        return _embedder
    # 1. fastembed (ONNX) — recommended, no torch.
    try:
        from fastembed import TextEmbedding
    except ImportError:
        pass
    else:
        try:
            log.info("loading embedding model %s via fastembed (ONNX)", _FASTEMBED_MODEL)
            _embedder = _Embedder(
                "fastembed", _FASTEMBED_MODEL,
                fe=TextEmbedding(model_name=_FASTEMBED_MODEL),
            )
            return _embedder
        except Exception:  # noqa: BLE001 — unsupported model / load fault; try ST
            log.exception("fastembed load failed; trying sentence-transformers")
    # 2. sentence-transformers (PyTorch) — byte-exact CE interop.
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        _embedder = False
        return None
    log.info("loading embedding model %s via sentence-transformers", _ST_MODEL)
    # Cache-first: without local_files_only, huggingface_hub REVALIDATES
    # every model file against the hub on each load (~15 HEAD/GET
    # requests per daemon boot, or hangs/timeouts offline) even though
    # the weights are cached. Only fall back to the network path when
    # the model genuinely isn't cached yet (first run).
    try:
        st = SentenceTransformer(_ST_MODEL, local_files_only=True)
    except Exception:  # noqa: BLE001 — not cached yet; fetch for real
        st = SentenceTransformer(_ST_MODEL)
    _embedder = _Embedder("sentence-transformers", _ST_MODEL, st=st)
    return _embedder


def reset_embedder() -> None:
    """Drop the cached embedder singleton so the next call re-selects the
    backend. Call after changing `embedding_backend` (or a provider key)
    so a switch takes effect without a daemon restart. The next drain's
    `_reconcile_embed_model` rebuilds the index if the vector space
    changed."""
    global _embedder
    _embedder = None


def _reconcile_embed_model(conn: sqlite3.Connection, active_model: str) -> None:
    """If the index holds vectors from a DIFFERENT model (backend/model
    switch), wipe them and re-mark every event for embedding so the drain
    rebuilds the index in the new vector space. Cheap no-op when the
    stored model already matches."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM event_embeddings_meta WHERE model != ?",
        (active_model,),
    ).fetchone()
    if row and row["n"]:
        log.info(
            "embedding model changed → rebuilding index for %s (%d stale vectors)",
            active_model, row["n"],
        )
        conn.execute(
            "DELETE FROM event_embeddings WHERE rowid IN "
            "(SELECT vec_rowid FROM event_embeddings_meta)"
        )
        conn.execute("DELETE FROM event_embeddings_meta")
        conn.execute("UPDATE events SET needs_embedding = 1")


def _select_pending(
    workspace: Path, batch: int, active_model: str,
) -> list[tuple[int, str]] | None:
    """Sync: open the DB, ensure the vec schema, reconcile the model
    (re-embed on a backend/model switch), return up to `batch`
    `(event_id, summary)` rows still needing an embedding. Returns None
    when sqlite-vec is unavailable (caller treats as "nothing to do").

    Runs off the event loop (the `_connect` open + read can block for
    tens of seconds on a cloud-sync-evicted conversations.db)."""
    try:
        import sqlite_vec  # noqa: F401
    except ImportError:
        return None
    with _connect(workspace) as conn:
        if not _ensure_vec_schema(conn):
            return None
        _reconcile_embed_model(conn, active_model)
        rows = conn.execute(
            "SELECT id, summary FROM events WHERE needs_embedding = 1 "
            "ORDER BY id ASC LIMIT ?",
            (batch,),
        ).fetchall()
        return [(int(r["id"]), r["summary"] or "") for r in rows]


def _write_embeddings(
    workspace: Path, ids: list[int], vecs: list[list[float]], model_id: str,
) -> None:
    """Sync: persist the encoded vectors and clear `needs_embedding`.
    Runs off the event loop for the same reason as `_select_pending`.
    `vecs` are plain normalised `list[float]`; `model_id` labels the
    vector space so a later backend/model switch can detect + rebuild."""
    import sqlite_vec

    with _connect(workspace) as conn:
        if not _ensure_vec_schema(conn):
            return
        now = time.time()
        for ev_id, vec in zip(ids, vecs):
            blob = sqlite_vec.serialize_float32(vec)
            cur = conn.execute(
                "INSERT INTO event_embeddings(embedding) VALUES (?)",
                (blob,),
            )
            conn.execute(
                "INSERT INTO event_embeddings_meta "
                "(vec_rowid, event_id, model, created_at) VALUES (?, ?, ?, ?)",
                (cur.lastrowid, ev_id, model_id, now),
            )
            conn.execute(
                "UPDATE events SET needs_embedding = 0 WHERE id = ?",
                (ev_id,),
            )


async def embed_pending(workspace: Path, *, batch: int = 64) -> int:
    """Background drain: encode events with `needs_embedding = 1` and
    write the vectors. Returns the count embedded this call (0 if vec
    unavailable or queue empty). Designed to run on a periodic timer
    in the daemon — every N seconds, or after every K appends.

    EVERYTHING heavy is off the event loop: the model load and encode
    on the dedicated embedding executor, and the two sqlite phases
    (`_select_pending` / `_write_embeddings`) via `asyncio.to_thread`.
    The sqlite open alone can block for tens of seconds on a
    cloud-sync-evicted DB, so it must never run on the loop."""
    embedder = await _aload_embedder()
    if embedder is None:
        return 0
    pending = await asyncio.to_thread(
        _select_pending, workspace, batch, embedder.model_id,
    )
    if not pending:  # None (vec unavailable) or [] (queue empty)
        return 0
    ids = [p[0] for p in pending]
    texts = [p[1] for p in pending]
    # Encode on the dedicated embedding executor (not the shared default
    # pool) so a big batch can't starve request offloads.
    loop = asyncio.get_running_loop()
    try:
        vecs = await loop.run_in_executor(
            _EMBED_EXECUTOR,
            functools.partial(embedder.embed_passages, texts),
        )
    except Exception:  # noqa: BLE001 — vendor network / API fault: leave
        # the events pending (needs_embedding=1) so the next drain retries.
        log.exception(
            "embedding batch failed (backend=%s) — leaving %d events pending",
            embedder.backend, len(ids),
        )
        return 0
    await asyncio.to_thread(
        _write_embeddings, workspace, ids, vecs, embedder.model_id,
    )
    return len(ids)


def _semantic_hits(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int,
    thread_id: str | None,
    kinds: list[str] | None,
) -> list[sqlite3.Row]:
    """Run a vec0 MATCH and return raw rows. Caller assembles the
    public hit dicts. Empty list if vec/embedder unavailable."""
    embedder = _load_embedder()
    if embedder is None or not _ensure_vec_schema(conn):
        return []
    try:
        import sqlite_vec
    except ImportError:
        return []
    try:
        qvec = embedder.embed_query(query)
    except Exception:  # noqa: BLE001 — vendor fault → fall back to FTS.
        log.exception("query embedding failed (backend=%s) — FTS only", embedder.backend)
        return []
    qblob = sqlite_vec.serialize_float32(qvec)
    # `k` is sqlite-vec's nearest-neighbour count; over-fetch so post-
    # filtering (thread/kind/model) still leaves enough hits.
    k = max(limit * 4, 20)
    sql = (
        "SELECT e.id, e.thread_id, e.kind, e.source, e.actor, "
        "       e.summary, e.created_at, e.payload_json, ev.distance "
        "FROM event_embeddings ev "
        "JOIN event_embeddings_meta m ON m.vec_rowid = ev.rowid "
        "JOIN events e ON e.id = m.event_id "
        "WHERE ev.embedding MATCH ? AND k = ? "
        # Only compare vectors from the ACTIVE model — during a
        # backend/model switch the index briefly holds both spaces; never
        # rank across them (stale rows drop out until the drain rebuilds).
        "AND m.model = ?"
    )
    params: list[Any] = [qblob, k, embedder.model_id]
    if thread_id:
        sql += " AND e.thread_id = ?"
        params.append(thread_id)
    if kinds:
        placeholders = ",".join("?" for _ in kinds)
        sql += f" AND e.kind IN ({placeholders})"
        params.extend(kinds)
    sql += " ORDER BY ev.distance ASC LIMIT ?"
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def _row_to_hit(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "event_id": r["id"],
        "thread_id": r["thread_id"],
        "kind": r["kind"],
        "source": r["source"],
        "actor": r["actor"],
        "snippet": (r["summary"] or "")[:RECALL_SNIPPET_CHARS],
        "at": r["created_at"],
    }


def recall(
    workspace: Path,
    query: str,
    *,
    limit: int = 10,
    thread_id: str | None = None,
    kinds: list[str] | None = None,
    mode: str = "fts",
) -> list[dict[str, Any]]:
    """Search past events by summary text.

    `mode` selects the retrieval strategy:
      · "fts"      — FTS5 keyword match (tier 1; default for back-compat)
      · "semantic" — sqlite-vec cosine similarity (tier 3); empty list
                      if vec/embedder isn't installed
      · "hybrid"   — both, merged via reciprocal rank fusion (k=60).
                      Falls back to FTS-only when vec is unavailable.

    Returns most-relevant first for semantic/hybrid; recent-first for
    FTS (matches prior behaviour). Optional `kinds` filter narrows by
    event kind, e.g. ['file_edit_external'] or ['user','assistant'].
    """
    if mode == "semantic":
        with _connect(workspace) as conn:
            rows = _semantic_hits(
                conn, query, limit=limit,
                thread_id=thread_id, kinds=kinds,
            )
        return [_row_to_hit(r) for r in rows]
    if mode == "hybrid":
        return _recall_hybrid(
            workspace, query, limit=limit,
            thread_id=thread_id, kinds=kinds,
        )
    # default: FTS
    with _connect(workspace) as conn:
        clauses = ["events_fts MATCH ?"]
        params: list[Any] = [_fts_query(query)]
        if thread_id:
            clauses.append("events_fts.thread_id = ?")
            params.append(thread_id)
        if kinds:
            placeholders = ",".join("?" for _ in kinds)
            clauses.append(f"events_fts.kind IN ({placeholders})")
            params.extend(kinds)
        sql = (
            "SELECT e.id, e.thread_id, e.kind, e.source, e.actor, "
            "e.summary, e.created_at, e.payload_json "
            "FROM events_fts JOIN events e ON e.id = events_fts.event_id "
            f"WHERE {' AND '.join(clauses)} ORDER BY e.id DESC LIMIT ?"
        )
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_hit(r) for r in rows]


def _recall_hybrid(
    workspace: Path,
    query: str,
    *,
    limit: int,
    thread_id: str | None,
    kinds: list[str] | None,
) -> list[dict[str, Any]]:
    """Reciprocal rank fusion of FTS + semantic results. Each list is
    over-fetched (3×limit) so the merge has good recall; rank within
    each list contributes 1/(k+rank) to a per-event score, and the
    top `limit` events overall are returned. Falls back to FTS alone
    when sqlite-vec / sentence-transformers aren't installed.
    Standard k=60 (Cormack 2009) — robust default; tuning hasn't
    proven valuable in any of the literature I trust."""
    over = max(limit * 3, 30)
    fts = recall(
        workspace, query, limit=over,
        thread_id=thread_id, kinds=kinds, mode="fts",
    )
    with _connect(workspace) as conn:
        sem_rows = _semantic_hits(
            conn, query, limit=over,
            thread_id=thread_id, kinds=kinds,
        )
    sem = [_row_to_hit(r) for r in sem_rows]
    if not sem:
        return fts[:limit]
    K = 60
    score: dict[int, float] = {}
    keep: dict[int, dict[str, Any]] = {}
    for rank, hit in enumerate(fts):
        eid = hit["event_id"]
        score[eid] = score.get(eid, 0.0) + 1.0 / (K + rank + 1)
        keep[eid] = hit
    for rank, hit in enumerate(sem):
        eid = hit["event_id"]
        score[eid] = score.get(eid, 0.0) + 1.0 / (K + rank + 1)
        keep.setdefault(eid, hit)
    ordered = sorted(score.keys(), key=lambda eid: score[eid], reverse=True)
    return [keep[eid] for eid in ordered[:limit]]


def _fts_query(q: str) -> str:
    """Sanitise user text for FTS5 — strip control chars, quote tokens
    so MATCH doesn't misparse user-supplied operators."""
    cleaned = "".join(c if c.isalnum() or c.isspace() else " " for c in q).split()
    if not cleaned:
        return '""'
    return " ".join(f'"{t}"' for t in cleaned)


def clear_all(workspace: Path) -> dict[str, int]:
    """Truncate every event + thread row in this workspace's rail DB.
    Returns the row counts that were removed so the caller can surface
    them in the confirmation message. The DB file + schema stay on
    disk — only the rows go."""
    with _connect(workspace) as conn:
        events_n = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        threads_n = conn.execute("SELECT COUNT(*) FROM threads").fetchone()[0]
        try:
            conn.execute("DELETE FROM events_fts")
        except sqlite3.OperationalError:
            # FTS table absent — older schema. Ignore.
            pass
        conn.execute("DELETE FROM events")
        conn.execute("DELETE FROM threads")
        conn.commit()
    return {"events": int(events_n), "threads": int(threads_n)}


def list_events(
    workspace: Path,
    thread_id: str | None = None,
    *,
    before_id: int | None = None,
    limit: int = 50,
    run_id: str | None = None,
    any_thread: bool = False,
) -> list[dict[str, Any]]:
    """Return events ordered chronologically (oldest → newest), suitable
    for hydrating the rail UI on page load and for "load older" scrollback.

    `before_id` restricts to events with `id < before_id` (i.e. older
    than the topmost entry the UI already has). `limit` caps the page
    size. By default we filter to one thread: if `thread_id` is
    provided, that one; otherwise the most-recently-updated thread in
    this workspace's DB. Set `any_thread=True` to skip the thread
    filter and paginate across every event in the workspace — that's
    what the rail hydrates from so the scrollback can reach prior
    threads. When `run_id` is set we ignore both filters and return
    that run's events across whichever thread owned them — the
    dashboard transcript expander uses this."""
    with _connect(workspace) as conn:
        clauses: list[str] = []
        params: list[Any] = []
        if run_id is not None:
            clauses.append("run_id = ?")
            params.append(run_id)
        elif any_thread:
            pass  # no thread filter — span the whole workspace
        else:
            if thread_id is None:
                row = conn.execute(
                    "SELECT id FROM threads ORDER BY updated_at DESC LIMIT 1"
                ).fetchone()
                if not row:
                    return []
                thread_id = row["id"]
            clauses.append("thread_id = ?")
            params.append(thread_id)
        if before_id is not None:
            clauses.append("id < ?")
            params.append(before_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            "SELECT id, thread_id, created_at, kind, source, actor, "
            "summary, payload_json, ref_id, run_id "
            f"FROM events {where} "
            "ORDER BY id DESC LIMIT ?"
        )
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
    rows.reverse()  # chronological
    out: list[dict[str, Any]] = []
    for r in rows:
        payload: Any = None
        if r["payload_json"]:
            try:
                payload = json.loads(r["payload_json"])
            except (ValueError, TypeError):
                payload = None
        out.append({
            "event_id": r["id"],
            "thread_id": r["thread_id"],
            "created_at": r["created_at"],
            "kind": r["kind"],
            "source": r["source"],
            "actor": r["actor"],
            "summary": r["summary"],
            "payload": payload,
            "ref_id": r["ref_id"],
            "run_id": r["run_id"],
        })
    return out


def active_thread_id(workspace: Path) -> str | None:
    """Most recently-updated thread id, or None if no rows."""
    with _connect(workspace) as conn:
        row = conn.execute(
            "SELECT id FROM threads ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
    return row["id"] if row else None


def export_recent(workspace: Path, thread_id: str, limit: int = 50) -> str:
    """Plain-text dump for debugging / `/log` inserts."""
    with _connect(workspace) as conn:
        rows = conn.execute(
            "SELECT kind, source, actor, summary, created_at FROM events "
            "WHERE thread_id = ? ORDER BY id DESC LIMIT ?",
            (thread_id, limit),
        ).fetchall()
    rows.reverse()
    return "\n\n".join(
        f"[{r['kind']}/{r['source']}] {r['summary']}" for r in rows
    )
