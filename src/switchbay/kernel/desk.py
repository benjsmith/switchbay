"""Desk lifetime: working, quiet, dismissed.

Quiet is the resting state (wave done, or a schedule window ended).
Dismissed is only Stop / a stand-down chat command.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import atomicio, orchestrator_fs

DESK_VERSION = 1
DESK_AUTO = "auto"
DESK_CURATE = "curate"
DESK_PROJECTS = "projects"
DESK_CODE = "code"

STATE_WORKING = "working"
STATE_QUIET = "quiet"
STATE_DISMISSED = "dismissed"
STATES = (STATE_WORKING, STATE_QUIET, STATE_DISMISSED)


@dataclass
class DeskRecord:
    desk_id: str
    state: str = STATE_QUIET
    chief_provider: str | None = None
    chief_model: str | None = None
    thread_id: str | None = None
    run_id: str | None = None
    org: list[dict[str, Any]] = field(default_factory=list)
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "desk_id": self.desk_id,
            "state": self.state,
            "chief_provider": self.chief_provider,
            "chief_model": self.chief_model,
            "thread_id": self.thread_id,
            "run_id": self.run_id,
            "org": list(self.org),
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: Any, *, desk_id: str = "") -> DeskRecord:
        if not isinstance(raw, dict):
            return cls(desk_id=desk_id or "auto")
        st = str(raw.get("state") or STATE_QUIET)
        if st not in STATES:
            st = STATE_QUIET
        org = raw.get("org") if isinstance(raw.get("org"), list) else []
        return cls(
            desk_id=str(raw.get("desk_id") or desk_id or "auto"),
            state=st,
            chief_provider=str(raw["chief_provider"]) if raw.get("chief_provider") else None,
            chief_model=str(raw["chief_model"]) if raw.get("chief_model") else None,
            thread_id=str(raw["thread_id"]) if raw.get("thread_id") else None,
            run_id=str(raw["run_id"]) if raw.get("run_id") else None,
            org=[x for x in org if isinstance(x, dict)],
            updated_at=float(raw.get("updated_at") or 0),
        )


def _path(workspace: Path) -> Path:
    return orchestrator_fs.root(workspace) / "state" / "desks.json"


def _load_all(workspace: Path) -> dict[str, Any]:
    p = _path(workspace)
    try:
        data = json_load(p)
    except Exception:  # noqa: BLE001
        return {"version": DESK_VERSION, "desks": {}}
    if not isinstance(data, dict) or data.get("version") != DESK_VERSION:
        return {"version": DESK_VERSION, "desks": {}}
    desks = data.get("desks")
    if not isinstance(desks, dict):
        data["desks"] = {}
    return data


def json_load(path: Path) -> Any:
    import json
    return json.loads(path.read_text(encoding="utf-8"))


def _save_all(workspace: Path, data: dict[str, Any]) -> None:
    orchestrator_fs.ensure(workspace)
    atomicio.write_json_atomic(_path(workspace), data)


def get(workspace: Path, desk_id: str) -> DeskRecord | None:
    data = _load_all(workspace)
    raw = (data.get("desks") or {}).get(desk_id)
    if not isinstance(raw, dict):
        return None
    rec = DeskRecord.from_dict(raw, desk_id=desk_id)
    if rec.state == STATE_DISMISSED:
        return rec
    return rec


def _put(workspace: Path, rec: DeskRecord) -> DeskRecord:
    rec.updated_at = time.time()
    data = _load_all(workspace)
    desks = data.setdefault("desks", {})
    desks[rec.desk_id] = rec.to_dict()
    _save_all(workspace, data)
    return rec


def seat(
    workspace: Path,
    desk_id: str,
    *,
    chief_provider: str,
    chief_model: str | None,
    thread_id: str | None = None,
    run_id: str | None = None,
    org: list[dict[str, Any]] | None = None,
) -> DeskRecord:
    """Seat (or re-seat) a chief. Existing dismissed desks can be reused."""
    rec = get(workspace, desk_id) or DeskRecord(desk_id=desk_id)
    rec.chief_provider = chief_provider
    rec.chief_model = chief_model
    rec.thread_id = thread_id or rec.thread_id
    rec.run_id = run_id
    rec.org = list(org or rec.org)
    rec.state = STATE_WORKING
    return _put(workspace, rec)


def set_working(workspace: Path, desk_id: str, *, run_id: str | None = None) -> DeskRecord | None:
    rec = get(workspace, desk_id)
    if rec is None or rec.state == STATE_DISMISSED:
        return rec
    rec.state = STATE_WORKING
    if run_id:
        rec.run_id = run_id
    return _put(workspace, rec)


def quiet(
    workspace: Path, desk_id: str, *, run_id: str | None = None,
) -> DeskRecord | None:
    """Wave done or schedule window ended. No-op if already dismissed.

    When ``run_id`` is set, an overlapping newer seat is left working.
    """
    rec = get(workspace, desk_id)
    if rec is None:
        return None
    if rec.state == STATE_DISMISSED:
        return rec
    if run_id and rec.run_id and rec.run_id != run_id:
        return rec
    rec.state = STATE_QUIET
    rec.run_id = None
    return _put(workspace, rec)


def dismiss(workspace: Path, desk_id: str) -> DeskRecord | None:
    """Stop / stand-down. The only path that tears the chief down."""
    rec = get(workspace, desk_id)
    if rec is None:
        rec = DeskRecord(desk_id=desk_id, state=STATE_DISMISSED)
        return _put(workspace, rec)
    rec.state = STATE_DISMISSED
    rec.run_id = None
    rec.org = []
    return _put(workspace, rec)


def dismiss_run(workspace: Path, run_id: str) -> list[str]:
    """Dismiss every desk whose live run matches. Used by Stop."""
    data = _load_all(workspace)
    hit: list[str] = []
    for did, raw in list((data.get("desks") or {}).items()):
        rec = DeskRecord.from_dict(raw, desk_id=str(did))
        if rec.run_id == run_id and rec.state != STATE_DISMISSED:
            dismiss(workspace, rec.desk_id)
            hit.append(rec.desk_id)
    return hit


def window_ended(item: dict[str, Any], *, now: float | None = None) -> bool:
    """True when a schedule's until_at has passed (alarm clock, not death)."""
    until = item.get("until_at")
    try:
        until_f = float(until) if until is not None else None
    except (TypeError, ValueError):
        return False
    if until_f is None:
        return False
    stamp = now if now is not None else time.time()
    return stamp >= until_f
