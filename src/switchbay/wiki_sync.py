"""Deterministic wiki wiring — no curate pass required.

The file browser walks the filesystem, so a newly authored page appears
there immediately. The wiki browser (CE sidebar) and graph read
``data.json`` nodes/edges, which stay stale until a viewer rebuild and
have no WikiLink edges until ``graph.py rebuild``. This module:

  1. Injects every on-disk ``wiki/**/*.md`` into a viewer bundle so the
     wiki browser lists the page before the next curate/rescan.
  2. Adds ``[[wikilink]]`` edges parsed from the pages themselves.
  3. Wraps title/stem mentions on a newly written page (and reciprocal
     mentions on existing pages) so the graph has real edges without
     waiting for a LINK/CURATE wave.
  4. Refreshes ``.curator/index.md`` via ``sweep.py fix-index``.
"""

from __future__ import annotations

import html
import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger("switchbay.wiki_sync")

_FM_RE = re.compile(
    r"\A---\s*\n(?P<fm>.*?)\n---\s*\n(?P<body>.*)\Z", re.DOTALL,
)
_FM_TITLE = re.compile(r"^title:\s*(.+)$", re.M)
_FM_TYPE = re.compile(r"^type:\s*['\"]?([A-Za-z0-9_-]+)", re.M)
_WIKILINK = re.compile(r"\[\[([^\]|#]+)")
_PREFIX = re.compile(
    r"^\[(?:ana|con|ent|evi|fac|fig|src|note|todo|proj|deck|tab|tbl)\]\s*",
    re.I,
)
_SKIP_DIR_PARTS = {"_assets", "_archive", ".git"}
_STOP_TITLES = {
    "overview", "summary", "notes", "index", "todo", "todos",
    "introduction", "untitled", "home", "readme", "log",
}
_TYPE_FROM_DIR = {
    "analyses": "analysis", "analysis": "analysis",
    "concepts": "concept", "concept": "concept",
    "entities": "entity", "entity": "entity",
    "evidence": "evidence",
    "facts": "fact", "fact": "fact",
    "figures": "figure", "figure": "figure",
    "tables": "table", "table": "table",
    "sources": "source", "source": "source",
    "notes": "note", "note": "note",
    "projects": "project", "project": "project",
    "todos": "todo-list",
}


def _display_title(title: str) -> str:
    return _PREFIX.sub("", (title or "").strip().strip('"').strip("'")).strip()


def _iter_wiki_md(workspace: Path) -> list[Path]:
    wiki = workspace / "wiki"
    if not wiki.is_dir():
        return []
    out: list[Path] = []
    for p in wiki.rglob("*.md"):
        if any(part in _SKIP_DIR_PARTS or part.startswith(".") for part in p.parts):
            continue
        out.append(p)
    return out


def page_id_for(workspace: Path, md: Path) -> str | None:
    wiki = workspace / "wiki"
    try:
        rel = md.resolve().relative_to(wiki.resolve())
    except ValueError:
        return None
    return rel.with_suffix("").as_posix()


def _page_meta(text: str) -> tuple[str, str]:
    title, ptype = "", ""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        head = text[3:end] if end != -1 else text[3:800]
        mt = _FM_TITLE.search(head)
        mk = _FM_TYPE.search(head)
        if mt:
            raw = mt.group(1).strip()
            if (raw.startswith('"') and raw.endswith('"')) or (
                raw.startswith("'") and raw.endswith("'")
            ):
                raw = raw[1:-1]
            title = raw
        if mk:
            ptype = mk.group(1).lower()
    return title, ptype


def catalog(workspace: Path) -> list[dict[str, str]]:
    """Every wiki page as {id, path, stem, title, display, type}."""
    wiki = workspace / "wiki"
    out: list[dict[str, str]] = []
    for md in _iter_wiki_md(workspace):
        pid = page_id_for(workspace, md)
        if not pid:
            continue
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        title, ptype = _page_meta(text)
        try:
            rel = md.resolve().relative_to(wiki.resolve()).as_posix()
        except ValueError:
            rel = f"{pid}.md"
        folder = pid.split("/", 1)[0] if "/" in pid else ""
        if not ptype:
            ptype = _TYPE_FROM_DIR.get(folder, "note")
        display = _display_title(title) or md.stem.replace("-", " ")
        out.append({
            "id": pid,
            "path": rel,
            "stem": md.stem,
            "title": title or display,
            "display": display,
            "type": ptype,
        })
    return out


_BODY_HTML_CAP = 4_000  # in-memory graph cache; full page is /api/page


def _body_html(text: str) -> str:
    body = text
    m = _FM_RE.match(text)
    if m:
        body = m.group("body")
    body = body.strip()
    if len(body) > _BODY_HTML_CAP:
        body = body[:_BODY_HTML_CAP] + "\n…"
    return "<pre class=\"wiki-draft\">" + html.escape(body) + "</pre>"


def slim_graph_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Drop bulky page HTML from an in-memory viewer bundle.

    The graph/Atlas only needs ids, types, titles, and edges. Full
    bodies belong in /api/page. Keeping every page's HTML in
    ``graph_data_per_ws`` is the kind of growth that can push the
    daemon into multi-GB RSS.
    """
    pages = data.get("pages") if isinstance(data, dict) else None
    if not isinstance(pages, dict):
        return data
    for page in pages.values():
        if not isinstance(page, dict):
            continue
        html_body = page.get("body_html")
        if isinstance(html_body, str) and len(html_body) > _BODY_HTML_CAP + 80:
            page["body_html"] = html_body[: _BODY_HTML_CAP + 80] + "…"
        page.pop("body", None)
        page.pop("html", None)
        page.pop("content", None)
    return data


def _wikilink_targets(text: str) -> list[str]:
    return [m.group(1).strip() for m in _WIKILINK.finditer(text)]


def inject_on_disk_pages(workspace: Path, data: dict[str, Any]) -> int:
    """Ensure every on-disk wiki page is in ``pages`` + ``nodes``.

    Also adds filesystem-derived wikilink edges so the graph shows
    connections before kuzu has been rebuilt. Mutates ``data``.
    Returns the number of nodes/pages/edges added or updated.
    """
    if not isinstance(data, dict):
        return 0
    pages = data.get("pages")
    nodes = data.get("nodes")
    edges = data.get("edges")
    if not isinstance(pages, dict):
        pages = {}
        data["pages"] = pages
    if not isinstance(nodes, list):
        nodes = []
        data["nodes"] = nodes
    if not isinstance(edges, list):
        edges = []
        data["edges"] = edges

    by_id = {
        str(n.get("id") or ""): n
        for n in nodes
        if isinstance(n, dict) and n.get("id")
    }
    stem_to_id: dict[str, str] = {}
    for rec in catalog(workspace):
        stem_to_id.setdefault(rec["stem"].casefold(), rec["id"])
        stem_to_id.setdefault(rec["id"].casefold(), rec["id"])
        stem_to_id.setdefault(Path(rec["path"]).stem.casefold(), rec["id"])

    changed = 0
    wiki = workspace / "wiki"
    for rec in catalog(workspace):
        pid = rec["id"]
        md = wiki / rec["path"]
        try:
            text = md.read_text(encoding="utf-8", errors="replace") if md.is_file() else ""
        except OSError:
            text = ""
        page = pages.get(pid)
        if not isinstance(page, dict):
            page = {
                "id": pid,
                "path": rec["path"],
                "title": rec["title"],
                "type": rec["type"],
                "properties": {},
                "body_html": _body_html(text) if text else "",
            }
            pages[pid] = page
            changed += 1
        else:
            page.setdefault("path", rec["path"])
            page.setdefault("title", rec["title"])
            page["type"] = rec["type"] or page.get("type") or "note"
            if not page.get("body_html") and text:
                page["body_html"] = _body_html(text)

        node = by_id.get(pid)
        if node is None:
            node = {
                "id": pid,
                "path": rec["path"],
                "type": rec["type"],
                "title": rec["title"],
                "degree": 0,
            }
            nodes.append(node)
            by_id[pid] = node
            changed += 1
        else:
            node["type"] = rec["type"] or node.get("type") or "note"
            node.setdefault("title", rec["title"])
            node.setdefault("path", rec["path"])

        if not text:
            continue
        existing = {
            (str(e.get("source") or ""), str(e.get("target") or ""),
             str(e.get("type") or "wikilink"))
            for e in edges
            if isinstance(e, dict)
        }
        for raw in _wikilink_targets(text):
            key = raw.casefold().removesuffix(".md").strip()
            target = (
                stem_to_id.get(key)
                or stem_to_id.get(key.split("/")[-1])
                or (key if key in by_id else None)
            )
            if not target or target == pid:
                continue
            trip = (pid, target, "wikilink")
            if trip in existing:
                continue
            edges.append({"source": pid, "target": target, "type": "wikilink"})
            existing.add(trip)
            changed += 1
            src_n = by_id.get(pid)
            dst_n = by_id.get(target)
            if isinstance(src_n, dict):
                src_n["degree"] = int(src_n.get("degree") or 0) + 1
            if isinstance(dst_n, dict):
                dst_n["degree"] = int(dst_n.get("degree") or 0) + 1

    if changed:
        log.info("inject_on_disk_pages: %d page/node/edge updates", changed)
    return changed


def _protected_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    i = 0
    while True:
        a = text.find("```", i)
        if a < 0:
            break
        b = text.find("```", a + 3)
        if b < 0:
            spans.append((a, len(text)))
            break
        spans.append((a, b + 3))
        i = b + 3
    for rx in (
        r"\[\[[^\]]*\]\]",
        r"\(vault:[^)]*\)",
        r"`[^`]+`",
        r"!\[[^\]]*\]\([^)]*\)",
    ):
        for m in re.finditer(rx, text):
            spans.append(m.span())
    # YAML frontmatter
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            spans.append((0, end + 5))
    return spans


def _is_protected(pos: int, spans: list[tuple[int, int]]) -> bool:
    return any(a <= pos < b for a, b in spans)


def _linkify_body(text: str, targets: list[tuple[str, str]]) -> tuple[str, int]:
    """Wrap whole-word mentions of ``(needle, stem)`` as ``[[stem]]``.

    ``targets`` should be longest-needle first. Returns (new_text, n).
    """
    if not targets:
        return text, 0
    spans = _protected_spans(text)
    n = 0
    for needle, stem in targets:
        if not needle or needle.casefold() in _STOP_TITLES:
            continue
        if len(needle) < 4:
            continue
        pat = re.compile(
            r"(?<![A-Za-z0-9_])" + re.escape(needle) + r"(?![A-Za-z0-9_])",
            re.I,
        )
        out: list[str] = []
        last = 0
        for m in pat.finditer(text):
            if _is_protected(m.start(), spans):
                continue
            # Already our stem as a bare mention we just want to wrap.
            out.append(text[last:m.start()])
            out.append(f"[[{stem}]]")
            last = m.end()
            n += 1
        if last:
            out.append(text[last:])
            text = "".join(out)
            spans = _protected_spans(text)
    return text, n


def wire_new_page(workspace: Path, rel: str) -> dict[str, Any]:
    """Add deterministic ``[[wikilinks]]`` on a newly written page.

    Wraps mentions of existing page titles/stems in the new page, and
    wraps mentions of the new page on other pages (reciprocal). Does
    not invent facts — only wraps text that is already there.
    """
    rel = (rel or "").strip().lstrip("/")
    if rel.startswith("wiki/"):
        path = workspace / rel
        wiki_rel = rel[5:]
    else:
        path = workspace / "wiki" / rel
        wiki_rel = rel
    if not path.is_file() or ".." in Path(wiki_rel).parts:
        return {"ok": False, "error": f"not a wiki page: {rel}"}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return {"ok": False, "error": str(e)}

    pages = catalog(workspace)
    self_id = Path(wiki_rel).with_suffix("").as_posix()
    others = [p for p in pages if p["id"] != self_id]
    targets: list[tuple[str, str]] = []
    seen: set[str] = set()
    for p in others:
        for needle in (p["display"], p["stem"].replace("-", " "), p["stem"]):
            key = needle.casefold()
            if not needle or key in seen or key in _STOP_TITLES or len(needle) < 4:
                continue
            seen.add(key)
            targets.append((needle, p["stem"]))
    targets.sort(key=lambda kv: len(kv[0]), reverse=True)
    new_text, outbound = _linkify_body(text, targets)
    if outbound and new_text != text:
        path.write_text(new_text, encoding="utf-8")
        text = new_text

    self_title, _ = _page_meta(text)
    self_display = _display_title(self_title) or Path(wiki_rel).stem.replace("-", " ")
    self_stem = Path(wiki_rel).stem
    inbound = 0
    wiki = workspace / "wiki"
    rec_needles = [
        (n, self_stem)
        for n in (self_display, self_stem.replace("-", " "), self_stem)
        if n and len(n) >= 4 and n.casefold() not in _STOP_TITLES
    ]
    rec_needles.sort(key=lambda kv: len(kv[0]), reverse=True)
    # Dedup needles
    rec_seen: set[str] = set()
    rec_targets: list[tuple[str, str]] = []
    for n, s in rec_needles:
        k = n.casefold()
        if k in rec_seen:
            continue
        rec_seen.add(k)
        rec_targets.append((n, s))
    for p in others:
        other = wiki / p["path"]
        if not other.is_file():
            continue
        try:
            ot = other.read_text(encoding="utf-8")
        except OSError:
            continue
        nt, n = _linkify_body(ot, rec_targets)
        if n and nt != ot:
            try:
                other.write_text(nt, encoding="utf-8")
                inbound += n
            except OSError:
                pass
    return {
        "ok": True,
        "page": f"wiki/{wiki_rel}",
        "outbound_links": outbound,
        "inbound_links": inbound,
    }


def refresh_index(workspace: Path) -> dict[str, Any]:
    """Rewrite ``.curator/index.md`` via CE ``sweep.py fix-index``."""
    from . import cebridge
    return cebridge.run_script(
        "sweep.py", ["fix-index", "wiki"],
        cwd=workspace, timeout=90.0, require_json=False,
    )


def after_wiki_write(workspace: Path, rel: str | None = None) -> dict[str, Any]:
    """Wire links + refresh the CE index after a wiki file is written."""
    wired: dict[str, Any] = {}
    if rel:
        wired = wire_new_page(workspace, rel)
    idx = refresh_index(workspace)
    return {"wired": wired, "index": idx}
