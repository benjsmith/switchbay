"""Synced folders are allowed only inside an explicit trust-boundary list.

Enterprise refuses a workspace or a chat-history file that sits in a
cloud-synced folder unless that path is under ``paths.trust_boundary``
in the admin file. Other profiles do not apply this check.
"""

from __future__ import annotations

import os
from pathlib import Path

from .. import admin_policy
from .policy import cloud_sync_name


class TrustBoundaryError(ValueError):
    pass


def allowlist() -> list[str]:
    paths = admin_policy.load().get("paths") or {}
    raw = paths.get("trust_boundary") or []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item).strip()]


def block_reason(path: Path) -> str:
    if admin_policy.profile() != "enterprise":
        return ""
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        resolved = path.expanduser()
    if not cloud_sync_name(resolved):
        return ""
    text = str(resolved)
    for prefix in allowlist():
        try:
            root = str(Path(prefix).expanduser().resolve())
        except OSError:
            root = str(Path(prefix).expanduser())
        if text == root or text.startswith(root + os.sep):
            return ""
    service = cloud_sync_name(resolved) or "a synced folder"
    return f"{text} is in {service}, outside the trust boundary"


def require(path: Path) -> None:
    reason = block_reason(path)
    if reason:
        raise TrustBoundaryError(reason)
