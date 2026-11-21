"""Items that arrived without a classification, waiting in Reviews.

Enterprise review is mandatory unless the admin turns it off. Outside
enterprise it is optional, and a workspace can turn it on.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import admin_policy, atomicio

_LABELS = ("public", "internal", "confidential", "restricted")


def _path(workspace: Path) -> Path:
    return workspace / ".workbench" / "state" / "classification_queue.json"


def _read(workspace: Path) -> list[dict[str, Any]]:
    path = _path(workspace)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _write(workspace: Path, rows: list[dict[str, Any]]) -> None:
    path = _path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(path, rows)


def mandatory(workspace: Path) -> bool:
    raw = (admin_policy.load().get("classification_review") or {})
    if isinstance(raw, dict) and "mandatory" in raw:
        return bool(raw["mandatory"])
    if admin_policy.profile() == "enterprise":
        return True
    path = workspace / ".workbench" / "classification-review.json"
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(isinstance(data, dict) and data.get("mandatory"))


def set_mandatory(workspace: Path, enabled: bool) -> dict:
    if admin_policy.profile() == "enterprise":
        return {"ok": False, "error": "an admin sets review for the enterprise profile"}
    path = workspace / ".workbench" / "classification-review.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(path, {"mandatory": bool(enabled)})
    return {"ok": True, "mandatory": bool(enabled)}


def add(workspace: Path, item: dict[str, Any]) -> dict[str, Any]:
    rows = _read(workspace)
    row = {
        "id": str(item.get("id") or ""),
        "title": str(item.get("title") or "Untitled"),
        "kind": str(item.get("kind") or "capture"),
        "source": str(item.get("source") or ""),
        "status": "pending",
        "classification": "",
    }
    rows = [existing for existing in rows if existing.get("id") != row["id"]]
    rows.append(row)
    _write(workspace, rows)
    return row


def pending(workspace: Path) -> list[dict[str, Any]]:
    return [row for row in _read(workspace) if row.get("status") == "pending"]


def decide(workspace: Path, item_id: str, label: str) -> dict[str, Any]:
    label = (label or "").strip().lower()
    if label not in _LABELS:
        return {"ok": False, "error": "choose public, internal, confidential, or restricted"}
    rows = _read(workspace)
    found = None
    for row in rows:
        if row.get("id") == item_id:
            row["status"] = "classified"
            row["classification"] = label
            found = row
    if found is None:
        return {"ok": False, "error": "no such item"}
    _write(workspace, rows)
    return {"ok": True, "item": found}
