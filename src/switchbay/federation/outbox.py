"""Remote writes. A change is a proposal unless the remote grants a
direct write and the workspace has turned direct writes on.

The outbox is append-only. The change id is the hash of the graph, the
path, the base revision, and the normalised content, so a retry does
not create a second proposal.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import audit, classify, live, ontology
from .live import GraphError
from .mounts import load
from .policy import effective_write


def _path(workspace: Path) -> Path:
    return workspace / ".workbench" / "state" / "graph-outbox.jsonl"


def _read(workspace: Path) -> list[dict[str, Any]]:
    path = _path(workspace)
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _append(workspace: Path, row: dict[str, Any]) -> None:
    path = _path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def change_id(graph_id: str, path: str, base_rev: str, content: str) -> str:
    blob = "\n".join([graph_id, path, base_rev, content.strip()])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def submit(
    workspace: Path, *, mount_id: str, path: str, content: str,
    base_rev: str, mode: str, title: str = "", base_content: str = "",
    public_write_choice: str = "",
) -> dict[str, Any]:
    cfg = load(workspace)
    mount = cfg.get(mount_id)
    if mount is None or mount.kind == "local":
        return {"ok": False, "error": "name a remote mount"}
    if mount.write == "none":
        audit.record(workspace, "refused_write", mount=mount_id, why="mount is read-only", path=path)
        return {"ok": False, "error": f"{mount_id} does not accept writes"}
    adapted, notes = ontology.adapt_for(workspace, mount, content)
    content = adapted
    block = classify.refuses(workspace, content, mount.ceiling)
    if block:
        audit.record(workspace, "refused_write", mount=mount_id, why=block, path=path)
        return {"ok": False, "error": block}
    from .public_write import confirm, gate
    content_label = classify.derived(workspace, content)
    decision = gate(workspace, mount_id=mount.id, ceiling=content_label if content_label == "public" else mount.ceiling)
    if content_label == "public" and mount.ceiling == "public":
        if decision.get("needs_dialog"):
            if not public_write_choice:
                return decision
            confirmed = confirm(workspace, public_write_choice, mount_id=mount.id)
            if not confirmed.get("ok"):
                return confirmed
        elif not decision.get("ok", True):
            return decision
    if mount.ceiling == "public":
        gate = ontology.presidio_note(content)
        if gate.get("blocked"):
            audit.record(workspace, "refused_write", mount=mount_id, why="presidio", path=path)
            return {"ok": False, "error": "presidio gate refused a public write"}
    remote_direct = False
    if mount.kind == "live":
        try:
            info = live.info(workspace, mount)
            remote_direct = bool((info.get("rights") or {}).get("direct_granted"))
            if not base_rev:
                base_rev = str(info.get("rev") or "")
        except GraphError as exc:
            audit.record(workspace, "refused_write", mount=mount_id, why=str(exc), path=path)
            return {"ok": False, "error": f"{mount_id} unreachable: {exc}"}
    rights = effective_write(mount, remote_direct=remote_direct, workspace_direct=cfg.direct_writes)
    if rights == "none":
        audit.record(workspace, "refused_write", mount=mount_id, why="policy", path=path)
        return {"ok": False, "error": "admin policy forbids this write"}
    cid = change_id(mount.graph_id, path, base_rev, content)
    for existing in _read(workspace):
        if existing.get("change_id") == cid:
            return {"ok": True, "duplicate": True, "change_id": cid, "state": existing.get("state")}
    local_proposal = None
    if mode == "both":
        from .. import proposals
        local_proposal = proposals.add(
            workspace, op="create", kind="concept", title=title or Path(path).stem,
            body=content, path=f"wiki/{path}.md" if not path.endswith(".md") else f"wiki/{path}",
        )
    proposal = {"state": "queued", "note": ""}
    if mount.kind == "live":
        try:
            proposal = live.propose(workspace, mount, {
                "path": path, "content": content, "base_rev": base_rev,
                "mode": "direct" if rights == "direct" else "propose",
            })
        except GraphError as exc:
            proposal = {"state": "queued", "note": str(exc)}
    if proposal.get("state") == "conflict":
        theirs = ""
        if mount.kind == "live":
            try:
                fetched = live.read_page(workspace, mount, path)
                fm = fetched.get("frontmatter") or {}
                lines = ["---"]
                if isinstance(fm, dict):
                    for key, value in fm.items():
                        lines.append(f"{key}: {value}")
                lines += ["---", "", str(fetched.get("body") or "")]
                theirs = "\n".join(lines)
            except GraphError:
                theirs = ""
        merged = ontology.merge_conflict(
            workspace, mount, path, content, base_rev,
            base_text=base_content, theirs_text=theirs,
        )
        proposal["merge"] = merged
        if not merged.get("merged"):
            _conflict_card(workspace, mount_id, path, merged)
    row = {
        "change_id": cid,
        "mount": mount_id,
        "graph_id": mount.graph_id,
        "path": path,
        "base_rev": base_rev,
        "state": proposal.get("state") or "queued",
        "proposal_id": proposal.get("proposal_id"),
        "mode": mode,
        "rights": rights,
        "ontology": notes,
        "local_proposal": None if local_proposal is None else local_proposal.get("id"),
    }
    _append(workspace, row)
    audit.record(
        workspace, "remote_proposal", mount=mount_id, change_id=cid,
        state=row["state"], path=path,
    )
    return {"ok": True, **row, "note": proposal.get("note") or ""}


def _conflict_card(workspace: Path, mount_id: str, path: str, merged: dict) -> None:
    from .. import proposals
    entries = proposals.list_proposals(workspace)
    entries.append({
        "id": f"conflict-{merged.get('change_id', path)[:8]}",
        "op": "conflict",
        "kind": "concept",
        "title": f"Conflict on {mount_id}:{path}",
        "path": f"wiki/{path}.md",
        "body": merged.get("ours") or "",
        "theirs": merged.get("theirs") or "",
        "status": "conflict",
        "created_at": 0,
        "review": {"one_line": "Both copies of this page changed. Neither was overwritten."},
        "written": False,
    })
    proposals._save(workspace, entries)


def list_entries(workspace: Path) -> list[dict[str, Any]]:
    return _read(workspace)
