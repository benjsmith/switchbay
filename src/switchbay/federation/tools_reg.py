"""Rail tools for mounts and sources. Registered from tools.py."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..tools import Tool, register
from . import audit, broker, classify, live, outbox, policy, snapshot
from .live import GraphError
from .mounts import load, save, Mount, Source


def _list(workspace: Path, _payload: dict[str, Any]) -> dict[str, Any]:
    cfg = load(workspace)
    rows = []
    for mount in cfg.mounts:
        row = mount.as_dict()
        row["freshness"] = "local"
        if mount.kind == "snapshot":
            snap = snapshot.pinned(workspace, mount)
            if snap is None:
                row["freshness"] = "not fetched"
                row["rev"] = ""
            else:
                row["freshness"] = "pinned"
                row["rev"] = snap.rev
        elif mount.kind == "live":
            try:
                info = live.info(workspace, mount)
                row["freshness"] = "live"
                row["rev"] = info.get("rev") or ""
                row["rights"] = info.get("rights") or {}
            except GraphError as exc:
                row["freshness"] = "unreachable"
                row["error"] = str(exc)
        rows.append(row)
    return {
        "mounts": rows,
        "read_default": cfg.read_default,
        "default_write": cfg.default_write,
        "sources": [source.as_dict() for source in cfg.sources],
    }


def _import(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    from .query import federated_read
    blocked = policy.synced_workspace_block(workspace)
    if blocked:
        audit.record(workspace, "refused_write", why=blocked)
        return {"ok": False, "error": blocked}
    page = str(payload.get("page") or "")
    fetched = federated_read(workspace, {"page": page, "rev": payload.get("rev") or ""})
    if not fetched or fetched.get("error"):
        return {"ok": False, "error": (fetched or {}).get("error") or "page not found"}
    mount_id = str(fetched.get("graph") or "remote")
    rel_path = str(fetched.get("page") or page).split(":", 1)[-1]
    safe = rel_path.replace("/", "__")
    rel = f"vault/ext/graphs/{mount_id}/{safe}.md"
    label = fetched.get("classification") or "public"
    body = (
        "---\n"
        "type: source\n"
        "untrusted: true\n"
        f"classification: {label}\n"
        f"source_url: {fetched.get('graph_id')}@{fetched.get('rev')}\n"
        f"origin: {mount_id}\n"
        "---\n\n"
        "<!-- BEGIN FETCHED CONTENT graph-import -->\n"
        f"{fetched.get('content') or ''}\n"
        "<!-- END FETCHED CONTENT -->\n"
    )
    from .scrub import gate_import
    decision = gate_import(workspace, rel, body)
    if not decision.get("ok"):
        return {"ok": False, "quarantined": True, "path": decision.get("path"), "error": decision.get("error")}
    audit.record(workspace, "snapshot", path=rel, mount=mount_id, rev=fetched.get("rev"))
    return {"ok": True, "path": rel, "citation": f"(vault:{rel})", "classification": label}


def _propose(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    mode = str(payload.get("mode") or "remote")
    if mode not in ("remote", "both"):
        return {"ok": False, "error": "mode must be remote or both"}
    return outbox.submit(
        workspace,
        mount_id=str(payload.get("mount") or ""),
        path=str(payload.get("path") or ""),
        content=str(payload.get("content") or ""),
        base_rev=str(payload.get("base_rev") or ""),
        mode=mode,
        title=str(payload.get("title") or ""),
        base_content=str(payload.get("base_content") or ""),
    )


def _declassify(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    return classify.declassify(workspace, str(payload.get("path") or ""))


def _list_sources(workspace: Path, _payload: dict[str, Any]) -> dict[str, Any]:
    from . import adapters
    cfg = load(workspace)
    rows = []
    for source in cfg.sources:
        reads, acts = adapters.tools_for(source.kind)
        rows.append({
            **source.as_dict(),
            "read_tools": list(reads),
            "act_tools": list(acts) if policy.act_tools_allowed() else [],
            "real_service_testing": "pending",
        })
    return {"sources": rows}


def _call_source(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    arguments = payload.get("arguments") or {}
    if not isinstance(arguments, dict):
        return {"ok": False, "error": "arguments must be an object"}
    return broker.call(
        workspace,
        str(payload.get("source") or ""),
        str(payload.get("tool") or ""),
        arguments,
        snapshot=bool(payload.get("snapshot")),
    )


def register_federated_tools() -> None:
    register(Tool(
        name="list_graph_mounts",
        description=(
            "List graphs mounted on this workspace: id, kind, trust, "
            "revision, and whether a live graph answered."
        ),
        input_schema={"type": "object", "properties": {}},
        handler=_list,
    ))
    register(Tool(
        name="import_graph_page",
        description=(
            "Copy one remote page into vault/ext as an untrusted source. "
            "It does not become a wiki page."
        ),
        input_schema={
            "type": "object",
            "required": ["page"],
            "properties": {
                "page": {"type": "string", "description": "mount:path"},
                "rev": {"type": "string"},
            },
        },
        handler=_import,
    ))
    register(Tool(
        name="propose_graph_write",
        description=(
            "Propose a page to a remote graph. mode remote sends only "
            "the proposal. mode both also writes the local page. Direct "
            "writes happen only when the remote grants them and this "
            "workspace has enabled them."
        ),
        input_schema={
            "type": "object",
            "required": ["mount", "path", "content"],
            "properties": {
                "mount": {"type": "string"},
                "path": {"type": "string"},
                "content": {"type": "string"},
                "base_rev": {"type": "string"},
                "base_content": {"type": "string"},
                "mode": {"type": "string", "enum": ["remote", "both"]},
                "title": {"type": "string"},
            },
        },
        handler=_propose,
    ))
    register(Tool(
        name="declassify_page",
        description=(
            "Lower a page to public. Succeeds when the caller can edit "
            "the page. The change is audited with the user, the page, "
            "and the old and new labels."
        ),
        input_schema={
            "type": "object",
            "required": ["path"],
            "properties": {
                "path": {"type": "string"},
            },
        },
        handler=_declassify,
    ))
    register(Tool(
        name="list_sources",
        description="List external sources configured for this workspace.",
        input_schema={"type": "object", "properties": {}},
        handler=_list_sources,
    ))
    register(Tool(
        name="call_source",
        description=(
            "Call one tool on an external source (Work IQ, Databricks "
            "Genie, AWS Context, AWS Quick) through the broker. The call "
            "is captured. Real services are not contacted unless a "
            "transport is configured; tests use fakes."
        ),
        input_schema={
            "type": "object",
            "required": ["source", "tool"],
            "properties": {
                "source": {"type": "string"},
                "tool": {"type": "string"},
                "arguments": {"type": "object"},
                "snapshot": {"type": "boolean"},
            },
        },
        handler=_call_source,
    ))


def add_mount(workspace: Path, mount: Mount) -> None:
    cfg = load(workspace)
    cfg.mounts = [item for item in cfg.mounts if item.id != mount.id]
    cfg.mounts.append(mount)
    save(workspace, cfg)
    audit.record(workspace, "mount_add", mount=mount.id, kind=mount.kind, graph_id=mount.graph_id)


def add_source(workspace: Path, source: Source) -> None:
    cfg = load(workspace)
    cfg.sources = [item for item in cfg.sources if item.id != source.id]
    cfg.sources.append(source)
    save(workspace, cfg)
