"""Desk lifetime: working, quiet, dismissed.

Quiet is the resting state: wave done, schedule window ended, or
``/work stop`` (the DAG stays). Dismissed is explicit only — Desks
button or ``/work dismiss`` — and drops the desk from the list.
"""

from __future__ import annotations

import re
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
DESK_DECK = "deck"

STATE_WORKING = "working"
STATE_QUIET = "quiet"
STATE_DISMISSED = "dismissed"
STATES = (STATE_WORKING, STATE_QUIET, STATE_DISMISSED)

# Slash + dashboard labels. `/work` is the projects desk (not D8
# `/project`, not mid-turn steer). `/steer` remains a silent alias.
# Deck has no slash — `/slideshow` already lists/opens HTML decks;
# authoring reuses this one standing desk from natural language.
DESK_INFO: dict[str, dict[str, str | None]] = {
    DESK_AUTO: {"label": "Auto", "slash": None},
    DESK_CURATE: {"label": "Curate", "slash": "curate"},
    DESK_PROJECTS: {"label": "Work", "slash": "work"},
    DESK_CODE: {"label": "Code", "slash": "code"},
    DESK_DECK: {"label": "Deck", "slash": None},
}

# Explicit slash / internal command → standing desk. Curate always
# seats, even when the wave is a single worker.
_COMMAND_DESK: dict[str, str] = {
    "curate": DESK_CURATE,
    "curator": DESK_CURATE,
    "work": DESK_PROJECTS,
    "working": DESK_PROJECTS,
    "steer": DESK_PROJECTS,
    "steering": DESK_PROJECTS,
    "code": DESK_CODE,
    "coding": DESK_CODE,
    "deck": DESK_DECK,
    "create-deck": DESK_DECK,
    "create_deck": DESK_DECK,
    "make-deck": DESK_DECK,
    "make-slides": DESK_DECK,
    "make_slides": DESK_DECK,
    "slideshow-author": DESK_DECK,
}

_TASK_KIND_DESK: dict[str, str] = {
    "curation": DESK_CURATE,
    "projects": DESK_PROJECTS,
    "code": DESK_CODE,
    "deck": DESK_DECK,
    "auto": DESK_AUTO,
}

# Authoring a presentation. A subject mention ("HTML slideshows",
# "the deck") is not enough — require a make/revise verb (or the
# create_slideshow tool name). Determiners may stack: "the existing
# HTML deck", "this slide deck".
_DECK_RE = re.compile(
    r"\b(?:"
    r"create_slideshow|"
    r"(?:make|create|build|author|revise|regen(?:erate)?)\s+"
    r"(?:(?:an?|the|this|that|existing|current)\s+)*"
    r"(?:html\s+)?"
    r"(?:slide\s*decks?|slideshows?|slides|decks?)"
    r")\b",
    re.I,
)

_DEEPER_RE = re.compile(
    r"\b("
    r"plan|roadmap|work-?plan|charter|"
    r"investigat|underwrite|"
    r"implement|refactor|"
    r"overnight"
    r")\b",
    re.I,
)


def looks_like_deck(text: str) -> bool:
    """True when the prompt is asking to author an HTML slideshow."""
    return bool(_DECK_RE.search(text or ""))


def choose_desk(
    *,
    task_kind: str | None = None,
    command: str | None = None,
    text: str = "",
    strategy: str | None = None,
    n_investigators: int = 1,
    include_verify: bool = False,
    lookup: bool = False,
    research: bool = False,
    code: bool = False,
) -> str | None:
    """Which standing desk this run reuses, or None for a one-shot.

    Named desks (curate / work / code / deck) always seat — including
    a single-worker ``/curate``. Simple wiki/lookup questions do not.
    Deeper Auto (plan, research, multi-worker) reuses Auto. A second
    slideshow ask returns the same Deck id, not a new desk.
    """
    cmd = (command or "").strip().lower()
    if cmd in _COMMAND_DESK:
        return _COMMAND_DESK[cmd]
    kind = (task_kind or "").strip().lower()
    if kind in _TASK_KIND_DESK:
        return _TASK_KIND_DESK[kind]
    if looks_like_deck(text):
        return DESK_DECK
    single = (strategy or "single") in {"single", "fast_lookup", ""}
    multi = include_verify or n_investigators > 1
    # Asking *about* a plan/roadmap/charter is still a lookup.
    # Named desks already returned above.
    if single and not multi and lookup:
        return None
    if (strategy or "") == "fast_lookup":
        return None
    if not single:
        return DESK_AUTO
    if multi or research or code or _DEEPER_RE.search(text or ""):
        return DESK_AUTO
    return None


@dataclass
class DeskRecord:
    desk_id: str
    state: str = STATE_QUIET
    chief_provider: str | None = None
    chief_model: str | None = None
    thread_id: str | None = None
    run_id: str | None = None
    org: list[dict[str, Any]] = field(default_factory=list)
    objective: str | None = None
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
            "objective": self.objective,
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
            objective=str(raw["objective"]) if raw.get("objective") else None,
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


def list_standing(workspace: Path) -> list[DeskRecord]:
    """Working or quiet desks. Dismissed rows stay on disk but are omitted."""
    data = _load_all(workspace)
    out: list[DeskRecord] = []
    for did, raw in (data.get("desks") or {}).items():
        rec = DeskRecord.from_dict(raw, desk_id=str(did))
        if rec.state in (STATE_WORKING, STATE_QUIET):
            out.append(rec)
    out.sort(key=lambda r: r.updated_at, reverse=True)
    return out


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
    objective: str | None = None,
) -> DeskRecord:
    """Seat (or re-seat) a chief. Existing dismissed desks can be reused."""
    rec = get(workspace, desk_id) or DeskRecord(desk_id=desk_id)
    rec.chief_provider = chief_provider
    rec.chief_model = chief_model
    rec.thread_id = thread_id or rec.thread_id
    rec.run_id = run_id
    rec.org = list(org or rec.org)
    if objective:
        rec.objective = objective.strip()[:2000]
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
    keep_run: bool = False,
) -> DeskRecord | None:
    """Wave done, window ended, or Stop. No-op if already dismissed.

    When ``run_id`` is set, an overlapping newer seat is left working.
    ``keep_run=True`` (Stop) freezes the DAG id so Start can resume it.
    """
    rec = get(workspace, desk_id)
    if rec is None:
        return None
    if rec.state == STATE_DISMISSED:
        return rec
    if run_id and rec.run_id and rec.run_id != run_id:
        return rec
    rec.state = STATE_QUIET
    if not keep_run:
        rec.run_id = None
    return _put(workspace, rec)


def dismiss(workspace: Path, desk_id: str) -> DeskRecord | None:
    """Tear the chief down. Only an explicit dismiss (Desks button,
    ``/work dismiss``, ``/code dismiss``) should call this — not Stop."""
    rec = get(workspace, desk_id)
    owned_run = rec.run_id if rec is not None else None
    if rec is None:
        rec = DeskRecord(desk_id=desk_id, state=STATE_DISMISSED)
        rec = _put(workspace, rec)
    else:
        rec.state = STATE_DISMISSED
        rec.run_id = None
        rec.org = []
        rec = _put(workspace, rec)
    # One standing-org file per workspace. Only drop it when this desk
    # owns the live org; dismissing Curate must not erase Code's DAG.
    try:
        org = orchestrator_fs.load_org(workspace)
        oid = str((org or {}).get("orchestration_id") or "")
        if org is not None and owned_run and oid == owned_run:
            orchestrator_fs.clear_org(workspace)
    except Exception:  # noqa: BLE001
        pass
    return rec


def dismiss_run(workspace: Path, run_id: str) -> list[str]:
    """Dismiss every desk whose live run matches. Explicit dismiss only."""
    data = _load_all(workspace)
    hit: list[str] = []
    for did, raw in list((data.get("desks") or {}).items()):
        rec = DeskRecord.from_dict(raw, desk_id=str(did))
        if rec.run_id == run_id and rec.state != STATE_DISMISSED:
            dismiss(workspace, rec.desk_id)
            hit.append(rec.desk_id)
    return hit


def quiet_run(workspace: Path, run_id: str) -> list[str]:
    """Quiet every working desk whose live run matches. Used by Stop."""
    data = _load_all(workspace)
    hit: list[str] = []
    for did, raw in list((data.get("desks") or {}).items()):
        rec = DeskRecord.from_dict(raw, desk_id=str(did))
        if rec.run_id == run_id and rec.state == STATE_WORKING:
            quiet(workspace, rec.desk_id, run_id=run_id, keep_run=True)
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
