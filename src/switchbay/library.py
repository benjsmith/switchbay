"""Unified library index: reports · slideshows · worksheets.

List + lightweight search for the Library tab. Full FTS5 index lands
in a later phase; v1 is in-memory filter over package metas (plenty
fast for personal workspaces) and exposes a stable API.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import html_decks, report_packages, worksheets_store


def list_all(workspace: Path) -> dict[str, Any]:
    reports = report_packages.list_packages(workspace)
    worksheets = worksheets_store.list_packages(workspace)
    slideshows = []
    for d in html_decks.list_decks(workspace):
        slideshows.append({
            "kind": "slideshow",
            "slug": d["slug"],
            "title": d.get("title") or d["slug"],
            "summary": "",
            "path": d.get("path"),
            "has_media": d.get("has_media"),
            "updated_at": d.get("updated_at") or 0,
            "wikilink": html_decks.wiki_link_markdown(
                d["slug"], str(d.get("title") or d["slug"]),
            ),
            "thumbs": [],  # filled when thumb pipeline exists
            "n_thumbs": 0,
        })
    return {
        "reports": reports,
        "slideshows": slideshows,
        "worksheets": worksheets,
        "counts": {
            "reports": len(reports),
            "slideshows": len(slideshows),
            "worksheets": len(worksheets),
        },
    }


def search(workspace: Path, query: str, *, limit: int = 40) -> list[dict[str, Any]]:
    """Simple ranked substring search over title/summary/slug/path."""
    q = (query or "").strip().lower()
    if not q:
        return []
    tokens = [t for t in re.split(r"\s+", q) if t]
    catalog = list_all(workspace)
    hits: list[tuple[int, dict[str, Any]]] = []
    for kind in ("reports", "slideshows", "worksheets"):
        for item in catalog[kind]:
            blob = " ".join([
                str(item.get("title") or ""),
                str(item.get("summary") or ""),
                str(item.get("slug") or ""),
                str(item.get("path") or ""),
                " ".join(str(s) for s in (item.get("sheet_names") or [])),
                " ".join(str(s) for s in (item.get("sources") or [])),
            ]).lower()
            if not all(t in blob for t in tokens):
                continue
            score = 0
            title = str(item.get("title") or "").lower()
            slug = str(item.get("slug") or "").lower()
            for t in tokens:
                if t in title:
                    score += 10
                if t in slug:
                    score += 6
                score += blob.count(t)
            hits.append((score, item))
    hits.sort(key=lambda x: (-x[0], str(x[1].get("title") or "").lower()))
    return [h for _, h in hits[: max(1, min(limit, 100))]]
