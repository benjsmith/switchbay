"""Auto schedules — overnight desks and other recurring prompts.

Workspace-scoped items live in
``<workspace>/.workbench/state/schedules.json`` so they roam with the
vault. Global items (run the prompt in every registered workspace)
live in ``$XDG_CONFIG_HOME/switchbay/schedules.json``. The daemon ticks
every ~20s and fires due items via Auto.
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

# ``None`` as a store means the machine-level global schedule file.
Store = Path | None


def _file(store: Store) -> Path:
    if store is None:
        from . import workspaces
        return workspaces.config_dir() / "schedules.json"
    return Path(store) / ".workbench" / "state" / "schedules.json"


def empty() -> dict[str, Any]:
    return {"version": VERSION, "items": []}


def load(store: Store) -> dict[str, Any]:
    p = _file(store)
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


def save(store: Store, data: dict[str, Any]) -> None:
    p = _file(store)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = dict(data)
    data["version"] = VERSION
    atomicio.write_json_atomic(p, data)


def list_items(store: Store) -> list[dict[str, Any]]:
    return list(load(store).get("items") or [])


def get(store: Store, sid: str) -> dict[str, Any] | None:
    for it in list_items(store):
        if str(it.get("id") or "") == sid:
            return it
    return None


def annotate(
    item: dict[str, Any],
    *,
    scope: str,
    workspace: Path | None,
    name: str,
) -> dict[str, Any]:
    out = dict(item)
    out["scope"] = scope
    out["workspace"] = str(workspace) if workspace is not None else None
    out["workspace_name"] = name
    return out


def list_all(paths: list[str]) -> list[dict[str, Any]]:
    """Global items first, then each registered workspace."""
    out: list[dict[str, Any]] = []
    for it in list_items(None):
        out.append(annotate(it, scope="global", workspace=None, name="all workspaces"))
    seen: set[str] = set()
    for raw in paths:
        p = Path(str(raw))
        key = str(p)
        if key in seen or not p.is_dir():
            continue
        seen.add(key)
        for it in list_items(p):
            out.append(annotate(it, scope="workspace", workspace=p, name=p.name))
    return out


def locate(sid: str, paths: list[str]) -> tuple[Store, dict[str, Any]] | None:
    """Find a schedule by id in the global store or any workspace."""
    hit = get(None, sid)
    if hit is not None:
        return None, hit
    seen: set[str] = set()
    for raw in paths:
        p = Path(str(raw))
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        hit = get(p, sid)
        if hit is not None:
            return p, hit
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
    until = item.get("until_at")
    try:
        until_f = float(until) if until is not None else None
    except (TypeError, ValueError):
        until_f = None
    if until_f is not None and now >= until_f:
        return False
    last = item.get("last_run_at")
    try:
        last_f = float(last) if last is not None else None
    except (TypeError, ValueError):
        last_f = None
    if last_f is None:
        return True
    return now - last_f >= interval_sec(item)


def expire_windows(store: Store, *, now: float | None = None) -> list[str]:
    """Disable items whose ``until_at`` has passed.

    ``until_at`` is a schedule lifetime (overnight window), not a desk
    identity. Recurring prompts with no window are untouched. Returns
    explicit ``desk_id`` values from newly expired rows so the ticker
    can Stop those standing desks — it must not guess Auto/Curate from
    the prompt text.
    """
    now = now if now is not None else time.time()
    data = load(store)
    changed = False
    desks: list[str] = []
    seen: set[str] = set()
    for it in data.get("items") or []:
        until = it.get("until_at")
        try:
            until_f = float(until) if until is not None else None
        except (TypeError, ValueError):
            until_f = None
        if until_f is None or now < until_f:
            continue
        if not (it.get("enabled", True) or it.get("running_run_id")):
            continue
        it["enabled"] = False
        it["running_run_id"] = None
        it["edited_at"] = now
        changed = True
        did = str(it.get("desk_id") or "").strip()
        if did and did not in seen:
            seen.add(did)
            desks.append(did)
    if changed:
        save(store, data)
    return desks


def create(
    store: Store,
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
        "until_at": None,
        "created_at": now,
        "created_day": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "edited_at": now,
        "last_run_at": None,
        "run_count": 0,
        "running_run_id": None,
    }
    data = load(store)
    data.setdefault("items", []).append(item)
    save(store, data)
    return item


def update(store: Store, sid: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    data = load(store)
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
        if "until_at" in patch:
            raw = patch["until_at"]
            if raw is None or raw == "":
                it["until_at"] = None
            else:
                try:
                    it["until_at"] = float(raw)
                except (TypeError, ValueError):
                    pass
        it["edited_at"] = time.time()
        found = it
        break
    if found is None:
        return None
    save(store, data)
    return found


def delete(store: Store, sid: str) -> bool:
    data = load(store)
    items = data.get("items") or []
    nxt = [i for i in items if str(i.get("id") or "") != sid]
    if len(nxt) == len(items):
        return False
    data["items"] = nxt
    save(store, data)
    return True


def mark_started(store: Store, sid: str, run_id: str) -> dict[str, Any] | None:
    data = load(store)
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
    save(store, data)
    return found


def set_running(store: Store, sid: str, run_id: str | None) -> None:
    """Update the live run id without bumping run_count."""
    data = load(store)
    for it in data.get("items") or []:
        if str(it.get("id") or "") == sid:
            it["running_run_id"] = run_id
            save(store, data)
            return


def clear_stale_running(store: Store, live_ids: set[str] | None = None) -> None:
    """Drop running_run_id when the daemon died mid-fire ('pending') or
    the run is no longer live and has no resumable checkpoint."""
    data = load(store)
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
        save(store, data)


def mark_finished(store: Store, sid: str) -> None:
    data = load(store)
    changed = False
    for it in data.get("items") or []:
        if str(it.get("id") or "") == sid:
            it["running_run_id"] = None
            changed = True
            break
    if changed:
        save(store, data)
