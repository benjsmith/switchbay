"""Tool registry for the rail agent.

A `Tool` is `{name, description, input_schema, handler}` where the
handler is `(workspace: Path, input: dict) -> dict | str`. Tools are
provider-agnostic — providers translate to their wire format (e.g.
Anthropic's `tools[]` parameter).

Today's tools mostly let the agent manipulate workspace state the
user can also reach via the UI (DuckDB starter pills, eventually
mode.json, plot configs, sketch metadata, etc.). Generic file/shell
access is intentionally NOT provided here — that lives in larger,
explicitly-scoped agents (ingest, project-curator) which the user
launches deliberately.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import json
import os
import re
import sys

from . import (
    agent_rules, analyses, conversations, duckdb_starters,
    plots, proposals, reports, sketches, skillkit, slide_layouts,
)

ToolHandler = Callable[[Path, dict[str, Any]], dict[str, Any] | str]


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler

    def to_anthropic(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> None:
    REGISTRY[tool.name] = tool


def execute(name: str, workspace: Path, payload: dict[str, Any]) -> dict[str, Any] | str:
    tool = REGISTRY.get(name)
    if tool is None:
        raise KeyError(f"unknown tool: {name}")
    return tool.handler(workspace, payload)


# ── DuckDB starter-pill tools ────────────────────────────────────────


def _list_starters(workspace: Path, _: dict[str, Any]) -> dict[str, Any]:
    return {"starters": duckdb_starters.load(workspace)}


def _add_starters(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    new = payload.get("starters") or []
    if not isinstance(new, list):
        return {"ok": False, "error": "`starters` must be an array"}
    current = duckdb_starters.load(workspace)
    current.extend(new)
    duckdb_starters.save(workspace, current)
    return {
        "ok": True,
        "added": len(new),
        "total": len(current),
        "starters": duckdb_starters.load(workspace),
    }


def _replace_starters(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    items = payload.get("starters") or []
    if not isinstance(items, list):
        return {"ok": False, "error": "`starters` must be an array"}
    duckdb_starters.save(workspace, items)
    return {"ok": True, "total": len(items), "starters": duckdb_starters.load(workspace)}


_STARTER_PILL_SCHEMA = {
    "type": "object",
    "required": ["starters"],
    "properties": {
        "starters": {
            "type": "array",
            "description": "List of SQL starter pills to add or set.",
            "items": {
                "type": "object",
                "required": ["label", "sql"],
                "properties": {
                    "label": {
                        "type": "string",
                        "description": "Short label shown on the pill button (≈30 chars max).",
                    },
                    "sql": {
                        "type": "string",
                        "description": "DuckDB SQL run when the pill is clicked.",
                    },
                },
            },
        },
    },
}


def _propose_wiki_page(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    kind = str(payload.get("kind") or "").strip().lower()
    title = str(payload.get("title") or "").strip()
    body = str(payload.get("body") or "").strip()
    if kind not in proposals.KIND_FOLDER:
        return {"ok": False, "error": f"kind must be one of {list(proposals.KIND_FOLDER)}"}
    if not title or not body:
        return {"ok": False, "error": "title and body are required"}
    scaffold = bool(payload.get("scaffold"))
    if scaffold:
        body = proposals.clip_scaffold_body(body, title=title)
    e = proposals.add(
        workspace, op="create", kind=kind, title=title, body=body,
        scaffold=scaffold,
    )
    return {"ok": True, "proposal_id": e["id"], "path": e["path"],
            "scaffold": scaffold,
            "note": (
                "Scaffold staged in Reviews — expand from sources, not "
                "from this outline."
                if scaffold else
                "Written provisionally. Keep going — Reviews is a "
                "backlog. Reject reverts this page. Do not propose it again."
            )}


def _propose_page_edit(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    path = str(payload.get("path") or "").strip()
    body = str(payload.get("body") or "").strip()
    if not path or not body:
        return {"ok": False, "error": "path and body are required"}
    scaffold = bool(payload.get("scaffold"))
    if scaffold:
        body = proposals.clip_scaffold_body(body, title=str(payload.get("title") or path))
    e = proposals.add(workspace, op="edit", kind=str(payload.get("kind") or "note"),
                      title=str(payload.get("title") or path), body=body, path=path,
                      scaffold=scaffold)
    return {"ok": True, "proposal_id": e["id"], "path": e["path"],
            "scaffold": scaffold,
            "note": (
                "Scaffold edit staged in Reviews."
                if scaffold else
                "Edit written provisionally. Keep going — Reviews is "
                "a backlog. Reject restores the previous text."
            )}


def _create_report(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    title = str(payload.get("title") or "").strip()
    summary = str(payload.get("summary") or "").strip()
    html = str(payload.get("html") or "")
    if not title or not html.strip():
        return {"ok": False, "error": "title and html are required"}
    if not summary:
        return {"ok": False, "error": "summary is required (the one-line chat reply)"}
    meta = reports.save(workspace, title=title, summary=summary, html=html)
    return {"ok": True, "report_id": meta["id"], "title": meta["title"],
            "summary": meta["summary"],
            "note": "Report opened in the Report tab. Your chat reply should "
            "be ONLY the one-line summary — do not repeat the full document."}


register(Tool(
    name="create_report",
    description=(
        "Render a rich, self-contained HTML document into a Report TAB "
        "(not the chat). Use this for ANALYSIS / comparison / structured "
        "or long answers where a formatted document reads far better than "
        "a wall of chat text — tables, sections, charts, side-by-sides. "
        "Give a `title`, a one-line `summary` (this becomes your chat "
        "reply), and the full `html` — a COMPLETE self-contained page "
        "(inline all CSS/JS; no external URLs/CDNs; it renders in a "
        "sandboxed iframe). After calling this, reply in chat with ONLY "
        "the one-line summary — the document lives in the tab. "
        "Plain language: avoid jargon and domain acronyms unless "
        "ubiquitous; define any necessary acronym on first use in the "
        "document."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "html": {"type": "string"},
        },
        "required": ["title", "summary", "html"],
    },
    handler=_create_report,
))


register(Tool(
    name="propose_wiki_page",
    description=(
        "Write a NEW wiki page (concept / entity / analysis / fact / "
        "evidence / source / note). It lands immediately and shows in "
        "Reviews as a backlog item — do not wait for the user. Reject "
        "reverts the file. Give `kind`, a `title`, and the full page "
        "`body` (CE format: YAML frontmatter + '# Title' + dense prose "
        "with [[wikilinks]]). Never invent specific numbers or facts "
        "you are not sure of. Keep going after each page."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": list(proposals.KIND_FOLDER)},
            "title": {"type": "string"},
            "body": {"type": "string"},
        },
        "required": ["kind", "title", "body"],
    },
    handler=_propose_wiki_page,
))

register(Tool(
    name="propose_page_edit",
    description=(
        "Edit an existing wiki page. Writes immediately (provisional); "
        "Reviews can revert it. Give the page `path` (repo-relative, "
        "under wiki/) and the full new `body`. Never deletes a page. "
        "Keep going after each edit."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "body": {"type": "string"},
            "title": {"type": "string"},
        },
        "required": ["path", "body"],
    },
    handler=_propose_page_edit,
))


def _run_command(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """VS Code Copilot-like: run a command in the workspace (no login shell).

    IT can disable via ``agent_run_command``. Home-scan hard-denies still apply.
    """
    import shlex
    import subprocess
    from . import admin_policy, permissions, workspaces

    if not admin_policy.feature_enabled("agent_run_command"):
        return {"ok": False, "error": admin_policy.feature_error("agent_run_command")}
    raw = payload.get("command")
    argv = payload.get("argv")
    if isinstance(argv, list) and argv:
        cmd = [str(a) for a in argv]
        display = subprocess.list2cmdline(cmd) if sys.platform == "win32" else " ".join(cmd)
    elif isinstance(raw, str) and raw.strip():
        display = raw.strip()
        try:
            cmd = shlex.split(display, posix=sys.platform != "win32")
        except ValueError as e:
            return {"ok": False, "error": f"bad command: {e}"}
    else:
        return {"ok": False, "error": "command or argv required"}
    if not cmd:
        return {"ok": False, "error": "empty command"}
    deny = permissions.hard_deny_reason("Bash", {"command": display})
    if deny:
        return {"ok": False, "error": deny}
    cwd = workspace
    extra = str(payload.get("cwd") or "").strip()
    if extra:
        cand = (workspace / extra).resolve() if not Path(extra).is_absolute() else Path(extra)
        if not workspaces.is_within_home(cand):
            return {"ok": False, "error": "cwd must stay under the user home"}
        cwd = cand
    try:
        r = subprocess.run(
            cmd, cwd=str(cwd), capture_output=True, text=True, timeout=120,
            env={k: v for k, v in os.environ.items()
                 if k not in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT")},
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "error": str(e)}
    out = (r.stdout or "")[-8000:]
    err = (r.stderr or "")[-4000:]
    return {"ok": r.returncode == 0, "exit_code": r.returncode, "stdout": out, "stderr": err}


register(Tool(
    name="run_command",
    description=(
        "Run a program in the workspace (argv or a simple command string). "
        "Use for builds, tests, git, and skill CLIs (`npx skills add`, "
        "`uvx skills add`) the way VS Code Copilot Agent uses the terminal. "
        "Not a login shell. Prefer Switch Bay wiki/CE tools for knowledge work."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Command line (split like a shell)."},
            "argv": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Explicit argv; preferred over command when you have it.",
            },
            "cwd": {"type": "string", "description": "Optional cwd relative to the workspace."},
        },
    },
    handler=_run_command,
))

register(Tool(
    name="list_duckdb_starters",
    description=(
        "List the SQL starter pills currently configured for the Table tab. "
        "Stored at <workspace>/.workbench/state/duckdb-starters.json."
    ),
    input_schema={"type": "object", "properties": {}},
    handler=_list_starters,
))

register(Tool(
    name="add_duckdb_starters",
    description=(
        "Append one or more SQL starter pills to the Table tab. The user can "
        "also edit these via the ✎ Edit starters dialog. Use this when the "
        "user asks to add a starter, common queries, etc. Each pill needs a "
        "short label and a SQL body. Available pre-seeded tables: "
        "`files (path, size, mtime, ext)`, `pages (id, path, type, title, degree)`."
    ),
    input_schema=_STARTER_PILL_SCHEMA,
    handler=_add_starters,
))

register(Tool(
    name="replace_duckdb_starters",
    description=(
        "Replace ALL SQL starter pills with the given list. Use only when "
        "the user explicitly wants to reset / wholesale replace. Otherwise "
        "prefer add_duckdb_starters."
    ),
    input_schema=_STARTER_PILL_SCHEMA,
    handler=_replace_starters,
))


# ── Rail event recall ────────────────────────────────────────────────


def _recall_rail(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    query = str(payload.get("query") or "").strip()
    if not query:
        return {"hits": [], "note": "query is empty"}
    limit = int(payload.get("limit") or 10)
    limit = max(1, min(50, limit))
    raw_kinds = payload.get("kinds")
    kinds: list[str] | None = None
    if isinstance(raw_kinds, list):
        kinds = [str(k) for k in raw_kinds if isinstance(k, str) and k]
        if not kinds:
            kinds = None
    mode = str(payload.get("mode") or "hybrid").lower()
    if mode not in ("fts", "semantic", "hybrid"):
        mode = "hybrid"
    hits = conversations.recall(
        workspace, query, limit=limit, kinds=kinds, mode=mode,
    )
    return {"hits": hits, "count": len(hits), "mode": mode}


# ── User-defined rail shortcuts ──────────────────────────────────────


def _register_rule(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    trigger = str(payload.get("trigger") or "").strip()
    action = str(payload.get("action") or "").strip()
    if not trigger or not action:
        return {"ok": False, "error": "both `trigger` and `action` are required"}
    try:
        rule = agent_rules.add(workspace, trigger, action)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "rule": rule, "total": len(agent_rules.load(workspace))}


def _list_rules(workspace: Path, _: dict[str, Any]) -> dict[str, Any]:
    return {"rules": agent_rules.load(workspace)}


def _delete_rule(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    rid = str(payload.get("id") or "").strip()
    if not rid:
        return {"ok": False, "error": "`id` is required"}
    removed = agent_rules.remove(workspace, rid)
    return {
        "ok": removed,
        "removed": removed,
        "total": len(agent_rules.load(workspace)),
    }


register(Tool(
    name="register_rule",
    description=(
        "Save a persistent rail shortcut: when the user types `trigger` "
        "(case-insensitive, exact-text), the daemon executes `action` "
        "instead of dispatching to chat. Use this when the user asks "
        "you to remember a shortcut, e.g. \"when I say 'show me X', "
        "/view X\" — call register_rule(trigger=\"show me X\", "
        "action=\"/view X\"). Rules persist across sessions in the "
        "workspace's agent_rules.json."
    ),
    input_schema={
        "type": "object",
        "required": ["trigger", "action"],
        "properties": {
            "trigger": {
                "type": "string",
                "description": "Exact phrase the user will type (case-insensitive).",
            },
            "action": {
                "type": "string",
                "description": (
                    "What to run instead. Today: a slash command like "
                    "'/view Mistral'. Future: arbitrary tool calls."
                ),
            },
        },
    },
    handler=_register_rule,
))

register(Tool(
    name="list_rules",
    description="List the user's saved rail shortcuts for this workspace.",
    input_schema={"type": "object", "properties": {}},
    handler=_list_rules,
))

register(Tool(
    name="delete_rule",
    description="Remove a saved rail shortcut by id (from list_rules).",
    input_schema={
        "type": "object",
        "required": ["id"],
        "properties": {
            "id": {"type": "string", "description": "Rule id from list_rules."},
        },
    },
    handler=_delete_rule,
))


register(Tool(
    name="recall_rail",
    description=(
        "Search past rail events in this workspace — chat turns, tool "
        "calls, file edits, executed commands, curation runs, etc. "
        "Returns the most relevant matching event snippets, hybrid-"
        "ranking FTS5 keyword matches with sqlite-vec semantic "
        "similarity (so paraphrases like 'database' also match "
        "'DuckDB'). Use when the user references something from "
        "earlier ('what did I ask about CSVs', 'when did we last edit "
        "foo.md', 'show recent file changes'). Only the most recent "
        "~20 chat turns are already in your context — everything else "
        "lives here. Pass `kinds` to filter by event type, e.g. "
        "['user','assistant'] for chat-only recall, or "
        "['file_edit_internal','file_edit_external'] for edit history. "
        "Pass `mode` to force a single retrieval strategy."
    ),
    input_schema={
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {
                "type": "string",
                "description": "Words/phrases to search for. Quote isn't needed.",
            },
            "limit": {
                "type": "integer",
                "description": "Max hits to return (1–50; default 10).",
                "default": 10,
            },
            "kinds": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional list of event kinds to restrict the search to. "
                    "Common values: user, assistant, tool_use, tool_result, "
                    "exec, sql, slash, file_edit_internal, file_edit_external, "
                    "file_delete, curation, mode_change, workspace_switch."
                ),
            },
            "mode": {
                "type": "string",
                "enum": ["hybrid", "fts", "semantic"],
                "description": (
                    "Retrieval strategy. Default 'hybrid' (recommended): "
                    "blends keyword and semantic matches via reciprocal "
                    "rank fusion. 'fts' for exact-keyword-only; "
                    "'semantic' for paraphrase-only. Hybrid auto-falls-back "
                    "to FTS when sqlite-vec / sentence-transformers aren't "
                    "installed, so this is safe to leave at the default."
                ),
                "default": "hybrid",
            },
        },
    },
    handler=_recall_rail,
))


# ── Slide-deck tools (rail-driven side of N.1) ──────────────────────


# Heading regex used by both make_slides_from_doc and make_slides_from_docs
# to chunk source markdown into placeholder slides.
_HEADING_RE = re.compile(r"^(#{1,2})\s+(.*\S)\s*$", re.MULTILINE)

# Generic spine when a source has few/no H2s (common for CE analyses:
# one long prose block under the H1, then a single "Open questions"
# H2). Without this, → Sketch deck yields a 1-slide "deck".
_GENERIC_DECK_SPINE = ("Introduction", "Key Points", "Evidence", "Next Steps")
# At least this many real H2s before we trust headings alone.
_MIN_HEADING_SLIDES = 3


def deck_section_titles_from_body(body: str, *, fallback_title: str = "Untitled") -> tuple[str, list[str]]:
    """Derive (doc_title, section_titles) for a sketch-deck scaffold.

    · ≥3 H2s → one slide per H2 (well-structured docs).
    · 0 H2s  → generic 4-slide spine (prose/property-shaped pages).
    · 1–2 H2s → generic intro spine + the real H2s as trailing slides
      so a long analysis with only "Open questions" still gets a
      full deck for the populate agent to fill.
    """
    headings = [m.group(2).strip() for m in _HEADING_RE.finditer(body or "")]
    doc_title = headings[0] if headings else fallback_title
    sub = headings[1:] if headings else []
    if len(sub) >= _MIN_HEADING_SLIDES:
        return doc_title, sub
    if not sub:
        return doc_title, list(_GENERIC_DECK_SPINE)
    # Sparse headings: keep a 3-slide content spine, then the named
    # H2s (deduped, case-insensitive) so e.g. "Open questions" lands
    # as the final card instead of being the *only* card.
    spine = ["Introduction", "Key Points", "Evidence"]
    seen = {s.lower() for s in spine}
    tail: list[str] = []
    for h in sub:
        key = h.lower()
        if key in seen:
            continue
        tail.append(h)
        seen.add(key)
    if not tail:
        tail = ["Next Steps"]
    return doc_title, spine + tail


def _scaffold_one_doc(workspace: Path, doc_path: str) -> dict[str, Any]:
    """Read a doc, derive section titles, create a placeholder
    Excalidraw sketch per section. Returns (doc_title, [sketch_id...]).
    Doesn't write the analysis page itself — caller composes the
    final analysis (single-doc OR multi-doc)."""
    src = analyses.resolve_doc_path(workspace, doc_path)
    if src is None:
        raise ValueError(f"source doc not in workspace: {doc_path}")
    text = src.read_text(encoding="utf-8")
    _, body = analyses.parse_frontmatter(text)
    doc_title, section_titles = deck_section_titles_from_body(
        body, fallback_title=src.stem,
    )
    slide_ids: list[str] = []
    for title in section_titles or [doc_title]:
        seed = {"elements": [], "appState": {"name": title}, "files": {}}
        rec = sketches.save_sketch(
            workspace, name=title, kind="excalidraw", data=seed,
        )
        slide_ids.append(rec["id"])
    return {"doc_title": doc_title, "slide_ids": slide_ids}


def _make_slides_from_doc(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    path = str(payload.get("path") or "").strip()
    if not path:
        return {"ok": False, "error": "path is required"}
    try:
        scaffolded = _scaffold_one_doc(workspace, path)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    name = str(payload.get("name") or "").strip() or scaffolded["doc_title"]
    a = analyses.save_analysis(
        workspace, title=name, slides=scaffolded["slide_ids"], sources=[path],
    )
    return {
        "ok": True,
        "analysis": {
            "slug": a["slug"], "path": a["path"], "title": a["title"],
            "slides": a["slides"], "sources": a["sources"],
        },
        "next_step_hint": (
            f"Each slide is a placeholder Excalidraw scene named after a "
            f"heading. To fill them in, open the analysis page in the "
            f"Sketch tab — the user can author the scenes by hand, or "
            f"you can update them via further conversation. PNG exports "
            f"land in figures/<sketch-id>.png the next time each slide "
            f"is rendered."
        ),
    }


register(Tool(
    name="make_slides_from_doc",
    description=(
        "Scaffold a sketcher slide deck from a single source markdown "
        "doc. Walks the doc's H1/H2 headings; one placeholder Excalidraw "
        "sketch per heading. Writes a CE-shaped analysis page at "
        "wiki/<slug>.md (kind: analysis, slides: [...], sources: [...]) "
        "that's the deck's spine — Sketch tab enters deck mode when the "
        "user opens it. Use when the user says things like 'make slides "
        "from foo.md' or 'turn the design doc into a deck'."
    ),
    input_schema={
        "type": "object",
        "required": ["path"],
        "properties": {
            "path": {
                "type": "string",
                "description": "Workspace-relative path to the source doc, e.g. 'wiki/q4-churn.md'.",
            },
            "name": {
                "type": "string",
                "description": "Deck title; defaults to the doc's first H1 (or filename when none).",
            },
        },
    },
    handler=_make_slides_from_doc,
))


def _make_slides_from_docs(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    raw_paths = payload.get("paths")
    if not isinstance(raw_paths, list) or not all(isinstance(p, str) for p in raw_paths):
        return {"ok": False, "error": "paths must be a list of doc paths"}
    if not raw_paths:
        return {"ok": False, "error": "paths is empty"}
    title = str(payload.get("title") or "").strip()
    all_slide_ids: list[str] = []
    doc_titles: list[str] = []
    for path in raw_paths:
        try:
            s = _scaffold_one_doc(workspace, path)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        all_slide_ids.extend(s["slide_ids"])
        doc_titles.append(s["doc_title"])
    if not title:
        # Compose a deck title from the source doc titles, capped at
        # something readable. The agent / user can rename via the
        # Sketch tab's inline title input afterwards.
        if len(doc_titles) == 1:
            title = doc_titles[0]
        elif len(doc_titles) <= 3:
            title = " · ".join(doc_titles)
        else:
            title = f"{doc_titles[0]} (+ {len(doc_titles) - 1} more)"
    a = analyses.save_analysis(
        workspace, title=title, slides=all_slide_ids, sources=list(raw_paths),
    )
    return {
        "ok": True,
        "analysis": {
            "slug": a["slug"], "path": a["path"], "title": a["title"],
            "slides": a["slides"], "sources": a["sources"],
        },
        "doc_titles": doc_titles,
    }


register(Tool(
    name="make_slides_from_docs",
    description=(
        "Multi-source variant: scaffold one slide deck spanning N source "
        "docs. Each doc's headings contribute a section to the deck in "
        "the order given. Use when the user says 'make slides from A, B, "
        "and C' or 'analyse these and show as slides'."
    ),
    input_schema={
        "type": "object",
        "required": ["paths"],
        "properties": {
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Workspace-relative paths to source docs, in the order "
                    "they should appear in the deck."
                ),
            },
            "title": {
                "type": "string",
                "description": (
                    "Deck title. Defaults to a join of the source-doc titles "
                    "when not supplied."
                ),
            },
        },
    },
    handler=_make_slides_from_docs,
))


def _compose_analysis(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    title = str(payload.get("title") or "").strip()
    slides = payload.get("slides")
    if not isinstance(slides, list) or not all(isinstance(s, str) for s in slides):
        return {"ok": False, "error": "slides must be a list of sketch ids"}
    sources = payload.get("sources") if isinstance(payload.get("sources"), list) else []
    body = payload.get("body") if isinstance(payload.get("body"), str) else None
    a = analyses.save_analysis(
        workspace, title=title, slides=slides,
        sources=list(sources), body=body,
    )
    return {"ok": True, "analysis": {
        "slug": a["slug"], "path": a["path"], "title": a["title"],
        "slides": a["slides"], "sources": a["sources"],
    }}


register(Tool(
    name="compose_analysis",
    description=(
        "Compose a fresh analysis page from existing slide ids — the "
        "remix path. Lets you build a NEW deck that references slides "
        "already in the workspace's sketch library, in whatever order "
        "tells the story you want. Different decks can share slides; "
        "the same library powers many narratives. Use when the user "
        "says 'make a board deck using slides X, Y, and Z' or 'compose "
        "an analysis page from these existing sketches'."
    ),
    input_schema={
        "type": "object",
        "required": ["title", "slides"],
        "properties": {
            "title": {"type": "string", "description": "Deck title."},
            "slides": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Existing sketch ids in the desired deck order.",
            },
            "sources": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of source doc paths the deck draws from.",
            },
            "body": {
                "type": "string",
                "description": (
                    "Optional narrative markdown body. Omit to get the auto-"
                    "generated stub (heading + figure block per slide)."
                ),
            },
        },
    },
    handler=_compose_analysis,
))


def _resolve_slide_image(workspace: Path, slots: dict[str, Any]) -> str | None:
    """If slots carry image/icon as a workspace-relative path, load it
    as a data URL + pixel size for title_slide. Returns error string or
    None on success / nothing to do."""
    import base64
    import mimetypes

    raw = slots.get("image") or slots.get("icon") or slots.get("image_path")
    if raw is None or raw == "":
        return None
    if isinstance(raw, str) and raw.startswith("data:image/"):
        slots["image_dataurl"] = raw
        return None
    path_s = str(raw).strip()
    if not path_s:
        return None
    # Absolute only if already under workspace; else treat as rel.
    p = Path(path_s)
    if not p.is_absolute():
        p = (workspace / path_s).resolve()
    else:
        p = p.resolve()
    try:
        p.relative_to(workspace.resolve())
    except ValueError:
        return f"image path must be inside the workspace: {path_s}"
    if not p.is_file():
        return f"image file not found: {path_s}"
    if p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
        return f"unsupported image type {p.suffix!r} (use png/jpg/webp)"
    try:
        data = p.read_bytes()
    except OSError as e:
        return f"cannot read image: {e}"
    if len(data) > 2_500_000:
        return "image too large (cap ~2.5 MB); use a smaller PNG"
    mime = mimetypes.guess_type(p.name)[0] or "image/png"
    b64 = base64.b64encode(data).decode("ascii")
    slots["image_dataurl"] = f"data:{mime};base64,{b64}"
    # Optional natural size for layout scaling (Pillow when available).
    try:
        from PIL import Image
        import io
        with Image.open(io.BytesIO(data)) as im:
            slots["image_w"] = float(im.size[0])
            slots["image_h"] = float(im.size[1])
    except Exception:  # noqa: BLE001
        slots.setdefault("image_w", 96.0)
        slots.setdefault("image_h", 96.0)
    return None


def _author_slide(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Author a real Excalidraw scene for one slide. The agent picks
    a layout and fills its slots; slide_layouts.py renders the scene
    and we save it as a sketch. If `sketch_id` is provided we update
    that placeholder in place (the typical post-make_slides_from_doc
    flow); otherwise a fresh sketch is created."""
    layout = str(payload.get("layout") or "").strip()
    slots = payload.get("slots")
    if not layout:
        return {"ok": False, "error": "`layout` is required"}
    if not isinstance(slots, dict):
        return {"ok": False, "error": "`slots` must be an object"}
    # Resolve workspace-relative image/icon paths into data URLs so
    # layouts can embed real PNGs (Excalidraw image elements). ASCII
    # art in subtitles is not an icon — use image/icon for that.
    slots = dict(slots)
    img_err = _resolve_slide_image(workspace, slots)
    if img_err:
        return {"ok": False, "error": img_err}
    try:
        scene = slide_layouts.render_layout(layout, slots)
    except KeyError as e:
        return {
            "ok": False,
            "error": str(e),
            "valid_layouts": list(slide_layouts.LAYOUTS.keys()),
        }
    except TypeError as e:
        return {"ok": False, "error": str(e)}
    name = (
        str(payload.get("name") or "").strip()
        or slide_layouts.display_name(scene)
    )
    sketch_id = payload.get("sketch_id")
    # Default to the slide the user is looking at so "fix the
    # title on this slide" doesn't create a stray sketch.
    if not (isinstance(sketch_id, str) and sketch_id.strip()):
        try:
            from . import ui_focus as uf
            focus = uf.load(workspace, "sketch")
            if focus and focus.get("sketch_id"):
                sketch_id = str(focus["sketch_id"])
                if not str(payload.get("name") or "").strip():
                    # Keep existing slide name when re-authoring in place.
                    existing = sketches.get_sketch(workspace, sketch_id)
                    if existing and existing.get("name"):
                        name = str(existing["name"])
        except Exception:  # noqa: BLE001
            pass
    rec = sketches.save_sketch(
        workspace, name=name, kind="excalidraw", data=scene,
        sketch_id=str(sketch_id) if isinstance(sketch_id, str) and sketch_id else None,
    )
    # Nudge the Sketch tab to show/reload the slide (best-effort; MCP
    # may not reach the daemon if CSWY_DAEMON_PORT is wrong).
    try:
        import os
        import urllib.request
        port = os.environ.get("CSWY_DAEMON_PORT") or "8765"
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/sketch/command",
            data=json.dumps({
                "op": "show", "sketch_id": rec["id"],
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5).read()
    except Exception:  # noqa: BLE001
        pass
    return {
        "ok": True,
        "sketch_id": rec["id"],
        "name": rec["name"],
        "layout": layout,
        "render_hint": (
            "save_sketch wrote a clean Pillow raster to figures/<id>.png "
            "for this slide so the deck doc's image references resolve "
            "immediately. The Sketch tab overwrites it with the canonical "
            "Excalidraw render (rough strokes, Virgil font) the next time "
            "the slide is opened."
        ),
    }


register(Tool(
    name="author_slide",
    description=(
        "Fill a sketcher slide with a real Excalidraw scene by picking "
        "a layout, an accent colour, and supplying the layout's slots. "
        "Use after make_slides_from_doc/make_slides_from_docs has "
        "scaffolded placeholder slides — pass `sketch_id` to update one "
        "of them in place. Or omit `sketch_id` to create a fresh slide "
        "and (later) thread it into a deck via compose_analysis.\n\n"
        "Layouts:\n"
        "  · title       — slots: title, subtitle?, image?/icon?  Cover slide.\n"
        "  · bullets     — slots: title, bullets[]            Heading + bullets with disc markers (cap 8).\n"
        "  · two_column  — slots: title, left_title, left_items[], right_title, right_items[]\n"
        "                                                     Compare/contrast as two outlined cards.\n"
        "  · quote       — slots: quote, attribution?         Pull-quote with oversized opening mark.\n"
        "  · section     — slots: label, subtitle?            Section break.\n"
        "  · paragraph   — slots: title, body                 Heading + prose paragraph.\n"
        "  · stat        — slots: stat, label, context?       Big number + caption + optional context.\n"
        "  · cards       — slots: title, cards[{header, body}] 2x2 grid of mini info cards (cap 4).\n\n"
        "Images/icons on title slides: pass `image` or `icon` as a "
        "workspace-relative path to a PNG/JPEG (e.g. "
        "`wiki/figures/_assets/bot.png` or a file under "
        "`.workbench/uploads/`). This embeds a real Excalidraw image "
        "element — do NOT fake icons with ASCII art in the subtitle "
        "(those clip and do not render as shapes). User can also drop "
        "images onto the canvas with the Sketch toolbar.\n\n"
        "Accent colour (pass `accent` in `slots` and use the SAME "
        "value across every slide in the deck):\n"
        "  · black   — neutral / professional default.\n"
        "  · red     — emphasis / risk topics.\n"
        "  · green   — growth / progress / approval topics.\n"
        "  · blue    — research / data / trust topics.\n"
        "  · orange  — energy / change / launch topics.\n\n"
        "These are exactly Excalidraw's stock five stroke colours so "
        "the user can re-recolour with the toolbar without finding a "
        "custom hex. The canvas stays white; saturation comes from "
        "the strokes (titles, accents, outlines, bullet markers).\n\n"
        "Design rules:\n"
        "  1. Pick an accent that fits the topic and use it for every "
        "slide. Don't default to black unless the content warrants it.\n"
        "  2. White canvas everywhere. No background-fills on shapes — "
        "rough strokes don't seal cleanly against fills.\n"
        "  3. Vary layouts — don't make 10 bullets slides in a row. "
        "Mix bullets / two_column / stat / cards / paragraph / quote.\n"
        "  4. Use the handwritten Excalidraw font (the layouts already "
        "do this — don't override it). The whole deck reads as a "
        "sketch, not an office document.\n"
        "  5. Keep prose terse: bullets ≤ 8 words each, body paragraphs "
        "3-4 sentences, stat captions ≤ 6 words. Slides aren't essays.\n"
        "  6. Plain language: avoid jargon and domain acronyms unless "
        "truly ubiquitous (AI, CPU, PDF, HTTP, SQL). Spell out "
        "shorthand like RLVR/RAG/RLHF/CoT. If an acronym is "
        "necessary, define it on FIRST use in the deck "
        "(\"retrieval-augmented generation (RAG)\"); never leave a "
        "bare undefined acronym on a title, card, or bullet.\n"
        "  7. stat and section slides land harder than bullets — use "
        "them for the highest-impact moments in the deck."
    ),
    input_schema={
        "type": "object",
        "required": ["layout", "slots"],
        "properties": {
            "layout": {
                "type": "string",
                "enum": [
                    "title", "bullets", "two_column",
                    "quote", "section", "paragraph",
                    "stat", "cards",
                ],
                "description": "Layout id; see tool description for slot expectations.",
            },
            "slots": {
                "type": "object",
                "description": (
                    "Layout-specific content. Required slots vary; see "
                    "tool description. Pass `accent` here too — one of "
                    "{black, red, green, blue, orange} — and use the "
                    "same value for every slide in the deck. Unknown "
                    "slots are ignored."
                ),
            },
            "sketch_id": {
                "type": "string",
                "description": (
                    "Existing sketch id to update in place (typical flow: a "
                    "placeholder slide created by make_slides_from_doc). "
                    "Omit to create a fresh slide."
                ),
            },
            "name": {
                "type": "string",
                "description": (
                    "Display name for the sketch. Defaults to the layout's "
                    "primary text (title/label/quote) when omitted."
                ),
            },
        },
    },
    handler=_author_slide,
))


# ── Skill loading ───────────────────────────────────────────────────


def _list_skills(workspace: Path, _: dict[str, Any]) -> dict[str, Any]:
    try:
        skillkit.mirror_into_workspace(workspace)
    except Exception:  # noqa: BLE001
        pass
    return {
        "skills": [skillkit.to_summary(s) for s in skillkit.list_skills(workspace)],
        "note": (
            "Prefer Switch Bay tools in covered_by. Then "
            "load_skill(name, detail='frontmatter'). Full body only "
            "when the peek says you need extra skill prose. Sandboxed "
            "shells can Read copies under .workbench/skill-mirrors/."
        ),
    }


def _load_skill(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "`name` is required"}
    sk = skillkit.get_skill(workspace, name)
    if sk is None:
        return {
            "ok": False,
            "error": f"skill {name!r} not found",
            "available": [s.name for s in skillkit.list_skills(workspace)][:20],
        }
    detail = str(payload.get("detail") or "frontmatter").strip().lower()
    section = str(payload.get("section") or "").strip()
    if section:
        prog = skillkit.progressive_section(sk.body, section)
        if prog is None:
            return {
                "ok": False,
                "error": f"no section {section!r}",
                "headings": skillkit.body_headings(sk.body),
                "skill": skillkit.to_peek(sk),
            }
        return {"ok": True, "skill": {**skillkit.to_peek(sk), **prog}}
    if detail in ("frontmatter", "peek", "meta", ""):
        return {"ok": True, "skill": skillkit.to_peek(sk)}
    return {"ok": True, "skill": skillkit.to_full(sk)}


register(Tool(
    name="list_skills",
    description=(
        "List skills for this workspace (name, when-to-use, headings, "
        "and covered_by Switch Bay tools). Prefer those tools. Then "
        "load_skill(name, detail='frontmatter') before loading a full "
        "body. Discovered from ~/.agents/skills/, workspace "
        ".workbench/skills/, packs, and the curiosity-engine SKILL.md."
    ),
    input_schema={"type": "object", "properties": {}},
    handler=_list_skills,
))


register(Tool(
    name="load_skill",
    description=(
        "Read a skill. Precedence: Switch Bay tools first, then "
        "detail='frontmatter' (description, extras, headings, "
        "covered_by) — this is the default. Use section='Heading' "
        "to pull one chapter (small models: load the next child "
        "heading if the chapter is still large). detail='full' "
        "only when the peek shows extra functionality you do not "
        "already have as a tool. Global SKILL.md files are also "
        "Readable under ~/.agents/skills/. CE scripts: ce_run / "
        "ce_sweep, not a guessed skill path."
    ),
    input_schema={
        "type": "object",
        "required": ["name"],
        "properties": {
            "name": {
                "type": "string",
                "description": "Skill name (the `name:` from its SKILL.md frontmatter).",
            },
            "detail": {
                "type": "string",
                "description": "frontmatter (default) or full.",
            },
            "section": {
                "type": "string",
                "description": "Optional ## heading to load instead of the whole body.",
            },
        },
    },
    handler=_load_skill,
))


def _save_skill(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Author (or overwrite) a user-owned skill. Used by the
    "save this thread as a skill" flow — the agent distills a workflow
    and calls this to persist it. Only the two writable scopes are
    allowed; built-in / bundled skills are refused by skillkit."""
    name = str(payload.get("name") or "").strip()
    description = str(payload.get("description") or "").strip()
    body = str(payload.get("body") or "").strip()
    scope = str(payload.get("scope") or "workspace").strip()
    if not name or not body:
        return {"ok": False, "error": "`name` and `body` are required"}
    try:
        existing = skillkit.find_writable(workspace, name)
        if existing is not None:
            sk = skillkit.update_skill(workspace, name, description, body)
            action = "updated"
        else:
            sk = skillkit.create_skill(workspace, scope, name, description, body)
            action = "created"
    except skillkit.SkillError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "action": action, "skill": skillkit.to_summary(sk)}


register(Tool(
    name="save_skill",
    description=(
        "Save a reusable skill to this workspace (or the user-global "
        "scope) as a SKILL.md the agent can load later. Use this when "
        "the user asks to 'save this as a skill' / 'remember how to do "
        "this' / turn a workflow into something re-invokable. Provide a "
        "short kebab-case `name`, a `description` that STARTS with a "
        "'Use when …' trigger clause (so the skill fires automatically "
        "on similar requests), and a `body` of numbered steps / rules. "
        "Editing a built-in (curiosity-engine, packs) is refused; this "
        "only writes user-owned skills. Local-only — never publishes."
    ),
    input_schema={
        "type": "object",
        "required": ["name", "body"],
        "properties": {
            "name": {"type": "string", "description": "kebab-case skill name"},
            "description": {
                "type": "string",
                "description": "One paragraph; start with 'Use when …' for auto-trigger.",
            },
            "body": {"type": "string", "description": "Markdown: numbered steps / rules."},
            "scope": {
                "type": "string",
                "enum": ["workspace", "user"],
                "description": "workspace = private to this workspace (default); user = personal, every workspace.",
            },
        },
    },
    handler=_save_skill,
))


# ── Plot authoring (Vega-Lite specs → Plot tab) ─────────────────────


def _save_plot(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Save a Vega-Lite spec as a plot. The Plot tab picks it up
    immediately on next list refresh; renders via vega-embed."""
    name = str(payload.get("name") or "").strip()
    spec = payload.get("spec")
    plot_id = payload.get("id")
    origin = payload.get("origin")
    if not isinstance(spec, dict):
        return {"ok": False, "error": "spec must be a JSON object"}
    caption = str(payload.get("caption") or "").strip()
    if not caption and isinstance(spec.get("description"), str):
        caption = spec["description"].strip()
    sources = payload.get("sources")
    relates = payload.get("relates_to") or payload.get("relates")
    analysis = payload.get("analysis") or payload.get("source_analysis")
    try:
        rec = plots.save_plot(
            workspace, name=name, spec=spec,
            plot_id=str(plot_id) if isinstance(plot_id, str) and plot_id else None,
            origin=str(origin) if isinstance(origin, str) and origin else None,
            caption=caption or None,
            sources=sources if isinstance(sources, list) else None,
            relates_to=relates if isinstance(relates, list) else None,
            analysis=str(analysis) if isinstance(analysis, str) and analysis else None,
        )
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    # Hand a notice into the rail so the user sees the plot landed
    # even when the Plot tab isn't focused. The Plot tab itself
    # polls /api/plots on focus + on a periodic tick to pick up
    # agent-authored plots; this is just user-visible feedback.
    show = _daemon_json(
        "POST", "/api/plot/command",
        {"op": "show", "id": rec["id"], "wait_ack": True},
        timeout=45, workspace=workspace,
    )
    opened = not (show.get("ok") is False or show.get("error"))
    return {
        "ok": True,
        "id": rec["id"],
        "name": rec["name"],
        "shown": opened,
        "note": (
            f"Opened the Plot tab · {rec['name']}"
            if opened else
            f"Plot saved as {rec['name']}. Open the Plot tab to view it."
        ),
    }


_VEGA_LITE_SCHEMA = "https://vega.github.io/schema/vega-lite/v5.json"


register(Tool(
    name="save_plot",
    description=(
        "Save a Vega-Lite spec as a plot and OPEN the Plot tab. "
        "Call ONCE. Put every requested series (history, projection, "
        "derivative) in THIS spec — do not save a second plot. "
        "The spec is stored at "
        ".workbench/plots/<id>.json. Use when the user asks for a "
        "plot, chart, histogram, scatter, etc. — author the spec "
        "based on data already in the workspace (CSVs, parquet, "
        "the wiki/vault DuckDB) and save it. Pre-seeded DuckDB "
        "tables `files`, `pages` are usable as data sources via "
        "`{\"data\": {\"name\": \"pages\"}}` ... but the simpler path "
        "is to inline aggregated values in `data.values: [...]` "
        "after running a SQL query yourself.\n\n"
        "Every spec MUST include these fields — the Plot tab will "
        "render blank / unlabelled cards if any are missing:\n"
        "  · `data` (with inline `values` OR a registered name).\n"
        "  · `mark` — bar, line, point, area, rect, etc.\n"
        "  · `encoding` — at minimum the axes the mark consumes.\n"
        "  · `title` — short descriptor for the card header.\n"
        "  · `description` — ONE plain-prose sentence that explains "
        "what the chart shows. The Plot tab surfaces this as the "
        "figure legend under the chart, so write it for someone "
        "scanning the gallery cold. Don't skip it.\n"
        "Plain language for title, description, and axis/legend "
        "labels: avoid jargon and domain acronyms unless ubiquitous "
        "(AI, CPU, PDF, HTTP, SQL). Spell out or define shorthand "
        "like RLVR/RAG on first use — never leave undefined "
        "acronyms on a chart a cold reader can't parse.\n"
        "Legends & labels:\n"
        "  · If `color` encodes a category (country, group), leave "
        "its legend ON. Do not set `legend: null` on every layer — "
        "that hides the shared color key.\n"
        "  · Keep axis titles short (a few words). For row facets, "
        "set `header.labelOrient: \"top\"` so long facet labels "
        "don't collide with the y-axis title.\n"
        "  · `strokeDash` / `opacity` can have their own short "
        "legend; they do not replace the color legend.\n\n"
        "Minimal valid spec:\n"
        "  {\"$schema\": \"" + _VEGA_LITE_SCHEMA + "\",\n"
        "   \"title\": \"Token counts per page\",\n"
        "   \"description\": \"Distribution of tokens per page across the wiki, log-binned.\",\n"
        "   \"mark\": \"bar\",\n"
        "   \"data\": {\"values\": [{\"x\": 0, \"n\": 7}, ...]},\n"
        "   \"encoding\": {\n"
        "     \"x\": {\"field\": \"x\", \"type\": \"ordinal\"},\n"
        "     \"y\": {\"field\": \"n\", \"type\": \"quantitative\"}}}\n\n"
        "Tile sizing in the gallery (optional). When a plot has a "
        "lot of marks / categories / facets and would feel cramped "
        "at one column, declare more cells via `spec.usermeta.tile`:\n"
        "  {\"usermeta\": {\"tile\": {\"size\": \"wide\"}}}   // 2 cols\n"
        "  {\"usermeta\": {\"tile\": {\"size\": \"tall\"}}}   // 2 rows\n"
        "  {\"usermeta\": {\"tile\": {\"size\": \"large\"}}}  // 2x2\n"
        "  {\"usermeta\": {\"tile\": {\"size\": \"full\"}}}   // full row\n"
        "Or pass `cols`/`rows` directly (cols 1-4, rows 1-3). "
        "Default is 1x1; use this hint sparingly — most plots fit "
        "one cell."
    ),
    input_schema={
        "type": "object",
        "required": ["name", "spec"],
        "properties": {
            "name": {
                "type": "string",
                "description": "Human-readable plot name. Becomes the slug filename + the title shown in the Plot tab.",
            },
            "spec": {
                "type": "object",
                "description": "Complete Vega-Lite spec. Must include `mark` and `data` (or a `transform` chain).",
            },
            "id": {
                "type": "string",
                "description": (
                    "Optional existing plot id to update in place. "
                    "Omit to create a fresh plot (slug derived from name)."
                ),
            },
            "origin": {
                "type": "string",
                "description": (
                    "Optional breadcrumb identifying where the plot "
                    "was derived from (e.g. `tables/foo.md#table-1` "
                    "for a plot fanned out from a wiki table). When "
                    "you author a plot via the table → Plot flow, "
                    "set this to the exact `origin` value the prompt "
                    "supplies so the frontend can recognise existing "
                    "plots and skip re-generation if the user clicks "
                    "↗ Plot on the same table twice. Carried onto the "
                    "figure page as provenance when the plot is saved."
                ),
            },
            "caption": {
                "type": "string",
                "description": (
                    "Figure caption. Defaults to spec.description. "
                    "Copied onto the wiki figure page on save."
                ),
            },
            "analysis": {
                "type": "string",
                "description": "Wiki analysis page this plot belongs to (path or stem).",
            },
            "sources": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Vault / wiki source paths cited by this plot.",
            },
            "relates_to": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Related wiki page stems for [[wikilinks]].",
            },
        },
    },
    handler=_save_plot,
))


# ── Sheet tab (Univer) — same pipe as rail `!fn` ────────────────────
# Live focus is published by the browser to /api/sheet/focus. Writes
# go through /api/sheet/command → WS formula.run / sheet.select so
# the agent can land formulas without telling the user to paste.


def _daemon_port() -> str:
    import os
    return os.environ.get("CSWY_DAEMON_PORT") or "8765"


def _daemon_json(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    timeout: float = 15,
    workspace: Path | None = None,
) -> dict[str, Any]:
    import urllib.error
    import urllib.request

    # Scope live-tab HTTP to the agent workspace (not only daemon focus).
    url = f"http://127.0.0.1:{_daemon_port()}{path}"
    if workspace is not None and method.upper() == "GET":
        sep = "&" if "?" in path else "?"
        from urllib.parse import quote
        url = (
            f"http://127.0.0.1:{_daemon_port()}{path}"
            f"{sep}workspace={quote(str(workspace.resolve()))}"
        )
    data = None
    headers: dict[str, str] = {}
    if body is not None:
        payload = dict(body)
        if workspace is not None and "workspace" not in payload:
            payload["workspace"] = str(workspace.resolve())
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if workspace is not None:
        headers["X-Switchbay-Workspace"] = str(workspace.resolve())
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            err_body = json.load(e)
        except Exception:  # noqa: BLE001
            err_body = {"error": f"HTTP {e.code}"}
        if isinstance(err_body, dict):
            return {"ok": False, **err_body}
        return {"ok": False, "error": str(err_body)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def _sheet_context(workspace: Path, _: dict[str, Any]) -> dict[str, Any]:
    # Prefer live daemon; fall back to on-disk focus if the HTTP hop
    # fails (e.g. tool run outside MCP).
    live = _daemon_json("GET", "/api/sheet/focus", workspace=workspace)
    focus = live.get("focus") if isinstance(live, dict) else None
    if focus is None and not (isinstance(live, dict) and live.get("ok") is False):
        # GET returns {focus: …} without ok — empty focus is fine.
        pass
    if focus is None:
        from . import sheet_focus as sf
        focus = sf.load(workspace)
    if not focus or not focus.get("a1"):
        return {
            "ok": True,
            "focus": focus,
            "note": (
                "No sheet cell focus yet. Ask the user to click a cell "
                "in the Sheet tab, or pass an explicit cell= to "
                "sheet_set_formula / sheet_select."
            ),
        }
    return {
        "ok": True,
        "focus": focus,
        "note": (
            "Use sheet_set_formula to write formulas into cells (same "
            "path as the user's !fn prefix). Do NOT paste formulas in "
            "chat or search the wiki/deck for the spreadsheet. "
            "If preview cells look like '1.28 ± 0.04' they are TEXT — "
            "plain AVERAGE on them fails until means are extracted."
        ),
    }


def _sheet_select(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    rng = str(payload.get("range") or "").strip()
    if not rng:
        return {"ok": False, "error": "`range` is required (e.g. H18 or C18:H18)"}
    body = _daemon_json("POST", "/api/sheet/command", {
        "op": "select",
        "range": rng,
    }, workspace=workspace)
    if body.get("ok") is False or body.get("error"):
        return {"ok": False, "error": body.get("error") or "select failed", **{
            k: v for k, v in body.items() if k not in ("ok",)
        }}
    return {
        "ok": True,
        "range": body.get("range") or rng.upper(),
        "note": "Selection sent to the Sheet tab.",
    }


def _sheet_set_formula(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    writes = payload.get("writes")
    body_in: dict[str, Any]
    if isinstance(writes, list) and writes:
        body_in = {"op": "set_formula", "writes": writes, "wait_ack": True}
    else:
        formula = str(payload.get("formula") or "").strip()
        cell = str(payload.get("cell") or "").strip()
        if not formula:
            return {
                "ok": False,
                "error": "pass `formula` (+ optional `cell`) or `writes: [{cell, formula}]`",
            }
        body_in = {"op": "set_formula", "formula": formula, "wait_ack": True}
        if cell:
            body_in["cell"] = cell
    # Wait for browser apply + durable snapshot (ACK path).
    body = _daemon_json(
        "POST", "/api/sheet/command", body_in,
        timeout=45, workspace=workspace,
    )
    if body.get("ok") is False or body.get("error"):
        return {"ok": False, "error": body.get("error") or "set_formula failed"}
    note = body.get("note") or "Formulas applied in the Sheet tab."
    if body.get("durable") is False:
        note += " Warning: workbook snapshot save did not confirm."
    return {
        "ok": True,
        "writes": body.get("writes"),
        "applied": body.get("applied"),
        "durable": body.get("durable"),
        "command_id": body.get("command_id"),
        "note": note,
    }


register(Tool(
    name="sheet_context",
    description=(
        "Read the live Sheet tab focus: active cell (A1), selection "
        "range, used range, header row, and a compact value preview. "
        "Call FIRST for any spreadsheet request (average, fill "
        "formulas, 'put X in the selected cell'). Do NOT search the "
        "wiki or slide deck for sheet contents — this tool is the "
        "source of truth for what the user has open in Sheet."
    ),
    input_schema={
        "type": "object",
        "properties": {},
    },
    handler=_sheet_context,
))


register(Tool(
    name="sheet_select",
    description=(
        "Select a cell or range in the Sheet tab (A1 notation, e.g. "
        "`H18` or `C18:H18`). Switches the UI to Sheet and moves the "
        "active selection. Use before or with sheet_set_formula when "
        "you need a different target than the user's current focus."
    ),
    input_schema={
        "type": "object",
        "required": ["range"],
        "properties": {
            "range": {
                "type": "string",
                "description": "A1 cell or range, e.g. H18 or C2:H17.",
            },
        },
    },
    handler=_sheet_select,
))


register(Tool(
    name="sheet_set_formula",
    description=(
        "Write one or more spreadsheet formulas into the Sheet tab — "
        "the same path as the user's `!fn` rail prefix. Prefer this "
        "over telling the user to paste. Pass either:\n"
        "  · formula + optional cell (defaults to current sheet focus)\n"
        "  · writes: [{cell, formula}, …] for a batch (e.g. averages "
        "across several columns in one call)\n"
        "Leading `=` is optional. After writing, keep the chat reply "
        "to a one-liner. If preview cells are text like "
        "'1.28 ± 0.04', plain AVERAGE will not work until means are "
        "numeric — say so briefly or write extract formulas only when "
        "the pattern is clear."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "formula": {
                "type": "string",
                "description": "Single formula, e.g. AVERAGE(C2:C17) or =SUM(H2:H17).",
            },
            "cell": {
                "type": "string",
                "description": "Target A1 cell (e.g. H18). Defaults to current sheet focus.",
            },
            "writes": {
                "type": "array",
                "description": "Batch write: list of {cell, formula}.",
                "items": {
                    "type": "object",
                    "required": ["cell", "formula"],
                    "properties": {
                        "cell": {"type": "string"},
                        "formula": {"type": "string"},
                    },
                },
            },
        },
    },
    handler=_sheet_set_formula,
))


def _sheet_set_values(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    values = payload.get("values")
    if not isinstance(values, list) or not values:
        return {
            "ok": False,
            "error": "`values` is required: a 2D array, first row = headers",
        }
    origin = str(payload.get("origin") or payload.get("title") or "agent").strip()
    body = _daemon_json(
        "POST", "/api/sheet/command",
        {"op": "set_values", "values": values, "origin": origin, "wait_ack": True},
        timeout=45, workspace=workspace,
    )
    if body.get("ok") is False or body.get("error"):
        return {"ok": False, "error": body.get("error") or "set_values failed"}
    return {
        "ok": True,
        "rows": body.get("rows"),
        "origin": origin,
        "applied": body.get("applied"),
        "durable": body.get("durable"),
        "note": (
            f"Opened the Sheet tab · {origin} "
            f"({body.get('rows') or len(values)} rows). "
            "Capped at 1000 rows × 20 cols."
        ),
    }


register(Tool(
    name="sheet_set_values",
    description=(
        "Write a 2D table of VALUES into a sheet (Table → ↗ Sheet). "
        "Row 0 = headers. Call ONCE per requested sheet — the same "
        "`origin` overwrites that tab instead of duplicating it. "
        "Do not follow with a second sheet_set_values. "
        "Capped at 1000 rows × 20 columns."
    ),
    input_schema={
        "type": "object",
        "required": ["values"],
        "properties": {
            "values": {
                "type": "array",
                "description": "2D grid. First row = headers.",
                "items": {"type": "array"},
            },
            "origin": {
                "type": "string",
                "description": "Sheet tab label, e.g. 'life expectancy 5 countries'.",
            },
        },
    },
    handler=_sheet_set_values,
))


# ── Table / Plot / Sketch — same live-focus pattern as Sheet ────────


def _ui_focus_get(workspace: Path, surface: str) -> dict[str, Any] | None:
    live = _daemon_json(
        "GET", f"/api/ui/focus?surface={surface}", workspace=workspace,
    )
    if isinstance(live, dict) and "focus" in live:
        return live.get("focus")
    from . import ui_focus as uf
    return uf.load(workspace, surface)


def _table_data_files(workspace: Path) -> list[dict[str, Any]]:
    from . import fileops
    try:
        inv = fileops.inventory(workspace)
    except Exception:  # noqa: BLE001
        return []
    want = {"csv", "tsv", "parquet", "pq", "json", "jsonl", "ndjson"}
    rows = [f for f in inv if str(f.get("ext") or "") in want]
    rows.sort(key=lambda f: int(f.get("size") or 0), reverse=True)
    return rows[:16]


def _table_context(workspace: Path, _: dict[str, Any]) -> dict[str, Any]:
    focus = _ui_focus_get(workspace, "table")
    data_files = _table_data_files(workspace)
    note = (
        "SQL runs in-browser DuckDB-WASM. Quote workspace-relative paths "
        "only, e.g. read_csv_auto('data/owid/life-expectancy.csv'). "
        "Never use /api/fs/raw or host absolute paths — they fail. "
        "Do not grep CSVs. Call table_run_sql once, then sheet_set_values "
        "once, then save_plot once."
    )
    if not focus or not (focus.get("sql") or focus.get("query")):
        return {
            "ok": True,
            "focus": focus,
            "data_files": data_files,
            "note": "No SQL in the editor yet. " + note,
        }
    return {
        "ok": True,
        "focus": focus,
        "data_files": data_files,
        "note": note,
    }


def _table_run_sql(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    sql = str(payload.get("sql") or payload.get("query") or "").strip()
    if not sql:
        return {"ok": False, "error": "`sql` is required"}
    body = _daemon_json(
        "POST", "/api/table/command",
        {"op": "run_sql", "sql": sql, "wait_ack": True},
        timeout=45, workspace=workspace,
    )
    if body.get("ok") is False or body.get("error"):
        return {"ok": False, "error": body.get("error") or "run_sql failed"}
    return {
        "ok": True,
        "sql": body.get("sql") or sql,
        "applied": body.get("applied"),
        "result": body.get("result"),
        "command_id": body.get("command_id"),
        "note": body.get("note") or "SQL ran in the Table tab.",
    }


def _plot_context(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    from . import plots as plots_mod
    pid = str(payload.get("id") or "").strip()
    focus = _ui_focus_get(workspace, "plot")
    if not pid and focus:
        pid = str(focus.get("id") or "").strip()
    if not pid:
        listed = plots_mod.list_plots(workspace)[:8]
        return {
            "ok": True,
            "focus": focus,
            "plots": listed,
            "note": (
                "No active plot focused. Pass id=, or pick from `plots` "
                "and call plot_update / plot_show."
            ),
        }
    rec = plots_mod.get_plot(workspace, pid)
    if not rec:
        return {"ok": False, "error": f"unknown plot id {pid!r}", "focus": focus}
    return {
        "ok": True,
        "focus": focus,
        "plot": {
            "id": rec.get("id"),
            "name": rec.get("name"),
            "origin": rec.get("origin"),
            "spec": rec.get("spec"),
            "updated_at": rec.get("updated_at"),
        },
        "note": (
            "To adjust this plot, call plot_update with the modified "
            "spec (and id). Prefer plot_update over save_plot when "
            "editing the visible chart."
        ),
    }


def _plot_update(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    spec = payload.get("spec")
    if not isinstance(spec, dict):
        return {"ok": False, "error": "`spec` object is required"}
    body_in: dict[str, Any] = {"op": "update", "spec": spec, "wait_ack": True}
    if payload.get("id"):
        body_in["id"] = str(payload["id"])
    if payload.get("name"):
        body_in["name"] = str(payload["name"])
    body = _daemon_json(
        "POST", "/api/plot/command", body_in, timeout=45, workspace=workspace,
    )
    if body.get("ok") is False or body.get("error"):
        return {"ok": False, "error": body.get("error") or "plot update failed"}
    return {
        "ok": True,
        "id": body.get("id"),
        "name": body.get("name"),
        "applied": body.get("applied"),
        "durable": body.get("durable"),
        "command_id": body.get("command_id"),
        "note": body.get("note") or "Plot updated.",
    }


def _plot_show(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    body_in: dict[str, Any] = {"op": "show", "wait_ack": True}
    if payload.get("id"):
        body_in["id"] = str(payload["id"])
    body = _daemon_json(
        "POST", "/api/plot/command", body_in, timeout=45, workspace=workspace,
    )
    if body.get("ok") is False or body.get("error"):
        return {"ok": False, "error": body.get("error") or "plot show failed"}
    return {
        "ok": True,
        "id": body.get("id"),
        "name": body.get("name"),
        "applied": body.get("applied"),
        "command_id": body.get("command_id"),
    }


def _sketch_context(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    from . import sketches as sk
    sid = str(payload.get("sketch_id") or payload.get("id") or "").strip()
    focus = _ui_focus_get(workspace, "sketch")
    if not sid and focus:
        sid = str(focus.get("sketch_id") or "").strip()
    if not sid:
        return {
            "ok": True,
            "focus": focus,
            "note": (
                "No visible sketch/slide focused. Ask the user to open "
                "a slide in the Sketch tab, or pass sketch_id=. For deck "
                "edits, sketch_context after they navigate to the slide."
            ),
        }
    rec = sk.get_sketch(workspace, sid)
    if not rec:
        return {"ok": False, "error": f"unknown sketch_id {sid!r}", "focus": focus}
    # Compact text extract from Excalidraw elements for "small edits".
    texts: list[str] = []
    data = rec.get("data")
    if isinstance(data, dict):
        for el in (data.get("elements") or [])[:80]:
            if not isinstance(el, dict):
                continue
            t = el.get("text")
            if isinstance(t, str) and t.strip():
                texts.append(t.strip()[:120])
    return {
        "ok": True,
        "focus": focus,
        "sketch": {
            "id": rec.get("id"),
            "name": rec.get("name"),
            "kind": rec.get("kind"),
            "text_elements": texts[:30],
            "updated_at": rec.get("updated_at"),
        },
        "note": (
            "To change the VISIBLE slide, call author_slide with "
            "sketch_id set to this id (defaults to focus if omitted "
            "on newer agents). Small copy tweaks: re-author the same "
            "layout with updated slots. sketch_show jumps the UI to a "
            "slide. Do not rebuild the whole deck for a one-line fix."
        ),
    }


def _sketch_show(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    body_in: dict[str, Any] = {"op": "show", "wait_ack": True}
    if payload.get("sketch_id") or payload.get("id"):
        body_in["sketch_id"] = str(payload.get("sketch_id") or payload.get("id"))
    if payload.get("slide_index") is not None:
        try:
            body_in["slide_index"] = int(payload["slide_index"])
        except (TypeError, ValueError):
            return {"ok": False, "error": "slide_index must be an integer"}
    body = _daemon_json(
        "POST", "/api/sketch/command", body_in, timeout=45, workspace=workspace,
    )
    if body.get("ok") is False or body.get("error"):
        return {"ok": False, "error": body.get("error") or "sketch show failed"}
    return {
        "ok": True,
        "sketch_id": body.get("sketch_id"),
        "slide_index": body.get("slide_index"),
        "name": body.get("name"),
        "applied": body.get("applied"),
        "command_id": body.get("command_id"),
    }


register(Tool(
    name="table_context",
    description=(
        "Read the live Table tab focus: SQL currently in the editor "
        "and any last-result preview the browser published. Call first "
        "for table/SQL requests."
    ),
    input_schema={"type": "object", "properties": {}},
    handler=_table_context,
))


register(Tool(
    name="table_run_sql",
    description=(
        "Put SQL into the Table tab editor and run it — same path as "
        "the user's `!sql` rail prefix. DuckDB-WASM; pre-seeded tables "
        "files + pages. For workspace CSVs use a RELATIVE path: "
        "read_csv_auto('data/owid/life-expectancy.csv'). Never "
        "/api/fs/raw or /Users/... absolute paths (those fail). "
        "Call table_context first to see data_files. Do not grep the CSV."
    ),
    input_schema={
        "type": "object",
        "required": ["sql"],
        "properties": {
            "sql": {
                "type": "string",
                "description": (
                    "DuckDB SQL. Workspace files: "
                    "read_csv_auto('data/foo.csv') — relative path only."
                ),
            },
        },
    },
    handler=_table_run_sql,
))


register(Tool(
    name="plot_context",
    description=(
        "Read the focused Plot (or a named id): full Vega-Lite spec + "
        "metadata. Call first when the user asks to adjust 'this chart' "
        "or the visible plot."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "Plot id. Defaults to the focused plot card.",
            },
        },
    },
    handler=_plot_context,
))


register(Tool(
    name="plot_update",
    description=(
        "Update (or create) a Vega-Lite plot and show it in the Plot "
        "tab. When adjusting the visible chart, pass the focused id "
        "(from plot_context) and the full modified spec. Prefer this "
        "over save_plot for 'tweak this chart' requests — it also "
        "switches the UI to the plot."
    ),
    input_schema={
        "type": "object",
        "required": ["spec"],
        "properties": {
            "spec": {
                "type": "object",
                "description": "Full Vega-Lite spec object.",
            },
            "id": {
                "type": "string",
                "description": "Existing plot id to overwrite. Defaults to focus.",
            },
            "name": {
                "type": "string",
                "description": "Display name (kept from existing plot if omitted).",
            },
        },
    },
    handler=_plot_update,
))


register(Tool(
    name="plot_show",
    description=(
        "Switch to the Plot tab and highlight a plot card by id "
        "(defaults to focused plot)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Plot id to show."},
        },
    },
    handler=_plot_show,
))


register(Tool(
    name="sketch_context",
    description=(
        "Read the visible Sketch/deck slide: id, name, deck position, "
        "and text elements on the canvas. Call first for 'change this "
        "slide' / 'fix the title on the current slide' requests. "
        "Then author_slide(sketch_id=…) to rewrite that slide."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "sketch_id": {
                "type": "string",
                "description": "Sketch id. Defaults to the focused slide.",
            },
        },
    },
    handler=_sketch_context,
))


register(Tool(
    name="sketch_show",
    description=(
        "Switch to the Sketch tab and show a slide by sketch_id or "
        "0-based slide_index within the open deck."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "sketch_id": {"type": "string"},
            "slide_index": {
                "type": "integer",
                "description": "0-based index in the current deck.",
            },
        },
    },
    handler=_sketch_show,
))


# ── Inter-thread agent collaboration (A2A, charter 2026-07-04) ──────
# ask_thread rides the daemon's LOCAL A2A endpoint so inter-thread and
# (later) inter-instance collaboration share one code path. The
# handler is sync + blocking-HTTP by design: the daemon offloads
# tools.execute to a worker thread, and the MCP bridge runs handlers
# in its own subprocess — in both homes the event loop stays free to
# actually SERVE the /a2a call this makes.


def _list_threads_tool(workspace: Path, _: dict[str, Any]) -> dict[str, Any]:
    rows = conversations.list_threads(workspace)
    return {"threads": [
        {
            "thread_id": r["thread_id"],
            "title": r["title"],
            "kind": r["kind"],
            "chat_count": r["chat_count"],
            "last_summary": r["last_summary"],
        }
        for r in rows
    ]}


def _ask_thread(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    import os
    import urllib.error
    import urllib.request
    import uuid as _uuid

    message = str(payload.get("message") or "").strip()
    if not message:
        return {"ok": False, "error": "message is required"}
    meta: dict[str, Any] = {}
    if payload.get("thread_id"):
        meta["thread_id"] = str(payload["thread_id"])
    if payload.get("workspace"):
        meta["workspace"] = str(payload["workspace"])
    port = os.environ.get("CSWY_DAEMON_PORT") or "8765"
    rpc = {
        "jsonrpc": "2.0",
        "id": _uuid.uuid4().hex[:8],
        "method": "message/send",
        "params": {
            "message": {
                "kind": "message",
                "role": "user",
                "messageId": _uuid.uuid4().hex,
                "parts": [{"kind": "text", "text": message}],
            },
            "metadata": {"switchbay": meta},
        },
    }
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/a2a",
        data=json.dumps(rpc).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=330) as r:
            body = json.load(r)
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        return {"ok": False, "error": f"a2a call failed: {e}"}
    if "error" in body:
        return {"ok": False, "error": body["error"].get("message", "a2a error")}
    task = body.get("result") or {}
    reply = ""
    for art in task.get("artifacts") or []:
        for part in art.get("parts") or []:
            if part.get("kind") == "text":
                reply += part.get("text", "")
    return {
        "ok": True,
        "state": (task.get("status") or {}).get("state"),
        "task_id": task.get("id"),
        "thread_id": task.get("contextId"),
        "reply": reply,
    }


def _propose_split(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    import os
    import urllib.error
    import urllib.request

    pages = payload.get("pages")
    if not isinstance(pages, list) or not pages:
        return {"ok": False, "error": "`pages` (a list of wiki page ids) is required"}
    port = os.environ.get("CSWY_DAEMON_PORT") or "8765"
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/split/proposal",
        data=json.dumps({
            "pages": [str(p) for p in pages],
            "reason": str(payload.get("reason") or ""),
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = json.load(r)
    except urllib.error.HTTPError as e:
        try:
            body = json.load(e)
        except Exception:  # noqa: BLE001
            body = {"error": f"HTTP {e.code}"}
        return {"ok": False, **body}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
    return {
        "ok": True,
        "shown": body.get("shown"),
        "invalid_refs": body.get("invalid") or [],
        "note": (
            "Proposal is highlighted on the Graph tab's split review "
            "surface. The USER now reviews (click to add/remove, "
            "right-click flips move↔copy), names the new workspace, "
            "and confirms — nothing is split until they do. Tell them "
            "to look at the Graph tab."
        ),
    }


register(Tool(
    name="propose_split",
    description=(
        "Propose splitting a set of wiki pages out of THIS workspace "
        "into a new one (the user's 'split out everything about X' "
        "flow). First gather the page ids with the wiki tools "
        "(search_wiki / list_wiki_pages / wiki_neighbors) — ids are "
        "wiki-relative stems like 'concepts/transformers'. Calling "
        "this shows the set pre-highlighted on the graph's split "
        "review surface; the USER edits, names, and confirms there. "
        "This tool never splits anything itself. Entities/concepts "
        "default to being COPIED to both sides; other pages MOVE."
    ),
    input_schema={
        "type": "object",
        "required": ["pages"],
        "properties": {
            "pages": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Wiki page ids to split out (wiki-relative stems).",
            },
            "reason": {
                "type": "string",
                "description": "One line on the organizing principle (shown to the user).",
            },
        },
    },
    handler=_propose_split,
))


register(Tool(
    name="list_threads",
    description=(
        "List this workspace's conversation threads (id, title, kind, "
        "message count, last summary). Use it to find the right "
        "`thread_id` before calling ask_thread — e.g. when the user "
        "says 'ask the irrigation thread what it decided'."
    ),
    input_schema={"type": "object", "properties": {}},
    handler=_list_threads_tool,
))

register(Tool(
    name="ask_thread",
    description=(
        "Ask ANOTHER thread's agent a question and get its reply "
        "(A2A message/send). That thread answers with its own "
        "conversation context and memory — use this to make parallel "
        "threads share progress, or to consult a thread in a "
        "DIFFERENT registered workspace that already solved a "
        "similar problem (set `workspace` to its name). Omit "
        "`thread_id` to open a fresh thread in the target workspace. "
        "The exchange lands in that thread's transcript, so the user "
        "can follow up there. Busy threads (mid-stream) refuse; try "
        "again later. Never ask the thread you are currently "
        "answering in."
    ),
    input_schema={
        "type": "object",
        "required": ["message"],
        "properties": {
            "message": {
                "type": "string",
                "description": (
                    "The question or context to send. Be explicit — "
                    "the target thread can't see this conversation; "
                    "include whatever background it needs."
                ),
            },
            "thread_id": {
                "type": "string",
                "description": "Target thread id (from list_threads). Omit for a fresh thread.",
            },
            "workspace": {
                "type": "string",
                "description": (
                    "Registered workspace name (or path) to target. "
                    "Omit for the current workspace."
                ),
            },
        },
    },
    handler=_ask_thread,
))


# ── Wiki read tools — the zero-friction knowledge path ──────────────
# (added 2026-07-05 after "what do we know about X?" cost five Bash
# approval cards). Questions about captured knowledge must answer as
# smoothly as a chatbot: these are pure reads, workspace-scoped, and
# promptless (mcp__switchbay__* + native registry are pre-approved),
# so the agent never needs a shell to consult the wiki.


def _wiki_root(workspace: Path) -> Path:
    return workspace / "wiki"


def _iter_wiki_pages(workspace: Path):
    root = _wiki_root(workspace)
    if not root.is_dir():
        return
    for p in sorted(root.rglob("*.md")):
        yield p.relative_to(workspace).as_posix(), p


_FM_TITLE = re.compile(r"^title:\s*(.+)$", re.M)
_FM_TYPE = re.compile(r"^(?:type|kind):\s*(.+)$", re.M)
_WIKILINK = re.compile(r"\[\[([^\]|#]+)")


def _page_meta(text: str) -> tuple[str | None, str | None]:
    """(title, type) from a page's frontmatter head, best-effort."""
    head = text[:800]
    if not head.startswith("---"):
        return None, None
    mt = _FM_TITLE.search(head)
    mk = _FM_TYPE.search(head)
    return (mt.group(1).strip().strip('"') if mt else None,
            mk.group(1).strip().strip('"') if mk else None)


def _resolve_wiki_page(workspace: Path, ref: str) -> tuple[str, Path] | None:
    """Resolve `ref` (rel path, path suffix, stem, or title) to one
    wiki page. Never escapes the wiki root."""
    ref = (ref or "").strip().strip("/")
    if not ref:
        return None
    ref_l = ref.casefold().removesuffix(".md")
    candidates = list(_iter_wiki_pages(workspace))
    for rel, p in candidates:  # exact rel path (with/without wiki/ or .md)
        rl = rel.casefold().removesuffix(".md")
        if rl == ref_l or rl == f"wiki/{ref_l}".casefold() or rl.removeprefix("wiki/") == ref_l.removeprefix("wiki/"):
            return rel, p
    for rel, p in candidates:  # stem match ([[entities/transformer]] → transformer)
        if Path(rel).stem.casefold() == Path(ref_l).name:
            return rel, p
    for rel, p in candidates:  # frontmatter title match
        try:
            title, _ = _page_meta(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if title and title.casefold() == ref.casefold():
            return rel, p
    for rel, p in candidates:  # last resort: substring of stem/title
        if ref_l.replace(" ", "-") in Path(rel).stem.casefold():
            return rel, p
    return None


def _search_wiki(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    query = str(payload.get("query") or "").strip()
    if not query:
        return {"error": "query is required"}
    limit = max(1, min(int(payload.get("limit") or 8), 25))
    terms = [t.casefold() for t in re.findall(r"\w{2,}", query)]
    if not terms:
        return {"results": []}
    results = []
    for rel, p in _iter_wiki_pages(workspace):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        low = text.casefold()
        stem = Path(rel).stem.casefold()
        score = 0
        first_hit = -1
        for t in terms:
            n = low.count(t)
            if n == 0:
                continue
            score += min(n, 10)
            if t in stem:
                score += 25
            if first_hit < 0:
                first_hit = low.find(t)
        if score == 0:
            continue
        title, ptype = _page_meta(text)
        start = max(0, (first_hit if first_hit >= 0 else 0) - 80)
        snippet = " ".join(text[start:start + 240].split())
        results.append({
            "page": rel, "title": title or Path(rel).stem,
            "type": ptype, "score": score, "snippet": snippet,
        })
    results.sort(key=lambda r: -r["score"])
    return {"results": results[:limit], "total_matches": len(results)}


def _read_wiki_page(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    hit = _resolve_wiki_page(workspace, str(payload.get("page") or ""))
    if hit is None:
        return {"error": f"no wiki page matching {payload.get('page')!r} — try search_wiki"}
    rel, p = hit
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"error": f"read failed: {e}"}
    title, ptype = _page_meta(text)
    truncated = len(text) > 12000
    return {
        "page": rel, "title": title or Path(rel).stem, "type": ptype,
        "content": text[:12000], "truncated": truncated,
    }


def _list_wiki_pages(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    want = str(payload.get("type") or "").strip().casefold() or None
    out = []
    for rel, p in _iter_wiki_pages(workspace):
        try:
            title, ptype = _page_meta(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if want and (ptype or "").casefold() != want:
            continue
        out.append({"page": rel, "title": title or Path(rel).stem, "type": ptype})
        if len(out) >= 400:
            break
    return {"pages": out, "count": len(out)}


# ── In-process knowledge graph (multi-hop) ───────────────────────────
# CE builds a rich typed graph in `.curator/graph.kuzu` (WikiLink / Cites
# / etc.) but that needs kuzu installed + a fresh rebuild, and the
# viewer's data.json drops all edges when kuzu is absent. So we build the
# same graph IN-PROCESS from the wiki pages themselves — the filesystem is
# the source of truth — giving the agent real multi-hop traversal, path
# finding, and co-citation ("bridge") queries with no external dependency.
# This is what lets the agent answer connective / multi-hop questions that
# lexical search alone can't (structural disconnection).

_VAULT_CITE = re.compile(r"\(vault:([^)\s]+)")


class _GraphIndex:
    __slots__ = ("out", "inc", "cites", "ptype", "ptitle")

    def __init__(self) -> None:
        self.out: dict[str, set[str]] = {}     # rel -> outgoing wikilink targets
        self.inc: dict[str, set[str]] = {}     # rel -> incoming backlinks
        self.cites: dict[str, set[str]] = {}   # rel -> cited vault source paths
        self.ptype: dict[str, str] = {}
        self.ptitle: dict[str, str] = {}


_GRAPH_CACHE: dict[str, tuple[tuple[int, float], _GraphIndex]] = {}


def _graph_signature(workspace: Path) -> tuple[int, float]:
    """Cheap staleness key: (page count, max mtime). Rebuild when it changes."""
    n = 0
    mx = 0.0
    for _rel, p in _iter_wiki_pages(workspace):
        n += 1
        try:
            mx = max(mx, p.stat().st_mtime)
        except OSError:
            pass
    return (n, mx)


def _graph_index(workspace: Path) -> _GraphIndex:
    """Build (or return cached) the wikilink + citation graph for a
    workspace. One pass over `wiki/**/*.md`: resolve `[[wikilinks]]` to
    page rels (both directions) and extract `(vault:…)` citations."""
    key = str(workspace)
    sig = _graph_signature(workspace)
    cached = _GRAPH_CACHE.get(key)
    if cached is not None and cached[0] == sig:
        return cached[1]

    texts: dict[str, str] = {}
    stem_to_rel: dict[str, str] = {}
    idx = _GraphIndex()
    for rel, p in _iter_wiki_pages(workspace):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        texts[rel] = text
        stem_to_rel.setdefault(Path(rel).stem.casefold(), rel)
        title, typ = _page_meta(text)
        idx.ptype[rel] = (typ or "").strip()
        idx.ptitle[rel] = title or Path(rel).stem
        idx.out[rel] = set()
        idx.inc[rel] = set()
        idx.cites[rel] = set()
    for rel, text in texts.items():
        for m in _WIKILINK.findall(text):
            tgt = stem_to_rel.get(Path(m.strip()).name.casefold())
            if tgt and tgt != rel:
                idx.out[rel].add(tgt)
                idx.inc[tgt].add(rel)
        for m in _VAULT_CITE.findall(text):
            idx.cites[rel].add(m.strip().rstrip(")").rstrip("."))
    _GRAPH_CACHE.pop(key, None)
    _GRAPH_CACHE[key] = (sig, idx)
    overflow = len(_GRAPH_CACHE) - 4
    if overflow > 0:
        for old in list(_GRAPH_CACHE)[:overflow]:
            _GRAPH_CACHE.pop(old, None)
    return idx


def _wiki_neighbors(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Multi-hop wikilink neighbourhood (BFS to `hops`, both directions),
    with per-neighbour distance + type. `hops=1` reproduces the old
    single-hop behaviour."""
    hit = _resolve_wiki_page(workspace, str(payload.get("page") or ""))
    if hit is None:
        return {"error": f"no wiki page matching {payload.get('page')!r} — try search_wiki"}
    rel, _ = hit
    hops = max(1, min(int(payload.get("hops") or 2), 4))
    direction = str(payload.get("direction") or "both").lower()
    idx = _graph_index(workspace)
    from collections import deque
    dist: dict[str, int] = {rel: 0}
    q: deque[str] = deque([rel])
    while q:
        cur = q.popleft()
        d = dist[cur]
        if d >= hops:
            continue
        nbrs: set[str] = set()
        if direction in ("out", "both"):
            nbrs |= idx.out.get(cur, set())
        if direction in ("in", "both"):
            nbrs |= idx.inc.get(cur, set())
        for nb in nbrs:
            if nb not in dist:
                dist[nb] = d + 1
                q.append(nb)
    items = sorted(((r, d) for r, d in dist.items() if r != rel), key=lambda kv: (kv[1], kv[0]))
    return {
        "page": rel, "hops": hops, "count": len(items),
        "neighbors": [
            {"page": r, "type": idx.ptype.get(r, ""),
             "title": idx.ptitle.get(r, ""), "distance": d}
            for r, d in items[:120]
        ],
    }


def _wiki_path(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Shortest wikilink path between two pages (undirected connectivity),
    so the agent can see HOW two concepts relate. Returns the page chain."""
    ha = _resolve_wiki_page(workspace, str(payload.get("from") or payload.get("page_a") or ""))
    hb = _resolve_wiki_page(workspace, str(payload.get("to") or payload.get("page_b") or ""))
    if ha is None or hb is None:
        return {"error": "both 'from' and 'to' must resolve to wiki pages"}
    a, b = ha[0], hb[0]
    if a == b:
        return {"from": a, "to": b, "hops": 0, "path": [a]}
    max_hops = max(1, min(int(payload.get("max_hops") or 6), 12))
    idx = _graph_index(workspace)
    from collections import deque
    prev: dict[str, str | None] = {a: None}
    q: deque[tuple[str, int]] = deque([(a, 0)])
    while q:
        cur, d = q.popleft()
        if d >= max_hops:
            continue
        for nb in idx.out.get(cur, set()) | idx.inc.get(cur, set()):
            if nb not in prev:
                prev[nb] = cur
                if nb == b:
                    path = [b]
                    while prev[path[-1]] is not None:
                        path.append(prev[path[-1]])  # type: ignore[arg-type]
                    path.reverse()
                    return {"from": a, "to": b, "hops": len(path) - 1, "path": path}
                q.append((nb, d + 1))
    return {"from": a, "to": b, "result": "no path found", "max_hops": max_hops}


def _wiki_shared_sources(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Vault sources cited by BOTH pages — the evidentiary overlap that
    grounds a relationship even when the pages don't link each other."""
    ha = _resolve_wiki_page(workspace, str(payload.get("from") or payload.get("page_a") or ""))
    hb = _resolve_wiki_page(workspace, str(payload.get("to") or payload.get("page_b") or ""))
    if ha is None or hb is None:
        return {"error": "both 'page_a' and 'page_b' must resolve to wiki pages"}
    idx = _graph_index(workspace)
    shared = sorted(idx.cites.get(ha[0], set()) & idx.cites.get(hb[0], set()))
    return {"page_a": ha[0], "page_b": hb[0], "shared_sources": shared, "count": len(shared)}


def _wiki_related_by_sources(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Pages that share the most vault sources with `page` but are NOT
    directly wikilinked — non-obvious ("bridge") connections co-citation
    surfaces that the link graph misses."""
    hit = _resolve_wiki_page(workspace, str(payload.get("page") or ""))
    if hit is None:
        return {"error": f"no wiki page matching {payload.get('page')!r} — try search_wiki"}
    rel = hit[0]
    limit = max(1, min(int(payload.get("limit") or 10), 40))
    idx = _graph_index(workspace)
    mine = idx.cites.get(rel, set())
    if not mine:
        return {"page": rel, "related": [], "note": "page cites no vault sources"}
    linked = idx.out.get(rel, set()) | idx.inc.get(rel, set())
    scored = []
    for other, srcs in idx.cites.items():
        if other == rel or other in linked or idx.ptype.get(other) == "source":
            continue
        n = len(mine & srcs)
        if n:
            scored.append((other, n))
    scored.sort(key=lambda kv: (-kv[1], kv[0]))
    return {
        "page": rel,
        "related": [
            {"page": r, "shared_sources": n, "type": idx.ptype.get(r, ""),
             "title": idx.ptitle.get(r, "")}
            for r, n in scored[:limit]
        ],
    }


register(Tool(
    name="search_wiki",
    description=(
        "Search this workspace's wiki (the curated knowledge base) by "
        "keywords. THE tool for any 'what do we know about X?' "
        "question — returns matching pages with title, type and a "
        "snippet, ranked. Follow up with read_wiki_page on the best "
        "hits. Never use shell commands to explore the wiki."
    ),
    input_schema={
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {"type": "string", "description": "Keywords, e.g. 'transformer attention scaling'."},
            "limit": {"type": "integer", "description": "Max results (default 8, cap 25)."},
        },
    },
    handler=_search_wiki,
))

register(Tool(
    name="read_wiki_page",
    description=(
        "Read one wiki page's full content (frontmatter + body, "
        "capped at 12k chars). Accepts a path from search_wiki "
        "results, a [[wikilink]] target, or a page title."
    ),
    input_schema={
        "type": "object",
        "required": ["page"],
        "properties": {
            "page": {"type": "string", "description": "Page path, wikilink target, stem, or title."},
        },
    },
    handler=_read_wiki_page,
))

register(Tool(
    name="list_wiki_pages",
    description=(
        "List the wiki's pages (path, title, type), optionally "
        "filtered by type (concept, entity, fact, evidence, analysis, "
        "note, source…). Good for an overview of what the workspace "
        "knows; use search_wiki for topical questions."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "type": {"type": "string", "description": "Optional page type filter."},
        },
    },
    handler=_list_wiki_pages,
))

register(Tool(
    name="wiki_neighbors",
    description=(
        "A page's graph neighbourhood by MULTI-HOP traversal of the "
        "[[wikilink]] graph — every page reachable within `hops` steps "
        "(both directions), each with its distance and type. THE tool for "
        "'how does X connect to the rest', building context around a "
        "topic, or gathering the pages a multi-hop question needs. Default "
        "2 hops; raise to 3–4 for broad context."
    ),
    input_schema={
        "type": "object",
        "required": ["page"],
        "properties": {
            "page": {"type": "string", "description": "Page path, wikilink target, stem, or title."},
            "hops": {"type": "integer", "description": "Traversal depth 1–4 (default 2)."},
            "direction": {"type": "string", "enum": ["out", "in", "both"],
                          "description": "Follow outgoing links, backlinks, or both (default)."},
        },
    },
    handler=_wiki_neighbors,
))

register(Tool(
    name="wiki_path",
    description=(
        "Shortest [[wikilink]] path between two pages — the chain of pages "
        "that connects them. Use to answer 'how are A and B related?' and "
        "to reason across the hops of a multi-hop question."
    ),
    input_schema={
        "type": "object",
        "required": ["from", "to"],
        "properties": {
            "from": {"type": "string", "description": "Start page (path/stem/title)."},
            "to": {"type": "string", "description": "End page (path/stem/title)."},
            "max_hops": {"type": "integer", "description": "Cap 1–12 (default 6)."},
        },
    },
    handler=_wiki_path,
))

register(Tool(
    name="wiki_shared_sources",
    description=(
        "The vault sources cited by BOTH of two pages — the shared "
        "evidence behind a relationship, even when the pages don't link "
        "each other. Use to ground a claim that two topics are connected."
    ),
    input_schema={
        "type": "object",
        "required": ["page_a", "page_b"],
        "properties": {
            "page_a": {"type": "string", "description": "First page (path/stem/title)."},
            "page_b": {"type": "string", "description": "Second page (path/stem/title)."},
        },
    },
    handler=_wiki_shared_sources,
))

register(Tool(
    name="wiki_related_by_sources",
    description=(
        "Pages that share the most vault sources with a page but AREN'T "
        "directly wikilinked — non-obvious ('bridge') connections that the "
        "link graph misses. Use to surface related knowledge that keyword "
        "search and link-walking overlook."
    ),
    input_schema={
        "type": "object",
        "required": ["page"],
        "properties": {
            "page": {"type": "string", "description": "Page path, wikilink target, stem, or title."},
            "limit": {"type": "integer", "description": "Max results 1–40 (default 10)."},
        },
    },
    handler=_wiki_related_by_sources,
))


# ── CE-native vault / kuzu tools (additive; do NOT replace search_wiki) ──
# search_wiki queries curated wiki pages. ce_vault_search queries ingested
# source documents in vault/vault.db. Different corpora — both offered so
# the model can pick. Graph tools shell out to CE's graph.py (kuzu).


def _ce_page_id(workspace: Path, ref: str) -> tuple[str | None, str | None]:
    """Resolve a user/agent page ref to CE's `type/slug.md` form.

    Bare stems return [] from graph.py with no error — resolve first.
    """
    hit = _resolve_wiki_page(workspace, ref)
    if hit is None:
        return None, f"no wiki page matching {ref!r} — try search_wiki"
    rel, _p = hit
    # rel is wiki-relative like "concepts/foo.md" or "concepts/foo"
    rid = rel
    if rid.startswith("wiki/"):
        rid = rid[5:]
    if not rid.endswith(".md"):
        rid = f"{rid}.md"
    return rid, None


def _ce_vault_search(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    from . import cebridge

    query = str(payload.get("query") or "").strip()
    if not query:
        return {"error": "query is required"}
    limit = max(1, min(int(payload.get("limit") or 10), 40))
    mode = str(payload.get("mode") or "hybrid").strip().lower()
    if mode not in ("fts5", "semantic", "hybrid"):
        mode = "hybrid"
    graph_expand = bool(payload.get("graph_expand", True))
    args = [query, "--mode", mode, "--limit", str(limit)]
    if graph_expand:
        args.append("--graph-expand")
    return cebridge.run_script("vault_search.py", args, cwd=workspace, timeout=90.0)


def _ce_graph_neighbors(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    from . import cebridge

    page_id, err = _ce_page_id(workspace, str(payload.get("page") or ""))
    if err:
        return {"error": err}
    hops = max(1, min(int(payload.get("hops") or 2), 6))
    direction = str(payload.get("direction") or "both").strip().lower()
    if direction not in ("out", "in", "both"):
        direction = "both"
    return cebridge.run_script(
        "graph.py",
        ["neighbors", "wiki", page_id, "--hops", str(hops), "--direction", direction],
        cwd=workspace, timeout=60.0,
    )


def _ce_graph_path(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    from . import cebridge

    a, err_a = _ce_page_id(
        workspace, str(payload.get("from") or payload.get("page_a") or ""))
    b, err_b = _ce_page_id(
        workspace, str(payload.get("to") or payload.get("page_b") or ""))
    if err_a:
        return {"error": err_a}
    if err_b:
        return {"error": err_b}
    max_hops = max(1, min(int(payload.get("max_hops") or 6), 12))
    return cebridge.run_script(
        "graph.py",
        ["path", "wiki", a, b, "--max-hops", str(max_hops)],
        cwd=workspace, timeout=60.0,
    )


def _ce_shared_sources(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    from . import cebridge

    a, err_a = _ce_page_id(
        workspace, str(payload.get("page_a") or payload.get("from") or ""))
    b, err_b = _ce_page_id(
        workspace, str(payload.get("page_b") or payload.get("to") or ""))
    if err_a:
        return {"error": err_a}
    if err_b:
        return {"error": err_b}
    return cebridge.run_script(
        "graph.py",
        ["shared-sources", "wiki", a, b],
        cwd=workspace, timeout=60.0,
    )


def _ce_bridge_candidates(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    from . import cebridge

    limit = max(1, min(int(payload.get("limit") or 20), 50))
    return cebridge.run_script(
        "graph.py",
        ["bridge-candidates", "wiki", "--limit", str(limit)],
        cwd=workspace, timeout=90.0,
    )


register(Tool(
    name="ce_vault_search",
    description=(
        "Search INGESTED SOURCE DOCUMENTS in the vault (vault/vault.db) via "
        "curiosity-engine: FTS5, semantic, or hybrid (default), optionally "
        "graph-expanded through kuzu. Use when the user wants primary "
        "sources / PDFs / raw notes — NOT the curated wiki. For curated "
        "wiki pages use search_wiki instead. Returns ranked vault paths "
        "and snippets. Missing embeddings/kuzu names the reason rather "
        "than failing silently."
    ),
    input_schema={
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {"type": "string", "description": "Search query over vault sources."},
            "limit": {"type": "integer", "description": "Max hits (default 10, cap 40)."},
            "mode": {
                "type": "string",
                "enum": ["fts5", "semantic", "hybrid"],
                "description": "Retrieval mode (default hybrid).",
            },
            "graph_expand": {
                "type": "boolean",
                "description": "1-hop kuzu expansion (default true).",
            },
        },
    },
    handler=_ce_vault_search,
))

register(Tool(
    name="ce_graph_neighbors",
    description=(
        "Kuzu-backed multi-hop neighbourhood of a wiki page (CE graph.py). "
        "Richer typed edges than the in-process wiki_neighbors tool when "
        "the graph DB is built. Accepts path/stem/title; resolved to "
        "type/slug.md for CE. On missing kuzu returns a clear install hint."
    ),
    input_schema={
        "type": "object",
        "required": ["page"],
        "properties": {
            "page": {"type": "string"},
            "hops": {"type": "integer", "description": "1–6 (default 2)."},
            "direction": {"type": "string", "enum": ["out", "in", "both"]},
        },
    },
    handler=_ce_graph_neighbors,
))

register(Tool(
    name="ce_graph_path",
    description=(
        "Shortest kuzu wikilink path between two pages (CE graph.py path). "
        "Prefer this over wiki_path when the CE graph is available."
    ),
    input_schema={
        "type": "object",
        "required": ["from", "to"],
        "properties": {
            "from": {"type": "string"},
            "to": {"type": "string"},
            "max_hops": {"type": "integer"},
        },
    },
    handler=_ce_graph_path,
))

register(Tool(
    name="ce_shared_sources",
    description=(
        "Vault sources cited by BOTH of two wiki pages (CE graph.py "
        "shared-sources) — co-citation evidence from the kuzu graph."
    ),
    input_schema={
        "type": "object",
        "required": ["page_a", "page_b"],
        "properties": {
            "page_a": {"type": "string"},
            "page_b": {"type": "string"},
        },
    },
    handler=_ce_shared_sources,
))

register(Tool(
    name="ce_bridge_candidates",
    description=(
        "Page pairs that share vault sources but are not wikilinked "
        "(CE graph.py bridge-candidates) — candidate connections for "
        "curation / multi-hop discovery."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Max pairs (default 20)."},
        },
    },
    handler=_ce_bridge_candidates,
))


# CE script wrappers (Copilot / HTTP providers have no CE-aware shell).
from . import ce_tools as _ce_tools  # noqa: E402,F401
from . import workspace_plan as _workspace_plan  # noqa: E402
_workspace_plan.register_tools()
