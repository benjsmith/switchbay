"""One door for external MCP sources.

Every call is recorded in the machine-local capture buffer. The record
does not live in the workspace, so sharing the workspace does not share
the payload. A snapshot copies one capture into ``vault/ext`` when a
page is going to cite it.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .. import statedir
from . import adapters, audit, policy
from .adapters import FakeTransport, Transport
from .mounts import Source, load

_BEGIN = "<!-- BEGIN FETCHED CONTENT source-capture -->"
_END = "<!-- END FETCHED CONTENT -->"


def _dir(workspace: Path) -> Path:
    digest = hashlib.sha256(str(workspace.resolve()).encode()).hexdigest()[:16]
    return statedir.state_root() / "captures" / digest


def _capture_id(source: str, tool: str, arguments: dict) -> str:
    blob = json.dumps({"source": source, "tool": tool, "arguments": arguments}, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20]


def capture_label(workspace: Path, capture_id: str) -> str:
    path = _dir(workspace) / f"{capture_id}.json"
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(data.get("classification") or "")


def call(
    workspace: Path, source_id: str, tool: str, arguments: dict[str, Any] | None = None,
    *, transport: Transport | None = None, snapshot: bool = False,
) -> dict[str, Any]:
    cfg = load(workspace)
    source = next((item for item in cfg.sources if item.id == source_id), None)
    if source is None:
        return {"ok": False, "error": f"unknown source {source_id}"}
    if not policy.source_allowed(source.kind, source.url):
        audit.record(workspace, "refused_write", why="source not allowed", source=source_id)
        return {"ok": False, "error": "source is not on the admin allowlist"}
    reads, acts = adapters.tools_for(source.kind)
    if tool not in reads and tool not in acts:
        return {"ok": False, "error": f"{source.kind} has no tool {tool}"}
    if tool in acts and not policy.act_tools_allowed():
        audit.record(workspace, "refused_write", why="act tool hidden", source=source_id, tool=tool)
        return {"ok": False, "error": f"{tool} is hidden until admin policy enables act tools"}
    arguments = arguments or {}
    transport = transport or FakeTransport()
    raw = transport.call(tool, arguments)
    normalised = adapters.normalise(source.kind, tool, raw if isinstance(raw, dict) else {"text": str(raw)})
    if normalised["policy_outcome"] == "denied":
        audit.record(
            workspace, "source_call", source=source_id, tool=tool,
            policy_outcome="denied",
        )
        return {
            "ok": False,
            "policy_outcome": "denied",
            "error": f"{source.kind} policy blocked this read",
            "message": normalised["message"],
        }
    label = adapters.inherited_label(
        source.classification, raw if isinstance(raw, dict) else {},
    )
    cid = _capture_id(source.id, tool, arguments)
    record = {
        "capture_id": cid,
        "source": f"{source.kind}:{source.id}",
        "server_url": source.url,
        "tool": tool,
        "arguments": arguments,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "result_sha256": hashlib.sha256(json.dumps(normalised, sort_keys=True).encode()).hexdigest(),
        "deep_links": normalised["deep_links"],
        "classification": label,
        "needs_classification": not bool(label),
        "policy_outcome": "allowed",
        "text": normalised["text"],
        "rows": normalised["rows"],
    }
    from . import review_queue, secure
    if not label:
        review_queue.add(workspace, {
            "id": cid,
            "title": f"{source.kind} {tool}",
            "kind": "capture",
            "source": record["source"],
        })
    dest = _dir(workspace)
    secure.owner_dir(dest)
    secure.owner_write(dest / f"{cid}.json", json.dumps(record))
    audit.record(
        workspace, "source_call", source=source_id, tool=tool,
        capture_id=cid, policy_outcome="allowed",
    )
    out: dict[str, Any] = {
        "ok": True,
        "capture_id": cid,
        "citation": f"(capture:{cid})",
        "classification": label,
        "needs_classification": not bool(label),
        "usable": bool(label) or not review_queue.mandatory(workspace),
        "text": normalised["text"],
        "rows": normalised["rows"],
        "deep_links": normalised["deep_links"],
        "policy_outcome": "allowed",
    }
    if snapshot:
        blocked = policy.synced_workspace_block(workspace)
        if blocked or not policy.snapshot_allowed():
            audit.record(workspace, "refused_write", why=blocked or "snapshots forbidden", capture_id=cid)
            out["snapshot"] = None
            out["snapshot_error"] = blocked or "snapshots are forbidden by admin policy"
        else:
            out["snapshot"] = write_snapshot(workspace, source, record)
            audit.record(workspace, "snapshot", capture_id=cid, path=out["snapshot"])
    return out


def write_snapshot(workspace: Path, source: Source, record: dict) -> str:
    day = record["ts"][:10]
    rel = f"vault/ext/{source.kind}/{day}/{record['capture_id']}.md"
    path = workspace / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        "type: source",
        "untrusted: true",
        f"classification: {record['classification']}",
        f"capture_id: {record['capture_id']}",
        f"capture_source: {record['source']}",
        f"capture_tool: {record['tool']}",
        f"source_url: {record.get('server_url') or source.kind}",
        f"sha256: {record['result_sha256']}",
        "---",
        "",
        _BEGIN,
        str(record.get("text") or ""),
        "",
    ]
    if record.get("rows"):
        lines.append(json.dumps(record["rows"], indent=2))
    lines.append(_END)
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return rel
