"""Curiosity-engine scripts as Switch Bay tools.

HTTP providers (GitHub Copilot, Anthropic, xAI, local models) have no
shell, so they cannot run CE's ``uv run python3 <skill>/scripts/…``
surface. Copilot additionally sandboxes any shell it *does* spawn, so
the global skill is invisible there.

These tools wrap every CE script the skill documents, running them
in-process via ``cebridge.run_script`` (workspace ``.venv``, pinned
Python). Any model that sees the Switch Bay tool registry can curate
without a CE-aware shell.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import cebridge
from .tools import Tool, register

# Scripts CE's SKILL.md names on the bash allowlist, plus the rest of
# the shipped scripts/ tree we wrap. Dynamic listing (below) still
# wins for newly added scripts; this is the documented contract.
_KNOWN_SCRIPTS = (
    "sweep.py", "graph.py", "vault_search.py", "vault_index.py",
    "local_ingest.py", "lint_scores.py", "score_diff.py", "scrub_check.py",
    "naming.py", "tables.py", "figures.py", "query_router.py",
    "epoch_summary.py", "planner.py", "scan.py", "bootstrap.py",
    "restyle.py", "okf_export.py", "code_repo.py", "entity_gate.py",
    "identifier_cache.py", "identifier_resolve.py", "shape_check.py",
    "derived_cache.py", "activity_log.py", "session_brief.py",
    "session_drainer.py", "embedder.py", "projects.py",
    "curate_status.py", "curate_launch.py", "code_capture.py",
)

_UNSAFE_ARG = re.compile(r"[;&|`$<>\n\r]|\$\(")


def _listed_scripts() -> list[str]:
    root = cebridge.ce_root() / "scripts"
    names: list[str] = []
    try:
        for f in sorted(root.iterdir()):
            if f.is_file() and f.suffix == ".py":
                names.append(f.name)
    except OSError:
        return list(_KNOWN_SCRIPTS)
    return names or list(_KNOWN_SCRIPTS)


def _safe_args(raw: Any) -> tuple[list[str], str | None]:
    if raw is None:
        return [], None
    if isinstance(raw, str):
        parts = raw.split()
    elif isinstance(raw, list):
        parts = [str(a) for a in raw]
    else:
        return [], "args must be a string or list of strings"
    out: list[str] = []
    for a in parts:
        if not a:
            continue
        if _UNSAFE_ARG.search(a):
            return [], f"refusing arg with shell metacharacters: {a!r}"
        out.append(a)
    return out, None


def _ce_run(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    script = str(payload.get("script") or "").strip()
    if script.endswith(".sh"):
        return {"error": "use viewer/setup via dedicated Switch Bay actions, not ce_run"}
    if not script.endswith(".py"):
        script = f"{script}.py"
    allowed = set(_listed_scripts()) | set(_KNOWN_SCRIPTS)
    if script not in allowed:
        return {
            "error": f"unknown CE script {script!r}",
            "available": sorted(allowed),
        }
    args, err = _safe_args(payload.get("args"))
    if err:
        return {"error": err}
    timeout = float(payload.get("timeout") or 180)
    timeout = max(15.0, min(timeout, 900.0))
    require_json = payload.get("json", True)
    if isinstance(require_json, str):
        require_json = require_json.lower() not in ("0", "false", "no")
    return cebridge.run_script(
        script, args, cwd=workspace, timeout=timeout,
        require_json=bool(require_json),
    )


def _ce_graph_rebuild(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    del payload
    return cebridge.run_script(
        "graph.py", ["rebuild", "wiki"],
        cwd=workspace, timeout=900.0, require_json=False,
    )


def _ce_graph_retrieve(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    query = str(payload.get("query") or "").strip()
    if not query:
        return {"error": "query is required"}
    args = ["retrieve", "wiki", query]
    if payload.get("seeds"):
        args.extend(["--seeds", str(int(payload["seeds"]))])
    if payload.get("limit"):
        args.extend(["--limit", str(int(payload["limit"]))])
    if payload.get("hops"):
        args.extend(["--hops", str(int(payload["hops"]))])
    route = str(payload.get("route") or "").strip()
    if route in ("auto", "graph", "blend"):
        args.extend(["--route", route])
    return cebridge.run_script("graph.py", args, cwd=workspace, timeout=180.0)


def _ce_sweep(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    verb = str(payload.get("verb") or payload.get("command") or "scan").strip()
    extra, err = _safe_args(payload.get("args"))
    if err:
        return {"error": err}
    args = [verb, "wiki", *extra]
    return cebridge.run_script(
        "sweep.py", args, cwd=workspace, timeout=180.0, require_json=False,
    )


def _ce_lint(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    args = ["wiki"]
    if payload.get("top"):
        args.extend(["--top", str(int(payload["top"]))])
    if payload.get("minimal"):
        args.append("--minimal")
    return cebridge.run_script("lint_scores.py", args, cwd=workspace, timeout=180.0)


def _ce_vault_index(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    extra, err = _safe_args(payload.get("args"))
    if err:
        return {"error": err}
    path = str(payload.get("path") or "").strip()
    title = str(payload.get("title") or "").strip()
    args: list[str] = []
    if payload.get("rebuild"):
        args.append("--rebuild")
    if payload.get("reembed"):
        args.append("--reembed")
    if path:
        args.append(path)
        if title:
            args.append(title)
    args.extend(extra)
    return cebridge.run_script("vault_index.py", args, cwd=workspace, timeout=180.0)


def _ce_ingest(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    extra, err = _safe_args(payload.get("args"))
    if err:
        return {"error": err}
    path = str(payload.get("path") or payload.get("directory") or "").strip()
    args: list[str] = list(extra)
    if path:
        args.insert(0, path)
    if payload.get("source_path_only"):
        args.append("--source-path-only")
    return cebridge.run_script("local_ingest.py", args, cwd=workspace, timeout=300.0)


def _ce_query(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    verb = str(payload.get("verb") or "introspect").strip()
    extra, err = _safe_args(payload.get("args"))
    if err:
        return {"error": err}
    q = str(payload.get("query") or "").strip()
    args = [verb]
    if q:
        args.append(q)
    args.extend(extra)
    return cebridge.run_script("query_router.py", args, cwd=workspace, timeout=120.0)


def _ce_score_diff(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    page = str(payload.get("page") or "").strip()
    extra, err = _safe_args(payload.get("args"))
    if err:
        return {"error": err}
    if not page:
        return {"error": "page is required"}
    args = [page, *extra]
    if payload.get("new_page"):
        args.append("--new-page")
    return cebridge.run_script("score_diff.py", args, cwd=workspace, timeout=120.0)


def _ce_scrub_check(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    mode = str(payload.get("mode") or "wiki").strip()
    extra, err = _safe_args(payload.get("args"))
    if err:
        return {"error": err}
    path = str(payload.get("path") or "").strip()
    args = ["--mode", mode]
    if path:
        args.append(path)
    args.extend(extra)
    return cebridge.run_script("scrub_check.py", args, cwd=workspace, timeout=60.0)


def _ce_naming(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    extra, err = _safe_args(payload.get("args"))
    if err:
        return {"error": err}
    return cebridge.run_script("naming.py", extra, cwd=workspace, timeout=30.0)


def _ce_tables(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    verb = str(payload.get("verb") or "list").strip()
    extra, err = _safe_args(payload.get("args"))
    if err:
        return {"error": err}
    return cebridge.run_script("tables.py", [verb, *extra], cwd=workspace, timeout=120.0)


def _ce_figures(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    verb = str(payload.get("verb") or "list").strip()
    extra, err = _safe_args(payload.get("args"))
    if err:
        return {"error": err}
    args = [verb, *extra]
    if verb in ("check", "list", "regen") and "wiki" not in args:
        args.append("wiki")
    return cebridge.run_script("figures.py", args, cwd=workspace, timeout=180.0)


def _ce_epoch_summary(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    extra, err = _safe_args(payload.get("args"))
    if err:
        return {"error": err}
    args = extra if extra else ["wiki"]
    return cebridge.run_script("epoch_summary.py", args, cwd=workspace, timeout=180.0)


def _ce_planner(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    extra, err = _safe_args(payload.get("args"))
    if err:
        return {"error": err}
    verb = str(payload.get("verb") or "pick-mode").strip()
    args = [verb, *extra]
    if "--wiki" not in args:
        args.extend(["--wiki", "wiki"])
    return cebridge.run_script("planner.py", args, cwd=workspace, timeout=60.0)


def _ce_scan(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    extra, err = _safe_args(payload.get("args"))
    if err:
        return {"error": err}
    verb = str(payload.get("verb") or "all").strip()
    args = [verb, *extra]
    if "--workspace" not in args:
        args.extend(["--workspace", str(workspace)])
    return cebridge.run_script("scan.py", args, cwd=workspace, timeout=180.0)


_SCRIPT_BLURB = (
    "Available scripts (pass as `script`): "
    + ", ".join(_KNOWN_SCRIPTS)
    + ". Common verbs: sweep.py scan|fix-index|fix-source-stubs|promote-extracted-tables; "
    "graph.py rebuild|retrieve|neighbors|path|shared-sources|bridge-candidates|"
    "link-candidates|embed; query_router.py introspect|sql|cypher|classify; "
    "tables.py list|query|schema|sync|insert|update; "
    "figures.py list|check|regen|render-all; naming.py; local_ingest.py; "
    "vault_index.py; lint_scores.py; score_diff.py; scrub_check.py; "
    "epoch_summary.py; planner.py pick-mode; scan.py all."
)


register(Tool(
    name="ce_run",
    description=(
        "Run any curiosity-engine script against this workspace. Use this "
        "instead of a shell — Copilot/HTTP sandboxes cannot see "
        "~/.agents/skills. " + _SCRIPT_BLURB
    ),
    input_schema={
        "type": "object",
        "required": ["script"],
        "properties": {
            "script": {"type": "string", "description": "CE script name, e.g. sweep.py"},
            "args": {
                "description": "Arguments after the script (string or list).",
            },
            "json": {"type": "boolean", "description": "Expect JSON stdout (default true)."},
            "timeout": {"type": "number", "description": "Seconds (default 180, cap 900)."},
        },
    },
    handler=_ce_run,
))

register(Tool(
    name="ce_graph_rebuild",
    description=(
        "Rebuild the kuzu knowledge graph from wiki pages on disk "
        "(CE graph.py rebuild wiki). Run after authoring or accepting "
        "pages so [[wikilink]] edges appear. Idempotent."
    ),
    input_schema={"type": "object", "properties": {}},
    handler=_ce_graph_rebuild,
))

register(Tool(
    name="ce_graph_retrieve",
    description=(
        "Primary CE retrieval: semantic seed → multi-hop graph expansion "
        "(graph.py retrieve). Prefer this over raw vault_search for "
        "named-entity / 'what do we know about X' questions."
    ),
    input_schema={
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {"type": "string"},
            "seeds": {"type": "integer"},
            "limit": {"type": "integer"},
            "hops": {"type": "integer"},
            "route": {"type": "string", "enum": ["auto", "graph", "blend"]},
        },
    },
    handler=_ce_graph_retrieve,
))

register(Tool(
    name="ce_sweep",
    description=(
        "CE mechanical hygiene (sweep.py). Verbs: scan, fix-index, "
        "fix-source-stubs, fix-citation-paths, promote-extracted-tables, "
        "concept-candidates, evidence-candidates, figure-candidates, "
        "orphan-sources, sync-notes, sync-todos, and the other sweep "
        "commands in the CE skill. Always pass wiki as the target — "
        "this tool adds it."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "verb": {"type": "string", "description": "sweep.py subcommand (default scan)."},
            "args": {"description": "Extra args after `wiki`."},
        },
    },
    handler=_ce_sweep,
))

register(Tool(
    name="ce_lint",
    description="Wiki health scores (lint_scores.py). Higher = worse.",
    input_schema={
        "type": "object",
        "properties": {
            "top": {"type": "integer"},
            "minimal": {"type": "boolean"},
        },
    },
    handler=_ce_lint,
))

register(Tool(
    name="ce_vault_index",
    description="Index a vault extraction into vault/vault.db (vault_index.py).",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "title": {"type": "string"},
            "rebuild": {"type": "boolean"},
            "reembed": {"type": "boolean"},
            "args": {},
        },
    },
    handler=_ce_vault_index,
))

register(Tool(
    name="ce_ingest",
    description=(
        "Ingest files into the vault (local_ingest.py). Drop-folder: no "
        "path (vault/raw/). External dir or file: pass `path`."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "source_path_only": {"type": "boolean"},
            "args": {},
        },
    },
    handler=_ce_ingest,
))

register(Tool(
    name="ce_query",
    description=(
        "Structured/structural queries (query_router.py). Verbs: "
        "introspect, sql, cypher, classify."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "verb": {"type": "string", "enum": ["introspect", "sql", "cypher", "classify"]},
            "query": {"type": "string"},
            "args": {},
        },
    },
    handler=_ce_query,
))

register(Tool(
    name="ce_score_diff",
    description="Citation/bloat gate (score_diff.py) for a wiki page.",
    input_schema={
        "type": "object",
        "required": ["page"],
        "properties": {
            "page": {"type": "string"},
            "new_page": {"type": "boolean"},
            "args": {},
        },
    },
    handler=_ce_score_diff,
))

register(Tool(
    name="ce_scrub_check",
    description="Injection/URL scrub (scrub_check.py) on a wiki or vault path.",
    input_schema={
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["wiki", "vault"]},
            "path": {"type": "string"},
            "args": {},
        },
    },
    handler=_ce_scrub_check,
))

register(Tool(
    name="ce_naming",
    description="CE naming helpers (naming.py) — citation_stem, titles, prefixes.",
    input_schema={"type": "object", "properties": {"args": {}}},
    handler=_ce_naming,
))

register(Tool(
    name="ce_tables",
    description="Class-table store (tables.py). Verbs: list, schema, query, sync, insert, update.",
    input_schema={
        "type": "object",
        "properties": {
            "verb": {"type": "string"},
            "args": {},
        },
    },
    handler=_ce_tables,
))

register(Tool(
    name="ce_figures",
    description="Figure assets (figures.py). Verbs: list, check, regen, render-all, pages, extract.",
    input_schema={
        "type": "object",
        "properties": {
            "verb": {"type": "string"},
            "args": {},
        },
    },
    handler=_ce_figures,
))

register(Tool(
    name="ce_epoch_summary",
    description="CURATE plan snapshot (epoch_summary.py wiki).",
    input_schema={"type": "object", "properties": {"args": {}}},
    handler=_ce_epoch_summary,
))

register(Tool(
    name="ce_planner",
    description="CURATE mode picker (planner.py pick-mode --wiki wiki).",
    input_schema={
        "type": "object",
        "properties": {
            "verb": {"type": "string"},
            "args": {},
        },
    },
    handler=_ce_planner,
))

register(Tool(
    name="ce_scan",
    description="Scan registered project-dirs for new/changed files (scan.py).",
    input_schema={
        "type": "object",
        "properties": {
            "verb": {"type": "string"},
            "args": {},
        },
    },
    handler=_ce_scan,
))

MECHANICAL_SWEEP_VERBS: tuple[str, ...] = (
    "scan",
    "fix-index",
    "fix-source-stubs",
    "sync-notes",
    "sync-todos",
)


def _preview_sweep_out(out: Any) -> str:
    if not isinstance(out, dict):
        return str(out)[:400]
    if out.get("error"):
        return str(out["error"])[:200]
    for key in ("stdout", "text", "summary", "result"):
        val = out.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()[:400]
        if isinstance(val, dict):
            return json.dumps(val, default=str)[:400]
    slim = {k: v for k, v in out.items() if k not in ("ok", "note")}
    if not slim:
        return ""
    return json.dumps(slim, default=str)[:400]


def mechanical_hygiene(
    workspace: Path,
    *,
    verbs: tuple[str, ...] = MECHANICAL_SWEEP_VERBS,
) -> dict[str, Any]:
    """Run deterministic sweep.py verbs (no LLM). Safe to call at
    /curate start. Failures are recorded; later verbs still run."""
    steps: list[dict[str, Any]] = []
    for verb in verbs:
        try:
            out = _ce_sweep(workspace, {"verb": verb})
        except Exception as exc:  # noqa: BLE001
            steps.append({
                "verb": verb, "ok": False, "error": str(exc)[:200],
                "preview": "",
            })
            continue
        err = None
        if isinstance(out, dict):
            err = out.get("error")
        steps.append({
            "verb": verb,
            "ok": not err,
            "error": (str(err)[:200] if err else None),
            "preview": _preview_sweep_out(out if isinstance(out, dict) else {}),
        })
    return {
        "ok": all(s["ok"] for s in steps),
        "steps": steps,
    }


# Public list for tests / ALLOWED_TOOLS sync.
CE_TOOL_NAMES = (
    "ce_run",
    "ce_graph_rebuild",
    "ce_graph_retrieve",
    "ce_sweep",
    "ce_lint",
    "ce_vault_index",
    "ce_ingest",
    "ce_query",
    "ce_score_diff",
    "ce_scrub_check",
    "ce_naming",
    "ce_tables",
    "ce_figures",
    "ce_epoch_summary",
    "ce_planner",
    "ce_scan",
)
