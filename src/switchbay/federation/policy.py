"""Admin limits for mounts and sources.

The daemon never writes the admin file. Open-profile defaults allow
mounts. The enterprise profile allows a mount only when its graph id
or URL matches the allowlist, refuses public mounts unless
``allow_public`` is set, and forces remote writes to proposals.
"""

from __future__ import annotations

from pathlib import Path

from .. import admin_policy
from .mounts import Mount

_OPEN_MOUNTS = {
    "enabled": True,
    "allowlist": ["*"],
    "allow_public": True,
    "remote_write": "propose",
    "max_ceiling_by_trust": {
        "external": "public",
        "org": "confidential",
        "own": "restricted",
    },
}
_ENTERPRISE_MOUNTS = {
    "enabled": True,
    "allowlist": [],
    "allow_public": False,
    "remote_write": "propose",
    "max_ceiling_by_trust": {
        "external": "public",
        "org": "confidential",
        "own": "restricted",
    },
}
_OPEN_SOURCES = {
    "enabled": True,
    "allowlist": ["*"],
    "allow_act_tools": False,
    "snapshot": "allowed",
    "declassify": "allow",
    "capture_retention_days": 0,
}
_ENTERPRISE_SOURCES = {
    "enabled": True,
    "allowlist": [],
    "allow_act_tools": False,
    "snapshot": "allowed",
    "declassify": "forbid",
    "capture_retention_days": 0,
}


def _merged(name: str, open_default: dict, enterprise_default: dict) -> dict:
    base = dict(enterprise_default if admin_policy.profile() == "enterprise" else open_default)
    raw = admin_policy.load().get(name)
    if isinstance(raw, dict):
        base.update(raw)
    return base


def mounts_policy() -> dict:
    return _merged("graph_mounts", _OPEN_MOUNTS, _ENTERPRISE_MOUNTS)


def sources_policy() -> dict:
    return _merged("sources", _OPEN_SOURCES, _ENTERPRISE_SOURCES)


def _allowed(value: str, allow) -> bool:
    if allow == "*":
        return True
    if isinstance(allow, str):
        allow = [allow]
    if not allow:
        return False
    return admin_policy._ref_allowed(value, list(allow))


def mount_block_reason(mount: Mount) -> str:
    policy = mounts_policy()
    if not policy.get("enabled", True):
        return "graph mounts are disabled by admin policy"
    if mount.kind == "local":
        return ""
    if mount.trust == "external" and not policy.get("allow_public", True):
        return "public mounts are disabled by admin policy"
    blob = mount.graph_id or mount.url
    if not _allowed(blob, policy.get("allowlist")) and not _allowed(mount.url, policy.get("allowlist")):
        return "graph is not on the admin allowlist"
    if mount.url.startswith(("http://", "https://")) and not admin_policy.egress_allowed(mount.url):
        return "graph host is not on the egress allowlist"
    forced = str(policy.get("remote_write") or "propose")
    if forced == "none" and mount.write != "none":
        return "admin policy forbids remote writes"
    if forced == "propose" and mount.write == "direct":
        return "admin policy forces remote writes to stay proposals"
    return ""


def effective_write(mount: Mount, *, remote_direct: bool, workspace_direct: bool) -> str:
    """What a write to this mount may do."""
    if mount.write == "none":
        return "none"
    forced = str(mounts_policy().get("remote_write") or "propose")
    if forced == "none":
        return "none"
    if mount.write == "direct" and remote_direct and workspace_direct and forced != "propose":
        return "direct"
    if forced == "propose":
        return "propose"
    if mount.write == "direct" and remote_direct and workspace_direct:
        return "direct"
    return "propose"


def source_allowed(kind: str, url: str) -> bool:
    policy = sources_policy()
    if not policy.get("enabled", True):
        return False
    allow = policy.get("allowlist")
    return _allowed(kind, allow) or _allowed(url, allow) or _allowed(f"{kind} {url}", allow)


def act_tools_allowed() -> bool:
    return bool(sources_policy().get("allow_act_tools", False))


def declassify_allowed() -> bool:
    return str(sources_policy().get("declassify") or "allow") != "forbid"


def snapshot_allowed() -> bool:
    return str(sources_policy().get("snapshot") or "allowed") != "forbid"


def cloud_sync_name(path: Path) -> str | None:
    """Name of a cloud-sync root in ``path``, ignoring ordinary home folders."""
    text = str(path)
    if "Mobile Documents" in text or "/Library/CloudStorage/iCloud" in text:
        return "iCloud"
    low = text.lower()
    if "onedrive" in low:
        return "OneDrive"
    if "dropbox" in low:
        return "Dropbox"
    if "google drive" in low or "googledrive" in low:
        return "Google Drive"
    return None


def synced_workspace_block(workspace: Path) -> str:
    if admin_policy.allow_synced_workspaces():
        return ""
    name = cloud_sync_name(workspace)
    if not name:
        return ""
    return (
        f"this workspace is in {name}; snapshots of external data "
        "are refused so they are not synced off this machine"
    )
