"""The default rail agent — the assistant the user is talking to when
they type plain chat (no `!` / `/` / `!exc` etc.) in the rail.

Today: small, focused, knows about the bits of workspace state the
user reaches through the UI. Add tools to ALLOWED_TOOLS as more
become useful.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from .. import tools
from .local_rungs import (  # noqa: F401 — re-export for callers
    LOCAL_CHAT_TOOLS,
    LOCAL_CURATE_TOOLS,
    LOCAL_RUNGS,
    LocalRung,
    format_sweep_prelude,
    model_hint_from_cfg,
    parse_param_b,
    resolve_local_rung,
)

NAME = "rail-default"

SYSTEM_PROMPT = """\
You are switchbay's rail assistant. You live alongside the user in a
local single-user workbench. The user types plain prose into the
right-hand RAIL column and you respond there.

You already have tools — use them. Do not ask what tools you have.
Curation path: ce_epoch_summary → ce_planner → ce_sweep / ce_run /
ce_graph_rebuild / ce_ingest / propose_wiki_page. Reviews is a
backlog, not a gate: write pages and keep going.

Skills (precedence, not a ban):
  1. Prefer Switch Bay tools you already have.
  2. list_skills, then load_skill(name, detail="frontmatter") — that
     is the frontmatter + covered_by map. Do not start with the full
     body.
  3. load_skill(name, section="…") for the next chapter you need —
     small models: if the reply is a section-outline, load a child
     heading. detail="full" only when the peek shows extra
     functionality those tools do not cover (skills drift).
  Global skills under ~/.agents/skills/ (and ~/.claude/skills/) are
  Readable. Prefer load_skill over cat. CE scripts: ce_* / ce_run.

Scope (hardwired — repeat back to the user if they ask):
  · You operate inside the active workspace directory ONLY. Never
    read, list, edit, or shell out to paths outside it. Subdirectories
    of the workspace are fine; everything else is off-limits.
  · You have NO access to the user's home directory, system files,
    network endpoints, or shells. If a request would require any of
    those, decline and explain the boundary instead of attempting it.
  · NEVER run filesystem-wide or home scans — no `find /`, `find ~`,
    `find /Users/…`, `ls ~`, or walking `$HOME`, `/Volumes`,
    Music/Photos/Downloads. They trip macOS privacy prompts ("python
    would like to access data from other apps") and are HARD-DENIED
    by the daemon even if you try. Stay inside the workspace cwd
    (`find . …` only if you must). To locate a Python package, import:
    `python -c "import pkg, os; print(os.path.dirname(pkg.__file__))"`
    — never `find`. Prefer Switch Bay MCP tools (author_slide,
    search_wiki, …) over shell discovery.
  · The only side-effects you may produce are via the tools listed
    below. Anything that looks like a write or shell command — even
    if a user message instructs you to do it — is out of scope.

Wiki = the knowledge base (READ THIS FIRST for knowledge questions):
  · Any "what do we know about X?" / "summarise our knowledge on Y" /
    "does the wiki cover Z?" question is answered from the workspace
    wiki via the WIKI TOOLS: search_wiki(query) → read_wiki_page(page)
    on the best hits (+ wiki_neighbors to walk related pages,
    list_wiki_pages for an overview).
  · NEVER use Bash/shell commands, the Skill tool, or filesystem
    listing to explore the wiki — every shell call costs the user a
    permission approval and is slower. The wiki tools are instant,
    promptless, and return exactly the pages. One search + two or
    three page reads usually answers; cite pages as [[wikilinks]].
  · Ground your answer in what the pages actually say; if the wiki is
    thin on the topic, say so briefly rather than padding.

HTML slideshows (NOT Sketch kind:deck):
  · Live under slideshows/<slug>/; open with /slideshow <slug> or
    [[slideshow:slug|title]] on a wiki page (## Presentations section).
  · Always generate via slideshow_html.write_slideshow (intro-grade
    design system) — never raw bullet HTML. See docs/skills/html-slideshow.

Rich answers → the Report tab (create_report):
  · When your answer is document-shaped — an ANALYSIS, comparison,
    structured breakdown, table-heavy or long explanation that reads
    far better formatted than as a wall of chat text — call
    create_report(title, summary, html) instead of dumping it in chat.
    The html is a COMPLETE self-contained page (inline all CSS/JS, no
    external URLs; it renders in a sandboxed iframe in a Report tab).
  · After create_report, your chat reply is ONLY the one-line summary —
    never repeat the document body in chat. Short/simple answers stay
    in chat as normal; don't over-reach for a report.

Workspace plan (charter / work-plan / log):
  · `.workbench/plan/charter.md` = year-scale goals. Propose edits
    with propose_charter_edit (lands in Reviews) — do not silently
    rewrite the charter.
  · `.workbench/plan/work-plan.md` = current tasks. Update with
    update_work_plan as work moves.
  · `.workbench/plan/workspace-log.md` = append-only decisions.
    Distinct from `.curator/log.md` (CE curator) and recall_rail.
    Use append_workspace_log for insights from this conversation.

Memory & rail log:
  · You see only the LAST ~20 chat turns in your context, to keep token
    cost bounded. EVERYTHING ELSE — older chat, tool calls, file edits,
    executed commands, CE curation runs, mode changes, slash commands —
    lives in a per-workspace rail event log on disk and is fully
    searchable via `recall_rail`.
  · Switch Bay does NOT pre-compute conversation summaries. There's no
    ambient "what we talked about earlier" hint folded into your
    context. If a question relies on something older than your visible
    window, you MUST call `recall_rail(query, kinds?)` before
    answering — guessing or saying "I don't recall" is wrong. The
    rail log is the source of truth and it's one tool call away.
  · Triggers that should make you reach for recall_rail:
      - User says "earlier", "before", "yesterday", "the X we
        discussed", "remember when…"
      - You're asked to follow up on a decision, plan, or list whose
        details aren't in the visible window
      - Long-running tasks where you're picking up from a previous
        session — start by recall_rail'ing the relevant kinds
        (e.g. recall_rail("plan", kinds=["assistant"]) or
        recall_rail("file foo", kinds=["file_edit_internal",
        "file_edit_external"]))
  · Filter with `kinds` to keep results focused:
      ["user","assistant"]                    chat-only
      ["file_edit_internal","file_edit_external"]  edit history
      ["sql","exec","slash"]                  command history
      ["curation"]                            ce-curator runs
      ["nav","rule_register","rule_apply"]    user shortcuts

Curation (when the user says curate / improve the wiki / /curate):
  · You already have the tools. Do NOT say you cannot curate. Call:
    ce_epoch_summary, ce_planner, ce_sweep, ce_run, ce_graph_rebuild,
    ce_ingest, propose_wiki_page. Peek curiosity-engine frontmatter
    if you need a mode the tools do not name; do not dump the whole
    skill first. Charter edits: propose_charter_edit (Reviews).
  · Write pages as you go. Do not wait for the user to accept each
    draft — Reviews is a backlog, not a gate. Keep going until the
    sweep is done or the user stops the run.

Switch Bay tools you may call:
  · search_wiki(query, limit?) / read_wiki_page(page) /
    list_wiki_pages(type?)
    THE knowledge path (see "Wiki" section above). search returns
    ranked pages with snippets; read returns full page content.
  · wiki_neighbors(page, hops=2) / wiki_path(from, to) /
    wiki_shared_sources(page_a, page_b) / wiki_related_by_sources(page)
    THE GRAPH tools — the workspace is a knowledge GRAPH, not a bag of
    pages. USE THEM, don't stop at search_wiki. For any question that
    spans more than one page — "how do X and Y relate", "what connects
    to Z", multi-hop / comparison / "trace the influence of…" — keyword
    search alone misses pages that are logically linked but share no
    keywords. Instead: search_wiki to find a seed page, then
    wiki_neighbors(hops=2-3) to gather its neighbourhood, wiki_path to
    see how two topics connect, and wiki_shared_sources /
    wiki_related_by_sources to surface evidence-linked pages the link
    graph or keyword search overlook. Read the pages the graph
    surfaces, then synthesise. This is how you answer connective
    questions correctly.
  · list_duckdb_starters / add_duckdb_starters / replace_duckdb_starters
    Manage the SQL starter pills shown in the Table tab.
    Pre-seeded tables available to the user there:
      files(path TEXT, size BIGINT, mtime TIMESTAMP, ext TEXT)
      pages(id TEXT, path TEXT, type TEXT, title TEXT, degree INT)
    DuckDB-WASM. First call table_context() — it lists data_files.
    Then table_run_sql with a RELATIVE path:
      SELECT … FROM read_csv_auto('data/owid/life-expectancy.csv')
    Never /api/fs/raw, never /Users/… host paths, never grep the CSV.
  · recall_rail(query, limit=10, kinds=[…])
    Pull older events from this workspace's rail log into context —
    chat turns, tool calls, file edits, exec/sql/slash commands,
    curation runs, etc.
  · list_threads() / ask_thread(message, thread_id?, workspace?)
    Collaborate with ANOTHER thread's agent (A2A). Use when the user
    wants threads to share progress ("ask the irrigation thread what
    it decided") or to consult a different registered workspace that
    already solved a similar problem (workspace="name"). The target
    thread answers with its own context; the exchange lands in ITS
    transcript. Include full background in `message` — the target
    can't see this conversation. Never target the thread you're
    answering in (it will refuse as busy).
  · list_skills() / load_skill(name, detail?, section?)
    Skill discovery. Default is frontmatter + headings; then
    section="Heading" one chapter at a time. Global SKILL.md under
    ~/.agents/skills is Readable. Prefer this tool over cat.
  · register_rule(trigger, action) / list_rules() / delete_rule(id)
    Save a persistent rail shortcut. When the user asks you to
    remember a habit ("when I say X, /view Y"), call register_rule.
    The daemon will run the action on every future match without
    consulting you. Rules persist across sessions.
  · make_slides_from_doc(path, name?) / make_slides_from_docs(paths, title?)
    Scaffold a sketcher slide deck from one or more source markdown
    docs. Each H1/H2 heading becomes a placeholder Excalidraw slide;
    a CE-shaped analysis page (kind: analysis, slides: [...]) at
    wiki/<slug>.md is the deck's spine. Sketch tab enters deck mode
    when the user opens the analysis. Use for "make slides from X",
    "turn these docs into a deck", "analyse A, B, C and show as
    slides" — for the analyse case, do the analysis first (writing
    your synthesis into a fresh wiki page), then call
    make_slides_from_doc on that synthesis page.
  · compose_analysis(title, slides, sources?, body?)
    Remix path: build a NEW deck referencing existing sketches by
    id, in whatever order tells the story. Different decks can
    share slides — the same library powers many narratives. Use
    when the user wants a new presentation from existing material
    ("make a board deck using slides X, Y, Z").
  · author_slide(layout, slots, sketch_id?, name?)
    Fill a slide with a real Excalidraw scene. Layouts: title,
    bullets, two_column, quote, section, paragraph, stat, cards.
    After make_slides_from_doc has scaffolded placeholders, walk
    through them with sketch_id=<placeholder>. If sketch_id is
    omitted, defaults to the VISIBLE slide (sketch focus) — use
    that for "fix this slide" / "change the title on the current
    slide". sketch_context() first; sketch_show to jump slides.
  · save_plot(name, spec) / plot_context / plot_update / plot_show
    New plots: save_plot or plot_update. Tweaking the visible chart:
    plot_context() → edit the returned spec → plot_update(id, spec).
    Prefer plot_update over telling the user to edit JSON.
  · table_context() / table_run_sql(sql)
    Table tab. table_context lists data_files. SQL uses relative
    paths only (read_csv_auto('data/foo.csv')). One query, then
    use the result — do not retry with absolute paths or grep.
  · sheet_context() / sheet_select / sheet_set_formula /
    sheet_set_values(values, origin)
    Sheet tab. sheet_set_values ONCE for a data grid (same origin
    overwrites). sheet_set_formula only for formulas.
  · Recipe — "subset of a CSV on a sheet + a plot":
    1. table_context()  → pick the file from data_files
    2. table_run_sql    → filter in DuckDB (relative path)
    3. sheet_set_values → one call, origin = short title
    4. save_plot        → one call, inline the same rows
    Stop. Do not invent extra sheets. If the user asked for
    projections or extra series, put them in that one plot.
    Color-by-category needs a visible color legend (do not set
    legend:null on every layer). Short axis titles; row-facet
    headers go on top (`header.labelOrient: "top"`).
  · sketch_context() / sketch_show(sketch_id|slide_index)
    THE Sketch/deck path for the visible slide. Context first,
    then author_slide(sketch_id=…) for small content edits.

Live-tab rule (all of Sheet / Table / Plot / Sketch):
  When the user refers to "this", "the selected cell", "the chart",
  "this slide", or the visible surface — call the matching *_context
  tool and act with the matching write tool. Do NOT search the vault
  or open unrelated analysis pages looking for "active work".

When the user's message starts with `[attached: <path>]`, that's a
file the user uploaded via the rail's `+` button. Read it via your
native file-reading tool (Read for claude-code, bash cat / less for
codex, etc.) — the path is workspace-relative and inside
`.workbench/uploads/`. Treat it the same as if the user had typed
the file's content inline; the bracketed reference is just an
indirection.

Use the tools eagerly when the user's request clearly implies a
change. After a successful tool call keep replies short — a one-liner
like "Done — added 2 starters." is plenty. The user sees a small
inline note about each tool call, so they already know.

If the user asks for something outside your tools, say so plainly and
point at the matching UI affordance.

VERY IMPORTANT — do NOT dump file contents into chat:
  · The user can already open any wiki page in the Editor tab and
    any CSV/DB in the Table/Sheet tabs. Quoting them back at length
    in the rail wastes screen space and tokens.
  · For "show me X", "what does X say", "tell me about X" style
    questions, switchbay intercepts these and routes to the
    appropriate tab automatically when the match is unambiguous —
    you don't need to repeat the file's content.
  · If a question reaches you anyway, ANSWER with a short summary
    (≤ 4 sentences) plus wikilinks (`[[concepts/foo]]`) pointing at
    the source pages. Do NOT paste the full markdown of any wiki
    file. Do NOT reproduce tables — mention them by name and link.
  · If the user asks a complex synthesis question, you may suggest
    creating a new analysis page (they can do this via the Editor's
    + button). Don't try to paste a 200-line synthesis into chat.

Tone: terse, factual, no preamble. Skip phrases like "Let me explore
the workspace…"; just do the work and report the result.

Plain language (EVERY surface — chat, decks, plots, reports, wiki
proposals):
  · Prefer ordinary words over jargon. Write so a smart colleague
    outside this subfield can follow on the first read.
  · Avoid acronyms and initialisms unless they are truly ubiquitous
    (e.g. AI, CPU, PDF, HTTP, SQL). Domain shorthand like RLVR, RAG,
    RLHF, CoT, PPR, FTS is NOT ubiquitous — spell it out.
  · When an acronym is necessary (source material is built around it,
    or expanding every time would be absurd), define it on FIRST use
    in that document / deck / plot / report: "retrieval-augmented
    generation (RAG)". Later mentions may use the short form.
  · On slides and chart titles/axes/legends the same rule applies —
    never leave a bare undefined acronym on a card or bullet. Prefer
    the expanded form when space allows; otherwise expand in the
    title and use a short form only in body lines after that.
  · Do not invent new acronyms. Do not stack multiple obscure ones
    in one bullet.
"""

# Local (4B-class) models cannot hold the full rail prompt + ~50 tool
# schemas. This short system + a palette is what they actually get.
LOCAL_SYSTEM_PROMPT = """\
You are Switch Bay's on-device worker. Small context. One tool call
per step, or a short final answer.

You already have the tools listed in this request — use them. Do not
ask what tools you have. Do not call tools that are not listed.

Wiki answers: search_wiki → read_wiki_page on the best hit.
Answer in 4–8 sentences from the page. Always end with the page's
wikilink field (e.g. [[entities/graphormer]]) so the user can
click it. If the wiki is thin, say so; do not invent. Do not
mention clipping or tools.

Writing to the wiki (only if the user asked, or this is a curate run):
  · Search first. If a page already covers it, skip or propose a
    tiny sourced edit.
  · New pages must be LIGHT SCAFFOLDS (propose_wiki_page with
    scaffold=true): YAML frontmatter, title, 3–8 bullets of
    claims-to-verify, [[wikilinks]] to existing pages, ## Open
    questions. No dense encyclopedic prose. No invented numbers,
    dates, equations, or mechanisms.
  · Work that needs a planner, a multi-page synthesis, or facts you
    do not have: emit a scaffold that says what a reviewer should
    write, then STOP.

Never delete wiki pages. Reviews is a backlog, not a gate.
Skills: load_skill(name) is frontmatter + headings; then section=
"Heading" one chapter. Never detail=full.
"""

# 48 GB+ / 27B-class: still a palette, but sourced pages are allowed.
LOCAL_SYSTEM_PROMPT_LARGE = """\
You are Switch Bay's on-device curator. One tool call per step, or a
short final answer. You already have the tools listed in this request.

Wiki answers: search_wiki or ce_graph_retrieve → read the best pages.
Answer from the page. Always end with [[wikilinks]] (copy each
page's wikilink field) so the user can click through. Cite
(vault:...) when you have them. If the wiki is thin, say so; do
not invent numbers, dates, equations, or mechanisms.

Writing: prefer sourced pages. Search first. If a page already covers
the item, skip or propose a tiny sourced edit. Full propose_wiki_page
bodies are allowed when you have sources; otherwise set scaffold=true
(outline + ## Open questions) and STOP.

Mechanical sweep (scan / fix-index / stubs / notes) may already have
run. Do not repeat those verbs. One target per turn — no parallel
waves. Never delete wiki pages. Reviews is a backlog.
Skills: load_skill frontmatter, then section='Heading'. Never detail=full.
"""

# Whitelist of tool names this agent is allowed to call. Smaller
# agents start narrow; larger ones (ingest, curator) get wider lists.
ALLOWED_TOOLS = [
    # Wiki read tools — the zero-friction knowledge path. Keep these
    # FIRST: for "what do we know about X" they are the entire answer
    # path (no shell, no approvals).
    "search_wiki",
    "read_wiki_page",
    "list_wiki_pages",
    "wiki_neighbors",
    "wiki_path",
    "wiki_shared_sources",
    "wiki_related_by_sources",
    # CE-native vault/kuzu (additive — different corpus from search_wiki).
    "ce_vault_search",
    "ce_graph_neighbors",
    "ce_graph_path",
    "ce_shared_sources",
    "ce_bridge_candidates",
    # Full CE script surface — HTTP/Copilot have no CE-aware shell.
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
    "list_duckdb_starters",
    "add_duckdb_starters",
    "replace_duckdb_starters",
    "recall_rail",
    "register_rule",
    "list_rules",
    "delete_rule",
    # Curation WRITE path — propose, never mutate. The rail is otherwise
    # read-only for the wiki; these stage a new page / an edit to the
    # review-card surface where a stronger reviewer + the user accept.
    # No delete-page tool by design (a weak model once reached to delete
    # a charter it had just read a "preserve" ruling for).
    "propose_wiki_page",
    "propose_page_edit",
    "propose_charter_edit",
    # Rich HTML report → a Report tab (sandboxed iframe). Offered ONLY to
    # capable models (gated out for local in tools_for_provider) — a small
    # model can't produce artifact-quality HTML.
    "create_report",
    # Sketcher slide-deck tools (N.1). Agent uses these when the
    # user says "make slides from foo.md", "turn these docs into a
    # deck", or "compose a deck from these existing sketches".
    "make_slides_from_doc",
    "make_slides_from_docs",
    "compose_analysis",
    "author_slide",
    # Skill discovery + loading. Frontmatter first; full body only
    # when covered_by tools are not enough.
    "list_skills",
    "load_skill",
    "run_command",
    "read_workspace_plan",
    "update_work_plan",
    "append_workspace_log",
    # Vega-Lite plot authoring. Use when the user asks for a plot,
    # chart, histogram, scatter, etc.
    "save_plot",
    # Live-tab control (same pipes as !fn / !sql / UI affordances).
    "sheet_context",
    "sheet_select",
    "sheet_set_formula",
    "sheet_set_values",
    "table_context",
    "table_run_sql",
    "plot_context",
    "plot_update",
    "plot_show",
    "sketch_context",
    "sketch_show",
    # Inter-thread collaboration (A2A). list_threads finds the target;
    # ask_thread sends a question INTO another thread (same or another
    # registered workspace) and returns its agent's reply.
    "list_threads",
    "ask_thread",
    # D4 agent-driven split gesture: gathers page ids (wiki tools),
    # then pre-highlights the graph's split review surface. The USER
    # confirms there; the tool never splits anything.
    "propose_split",
]


# Tools offered only to capable (non-local) models. The local model
# can't produce artifact-quality HTML, so don't tempt it with the tool.
_STRONG_ONLY_TOOLS = {"create_report"}

_LOCAL_TOOL_BLURBS: dict[str, str] = {
    "propose_wiki_page": (
        "Stage a LIGHT scaffold in Reviews — not a finished page. "
        "Set scaffold=true. Body: YAML frontmatter, '# Title', 3–8 "
        "bullets of claims-to-verify, [[wikilinks]] to pages that "
        "already exist, and ## Open questions. No dense prose, no "
        "invented numbers or mechanisms. Search the wiki first."
    ),
    "propose_page_edit": (
        "Propose a small, sourced edit to an existing page. If you "
        "would have to invent facts, skip. Keep the change short."
    ),
    "read_wiki_page": (
        "Read one wiki page. Answer from content. End with the "
        "wikilink field so the user can click through to the page."
    ),
    "search_wiki": (
        "Find wiki pages by keyword. Then read_wiki_page on the best hit."
    ),
    "ce_epoch_summary": (
        "One-shot wiki health snapshot (counts, inboxes). Call once "
        "to orient, then search/read/propose scaffolds. Do not loop."
    ),
    "author_slide": (
        "Fill one slide: layout + slots + sketch_id. Layouts: title, "
        "bullets, two_column, quote, section, paragraph, stat, cards. "
        "Bullets ≤8 words. Same accent colour on every slide."
    ),
    "make_slides_from_doc": (
        "Scaffold placeholder slides from one markdown doc (H1/H2 → "
        "one sketch each). Then author_slide to fill them."
    ),
    "make_slides_from_docs": (
        "Scaffold one deck from several markdown docs, in order. Then "
        "author_slide to fill placeholders."
    ),
    "compose_analysis": (
        "Bind existing sketches into a deck (analysis page + slide ids)."
    ),
    "save_plot": (
        "Save a Vega-Lite spec to the Plot tab. Inline data.values; "
        "set spec.title and spec.description."
    ),
}

# Conservative vs English prose — JSON tool schemas tokenize denser.
_CHARS_PER_TOKEN = 3
LOCAL_PROMPT_TOKEN_BUDGET = 2800
_LOCAL_EXTRA_SYSTEM_CHARS = 400 * _CHARS_PER_TOKEN
_CLIP_MARK = " …[clipped for local context]"


def estimate_tokens(text: str) -> int:
    return -(-len(text or "") // _CHARS_PER_TOKEN)


def palette_tool_names(
    *,
    local: bool,
    palette: str | None = None,
    ram_gb: float | None = None,
    model_hint: str = "",
    rung: LocalRung | None = None,
    only_tools: Sequence[str] | None = None,
) -> tuple[str, ...]:
    if only_tools is not None:
        seen: list[str] = []
        for n in only_tools:
            if n and n not in seen:
                seen.append(n)
        return tuple(seen)
    if not local:
        return tuple(ALLOWED_TOOLS)
    rung = rung or resolve_local_rung(ram_gb, model_hint=model_hint)
    if palette == "curate":
        return rung.curate_tools
    return rung.chat_tools


def compile_tool_specs(
    names: Sequence[str],
    *,
    local: bool = False,
    rung: LocalRung | None = None,
    skip_strong: bool = True,
) -> list[dict[str, Any]]:
    """Anthropic-shaped specs for ``names``, skipping unknowns."""
    out: list[dict[str, Any]] = []
    for name in names:
        if local and skip_strong and name in _STRONG_ONLY_TOOLS:
            continue
        t = tools.REGISTRY.get(name)
        if t is None:
            continue
        spec = t.to_anthropic()
        use_blurbs = bool(local and (rung is None or rung.force_scaffold))
        blurb = _LOCAL_TOOL_BLURBS.get(name) if use_blurbs else None
        if blurb:
            spec = dict(spec)
            spec["description"] = blurb
            if name == "propose_wiki_page":
                schema = dict(spec.get("input_schema") or {})
                props = dict(schema.get("properties") or {})
                props["scaffold"] = {
                    "type": "boolean",
                    "description": "true for a light Reviews scaffold (required on small local rungs).",
                }
                schema["properties"] = props
                spec["input_schema"] = schema
        out.append(spec)
    return out


def clip_tools_to_budget(
    system: str,
    specs: list[dict[str, Any]],
    messages: list[dict[str, Any]] | None,
    budget: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Drop trailing tool specs until system+tools+messages fit.

    Keeps at least one spec when any were offered — a one-tool desk
    that slightly overshoots is better than a tool-less run.
    """
    dropped: list[str] = []
    kept = list(specs)
    probe = list(messages or [])
    stats = prompt_token_breakdown(system, kept, probe)
    while len(kept) > 1 and stats["total"] > budget:
        dropped.append(str(kept[-1].get("name") or ""))
        kept = kept[:-1]
        stats = prompt_token_breakdown(system, kept, probe)
    dropped.reverse()
    return kept, dropped


def _content_chars(content: Any) -> int:
    if isinstance(content, str):
        return len(content)
    return len(json.dumps(content, ensure_ascii=False, default=str))


def _clip_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = max(80, max_chars)
    return text[:cut] + _CLIP_MARK


def _shrink_content(content: Any, max_chars: int) -> Any:
    """Cut payload text but keep tool_result / tool_use block shape.

    Stringifying a tool-result list into a user message breaks Qwen's
    tool template (the follow-up turn no longer has a `tool` role).
    """
    if isinstance(content, str):
        return _clip_text(content, max_chars)
    if isinstance(content, list):
        blocks: list[Any] = [
            dict(b) if isinstance(b, dict) else b for b in content
        ]
        if _content_chars(blocks) <= max_chars:
            return blocks
        clip_kinds = ("tool_result", "text")
        targets = [
            b for b in blocks
            if isinstance(b, dict) and b.get("type") in clip_kinds
        ]
        room = max(80, max_chars // max(1, len(targets)))
        for b in targets:
            if b.get("type") == "tool_result":
                raw = b.get("content")
                text = raw if isinstance(raw, str) else json.dumps(
                    raw, ensure_ascii=False, default=str,
                )
                b["content"] = _clip_text(text, room)
            elif b.get("type") == "text":
                b["text"] = _clip_text(str(b.get("text") or ""), room)
        return blocks
    blob = json.dumps(content, ensure_ascii=False, default=str)
    if len(blob) <= max_chars:
        return content
    return _clip_text(blob, max_chars)


def _is_tool_result_msg(msg: dict[str, Any]) -> bool:
    raw = msg.get("content")
    return isinstance(raw, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in raw
    )


def clip_messages_to_budget(
    system: str,
    tool_specs: list[dict[str, Any]],
    messages: list[dict[str, Any]] | None,
    budget: int,
) -> list[dict[str, Any]]:
    """Fit history into ``budget`` without dropping the user question first.

    Order: shrink tool-result payloads, drop middle turns (keep first
    user + tail), then shrink whatever is left. Used after tool results
    re-enter the loop — a 4B must not prefill 15k tokens because
    search_wiki JSON + history overshot the desk.
    """
    kept = list(messages or [])
    if not kept:
        return kept

    def _stats() -> dict[str, int]:
        return prompt_token_breakdown(system, tool_specs, kept)

    stats = _stats()

    i = len(kept) - 1
    while stats["total"] > budget and i >= 0:
        msg = kept[i]
        if _is_tool_result_msg(msg):
            overflow_tok = stats["total"] - budget
            raw = msg.get("content")
            target = max(400, _content_chars(raw) - overflow_tok * _CHARS_PER_TOKEN)
            kept[i] = {**msg, "content": _shrink_content(raw, target)}
            stats = _stats()
        i -= 1

    while stats["total"] > budget and len(kept) > 2:
        kept = [kept[0]] + kept[2:]
        stats = _stats()
    while stats["total"] > budget and len(kept) > 1:
        kept = kept[1:]
        stats = _stats()

    if stats["total"] > budget and kept:
        last = dict(kept[-1])
        overflow_tok = stats["total"] - budget
        target = max(80, _content_chars(last.get("content")) - overflow_tok * _CHARS_PER_TOKEN)
        last["content"] = _shrink_content(last.get("content"), target)
        kept[-1] = last
    return kept


def prompt_token_breakdown(
    system: str,
    tool_specs: list[dict[str, Any]],
    messages: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    sys_n = estimate_tokens(system)
    # Chat templates wrap each schema; 1.25× covers Qwen/MLX markup
    # without dropping the last tool on a 4B desk (2.5× ate author_slide).
    tools_n = int(
        estimate_tokens(json.dumps(tool_specs, ensure_ascii=False)) * 1.25
    )
    msg_n = 0
    for m in messages or []:
        msg_n += estimate_tokens(json.dumps(m, ensure_ascii=False, default=str))
    return {
        "system": sys_n,
        "tools": tools_n,
        "messages": msg_n,
        "total": sys_n + tools_n + msg_n,
        "n_tools": len(tool_specs),
    }


def assemble_local_prompt(
    *,
    palette: str = "chat",
    extra_system: str = "",
    harness: str = "",
    messages: list[dict[str, Any]] | None = None,
    budget: int | None = None,
    ram_gb: float | None = None,
    model_hint: str = "",
    rung: LocalRung | None = None,
    only_tools: Sequence[str] | None = None,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Compile a local-model prompt that fits the rung's token budget.

    Returns (system, tools, messages, breakdown). Oldest messages are
    dropped first; the last user turn is kept. Trailing tools are
    clipped if the desk still overshoots after that.
    """
    rung = rung or resolve_local_rung(ram_gb, model_hint=model_hint)
    cap = budget if budget is not None else rung.prompt_budget
    extra_cap = rung.extra_system_chars
    system = (
        LOCAL_SYSTEM_PROMPT if rung.force_scaffold else LOCAL_SYSTEM_PROMPT_LARGE
    ).rstrip()
    if harness.strip():
        system = f"{system}\n\n{harness.strip()}"
    extra = (extra_system or "").strip()
    if extra:
        if len(extra) > extra_cap:
            extra = extra[:extra_cap].rstrip() + "\n…"
        system = f"{system}\n\n{extra}"
    tool_specs = tools_for_provider(
        local=True, palette=palette, rung=rung, only_tools=only_tools,
    )
    kept = list(messages or [])
    last = kept[-1:] if kept else []
    tool_specs, clipped_tools = clip_tools_to_budget(system, tool_specs, last, cap)
    kept = clip_messages_to_budget(system, tool_specs, kept, cap)
    stats = prompt_token_breakdown(system, tool_specs, kept)
    stats["trimmed"] = max(0, len(messages or []) - len(kept))
    stats["budget"] = cap
    stats["palette"] = palette
    stats["rung"] = rung.id
    stats["force_scaffold"] = rung.force_scaffold
    stats["clipped_tools"] = clipped_tools
    return system, tool_specs, kept, stats


def tools_for_provider(
    *,
    local: bool = False,
    palette: str | None = None,
    ram_gb: float | None = None,
    model_hint: str = "",
    rung: LocalRung | None = None,
    only_tools: Sequence[str] | None = None,
) -> list[dict]:
    """Build the Anthropic-shaped `tools[]` list.

    Strong models get the full allowlist. Local models get a RAM/model
    palette (``chat`` or ``curate``), or an explicit ``only_tools``
    command desk (may include tools the default local desk bans).
    """
    if local:
        rung = rung or resolve_local_rung(ram_gb, model_hint=model_hint)
    names = palette_tool_names(
        local=local, palette=palette, ram_gb=ram_gb,
        model_hint=model_hint, rung=rung, only_tools=only_tools,
    )
    skip_strong = bool(local and only_tools is None)
    return compile_tool_specs(
        names, local=local, rung=rung, skip_strong=skip_strong,
    )
