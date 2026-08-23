"""Workspace Auto schedules — overnight desks and other recurring prompts.

Stored in ``<workspace>/.workbench/state/schedules.json`` so they roam
with the vault. The daemon ticks every ~20s and fires due items via
Auto in that workspace (not necessarily the focused one).
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import atomicio

VERSION = 1
FREQUENCIES = ("hourly", "daily", "weekly", "every_n_hours")


def _path(workspace: Path) -> Path:
    return Path(workspace) / ".workbench" / "state" / "schedules.json"


def empty() -> dict[str, Any]:
    return {"version": VERSION, "items": []}


def load(workspace: Path) -> dict[str, Any]:
    p = _path(workspace)
    if not p.is_file():
        return empty()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty()
    if not isinstance(data, dict) or data.get("version") != VERSION:
        return empty()
    items = data.get("items")
    if not isinstance(items, list):
        items = []
    data["items"] = [i for i in items if isinstance(i, dict)]
    return data


def save(workspace: Path, data: dict[str, Any]) -> None:
    p = _path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = dict(data)
    data["version"] = VERSION
    atomicio.write_json_atomic(p, data)


def list_items(workspace: Path) -> list[dict[str, Any]]:
    return list(load(workspace).get("items") or [])


def get(workspace: Path, sid: str) -> dict[str, Any] | None:
    for it in list_items(workspace):
        if str(it.get("id") or "") == sid:
            return it
    return None


def interval_sec(item: dict[str, Any]) -> float:
    freq = str(item.get("frequency") or "daily")
    if freq == "hourly":
        return 3600.0
    if freq == "weekly":
        return 7 * 86400.0
    if freq == "every_n_hours":
        try:
            n = float(item.get("every_hours") or 24)
        except (TypeError, ValueError):
            n = 24.0
        return max(1.0, n) * 3600.0
    return 86400.0


def is_due(item: dict[str, Any], *, now: float | None = None) -> bool:
    if not item.get("enabled", True):
        return False
    if item.get("running_run_id"):
        return False
    now = now if now is not None else time.time()
    last = item.get("last_run_at")
    try:
        last_f = float(last) if last is not None else None
    except (TypeError, ValueError):
        last_f = None
    if last_f is None:
        return True
    return now - last_f >= interval_sec(item)


def create(
    workspace: Path,
    *,
    title: str,
    prompt: str,
    frequency: str = "daily",
    every_hours: float | None = None,
    enabled: bool = True,
    preference: float | None = None,
) -> dict[str, Any]:
    now = time.time()
    freq = frequency if frequency in FREQUENCIES else "daily"
    item = {
        "id": f"sch-{uuid.uuid4().hex[:10]}",
        "title": (title or "Untitled").strip()[:120],
        "prompt": prompt or "",
        "frequency": freq,
        "every_hours": float(every_hours) if every_hours is not None else 24.0,
        "enabled": bool(enabled),
        "preference": preference,
        "created_at": now,
        "created_day": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "edited_at": now,
        "last_run_at": None,
        "run_count": 0,
        "running_run_id": None,
    }
    data = load(workspace)
    data.setdefault("items", []).append(item)
    save(workspace, data)
    return item


def update(workspace: Path, sid: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    data = load(workspace)
    found = None
    for it in data.get("items") or []:
        if str(it.get("id") or "") != sid:
            continue
        if "title" in patch:
            it["title"] = str(patch["title"] or "").strip()[:120]
        if "prompt" in patch:
            it["prompt"] = str(patch["prompt"] or "")
        if "frequency" in patch:
            freq = str(patch["frequency"] or "daily")
            if freq in FREQUENCIES:
                it["frequency"] = freq
        if "every_hours" in patch:
            try:
                it["every_hours"] = float(patch["every_hours"])
            except (TypeError, ValueError):
                pass
        if "enabled" in patch:
            it["enabled"] = bool(patch["enabled"])
        if "preference" in patch:
            it["preference"] = patch["preference"]
        it["edited_at"] = time.time()
        found = it
        break
    if found is None:
        return None
    save(workspace, data)
    return found


def delete(workspace: Path, sid: str) -> bool:
    data = load(workspace)
    items = data.get("items") or []
    nxt = [i for i in items if str(i.get("id") or "") != sid]
    if len(nxt) == len(items):
        return False
    data["items"] = nxt
    save(workspace, data)
    return True


def mark_started(workspace: Path, sid: str, run_id: str) -> dict[str, Any] | None:
    data = load(workspace)
    found = None
    now = time.time()
    for it in data.get("items") or []:
        if str(it.get("id") or "") != sid:
            continue
        it["last_run_at"] = now
        it["run_count"] = int(it.get("run_count") or 0) + 1
        it["running_run_id"] = run_id
        found = it
        break
    if found is None:
        return None
    save(workspace, data)
    return found


def set_running(workspace: Path, sid: str, run_id: str | None) -> None:
    """Update the live run id without bumping run_count."""
    data = load(workspace)
    for it in data.get("items") or []:
        if str(it.get("id") or "") == sid:
            it["running_run_id"] = run_id
            save(workspace, data)
            return


def clear_stale_running(workspace: Path, live_ids: set[str] | None = None) -> None:
    """Drop running_run_id when the daemon died mid-fire ('pending') or
    the run is no longer live and has no resumable checkpoint."""
    data = load(workspace)
    changed = False
    live_ids = live_ids or set()
    for it in data.get("items") or []:
        rid = str(it.get("running_run_id") or "")
        if not rid:
            continue
        if rid == "pending" or rid not in live_ids:
            it["running_run_id"] = None
            changed = True
    if changed:
        save(workspace, data)


def mark_finished(workspace: Path, sid: str) -> None:
    data = load(workspace)
    changed = False
    for it in data.get("items") or []:
        if str(it.get("id") or "") == sid:
            it["running_run_id"] = None
            changed = True
            break
    if changed:
        save(workspace, data)
