"""Page proposals — the local model's write path, gated by review.

The rail tool registry is read-only for the wiki (search/read/list), so
the local model can't mutate it directly. That's deliberate: a small
model confidently hallucinates specifics (a fabricated scaling exponent,
HBM mis-defined) and once reached to *delete* a charter it had read a
"preserve" ruling for. So it PROPOSES, it doesn't mutate:

  propose_wiki_page / propose_page_edit  →  a proposal here (status
  "proposed")  →  a strong reviewer auto-vets it (accept | edit |
  reject)  →  a rail review card  →  accept writes the page.

Store: `<workspace>/.workbench/state/page_proposals.json` (machine-local
state, regenerable; never on a sync service). Mirrors the D9 decisions
sidecar shape so the two review flows feel the same.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any
from . import atomicio

# kind → wiki subfolder. CE's standard layout (see a real curiosity
# workspace): concepts/ entities/ analyses/ facts/ evidence/ sources/.
KIND_FOLDER = {
    "concept": "concepts",
    "entity": "entities",
    "analysis": "analyses",
    "fact": "facts",
    "evidence": "evidence",
    "source": "sources",
    "note": "notes",
}
TAG = {"concept": "con", "entity": "ent", "analysis": "ana",
       "fact": "fact", "evidence": "ev", "source": "src", "note": "note"}

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    return _SLUG_RE.sub("-", (name or "").strip().lower()).strip("-") or "untitled"


def _store(workspace: Path) -> Path:
    return workspace / ".workbench" / "state" / "page_proposals.json"


def list_proposals(workspace: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(_store(workspace).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _save(workspace: Path, entries: list[dict[str, Any]]) -> None:
    p = _store(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(p, entries)


def get(workspace: Path, pid: str) -> dict[str, Any] | None:
    return next((e for e in list_proposals(workspace) if e.get("id") == pid), None)


def update(workspace: Path, pid: str, **fields: Any) -> dict[str, Any] | None:
    entries = list_proposals(workspace)
    out = None
    for e in entries:
        if e.get("id") == pid:
            e.update(fields)
            out = e
            break
    if out is not None:
        _save(workspace, entries)
    return out


def target_path(workspace: Path, kind: str, title: str) -> Path:
    folder = KIND_FOLDER.get(kind, "notes")
    return workspace / "wiki" / folder / f"{slugify(title)}.md"


def add(
    workspace: Path, *, op: str, kind: str, title: str, body: str,
    path: str | None = None, ts: float | None = None,
) -> dict[str, Any]:
    """Record a proposal (status 'proposed'). `op` is 'create' or 'edit'.
    For 'create' the target is derived from kind+title; for 'edit' the
    caller supplies the existing page `path` (repo-relative)."""
    if op == "edit" and path:
        rel = path if path.startswith("wiki/") else f"wiki/{path.lstrip('/')}"
    else:
        rel = str(target_path(workspace, kind, title).relative_to(workspace))
    entry = {
        "id": f"prop-{uuid.uuid4().hex[:8]}",
        "op": op,
        "kind": kind,
        "title": title,
        "path": rel,
        "body": body,
        "status": "proposed",           # proposed → accepted | dismissed
        "created_at": ts if ts is not None else time.time(),
        "review": None,                 # {verdict, confidence, issues, one_line}
    }
    entries = list_proposals(workspace)
    entries.append(entry)
    _save(workspace, entries)
    return entry


def accept(workspace: Path, pid: str) -> dict[str, Any] | None:
    """Write the proposed page (create or overwrite the edit target),
    mark the proposal accepted. Never deletes. Returns the entry."""
    e = get(workspace, pid)
    if e is None or e.get("status") != "proposed":
        return None
    rel = str(e.get("path") or "")
    if not rel.startswith("wiki/") or ".." in rel:
        return update(workspace, pid, status="dismissed",
                      error="unsafe path refused")
    dest = workspace / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text((e.get("body") or "").rstrip() + "\n", encoding="utf-8")
    return update(workspace, pid, status="accepted", accepted_at=time.time())


def dismiss(workspace: Path, pid: str) -> dict[str, Any] | None:
    return update(workspace, pid, status="dismissed", dismissed_at=time.time())
