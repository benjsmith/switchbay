"""Page proposals — provisional wiki writes, reviewed in the Reviews tab.

Curation writes as it goes (status "proposed"). Reject restores the
previous file (or deletes a new one). Comments rewrite the provisional
page. A reviewer card may attach, but never auto-files or auto-reverts.

Store: `<workspace>/.workbench/state/page_proposals.json` (machine-local
state, regenerable; never on a sync service).
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


CHARTER_REL = ".workbench/plan/charter.md"
_COMMENT_HEAD = "\n\n## Review comments\n\n"
_COMMENT_RE = re.compile(r"\n## Review comments\n.*\Z", re.S)


def _posix_rel(rel: str) -> str:
    return (rel or "").replace("\\", "/").lstrip("/")


def _writable_rel(rel: str) -> bool:
    rel = _posix_rel(rel)
    if not rel or ".." in rel.split("/"):
        return False
    return rel.startswith("wiki/") or rel == CHARTER_REL


_SCAFFOLD_BODY_CAP = 2000


def clip_scaffold_body(body: str, *, title: str = "", cap: int = _SCAFFOLD_BODY_CAP) -> str:
    """Keep a local-model draft short enough to be a Reviews scaffold."""
    text = (body or "").strip()
    if len(text) <= cap:
        return text
    cut = text[:cap].rsplit("\n", 1)[0]
    extra = (
        "\n\n## Open questions\n\n"
        "- Draft truncated — too long for a local-model scaffold. "
        "A reviewer should expand from sources, not from the cut-off prose."
    )
    if "## Open questions" in cut:
        extra = "\n\n*(truncated for scaffold cap)*"
    return cut + extra


def add(
    workspace: Path, *, op: str, kind: str, title: str, body: str,
    path: str | None = None, ts: float | None = None,
    scaffold: bool = False,
) -> dict[str, Any]:
    """Record a proposal (status 'proposed'). `op` is 'create' or 'edit'.
    Writes the page immediately (provisional). Reject restores `original`
    or deletes a new file. For 'create' the target is derived from
    kind+title; for 'edit' the caller supplies the existing page `path`
    (repo-relative, or the workspace charter)."""
    if op == "edit" and path:
        rel = _posix_rel(path)
        if rel != CHARTER_REL and not rel.startswith("wiki/"):
            rel = f"wiki/{rel}"
    else:
        rel = target_path(workspace, kind, title).relative_to(workspace).as_posix()
    original: str | None = None
    written = False
    if _writable_rel(rel):
        dest = workspace / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            original = dest.read_text(encoding="utf-8")
        except OSError:
            original = None
        dest.write_text((body or "").rstrip() + "\n", encoding="utf-8")
        written = True
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
        "original": original,           # prior file text; None = new page
        "written": written,             # already on disk (provisional)
        "scaffold": bool(scaffold),     # light outline, not finished prose
    }
    entries = list_proposals(workspace)
    entries.append(entry)
    _save(workspace, entries)
    return entry


def accept(workspace: Path, pid: str) -> dict[str, Any] | None:
    """Keep the provisional page (rewrite if body changed), mark accepted."""
    e = get(workspace, pid)
    if e is None or e.get("status") != "proposed":
        return None
    rel = _posix_rel(str(e.get("path") or ""))
    if not _writable_rel(rel):
        return update(workspace, pid, status="dismissed",
                      error="unsafe path refused")
    dest = workspace / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text((e.get("body") or "").rstrip() + "\n", encoding="utf-8")
    return update(workspace, pid, status="accepted", accepted_at=time.time())


def dismiss(workspace: Path, pid: str) -> dict[str, Any] | None:
    """Reject: revert a provisional write (restore original or delete)."""
    e = get(workspace, pid)
    if e is None or e.get("status") != "proposed":
        return None
    rel = _posix_rel(str(e.get("path") or ""))
    if e.get("written") and _writable_rel(rel):
        dest = workspace / rel
        original = e.get("original")
        if original is None:
            try:
                dest.unlink()
            except OSError:
                pass
        else:
            try:
                dest.write_text(str(original), encoding="utf-8")
            except OSError:
                pass
    return update(workspace, pid, status="dismissed", dismissed_at=time.time())


def apply_comments(workspace: Path, pid: str, comments: str) -> dict[str, Any] | None:
    """Store comments and rewrite the provisional page with them.

    A `## Review comments` section is replaced in-place so the wiki
    reflects the user's notes immediately. Reject still restores
    `original`.
    """
    e = get(workspace, pid)
    if e is None or e.get("status") != "proposed":
        return None
    note = (comments or "").strip()
    body = _COMMENT_RE.sub("", str(e.get("body") or "")).rstrip()
    if note:
        body = body + _COMMENT_HEAD + note + "\n"
    rel = _posix_rel(str(e.get("path") or ""))
    if e.get("written") and _writable_rel(rel):
        dest = workspace / rel
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(body.rstrip() + "\n", encoding="utf-8")
        except OSError:
            pass
    return update(workspace, pid, comments=note, body=body)
