"""Provenance scan behind the Browser column's Sources view (D1).

The Sources view is a *provenance view over `extracted_from`
frontmatter paths*, not a second file browser: it answers "which
outside files/streams did this wiki's pages come from?". Rules
(charter, 2026-07-04 note):

  * Only EXTERNAL provenance shows — an `extracted_from` that points
    inside the workspace (the usual `vault/<digest>/<name>` staging
    path) folds into the vault/FILES view instead of duplicating it.
    Those are counted (`internal_pages`) so the UI can render an
    honest empty state ("no external sources — everything lives in
    the vault") rather than a bare blank.
  * URLs (comms-stream deep links, web articles) are external
    provenance too — kind "url"; local paths are kind "file" with an
    existence check so moved/deleted originals surface honestly.

One source may back many pages (and one page names one source —
CE's `extracted_from` is single-valued). The frontend builds the
path-compressed tree; this module just aggregates.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

# Frontmatter is scanned with cheap regexes over the file head — the
# wiki can be thousands of pages and this runs off-thread per request;
# a YAML parse per page is needless weight for two scalar keys.
_EXTRACTED_RE = re.compile(r"^extracted_from:\s*(.+?)\s*$", re.MULTILINE)
_TITLE_RE = re.compile(r"^title:\s*(.+?)\s*$", re.MULTILINE)

_HEAD_BYTES = 4096


def _frontmatter_head(p: Path) -> str | None:
    """The page's frontmatter block (sans fences), or None when the
    file doesn't start with one / can't be read."""
    try:
        with p.open("r", encoding="utf-8", errors="replace") as f:
            head = f.read(_HEAD_BYTES)
    except OSError:
        return None
    if not head.startswith("---"):
        return None
    end = head.find("\n---", 3)
    return head[3:end] if end != -1 else head[3:]


def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    return v.strip()


def scan(workspace: Path) -> dict[str, Any]:
    """Aggregate provenance across `wiki/**/*.md`. Returns
    {sources: [{path, kind, exists, pages: [{page, title}]}],
     internal_pages, pages_scanned} — sources sorted by path,
    external only."""
    wiki = workspace / "wiki"
    try:
        ws_real = str(workspace.resolve())
    except OSError:
        ws_real = str(workspace)
    by_source: dict[str, dict[str, Any]] = {}
    internal_pages = 0
    pages_scanned = 0
    if wiki.is_dir():
        for root, dirnames, filenames in os.walk(wiki):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in filenames:
                if not name.endswith(".md") or name.startswith("."):
                    continue
                p = Path(root) / name
                fm = _frontmatter_head(p)
                if fm is None:
                    continue
                pages_scanned += 1
                m = _EXTRACTED_RE.search(fm)
                if not m:
                    continue
                raw = _unquote(m.group(1))
                if not raw:
                    continue
                if raw.startswith(("http://", "https://")):
                    key, kind = raw, "url"
                else:
                    q = Path(os.path.expanduser(raw))
                    if not q.is_absolute():
                        q = workspace / q
                    try:
                        q = q.resolve()
                    except OSError:
                        pass
                    if str(q) == ws_real or str(q).startswith(ws_real + os.sep):
                        internal_pages += 1
                        continue
                    key, kind = str(q), "file"
                tm = _TITLE_RE.search(fm)
                title = _unquote(tm.group(1)) if tm else ""
                rec = by_source.setdefault(
                    key, {"path": key, "kind": kind, "exists": None, "pages": []},
                )
                rec["pages"].append({
                    "page": str(p.relative_to(workspace)),
                    "title": title,
                })
    for rec in by_source.values():
        if rec["kind"] == "file":
            # A cheap existence probe; dataless cloud placeholders
            # still count as present (the file exists, just evicted).
            rec["exists"] = os.path.exists(rec["path"])
    return {
        "sources": sorted(by_source.values(), key=lambda r: str(r["path"])),
        "internal_pages": internal_pages,
        "pages_scanned": pages_scanned,
    }


def known_paths(scan_result: dict[str, Any]) -> set[str]:
    """The set of file-kind source paths in a scan result — the
    validation allowlist for reveal/open on EXTERNAL paths (the
    only fs endpoints that ever leave the workspace; they act
    strictly on paths the user's own frontmatter declared)."""
    return {
        str(s["path"])
        for s in scan_result.get("sources", [])
        if s.get("kind") == "file"
    }
