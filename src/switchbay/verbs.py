"""Verb registry: maps user intent (view/plot/sketch/...) to a tab + payload.

A "verb" is a small function that takes a search query against the
workspace and returns ranked `Match` candidates. Each match knows
which tab kind it should open in and the payload that tab needs
(page id, file path, etc). The same registry powers two surfaces:

  · slash commands today — `/view sales pipeline` resolves through here
  · agent tool calls when the MCP bridge lands — verbs become the
    canonical "do this" entry points the assistant can call

New tabs register their verbs here as they're added: a Plot tab might
register a `plot` verb that filters the candidate set to plottable
sources (csv/parquet/table-shaped); a Sketch tab might register
`sketch`. Everything stays centralised so adding a verb is one line of
glue plus a handler.

Tab routing is verb-dependent: `view notes/foo.md` opens the Editor
(markdown) tab; `plot data.csv` would open the Plot (vega) tab even
though `view data.csv` opens the Sheet (univer) tab. This module
provides the common asset → default-tab mapping by file extension;
verbs override it as needed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Iterable

log = logging.getLogger("switchbay.verbs")

# Tab kinds we know how to route to today. Strings here MUST match the
# `kind` values used in mode.json — the frontend's TabsContext indexes
# by kind to switch tabs. Adding a new tab just means registering its
# extensions + verbs from the new tab's setup; nothing in this module
# needs to change. The set is informational — new strings are accepted
# at runtime.
KNOWN_TAB_KINDS = {
    "markdown", "duckdb", "graph", "univer", "vega",
    "sketch",   # Excalidraw + drawio combined sketcher
    "agents",
}


@dataclass
class Match:
    """One candidate result from a verb. The frontend's `nav` handler
    uses (tab_kind, payload) to switch tabs and prime selection."""
    label: str               # human-readable name shown in disambiguation lists
    detail: str              # extra context line under the label
    tab_kind: str            # which tab to open ("editor", "duckdb", …)
    payload: dict[str, Any]  # tab-specific nav payload (selection, hints)
    score: float = 0.0


@dataclass
class VerbResult:
    matches: list[Match] = field(default_factory=list)

    @property
    def best(self) -> Match | None:
        return self.matches[0] if self.matches else None


@dataclass
class VerbContext:
    """Everything a verb handler needs to find candidates."""
    workspace: Path
    query: str
    # CE data.json `pages` map (id → page dict) when available.
    # None if no wiki/ or the daemon hasn't built it yet.
    pages: dict[str, Any] | None = None
    # Workspace-relative file paths the verb can search through.
    # Populated by the dispatcher to avoid re-walking the tree per verb.
    files: list[str] = field(default_factory=list)
    # Saved Vega-Lite plot metadata (id, name, …) — populated lazily
    # for verbs that care (e.g. `plot`); empty list otherwise.
    plots: list[dict[str, Any]] = field(default_factory=list)
    # Saved sketches (Excalidraw / drawio) — populated for the
    # `sketch` verb.
    sketches: list[dict[str, Any]] = field(default_factory=list)


VerbHandler = Callable[[VerbContext], VerbResult]


@dataclass
class Verb:
    name: str
    aliases: list[str]
    description: str
    handler: VerbHandler


REGISTRY: dict[str, Verb] = {}


def register(verb: Verb) -> None:
    REGISTRY[verb.name] = verb
    for alias in verb.aliases:
        REGISTRY[alias] = verb


def lookup(name: str) -> Verb | None:
    """Resolve a verb by name OR alias (case-insensitive)."""
    return REGISTRY.get(name.lower().strip())


def all_verbs() -> list[Verb]:
    """Distinct verbs (de-duplicating alias entries)."""
    seen: set[str] = set()
    out: list[Verb] = []
    for v in REGISTRY.values():
        if v.name in seen:
            continue
        seen.add(v.name)
        out.append(v)
    return out


# ── Tab routing ─────────────────────────────────────────────────────


_EXT_TO_TAB = {
    # Pages live in the Editor tab (kind=markdown in mode.json).
    ".md": "markdown",
    ".markdown": "markdown",
    # Table-shaped sources open in the Sheet tab (kind=univer) — the
    # editable surface; the Table (DuckDB) tab is for SQL exploration
    # which the user can swap to via the ↗ Table button. Distinct from
    # .db files below, which only have an SQL story today.
    ".csv": "univer",
    ".tsv": "univer",
    ".parquet": "univer",
    ".json": "univer",
    ".ndjson": "univer",
    # Database files → Table tab (introspection + read-only SQL).
    ".db": "duckdb",
    ".sqlite": "duckdb",
    ".sqlite3": "duckdb",
    # Text-ish things that don't have a dedicated tab fall back to the
    # Editor for now (read-only).
    ".txt": "markdown",
}


def tab_kind_for_path(rel: str) -> str:
    """Default tab kind for a workspace-relative path. Verbs may
    override (e.g. `plot` always returns the Plot tab regardless of
    extension)."""
    ext = Path(rel).suffix.lower()
    return _EXT_TO_TAB.get(ext, "editor")


def register_extension(ext: str, tab_kind: str) -> None:
    """Add or override a file extension → tab kind mapping. New tabs
    (Plot, Sketch, …) call this from their setup to take over
    extensions; user-customised tabs can do the same. The leading dot
    is required ('.csv' not 'csv') for parity with `Path.suffix`."""
    if not ext.startswith("."):
        ext = "." + ext
    _EXT_TO_TAB[ext.lower()] = tab_kind


# ── Fuzzy matching helpers ──────────────────────────────────────────


def _normalise(s: str) -> str:
    return s.lower().strip()


def _score(query: str, candidate: str) -> float:
    """Hybrid fuzzy-ish score in [0, 1]. We require every query token
    to appear as a substring (precision), then sort by overall string
    similarity (relevance)."""
    q = _normalise(query)
    c = _normalise(candidate)
    if not q:
        return 0.0
    tokens = q.split()
    for t in tokens:
        if t and t not in c:
            return 0.0
    # Boost full prefix match — "sales" matching "sales-pipeline".
    base = SequenceMatcher(None, q, c).ratio()
    if c.startswith(q):
        base += 0.15
    if all(c.find(t) <= len(c) // 2 for t in tokens):
        base += 0.05  # tokens cluster early
    return min(base, 1.0)


def _match_page(page_id: str, page: dict, score: float) -> Match:
    title = str(page.get("title") or page_id)
    path = str(page.get("path") or "")
    ptype = str(page.get("type") or "page")
    # CE's data.json paths are relative to wiki/. The selection layer
    # uses workspace-relative paths everywhere else.
    workspace_rel = path if path.startswith("wiki/") else f"wiki/{path}"
    return Match(
        label=title,
        detail=f"page · {ptype} · {workspace_rel}",
        tab_kind="markdown",
        payload={
            "selection": {"kind": "page", "id": page_id, "path": workspace_rel},
        },
        score=score,
    )


def _match_file(rel: str, score: float) -> Match:
    p = Path(rel)
    ext = p.suffix.lower()
    tab = tab_kind_for_path(rel)
    payload: dict[str, Any] = {}
    if tab == "duckdb":
        # Database file. The Table tab opens these by introspection;
        # the path travels through payload.open_db so the tab's effect
        # can pick it up regardless of the selection layer.
        payload = {"selection": None, "open_db": rel}
    elif tab == "univer":
        # CSV / parquet / JSON-as-table — the Sheet tab consumes a
        # `csv`-kinded selection and pumps the rows into Univer.
        payload = {"selection": {"kind": "csv", "path": rel}}
    elif tab == "markdown":
        # Markdown or generic text. The Editor tab uses the same
        # `page`-kinded selection it already gets from sidebar clicks.
        payload = {"selection": {"kind": "page", "id": rel, "path": rel}}
    else:
        # Custom tab kinds (extension packs, …) get the raw path; their
        # effect can pick it up.
        payload = {"selection": None, "open_path": rel}
    return Match(
        label=p.name,
        detail=f"{ext.lstrip('.') or 'file'} · {rel}",
        tab_kind=tab,
        payload=payload,
        score=score,
    )


def search_pages(ctx: VerbContext) -> list[Match]:
    if not ctx.pages:
        return []
    out: list[Match] = []
    for pid, page in ctx.pages.items():
        if not isinstance(page, dict):
            continue
        title = str(page.get("title") or pid)
        path = str(page.get("path") or "")
        # Score against title first, then path, then id; take the best.
        s = max(_score(ctx.query, title), _score(ctx.query, path), _score(ctx.query, pid))
        if s > 0:
            out.append(_match_page(pid, page, s))
    return out


def search_files(ctx: VerbContext, *, exts: Iterable[str] | None = None) -> list[Match]:
    """Score workspace files by name-against-query. `exts` filters to a
    subset (e.g. {'.csv', '.parquet'} for the `plot` verb)."""
    out: list[Match] = []
    ext_filter = {e.lower() for e in exts} if exts else None
    for rel in ctx.files:
        if ext_filter and Path(rel).suffix.lower() not in ext_filter:
            continue
        s = _score(ctx.query, rel)
        if s > 0:
            out.append(_match_file(rel, s))
    return out


def merge_and_rank(*groups: list[Match], limit: int = 10) -> list[Match]:
    flat: list[Match] = []
    for g in groups:
        flat.extend(g)
    flat.sort(key=lambda m: -m.score)
    return flat[:limit]


# ── Built-in verbs ──────────────────────────────────────────────────


def _view_handler(ctx: VerbContext) -> VerbResult:
    """Open the matching page or file in its natural tab. Pages map to
    the Editor; CSV/parquet/db files map to the Table tab; other
    files default to the Editor."""
    return VerbResult(matches=merge_and_rank(
        search_pages(ctx),
        search_files(ctx),
    ))


register(Verb(
    name="view",
    aliases=["show", "open", "go"],
    description=(
        "Open a doc, table, sheet, or DB in the appropriate tab. "
        "Fuzzy-matches against page titles and file paths."
    ),
    handler=_view_handler,
))


def _match_plot(plot: dict[str, Any], score: float) -> Match:
    pid = str(plot.get("id") or "")
    name = str(plot.get("name") or pid)
    return Match(
        label=name,
        detail=f"plot · {pid}",
        tab_kind="vega",
        payload={
            "selection": {"kind": "plot", "id": pid, "name": name},
            "open_plot": pid,
        },
        score=score,
    )


def _plot_handler(ctx: VerbContext) -> VerbResult:
    """Open a saved Vega-Lite plot by name. Falls back to listing
    plottable data files (csv/parquet) so `/plot sales` can both
    surface an existing 'sales-pipeline' plot AND offer to plot
    'sales.csv' if no saved plot matches."""
    plot_matches: list[Match] = []
    for p in ctx.plots:
        s = max(
            _score(ctx.query, str(p.get("name") or "")),
            _score(ctx.query, str(p.get("id") or "")),
        )
        if s > 0:
            plot_matches.append(_match_plot(p, s))
    file_matches = search_files(
        ctx, exts={".csv", ".tsv", ".parquet", ".json", ".ndjson"},
    )
    # Files normally route to the Sheet tab; for the `plot` verb,
    # override their tab_kind so the agent knows we mean "open this
    # source in the Plot tab and ask the LLM to author a spec".
    for m in file_matches:
        m.tab_kind = "vega"
        m.payload = {
            "selection": m.payload.get("selection"),
            "open_data": m.payload.get("selection", {}).get("path"),
        }
    return VerbResult(matches=merge_and_rank(plot_matches, file_matches))


register(Verb(
    name="plot",
    aliases=["chart", "graph-data"],
    description=(
        "Open a saved Vega-Lite plot by name, or surface a CSV / parquet "
        "to author a new plot from. Fuzzy-matches plot names first, then "
        "data files."
    ),
    handler=_plot_handler,
))


def _match_sketch(sk: dict[str, Any], score: float) -> Match:
    sid = str(sk.get("id") or "")
    name = str(sk.get("name") or sid)
    kind = str(sk.get("kind") or "excalidraw")
    return Match(
        label=name,
        detail=f"sketch · {kind} · {sid}",
        tab_kind="sketch",
        payload={
            "selection": {"kind": "sketch", "id": sid, "name": name},
            "open_sketch": sid,
        },
        score=score,
    )


def _sketch_handler(ctx: VerbContext) -> VerbResult:
    """Open a saved sketch (Excalidraw or drawio) by name."""
    out: list[Match] = []
    for sk in ctx.sketches:
        s = max(
            _score(ctx.query, str(sk.get("name") or "")),
            _score(ctx.query, str(sk.get("id") or "")),
        )
        if s > 0:
            out.append(_match_sketch(sk, s))
    return VerbResult(matches=merge_and_rank(out))


register(Verb(
    name="sketch",
    aliases=["draw", "diagram"],
    description=(
        "Open a saved sketch by name. Sketches are Excalidraw scenes or "
        "drawio diagrams stored in `.workbench/sketches/` with a PNG "
        "export at `figures/<id>.png`."
    ),
    handler=_sketch_handler,
))


# `/rule` and `/rules` are routed through the verb registry so the
# autocomplete menu surfaces them, but their handlers are stubs — the
# real plumbing lives in daemon._try_rule_dispatch (rule registration)
# and a dedicated dispatcher for /rules (listing). Both are intercepted
# before the normal verb-dispatch path; these registrations exist so
# the autocomplete shows them as options.

def _rule_stub(_: VerbContext) -> VerbResult:
    return VerbResult(matches=[])


register(Verb(
    name="rule",
    aliases=[],
    description=(
        "Save a shortcut, e.g. `/rule \"show me Mistral\" /view Mistral`. "
        "Or just type 'when I say X, do Y' and switchbay will save it."
    ),
    handler=_rule_stub,
))


register(Verb(
    name="rules",
    aliases=[],
    description="List or delete saved shortcuts. `/rules` to list, `/rules delete <id>` to remove.",
    handler=_rule_stub,
))


# ── CE action verbs ─────────────────────────────────────────────────


# These four slash commands don't navigate / don't return Match
# candidates — the daemon special-cases their slash names and
# dispatches a canned prompt to the chat agent (which already has
# the curiosity-engine skill discoverable via skillkit). The verb
# registry entries exist so autocomplete shows them with a
# description, and so /rule "x" /curate ... can register them.

def _action_stub(_: VerbContext) -> VerbResult:
    return VerbResult(matches=[])


register(Verb(
    name="curate",
    aliases=["curator"],
    description=(
        "Run the curiosity-engine curator agent in the background. "
        "Optional mode picks a curator pass: `/curate figures`, "
        "`/curate tables`, `/curate sources`, `/curate repair`, "
        "`/curate analyses`, `/curate sweep`. Without a mode, runs "
        "the standard sweep over the active workspace."
    ),
    handler=_action_stub,
))


register(Verb(
    name="viewer",
    aliases=["build-viewer"],
    description=(
        "Regenerate the wiki viewer (data.json + static bundle) by "
        "running CE's viewer.sh build. Distinct from /view (which "
        "OPENS a doc) — this one REBUILDS the data the graph tab "
        "renders. Use after curation, manual page edits, or when "
        "node colours / counts look stale."
    ),
    handler=_action_stub,
))


register(Verb(
    name="add-source",
    aliases=["addsource", "source-add"],
    description=(
        "Drop a file or pasted text into the workspace's vault/raw/ "
        "and immediately ingest it via CE's local_ingest.py — "
        "distilling vault content into wiki/sources/. Pass a path "
        "(`/add-source /Users/me/paper.pdf`) or paste raw text "
        "(`/add-source Some research notes…`) and the agent does "
        "the right thing."
    ),
    handler=_action_stub,
))


register(Verb(
    name="rescan",
    aliases=["refresh", "reindex"],
    description=(
        "Force a cold re-index of the workspace: drops switchbay's "
        "in-memory wiki cache, deletes the on-disk data.json, runs "
        "CE's viewer.sh build fresh, and tells the frontend to "
        "refetch /api/tree + /api/graph/data. Use when the BROWSER "
        "sidebar shows stale folders / pages that don't clear after "
        "a workspace switch."
    ),
    handler=_action_stub,
))


register(Verb(
    name="intro",
    aliases=[],
    description=(
        "Reopen the Switch Bay intro deck in its own tab — a short "
        "tour of what the workbench does plus the CE-vs-RAG benchmark. "
        "Pinned on first install; closable; this brings it back."
    ),
    handler=_action_stub,
))


register(Verb(
    name="slideshow",
    aliases=[
        "slideshows", "presentation", "presentations",
        "html-deck", "html-decks", "slideshow-from-md",
    ],
    description=(
        "List/open HTML slideshows (`slideshows/<slug>/`, "
        "`[[slideshow:slug|title]]`) or build one from markdown. "
        "Not Sketch kind:deck. "
        "`/slideshows` lists; `/slideshow <slug>` opens; "
        "`/slideshow from-md <path.md> [slug] [--no-media]` builds "
        "(H1 title slide, H2 per slide, lists, image:/figure wikilinks, "
        "### Voiceover → TTS with ~3s autoplay delay)."
    ),
    handler=_action_stub,
))


register(Verb(
    name="library",
    aliases=["lib", "portfolio"],
    description=(
        "Open the Library tab — carousels of durable reports, "
        "slideshows, and worksheets under `reports/`, `slideshows/`, "
        "`worksheets/`. Search with `/library search <q>`."
    ),
    handler=_action_stub,
))


register(Verb(
    name="report-doc",
    aliases=["report-package", "durable-report"],
    description=(
        "Open a durable report package from `reports/<slug>/` "
        "(wikilink `[[report:slug|title]]`). Distinct from ephemeral "
        "agent Report tab / create_report. "
        "`/report-doc <slug>` opens; `/report-doc promote <id>` saves "
        "an ephemeral report into the library."
    ),
    handler=_action_stub,
))


register(Verb(
    name="worksheet",
    aliases=["worksheets", "workbook", "workbooks"],
    description=(
        "List or open named worksheets under `worksheets/<slug>/` "
        "(`[[worksheet:slug|title]]`). Scratch sheet stays at "
        "`.workbench/state/sheet.json`; Save as promotes a named package. "
        "`/worksheets` lists; `/worksheet <slug>` opens in the Sheet tab."
    ),
    handler=_action_stub,
))


register(Verb(
    name="walkthrough",
    aliases=["tour", "guide"],
    description=(
        "Start the interactive product tour — coach-marks over "
        "Settings, ingest, curate, graph, tabs, Zen mode, and more. "
        "Also auto-runs once on first install (Esc or ✕ exits anytime)."
    ),
    handler=_action_stub,
))


register(Verb(
    name="ingest",
    aliases=["drain"],
    description=(
        "Drain everything currently sitting in vault/raw/ — runs "
        "CE's local_ingest.py against the queue and writes "
        "wiki/sources/ pages with citations. Usually paired with a "
        "follow-up /curate to stitch the new sources into the rest "
        "of the wiki."
    ),
    handler=_action_stub,
))


# Capture verbs (D7) + thread→project binding (D8). Deterministic,
# daemon-side, intercepted in handle_ws BEFORE the CE-action stage —
# no LLM turn in the capture path. Stubs exist for autocomplete and
# so /rule can target them.

register(Verb(
    name="note",
    aliases=[],
    description=(
        "Capture a note instantly (no agent turn). Lands in "
        "wiki/notes/new.md for the curator to file; start with "
        "`topic: <name>` to route to a topic page directly. A "
        "thread bound via /project tags the note; inline "
        "#<project> overrides."
    ),
    handler=_action_stub,
))


register(Verb(
    name="todo",
    aliases=[],
    description=(
        "Capture a todo instantly (no agent turn). Appends a "
        "checkbox to wiki/todos/unfiled.md; the curator assigns "
        "priority + ID on its next sweep. Project binding as /note."
    ),
    handler=_action_stub,
))


register(Verb(
    name="decision",
    aliases=[],
    description=(
        "Capture a decision instantly (no agent turn). Appends to "
        "wiki/notes/decisions.md and queues it for heartbeat "
        "promotion into the project's charter page (review card "
        "in the rail before anything is amended)."
    ),
    handler=_action_stub,
))


register(Verb(
    name="project",
    aliases=[],
    description=(
        "Bind the focused thread to a project: /project <name>. "
        "Captures in the thread inherit the project; /project none "
        "unbinds; bare /project shows the binding. Same set as the "
        "ThreadBar picker (CE's project registry)."
    ),
    handler=_action_stub,
))


register(Verb(
    name="clear-rail-history",
    aliases=["clear-history", "clear-rail", "rail-clear", "wipe-rail"],
    description=(
        "Truncate the rail's persisted history for the active "
        "workspace. Drops every event row + thread row in "
        ".workbench/state/conversations.db, then clears the rail "
        "UI. Permanent — there's no undo. Use when the transcript "
        "has accumulated noise you don't want carried forward."
    ),
    handler=_action_stub,
))
