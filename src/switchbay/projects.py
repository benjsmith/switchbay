"""Read-only view over a workspace's CE multi-project state.

CE shipped first-class projects: each workspace can host N named
projects, with a registry at `.curator/projects.json` and home pages
at `wiki/projects/<name>.md`. Each wiki page declares its memberships
via a `projects: [...]` frontmatter list. This module gives switchbay
a structured view over that state for the Project Dashboard tab.

We don't write here — lifecycle (`create`, `archive`, `rename`,
`delete`, `restore`, `purge`) goes through CE's `scripts/projects.py`,
invoked via verbs / agent runs. That keeps the contract one-way: CE
owns the registry, switchbay renders it.

Workspaces that haven't activated multi-project mode (no
`.curator/projects.json`) are perfectly valid — `list_projects`
returns an empty list and the dashboard renders an empty state with
a hint to run `projects.py create`.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger("switchbay.projects")


# ── Registry I/O ───────────────────────────────────────────────────


def _registry_path(workspace: Path) -> Path:
    return workspace / ".curator" / "projects.json"


def load_registry(workspace: Path) -> dict[str, Any]:
    """Return the parsed `.curator/projects.json`. If absent or
    unreadable, return an empty registry (multi-project mode just
    hasn't been activated for this workspace)."""
    p = _registry_path(workspace)
    if not p.is_file():
        return {"projects": {}}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("projects.json unreadable; treating as empty registry")
        return {"projects": {}}
    raw.setdefault("projects", {})
    return raw


# ── Frontmatter helpers ────────────────────────────────────────────


_PROJECTS_LINE = re.compile(r"^\s*projects:\s*\[(?P<list>[^\]]*)\]\s*$")
_PROJECT_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9-]*")
_TITLE_LINE = re.compile(r"^\s*title:\s*(?P<val>.+?)\s*$")
_TYPE_LINE = re.compile(r"^\s*type:\s*(?P<val>\S+)\s*$")


def _read_frontmatter_block(text: str) -> str | None:
    """Tiny pure-Python YAML-front-matter slicer. Returns the raw
    content between the `---` fences, or None when the file isn't
    front-mattered. Avoids pulling pyyaml in for a one-off."""
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    return text[3:end]


def _extract_projects_field(block: str) -> set[str]:
    """Pull project tokens out of a `projects: [a, b, c]` line. We
    only support the inline-list form, which is what CE's
    `set_frontmatter_field` writes — a multi-line YAML list would
    need a real parser."""
    for line in block.splitlines():
        m = _PROJECTS_LINE.match(line)
        if not m:
            continue
        return set(_PROJECT_TOKEN.findall(m.group("list")))
    return set()


def _extract_scalar(block: str, pattern: re.Pattern[str]) -> str | None:
    for line in block.splitlines():
        m = pattern.match(line)
        if not m:
            continue
        val = m.group("val").strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        return val
    return None


# ── Walk wiki/ once, build per-project page index ─────────────────


def _walk_wiki(workspace: Path) -> list[Path]:
    wiki = workspace / "wiki"
    if not wiki.is_dir():
        return []
    return [p for p in wiki.rglob("*.md") if p.is_file()]


# Page types that count as "notes" or "todos" for the dashboard
# rollup. CE's canonical taxonomy uses `note` and `todo-list`; we
# accept the alternate `todo` token in case workspaces drift.
_NOTE_TYPES = {"note"}
_TODO_TYPES = {"todo-list", "todo", "todos"}


# Synthetic project name for untagged notes/todos. Not a real project
# in CE's registry — we never write this anywhere; it only exists in
# the dashboard rollup. Chosen as a non-CE-valid name so no real
# project can ever collide with it.
GENERAL_BUCKET = "_general"


def _index_pages(workspace: Path) -> tuple[
    dict[str, list[dict[str, Any]]], list[dict[str, Any]]
]:
    """One pass over `wiki/**/*.md`. Returns
    `(tagged_by_project, untagged_notes_todos)`:

      - `tagged_by_project[name]` — every page with a `projects:` field
        listing that name. Includes notes + todos + any other type.
      - `untagged_notes_todos` — pages with NO `projects:` field whose
        type is `note` or `todo-list`. These get rolled up under a
        synthetic "General" project card so they're never lost.

    Other-type pages with no `projects:` tag are skipped — they live
    in the broader wiki and are reachable via the Browser/Graph tabs;
    the Projects dashboard's job is the project rollup specifically."""
    tagged: dict[str, list[dict[str, Any]]] = {}
    untagged: list[dict[str, Any]] = []
    workspace_str = str(workspace.resolve())
    for path in _walk_wiki(workspace):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        block = _read_frontmatter_block(text)
        if block is None:
            continue
        members = _extract_projects_field(block)
        title = _extract_scalar(block, _TITLE_LINE) or path.stem
        ptype = (_extract_scalar(block, _TYPE_LINE) or "unclassified").lower()
        rel = str(path.resolve())
        if rel.startswith(workspace_str + "/"):
            rel = rel[len(workspace_str) + 1:]
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        record = {
            "path": rel,
            "title": title,
            "type": ptype,
            "mtime": mtime,
        }
        if members:
            for name in members:
                tagged.setdefault(name, []).append(record)
            continue
        # No project tag — only keep notes/todos for the General card.
        if ptype in _NOTE_TYPES or ptype in _TODO_TYPES:
            untagged.append(record)
    return tagged, untagged


def _split_by_kind(pages: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Bucket a list of page records into `notes`, `todos`, `other`
    so the dashboard can render them separately within each project's
    card without asking the frontend to re-classify."""
    notes: list[dict[str, Any]] = []
    todos: list[dict[str, Any]] = []
    other: list[dict[str, Any]] = []
    for p in pages:
        t = (p.get("type") or "").lower()
        if t in _NOTE_TYPES:
            notes.append(p)
        elif t in _TODO_TYPES:
            todos.append(p)
        else:
            other.append(p)
    return {"notes": notes, "todos": todos, "other": other}


# ── Curator log tail ───────────────────────────────────────────────


# Curator-log line shape (CURATE-wave classification entries):
#   - `<path>` + {<tag>} (was [...], now [...])  [<reason>, sim=<N>]
# Captures the verb glyph (`+` add / `-` remove), the file path, the
# project token, and the reason+sim. Anything that doesn't match
# falls through to the raw-line fallback.
_CURATOR_LINE = re.compile(
    r"""
    ^\s*-\s+                              # bullet
    `(?P<path>[^`]+)`\s*                  # backticked path
    (?P<op>[+\-])\s*                      # add or remove
    \{(?P<tag>[^}]+)\}                    # the changed project tag
    .*?                                   # audit (was/now)
    (?:                                   # optional reason block
      \[(?P<reason>[a-zA-Z]+)
      (?:,\s*sim=(?P<sim>[0-9.]+))?
      \]
    )?
    \s*$
    """,
    re.VERBOSE,
)


def _humanize_curator_line(line: str) -> str:
    """Translate one classifier line into a terse single-clause
    sentence. Returns the raw line on parse failure so we never lose
    information — better an awkward line than a missing one."""
    m = _CURATOR_LINE.match(line)
    if not m:
        return line
    path = m.group("path")
    # Strip dir + extension; CE pages are slug-named so the bare
    # filename reads naturally even without spaces.
    slug = path.rsplit("/", 1)[-1].removesuffix(".md")
    bucket = path.split("/", 1)[0] if "/" in path else ""
    bucket_label = {
        "entities": "entity",
        "concepts": "concept",
        "evidence": "evidence",
        "facts": "fact",
        "analyses": "analysis",
        "sources": "source",
        "figures": "figure",
        "tables": "table",
        "notes": "note",
        "todos": "todo",
        "projects": "project",
    }.get(bucket, "page")
    op = m.group("op")
    tag = m.group("tag")
    reason = m.group("reason")
    sim = m.group("sim")
    verb = "Tagged" if op == "+" else "Untagged"
    detail = ""
    if reason:
        # Rewrite a couple of the dense reason tokens into something
        # less jargony. `semantic` and `citation` are the common ones.
        nice_reason = {
            "semantic": "semantic match",
            "citation": "cited from project",
            "wikilink": "wiki-linked from project",
            "inheritance": "inherited from synthesis",
        }.get(reason, reason)
        if sim:
            try:
                detail = f" ({nice_reason}, {float(sim):.2f})"
            except ValueError:
                detail = f" ({nice_reason})"
        else:
            detail = f" ({nice_reason})"
    return f"{verb} {bucket_label} {slug} → {tag}{detail}"


def _curator_log_tail(workspace: Path, project: str, limit: int = 30) -> list[str]:
    """Best-effort scan of `.curator/log.md` for recent classifier
    lines that mention this project. CE's curator writes entries
    like `- \`entities/foo.md\` + {bar} (was [], now ['bar'])
    [semantic, sim=0.5763]`; we humanize each line into a single
    sentence. Lines that don't fit the classifier shape (session
    headers, prose) fall through unchanged. Newest-first."""
    p = workspace / ".curator" / "log.md"
    if not p.is_file():
        return []
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return []
    needle = project.lower()
    raw = [ln.rstrip() for ln in text.splitlines() if needle in ln.lower()]
    pretty = [_humanize_curator_line(ln) for ln in raw]
    return list(reversed(pretty[-limit:]))


# ── Public API ─────────────────────────────────────────────────────


def list_projects(workspace: Path) -> dict[str, Any]:
    """Enriched per-project view for the Project Dashboard.

    Each project card carries the registry meta + total member count
    + a `kinds` rollup with `{notes, todos, other}` integer counts so
    the UI can show "3 notes · 2 todos" badges without a follow-up
    fetch.

    A synthetic "General" project (`name == GENERAL_BUCKET`) is
    appended whenever there are notes or todos in the wiki without a
    `projects:` tag — that bucket is a write-time UX promise: a note
    or todo never disappears just because it wasn't tagged."""
    reg = load_registry(workspace)
    raw = reg.get("projects") or {}
    tagged, untagged = _index_pages(workspace)

    items: list[dict[str, Any]] = []
    for name, entry in raw.items():
        pages = tagged.get(name, [])
        kinds = _split_by_kind(pages)
        archived = bool(entry.get("deleted_at"))
        items.append({
            "name": name,
            "description": entry.get("description") or "",
            "home_page": entry.get("home_page") or f"projects/{name}.md",
            "created_at": entry.get("created_at"),
            "deleted_at": entry.get("deleted_at"),
            "archived": archived,
            "member_count": len(pages),
            "kinds": {k: len(v) for k, v in kinds.items()},
            "synthetic": False,
        })

    # Active first, then alphabetic — matches the natural reading
    # order of the dashboard.
    items.sort(key=lambda x: (x["archived"], x["name"]))

    if untagged:
        general_kinds = _split_by_kind(untagged)
        items.append({
            "name": GENERAL_BUCKET,
            "title": "General",
            "description": (
                "Notes and todos that aren't tagged to a project. "
                "Tag a page with `projects: [<name>]` in its "
                "frontmatter to move it to a project card."
            ),
            "home_page": None,
            "created_at": None,
            "deleted_at": None,
            "archived": False,
            "member_count": len(untagged),
            "kinds": {k: len(v) for k, v in general_kinds.items()},
            "synthetic": True,
        })

    return {
        "registry_present": _registry_path(workspace).is_file(),
        "projects": items,
    }


def project_detail(workspace: Path, name: str) -> dict[str, Any] | None:
    """Drill-in payload: project meta + member pages bucketed by kind
    (notes / todos / other) + recent log excerpts.

    Pass `name == GENERAL_BUCKET` to fetch the synthetic "General"
    bucket (untagged notes + todos). Returns None when a non-synthetic
    name isn't in the registry."""
    tagged, untagged = _index_pages(workspace)

    if name == GENERAL_BUCKET:
        pages = sorted(untagged, key=lambda p: p["mtime"], reverse=True)
        return {
            "project": {
                "name": GENERAL_BUCKET,
                "title": "General",
                "description": (
                    "Notes and todos that aren't tagged to a project."
                ),
                "home_page": None,
                "archived": False,
                "member_count": len(pages),
                "synthetic": True,
            },
            "pages": pages,
            "kinds": _split_by_kind(pages),
            "log": [],
        }

    reg = load_registry(workspace)
    entry = (reg.get("projects") or {}).get(name)
    if entry is None:
        return None

    pages = tagged.get(name, [])
    pages = sorted(pages, key=lambda p: p["mtime"], reverse=True)

    archived = bool(entry.get("deleted_at"))
    return {
        "project": {
            "name": name,
            "description": entry.get("description") or "",
            "home_page": entry.get("home_page") or f"projects/{name}.md",
            "created_at": entry.get("created_at"),
            "deleted_at": entry.get("deleted_at"),
            "archived": archived,
            "member_count": len(pages),
            "synthetic": False,
        },
        "pages": pages,
        "kinds": _split_by_kind(pages),
        "log": _curator_log_tail(workspace, name),
    }
