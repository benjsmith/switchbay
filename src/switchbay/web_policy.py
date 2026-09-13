"""Per-workspace web egress policy. Default off.

When enabled, individual search/fetch calls may request a once/deny
approval card. Never a blanket consent. Admin policy can force off.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import atomicio, orchestrator_fs

POLICY_FILE = "web-policy.json"


def _path(workspace: Path) -> Path:
    return orchestrator_fs.root(workspace) / "state" / POLICY_FILE


def load(workspace: Path) -> dict[str, Any]:
    p = _path(workspace)
    if not p.is_file():
        return {"enabled": False}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"enabled": False}
    if not isinstance(raw, dict):
        return {"enabled": False}
    return {"enabled": bool(raw.get("enabled"))}


def save(workspace: Path, *, enabled: bool) -> dict[str, Any]:
    data = {"enabled": bool(enabled)}
    p = _path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(p, data)
    return data


def is_enabled(workspace: Path) -> bool:
    return bool(load(workspace).get("enabled"))


def admin_allows() -> bool:
    from . import admin_policy
    return admin_policy.feature_enabled("web_egress")


def effective_enabled(workspace: Path) -> bool:
    """User toggle AND admin allow. Default off."""
    if not admin_allows():
        return False
    return is_enabled(workspace)


def public_view(workspace: Path) -> dict[str, Any]:
    admin = admin_allows()
    enabled = bool(admin and is_enabled(workspace))
    return {
        "enabled": enabled,
        "admin_allows": admin,
        "requested": is_enabled(workspace),
        "workspace": str(workspace),
    }
