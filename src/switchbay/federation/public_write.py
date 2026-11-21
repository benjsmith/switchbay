"""Public writes when Presidio is not scanning.

Enterprise defaults: public writes are off except configured
connections, and Presidio is required. A person can turn Presidio off
for one workspace unless an admin has taken that control away. With
no Presidio and no remembered allow, the caller must show OK / Always
allow / Cancel. Always allow is stored as a global rule. The person
can later move that rule to the workspace.
"""

from __future__ import annotations

import getpass
import json
import uuid
from pathlib import Path
from typing import Any

from .. import admin_policy, atomicio, workspaces
from . import audit

GUIDANCE = (
    "Presidio is off in this workspace, so public writes are not scanned "
    "for personal data. You are responsible for complying with the "
    "policies and regulations that apply."
)


def _enterprise() -> bool:
    return admin_policy.profile() == "enterprise"


def _section() -> dict:
    raw = admin_policy.load().get("public_writes")
    base = {
        "allowed": not _enterprise(),
        "presidio_required": _enterprise(),
        "user_control": True,
        "enabled_users": [],
        "connections": [],
    }
    if isinstance(raw, dict):
        base.update(raw)
    return base


def presidio_installed() -> bool:
    try:
        import presidio_analyzer  # noqa: F401
        return True
    except ImportError:
        return False


def user_may_toggle() -> bool:
    section = _section()
    if not _enterprise():
        return True
    return bool(section.get("user_control", True))


def presidio_enabled_for_user(workspace: Path) -> bool:
    """Whether scanning should run for this person in this workspace."""
    section = _section()
    user = getpass.getuser()
    if _enterprise() and not section.get("user_control", True):
        enabled = {str(item) for item in (section.get("enabled_users") or [])}
        return user in enabled
    return _workspace_flag(workspace)


def _workspace_flag(workspace: Path) -> bool:
    path = workspace / ".workbench" / "presidio.json"
    if not path.is_file():
        return True
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    if isinstance(data, dict) and "enabled" in data:
        return bool(data["enabled"])
    return True


def set_workspace_presidio(workspace: Path, enabled: bool) -> dict:
    if not user_may_toggle():
        return {"ok": False, "error": "an admin controls Presidio for this install"}
    path = workspace / ".workbench" / "presidio.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(path, {"enabled": bool(enabled)})
    audit.record(workspace, "presidio", enabled=bool(enabled), user=getpass.getuser())
    return {"ok": True, "enabled": bool(enabled), "guidance": GUIDANCE if not enabled else ""}


def _rules_path(scope: str, workspace: Path | None) -> Path:
    if scope == "workspace":
        if workspace is None:
            raise ValueError("workspace scope needs a workspace")
        return workspace / ".workbench" / "public-write-rules.json"
    return workspaces.config_dir() / "public-write-rules.json"


def list_rules(workspace: Path) -> list[dict[str, str]]:
    rows = []
    for scope, path in (
        ("global", _rules_path("global", None)),
        ("workspace", _rules_path("workspace", workspace)),
    ):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, list):
            continue
        for row in data:
            if isinstance(row, dict):
                rows.append({
                    "id": str(row.get("id") or ""),
                    "description": str(row.get("description") or "Public write without Presidio"),
                    "decision": "allow",
                    "scope": scope,
                })
    return rows


def remember_always(workspace: Path, *, scope: str = "global") -> dict:
    if scope not in ("global", "workspace"):
        scope = "global"
    path = _rules_path(scope, workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                rows = loaded
        except (OSError, json.JSONDecodeError):
            rows = []
    row = {
        "id": uuid.uuid4().hex[:8],
        "description": "Public write without Presidio",
        "decision": "allow",
        "scope": scope,
    }
    rows.append(row)
    atomicio.write_json_atomic(path, rows)
    audit.record(workspace, "public_write_allow", scope=scope, rule_id=row["id"])
    return row


def set_rule_scope(workspace: Path, rule_id: str, scope: str) -> dict:
    if scope not in ("global", "workspace"):
        return {"ok": False, "error": "scope must be global or workspace"}
    rules = list_rules(workspace)
    found = next((row for row in rules if row["id"] == rule_id), None)
    if found is None:
        return {"ok": False, "error": "no such rule"}
    for old in ("global", "workspace"):
        path = _rules_path(old, workspace)
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, list):
            continue
        kept = [row for row in data if str(row.get("id")) != rule_id]
        atomicio.write_json_atomic(path, kept)
    found["scope"] = scope
    path = _rules_path(scope, workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                existing = loaded
        except (OSError, json.JSONDecodeError):
            existing = []
    existing.append(found)
    atomicio.write_json_atomic(path, existing)
    return {"ok": True, "rule": found}


def _always(workspace: Path) -> bool:
    return any(row["decision"] == "allow" for row in list_rules(workspace))


def connection_allowed(mount_id: str) -> bool:
    section = _section()
    if section.get("allowed", True):
        return True
    return mount_id in {str(item) for item in (section.get("connections") or [])}


def gate(workspace: Path, *, mount_id: str, ceiling: str) -> dict[str, Any]:
    """Decide whether a public write may proceed."""
    if ceiling != "public":
        return {"ok": True}
    if not connection_allowed(mount_id):
        audit.record(workspace, "refused_write", why="public writes are not allowed", mount=mount_id)
        return {"ok": False, "error": "public writes are limited to configured connections"}
    if not presidio_enabled_for_user(workspace):
        return {"ok": True, "presidio": "off", "guidance": GUIDANCE}
    if presidio_installed():
        return {"ok": True, "presidio": "scanned"}
    if _section().get("presidio_required") and _enterprise() and not _always(workspace):
        # Required, but the person can still take responsibility unless
        # an admin removed that control. The dialog is that responsibility.
        pass
    if _always(workspace):
        return {"ok": True, "presidio": "always-allow"}
    return {
        "ok": False,
        "needs_dialog": True,
        "error": "confirm this public write is free of personal data",
        "choices": ["ok", "always", "cancel"],
    }


def confirm(workspace: Path, choice: str, *, mount_id: str) -> dict:
    if choice == "cancel":
        audit.record(workspace, "refused_write", why="public write cancelled", mount=mount_id)
        return {"ok": False, "error": "cancelled"}
    if choice == "always":
        rule = remember_always(workspace, scope="global")
        return {"ok": True, "rule": rule}
    if choice == "ok":
        audit.record(workspace, "public_write_allow", scope="once", mount=mount_id)
        return {"ok": True, "once": True}
    return {"ok": False, "error": "choice must be ok, always, or cancel"}
