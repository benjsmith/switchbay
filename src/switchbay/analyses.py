"""Analysis pages = CE-shaped markdown docs that act as the spine
of a sketcher slide deck.

An analysis page lives at `<workspace>/wiki/<slug>.md` and looks like:

    ---
    kind:    analysis
    title:   Q4 Churn Analysis
    slides:  [<sketch-id-1>, <sketch-id-2>, ...]
    sources: [wiki/q4-churn.md]
    ---

    # Q4 Churn Analysis

    ![](figures/<sketch-id-1>.png)

    Churn jumped 14% QoQ, driven by ...

    ![](figures/<sketch-id-2>.png)

    ...

The page IS the story. Slides stay pure visual artifacts in
`figures/`. New analyses with overlapping slide sets define new
paths through the same library — exactly the "remix" model.

This module just persists/loads the frontmatter contract. CE's
existing wiki/graph pipeline picks up the figure references and
wikilinks for free; no new daemon module needed for routing.

Frontmatter is YAML when CE is around; we hand-roll a minimal
subset (kind / title / slides / sources) so we don't pull a YAML
dep just for our own writes. Reads tolerate full YAML when CE
generated the page.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any

log = logging.getLogger("switchbay.analyses")


def _wiki_dir(workspace: Path) -> Path:
    return workspace / "wiki"


def _analyses_dir(workspace: Path) -> Path:
    """CE's standard wiki layout puts analysis-kind pages under
    `wiki/analyses/`. Decks (the deck-mode flavour scaffolded via
    `→ Slides`) land here too — distinguished by `kind: deck` in
    frontmatter and a `[deck]` title prefix so they don't get
    swept up by the curator's analysis pipeline."""
    return workspace / "wiki" / "analyses"


# Title prefix for deck-mode analyses. Mirrors CE's `[ana]`, `[ent]`,
# etc. bracket-tag convention so the curator + sidebar can recognise
# a deck at a glance.
DECK_TITLE_PREFIX = "[deck] "


def _slugify(text: str) -> str:
    """Lowercase, hyphen-separated, alnum-only. Falls back to a uuid
    fragment if the input has no usable characters. Same shape used by
    `plots.py` and `sketches.py` so identifiers feel consistent across
    the workbench."""
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s or uuid.uuid4().hex[:8]


def path_for_slug(workspace: Path, slug: str, *, in_analyses: bool = False) -> Path:
    """Resolve the on-disk path for an analysis-or-deck slug. Decks
    and freshly-scaffolded analyses land under `wiki/analyses/` (CE
    layout convention). The flat-wiki form remains the default so
    legacy analysis pages already in `wiki/<slug>.md` still resolve
    when read back."""
    if "/" in slug or ".." in slug or not slug:
        raise ValueError(f"invalid analysis slug: {slug!r}")
    base = _analyses_dir(workspace) if in_analyses else _wiki_dir(workspace)
    return base / f"{slug}.md"


# Tolerant frontmatter reader — leans on a regex rather than a YAML
# library because CE-shaped frontmatter is a flat key/value table in
# practice. Lists are written as inline `[a, b, c]` arrays.

_FM_RE = re.compile(
    r"\A---\s*\n(?P<fm>.*?)\n---\s*\n(?P<body>.*)\Z", re.DOTALL,
)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return (frontmatter dict, body). On no/malformed frontmatter
    returns ({}, text) so callers can treat plain markdown as an
    empty-frontmatter doc."""
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    fm: dict[str, Any] = {}
    for line in m.group("fm").splitlines():
        line = line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip()
        if not k:
            continue
        fm[k] = _coerce_fm_value(v)
    return fm, m.group("body")


def _parse_slide_notes(v: Any) -> dict[str, str]:
    """Decode the `slide_notes` frontmatter value into a
    {sketch_id: note} map. Stored as a single-line JSON string (our
    hand-rolled frontmatter dialect can't express multi-line maps, and
    JSON keeps notes — which may contain commas/quotes/newlines — on one
    safe line). Tolerates a missing/blank/garbage value → {}."""
    if isinstance(v, dict):
        return {str(k): str(val) for k, val in v.items()}
    if not isinstance(v, str) or not v.strip():
        return {}
    try:
        parsed = json.loads(v)
    except (ValueError, TypeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(k): str(val) for k, val in parsed.items() if str(val).strip()}


def _coerce_fm_value(v: str) -> Any:
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip('"').strip("'") for item in inner.split(",") if item.strip()]
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    return v


def _format_frontmatter(fm: dict[str, Any]) -> str:
    """Render our minimal frontmatter dialect. Strings are written
    bare; lists are inline arrays. Order is fixed (kind, title,
    slides, sources, then any extras alphabetically) so successive
    saves produce stable diffs."""
    lines = ["---"]
    canonical = ["kind", "title", "slides", "sources"]
    extras = sorted(k for k in fm if k not in canonical)
    for k in canonical + extras:
        if k not in fm:
            continue
        v = fm[k]
        if isinstance(v, list):
            inner = ", ".join(_quote(item) for item in v)
            lines.append(f"{k}: [{inner}]")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines)


def _quote(item: Any) -> str:
    s = str(item)
    if "," in s or ":" in s or s != s.strip():
        return f'"{s}"'
    return s


def is_analysis(workspace: Path, page_path: str) -> bool:
    """Cheap check used by the frontend to decide whether to enter
    deck mode. Tolerates both workspace-relative ('wiki/foo.md') and
    bare-slug ('foo') forms. Both `kind: analysis` and `kind: deck`
    return True — the deck-mode UI treats both the same way."""
    p = _resolve_page(workspace, page_path)
    if p is None or not p.is_file():
        return False
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return False
    fm, _ = parse_frontmatter(text)
    kind = str(fm.get("kind") or "").strip().lower()
    return kind in ("analysis", "deck")


def _resolve_page(workspace: Path, page_path: str) -> Path | None:
    """Best-effort page-path resolution: accepts 'wiki/foo.md',
    'wiki/analyses/foo.md', 'foo.md', or 'foo'. Returns the
    absolute path even if the file doesn't exist yet (callers can
    check is_file). Probes the analyses subdir as a fallback so the
    Editor → Slides scaffolds (which now write under `wiki/analyses/`)
    still resolve from a bare slug."""
    p = (page_path or "").strip()
    if not p:
        return None
    candidate = workspace / p
    if not candidate.suffix:
        candidate = candidate.with_suffix(".md")
    if candidate.is_file():
        return candidate
    if not p.startswith("wiki/"):
        flat = _wiki_dir(workspace) / candidate.name
        if flat.is_file():
            return flat
        sub = _analyses_dir(workspace) / candidate.name
        if sub.is_file():
            return sub
        # Even when nothing exists yet, prefer the flat-wiki fallback
        # for backwards compatibility — the deck-creating callers know
        # to construct paths under wiki/analyses/ explicitly.
        return flat
    return candidate


def resolve_doc_path(workspace: Path, source_path: str) -> Path | None:
    """Strict variant of `_resolve_page` for the doc-consuming
    endpoints (analysis from-doc, slide-scaffold tools, etc.).
    Tries the path as-given, with `wiki/` prefix, and as a bare
    slug under wiki/. Confirms file existence + path-traversal
    containment before returning. Returns None when no candidate
    resolves to a real file inside the workspace.
    """
    if not source_path:
        return None
    ws = workspace.resolve()
    candidates: list[Path] = []
    candidates.append((workspace / source_path).resolve())
    if not source_path.startswith("wiki/"):
        candidates.append((_wiki_dir(workspace) / source_path).resolve())
    if not source_path.endswith(".md"):
        candidates.append((workspace / f"{source_path}.md").resolve())
        candidates.append((_wiki_dir(workspace) / f"{source_path}.md").resolve())
    for c in candidates:
        if not c.is_file():
            continue
        try:
            c.relative_to(ws)
        except ValueError:
            continue
        return c
    return None


def load_analysis(workspace: Path, slug_or_path: str) -> dict[str, Any] | None:
    """Read an analysis-or-deck page; return its parsed shape or None
    if missing / not an analysis-or-deck-kind page."""
    p = _resolve_page(workspace, slug_or_path)
    if p is None or not p.is_file():
        return None
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return None
    fm, body = parse_frontmatter(text)
    kind = str(fm.get("kind") or "").lower()
    if kind not in ("analysis", "deck"):
        return None
    slug = p.stem
    slides = fm.get("slides") or []
    # Dedup on read too (order-preserving) so decks that already have
    # duplicate ids on disk render + export clean immediately; the next
    # write persists the cleaned list.
    slides = list(dict.fromkeys(str(s) for s in slides)) if isinstance(slides, list) else []
    sources = fm.get("sources") or []
    rel = p.resolve().relative_to(workspace.resolve()).as_posix()
    return {
        "slug": slug,
        "path": rel,
        "title": fm.get("title") or slug,
        "kind": kind,
        "slides": slides,
        "sources": list(sources) if isinstance(sources, list) else [],
        # {sketch_id: presenter-note} — drives reveal speaker view +
        # pptx notes slides. Empty map for decks authored before notes.
        "slide_notes": _parse_slide_notes(fm.get("slide_notes")),
        "body": body,
        # Optional template hints carried in frontmatter — surfaced
        # so /api/analysis/populate can tailor the agent prompt
        # (project decks get the Intro/Themes/Latest/Summary/Next
        # outline; free-form decks get the per-heading prompt).
        "deck_template": str(fm.get("deck_template") or "") or None,
        "deck_project": str(fm.get("deck_project") or "") or None,
    }


def save_analysis(
    workspace: Path,
    *,
    title: str,
    slides: list[str],
    sources: list[str] | None = None,
    body: str | None = None,
    slug: str | None = None,
    is_deck: bool = False,
    deck_template: str | None = None,
    deck_project: str | None = None,
    slide_notes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Write an analysis-or-deck page. Decks land at
    `wiki/analyses/<slug>.md` with `kind: deck` and a `[deck]`
    title prefix so the curator's analysis sweep doesn't pick them
    up. Plain analyses keep the legacy flat-wiki location for
    backwards compatibility (eventual move-into-analyses/ when CE
    confirms its convention).

    If `slug` is omitted we slugify `title` (without the bracket
    prefix); collisions resolved with a short uuid suffix. `body`
    is the narrative prose — when not supplied we generate a stub
    with each slide embedded as a figure reference."""
    title = (title or "").strip() or "Untitled analysis"
    sources = sources or []
    # Order-preserving dedup at the source: no deck/analysis ever
    # persists the same sketch id twice (it would render as a duplicate
    # slide). Every write path funnels through here.
    slides = list(dict.fromkeys(str(s) for s in (slides or [])))
    kind = "deck" if is_deck else "analysis"
    display_title = title
    if is_deck and not display_title.lower().startswith("[deck"):
        display_title = DECK_TITLE_PREFIX + title

    in_analyses = is_deck
    slug_seed = title  # slugify the bare title — no prefix in the slug
    if slug is None:
        slug = _slugify(slug_seed)
        target = path_for_slug(workspace, slug, in_analyses=in_analyses)
        while target.exists():
            slug = f"{_slugify(slug_seed)}-{uuid.uuid4().hex[:4]}"
            target = path_for_slug(workspace, slug, in_analyses=in_analyses)
    target = path_for_slug(workspace, slug, in_analyses=in_analyses)
    target.parent.mkdir(parents=True, exist_ok=True)
    fm: dict[str, Any] = {
        "kind": kind,
        "title": display_title,
        "slides": slides,
        "sources": sources,
    }
    # Optional deck-template hint — read by /api/analysis/populate to
    # adjust the agent prompt (project decks get a structured
    # template, free-form decks get the per-heading prompt).
    if deck_template:
        fm["deck_template"] = deck_template
    if deck_project:
        fm["deck_project"] = deck_project
    # Drop blank notes so we don't persist an empty map; store as a
    # single-line JSON string (see _parse_slide_notes). sort_keys keeps
    # diffs stable across saves.
    clean_notes = {k: v for k, v in (slide_notes or {}).items() if v.strip()}
    if clean_notes:
        fm["slide_notes"] = json.dumps(clean_notes, ensure_ascii=False, sort_keys=True)
    if body is None:
        body = _stub_body(display_title, slides)
    target.write_text(
        _format_frontmatter(fm) + "\n\n" + body.strip() + "\n",
        encoding="utf-8",
    )
    log.info("saved %s %s (%d slides)", kind, slug, len(slides))
    rel_path = target.resolve().relative_to(workspace.resolve()).as_posix()
    return load_analysis(workspace, rel_path) or {
        "slug": slug, "path": rel_path,
        "title": display_title, "kind": kind,
        "slides": slides, "sources": sources,
        "slide_notes": clean_notes, "body": body,
    }


def set_note(
    workspace: Path, slug_or_path: str, sketch_id: str, note: str,
) -> dict[str, Any] | None:
    """Set (or clear, when `note` is blank) the presenter note for one
    slide in an analysis/deck, preserving everything else. Returns the
    updated record or None if the page doesn't exist."""
    a = load_analysis(workspace, slug_or_path)
    if a is None:
        return None
    notes = dict(a.get("slide_notes") or {})
    if note.strip():
        notes[sketch_id] = note
    else:
        notes.pop(sketch_id, None)
    return save_analysis(
        workspace,
        title=a["title"], slides=list(a["slides"]),
        sources=a["sources"], body=a["body"], slug=a["slug"],
        is_deck=(a.get("kind") == "deck"),
        deck_template=a.get("deck_template"),
        deck_project=a.get("deck_project"),
        slide_notes=notes,
    )


def _stub_body(title: str, slides: list[str]) -> str:
    """Initial narrative for a fresh analysis: a heading + one figure
    block per slide. The agent / user fills in the prose later."""
    lines = [f"# {title}", ""]
    for sid in slides:
        lines.append(f"![](figures/_assets/{sid}.png)")
        lines.append("")
    if not slides:
        lines.append("_No slides yet — use the Sketch tab's Add Sketch button to add the first one._")
    return "\n".join(lines)


def list_analyses(workspace: Path) -> list[dict[str, Any]]:
    """Newest-first list of every analysis-or-deck page. Walks both
    the legacy flat-wiki location AND `wiki/analyses/` so decks
    scaffolded into the subdir surface in the deck-mode picker."""
    out: list[dict[str, Any]] = []
    seen: set[Path] = set()
    ws_root = workspace.resolve()
    for d in (_wiki_dir(workspace), _analyses_dir(workspace)):
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md")):
            r = f.resolve()
            if r in seen:
                continue
            seen.add(r)
            try:
                text = f.read_text(encoding="utf-8")
            except OSError:
                continue
            fm, _ = parse_frontmatter(text)
            kind = str(fm.get("kind") or "").lower()
            if kind not in ("analysis", "deck"):
                continue
            slides = fm.get("slides") or []
            slides = (
                list(dict.fromkeys(str(s) for s in slides))
                if isinstance(slides, list) else []
            )
            out.append({
                "slug": f.stem,
                "path": r.relative_to(ws_root).as_posix(),
                "title": fm.get("title") or f.stem,
                "kind": kind,
                "slides": slides,
                "slide_notes": _parse_slide_notes(fm.get("slide_notes")),
                "updated_at": f.stat().st_mtime,
            })
    out.sort(key=lambda a: a.get("updated_at") or 0, reverse=True)
    return out


def append_slide(
    workspace: Path, slug: str, sketch_id: str,
) -> dict[str, Any] | None:
    """Add a sketch id to an analysis's slides list and rewrite the
    body to include the new figure block. Returns the updated record
    or None if the analysis doesn't exist."""
    a = load_analysis(workspace, slug)
    if a is None:
        return None
    if sketch_id in a["slides"]:
        return a  # already there; no-op
    new_slides = list(a["slides"]) + [sketch_id]
    new_body = (a["body"].rstrip() + f"\n\n![](figures/_assets/{sketch_id}.png)\n").lstrip()
    return save_analysis(
        workspace,
        title=a["title"], slides=new_slides,
        sources=a["sources"], body=new_body, slug=a["slug"],
        is_deck=(a.get("kind") == "deck"),
        deck_template=a.get("deck_template"),
        deck_project=a.get("deck_project"),
        slide_notes=a.get("slide_notes"),
    )


def set_slides(
    workspace: Path, slug_or_path: str, slides: list[str],
) -> dict[str, Any] | None:
    """Replace an analysis-or-deck's slides list. Used by the Sketch
    tab's Delete handler to drop a slide from the deck before
    deleting the underlying sketch — without this the deck mode
    keeps the deleted id and renders an off-by-one navigation.

    Body is rewritten to match (one figure block per remaining
    slide) so the doc and the slides list stay in sync."""
    a = load_analysis(workspace, slug_or_path)
    if a is None:
        return None
    # Order-preserving dedup — a deck must never list the same sketch
    # twice (the body rewrite below + the Sketch deck render both key
    # off this list, so a dup id renders as a duplicate slide).
    new_slides = list(dict.fromkeys(str(s) for s in slides))
    # Rebuild the body: keep any prose above the first figure
    # block, then one figure per slide. Avoids leaving a broken
    # `![](figures/<deleted>.png)` reference behind.
    body_lines = a["body"].splitlines()
    prose: list[str] = []
    for line in body_lines:
        if line.strip().startswith("![](figures/"):
            break
        prose.append(line)
    new_body = "\n".join(prose).rstrip() + "\n"
    for sid in new_slides:
        new_body += f"\n![](figures/_assets/{sid}.png)\n"
    return save_analysis(
        workspace,
        title=a["title"], slides=new_slides,
        sources=a["sources"], body=new_body.strip() + "\n",
        slug=a["slug"],
        is_deck=(a.get("kind") == "deck"),
        deck_template=a.get("deck_template"),
        deck_project=a.get("deck_project"),
        slide_notes=a.get("slide_notes"),
    )
