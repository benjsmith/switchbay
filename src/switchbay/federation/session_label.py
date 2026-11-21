"""Session floor for classification.

Once a session reads confidential or restricted content, later output
in that session is at least that label until a person lowers it. The
read is audited. A chat answer takes the highest label of the session
floor and the content that answer used.
"""

from __future__ import annotations

import json
from contextvars import ContextVar
from pathlib import Path

from . import audit, classify, secure

_current: ContextVar[str] = ContextVar("switchbay_session", default="default")


def set_current(session_id: str) -> None:
    _current.set(session_id or "default")


def current_id() -> str:
    return _current.get()


def _path(workspace: Path) -> Path:
    from .. import statedir
    import hashlib
    digest = hashlib.sha256(str(workspace.resolve()).encode()).hexdigest()[:16]
    return statedir.state_root() / "sessions" / digest / "labels.json"


def _load(workspace: Path) -> dict:
    path = _path(workspace)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(workspace: Path, data: dict) -> None:
    secure.owner_write(_path(workspace), json.dumps(data, indent=2) + "\n")


def floor(workspace: Path, session_id: str | None = None) -> str:
    sid = session_id or current_id()
    return str(_load(workspace).get(sid) or "public")


def note_read(workspace: Path, label: str, *, source: str, session_id: str | None = None) -> str:
    """Raise the session floor when the read is confidential or higher."""
    sid = session_id or current_id()
    label = (label or "public").strip().lower()
    if classify.rank(label) >= classify.rank("confidential"):
        audit.record(
            workspace, "confidential_read", session=sid, label=label, source=source,
        )
        data = _load(workspace)
        current = str(data.get(sid) or "public")
        if classify.rank(label) > classify.rank(current):
            data[sid] = label
            _save(workspace, data)
            return label
        return current
    return floor(workspace, sid)


def answer_label(workspace: Path, used: list[str], session_id: str | None = None) -> str:
    return classify.highest(floor(workspace, session_id), *used)


def lower(workspace: Path, reason: str, *, human_confirmed: bool, session_id: str | None = None) -> dict:
    sid = session_id or current_id()
    if not human_confirmed:
        audit.record(workspace, "refused_write", why="session label requires a person", session=sid)
        return {"ok": False, "error": "only a person can lower a session label"}
    reason = (reason or "").strip()
    if len(reason) < 8:
        return {"ok": False, "error": "a reason is required"}
    before = floor(workspace, sid)
    data = _load(workspace)
    data[sid] = "public"
    _save(workspace, data)
    audit.record(
        workspace, "declassify", session=sid, before=before, after="public", reason=reason,
    )
    return {"ok": True, "before": before, "after": "public", "session": sid}
