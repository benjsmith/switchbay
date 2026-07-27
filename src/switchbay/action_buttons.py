"""User-global custom action buttons for the rail.

The rail's action row ships with three built-in buttons (Curate,
Rebuild Viewer, Rescan) plus the file-attach `+` and a trailing
register-a-new-button `+`. The user can add their own bookmarks
here — anything they'd otherwise type in chat or as a slash
command. Persists across workspace switches because the registry
lives at `~/.config/switchbay/action-buttons.json` (user-global,
NOT in `<workspace>/.workbench/`).

Each button: `{id, label, command, created_at}`. `command` is the
text submitted to the rail when the button is clicked — typically
a slash command (`/curate figures`) but plain prose works too.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from . import workspaces  # for config_dir() — same ~/.config/switchbay/
from . import atomicio

log = logging.getLogger("switchbay.action_buttons")


def _path() -> Path:
    return workspaces.config_dir() / "action-buttons.json"


def load() -> list[dict[str, Any]]:
    p = _path()
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("action-buttons.json unreadable; starting empty")
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        bid = str(entry.get("id") or "").strip()
        label = str(entry.get("label") or "").strip()
        command = str(entry.get("command") or "").strip()
        if not bid or not label or not command:
            continue
        out.append({
            "id": bid,
            "label": label,
            "command": command,
            "created_at": entry.get("created_at"),
        })
    return out


def _save(records: list[dict[str, Any]]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(p, records)


def add(label: str, command: str) -> dict[str, Any]:
    label = (label or "").strip()
    command = (command or "").strip()
    if not label:
        raise ValueError("label is required")
    if not command:
        raise ValueError("command is required")
    rec = {
        "id": uuid.uuid4().hex[:10],
        "label": label,
        "command": command,
        "created_at": time.time(),
    }
    records = load()
    records.append(rec)
    _save(records)
    return rec


def remove(button_id: str) -> bool:
    button_id = (button_id or "").strip()
    if not button_id:
        return False
    records = load()
    keep = [r for r in records if r.get("id") != button_id]
    if len(keep) == len(records):
        return False
    _save(keep)
    return True
