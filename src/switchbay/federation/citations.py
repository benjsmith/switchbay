"""Resolve ``(graph:<mount>/<path>@<rev>)`` against a snapshot or cache.

A live mount that was read at ``rev`` has a cache file. If that file is
missing, the citation is stale rather than accepted. A snapshot citation
must name the revision the snapshot was pinned to.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .. import statedir
from .mounts import load


def parse(body: str) -> tuple[str, str, str]:
    text = (body or "").strip()
    mount, _, rest = text.partition("/")
    path, _, rev = rest.rpartition("@")
    if not path:
        path, rev = rest, ""
    if path.endswith(".md"):
        path = path[:-3]
    return mount.strip(), path.strip().lstrip("/"), rev.strip()


def _cache_root(workspace: Path, mount: str) -> Path:
    digest = hashlib.sha256(str(workspace.resolve()).encode()).hexdigest()[:16]
    return statedir.state_root() / "graph-cache" / digest / mount


def cache_page(workspace: Path, mount: str, rev: str, path: str, page: dict) -> Path:
    dest = _cache_root(workspace, mount) / rev / f"{path}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(page), encoding="utf-8")
    return dest


def cached_page(workspace: Path, mount: str, rev: str, path: str) -> dict | None:
    dest = _cache_root(workspace, mount) / rev / f"{path}.json"
    if not dest.is_file():
        return None
    try:
        data = json.loads(dest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def cached_label(workspace: Path, body: str) -> str:
    mount, path, rev = parse(body)
    page = cached_page(workspace, mount, rev, path)
    if not page:
        return ""
    return str(page.get("classification") or "public")


def graph_problem(workspace: Path, body: str) -> str:
    """Empty string when the citation resolves, otherwise a problem phrase."""
    mount_id, path, rev = parse(body)
    if not mount_id or not path or not rev:
        return "is missing a mount, path, or revision"
    cfg = load(workspace)
    mount = cfg.get(mount_id)
    if mount is None:
        return f"names unknown mount {mount_id}"
    if mount.kind == "local":
        page = workspace / "wiki" / f"{path}.md"
        if not page.is_file():
            return f"is missing page {path}"
        return ""
    if mount.kind == "snapshot":
        from .snapshot import pinned
        snap = pinned(workspace, mount)
        if snap is None:
            return "is stale and unverifiable"
        if snap.rev != rev:
            return f"is not at revision {rev} (snapshot is {snap.rev})"
        if not (snap.wiki / f"{path}.md").is_file():
            return f"is missing page {path}"
        return ""
    page = cached_page(workspace, mount_id, rev, path)
    if page is None:
        return "is stale and unverifiable"
    if str(page.get("path") or "") not in (path, path + ".md"):
        return f"is missing page {path}"
    return ""
