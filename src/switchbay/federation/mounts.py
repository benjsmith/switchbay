"""Per-workspace graph mount configuration.

The file is ``<workspace>/.workbench/graph-mounts.json``. It holds no
tokens. Okstratr seats see the same file because they call Switchbay's
tools, which read it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import atomicio

SCHEMA = "switchbay-graph-mounts/1"
_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,40}$")
_WRITE = {"none", "propose", "direct"}
_TRUST = {"own", "org", "external"}
_KINDS = {"local", "snapshot", "live"}


@dataclass
class Mount:
    id: str
    graph_id: str
    kind: str
    url: str = ""
    ref: str = ""
    read: bool = True
    write: str = "none"
    trust: str = "external"
    ceiling: str = "public"
    auth: str = "anonymous"
    refresh: str = "manual"

    def as_dict(self) -> dict[str, Any]:
        row = {
            "id": self.id,
            "graph_id": self.graph_id,
            "kind": self.kind,
            "read": self.read,
            "write": self.write,
            "trust": self.trust,
            "ceiling": self.ceiling,
        }
        if self.url:
            row["url"] = self.url
        if self.ref:
            row["ref"] = self.ref
        if self.kind == "live":
            row["auth"] = self.auth
        if self.refresh != "manual":
            row["refresh"] = self.refresh
        return row


@dataclass
class Source:
    id: str
    kind: str
    url: str = ""
    auth: str = "oauth"
    classification: str = "confidential"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "kind": self.kind, "url": self.url,
            "auth": self.auth, "classification": self.classification,
        }


@dataclass
class Config:
    mounts: list[Mount] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    read_default: list[str] = field(default_factory=lambda: ["local"])
    default_write: str = "local"
    direct_writes: bool = False

    def get(self, mount_id: str) -> Mount | None:
        for mount in self.mounts:
            if mount.id == mount_id:
                return mount
        return None


def config_path(workspace: Path) -> Path:
    return workspace / ".workbench" / "graph-mounts.json"


def _local_mount(workspace: Path) -> Mount:
    name = workspace.name or "workspace"
    return Mount(
        id="local",
        graph_id=f"ceg://local/{name}",
        kind="local",
        read=True,
        write="direct",
        trust="own",
        ceiling="restricted",
        auth="anonymous",
    )


def _mount_from(row: dict[str, Any]) -> Mount | None:
    mid = str(row.get("id") or "").strip()
    kind = str(row.get("kind") or "").strip()
    if not _ID_RE.match(mid) or kind not in _KINDS or mid == "local":
        return None
    write = str(row.get("write") or "none")
    if write not in _WRITE:
        write = "none"
    trust = str(row.get("trust") or "external")
    if trust not in _TRUST:
        trust = "external"
    auth = str(row.get("auth") or ("oauth" if kind == "live" else "anonymous"))
    if auth not in ("anonymous", "oauth", "dev"):
        auth = "oauth"
    return Mount(
        id=mid,
        graph_id=str(row.get("graph_id") or ""),
        kind=kind,
        url=str(row.get("url") or ""),
        ref=str(row.get("ref") or ""),
        read=bool(row.get("read", True)),
        write=write,
        trust=trust,
        ceiling=str(row.get("ceiling") or "public"),
        auth=auth,
        refresh=str(row.get("refresh") or "manual"),
    )


def _source_from(row: dict[str, Any]) -> Source | None:
    sid = str(row.get("id") or "").strip()
    kind = str(row.get("kind") or "").strip()
    if not _ID_RE.match(sid) or not kind:
        return None
    return Source(
        id=sid,
        kind=kind,
        url=str(row.get("url") or ""),
        auth=str(row.get("auth") or "oauth"),
        classification=str(row.get("classification") or "confidential"),
    )


def load(workspace: Path) -> Config:
    cfg = Config(mounts=[_local_mount(workspace)])
    path = config_path(workspace)
    if not path.is_file():
        return cfg
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return cfg
    if not isinstance(data, dict):
        return cfg
    read_default = data.get("read_default")
    if isinstance(read_default, list) and read_default:
        cfg.read_default = [str(x) for x in read_default]
    write = str(data.get("default_write") or "local")
    cfg.default_write = write if write in ("local", "remote", "both") else "local"
    cfg.direct_writes = bool(data.get("direct_writes", False))
    for row in data.get("mounts") or []:
        if isinstance(row, dict):
            mount = _mount_from(row)
            if mount is not None:
                cfg.mounts.append(mount)
    for row in data.get("sources") or []:
        if isinstance(row, dict):
            source = _source_from(row)
            if source is not None:
                cfg.sources.append(source)
    return cfg


def save(workspace: Path, cfg: Config) -> None:
    from . import policy
    path = config_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    mounts = []
    for mount in cfg.mounts:
        if mount.id == "local":
            continue
        reason = policy.mount_block_reason(mount)
        if reason:
            raise ValueError(reason)
        mounts.append(mount.as_dict())
    payload = {
        "schema": SCHEMA,
        "default_write": cfg.default_write,
        "direct_writes": cfg.direct_writes,
        "read_default": cfg.read_default or ["local"],
        "mounts": mounts,
        "sources": [source.as_dict() for source in cfg.sources],
    }
    atomicio.write_json_atomic(path, payload)


def selected_ids(workspace: Path, payload: dict[str, Any] | None) -> list[str] | None:
    """Mount ids to read. None means 'local only, use the existing path'."""
    cfg = load(workspace)
    raw = None if payload is None else payload.get("graphs")
    if raw in (None, "", []):
        ids = list(cfg.read_default or ["local"])
    elif raw == "all":
        ids = [mount.id for mount in cfg.mounts if mount.read]
    elif isinstance(raw, str):
        ids = [part.strip() for part in raw.split(",") if part.strip()]
    elif isinstance(raw, list):
        ids = [str(part).strip() for part in raw if str(part).strip()]
    else:
        ids = ["local"]
    known = {mount.id for mount in cfg.mounts}
    ids = [mid for mid in ids if mid in known]
    if not ids:
        ids = ["local"]
    if ids == ["local"]:
        return None
    return ids


def split_ref(ref: str, cfg: Config) -> tuple[str, str]:
    """Return (mount id, path). A bare path is local."""
    text = (ref or "").strip().strip("/")
    if text.startswith("[[") and text.endswith("]]"):
        text = text[2:-1].strip()
    ids = {mount.id for mount in cfg.mounts}
    if ":" in text:
        mount, _, path = text.partition(":")
        if mount in ids and path:
            return mount, path.lstrip("/")
    return "local", text
