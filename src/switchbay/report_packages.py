"""Durable workspace report packages (outside the wiki).

Convention::

  <workspace>/reports/<slug>/
      index.html | report.pdf   # entry
      report.json               # {title, summary, sources, format, …}
      assets/                   # optional media
      thumbs/                   # optional page previews

Ephemeral agent reports stay in statedir via ``reports.py``; promote
with ``import_from_ephemeral``. Wikilink: ``[[report:slug|title]]``.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

from . import atomicio, reports as ephemeral_reports

DIRNAME = "reports"
_SLUG_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,80}$")


def is_valid_slug(slug: str) -> bool:
    return bool(_SLUG_RE.match(slug or ""))


def root(workspace: Path) -> Path:
    return workspace / DIRNAME


def package_dir(workspace: Path, slug: str) -> Path:
    if not is_valid_slug(slug):
        raise ValueError(f"invalid report slug: {slug!r}")
    return root(workspace) / slug


def _read_meta(d: Path) -> dict[str, Any]:
    p = d / "report.json"
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def entry_path(workspace: Path, slug: str) -> Path | None:
    if not is_valid_slug(slug):
        return None
    d = package_dir(workspace, slug)
    if not d.is_dir():
        return None
    for name in ("index.html", "index.htm", "report.pdf", "report.html"):
        p = d / name
        if p.is_file():
            return p
    for f in sorted(d.glob("*.html")):
        return f
    for f in sorted(d.glob("*.pdf")):
        return f
    return None


def resolve_file(workspace: Path, slug: str, rel: str) -> Path | None:
    if not is_valid_slug(slug):
        return None
    rel = (rel or "").strip().lstrip("/")
    if not rel or rel in (".", "./"):
        entry = entry_path(workspace, slug)
        return entry
    if ".." in Path(rel).parts:
        return None
    d = package_dir(workspace, slug)
    if not d.is_dir():
        return None
    candidate = (d / rel).resolve()
    try:
        candidate.relative_to(d.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def list_packages(workspace: Path) -> list[dict[str, Any]]:
    r = root(workspace)
    if not r.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for child in sorted(r.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if not is_valid_slug(child.name):
            continue
        entry = entry_path(workspace, child.name)
        if entry is None:
            continue
        meta = _read_meta(child)
        fmt = str(meta.get("format") or entry.suffix.lstrip(".") or "html")
        thumbs: list[Path] = []
        for pat in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
            thumbs.extend((child / "thumbs").glob(pat) if (child / "thumbs").is_dir() else [])
        thumbs = sorted(thumbs)
        out.append({
            "kind": "report",
            "slug": child.name,
            "title": str(meta.get("title") or child.name),
            "summary": str(meta.get("summary") or ""),
            "format": fmt,
            "path": f"{DIRNAME}/{child.name}/",
            "entry": str(entry.relative_to(workspace)),
            "n_thumbs": len(thumbs),
            "thumbs": [
                f"/api/report-packages/{child.name}/thumbs/{t.name}"
                for t in thumbs[:12]
            ],
            "sources": meta.get("sources") or [],
            "updated_at": float(
                meta.get("updated_at") or child.stat().st_mtime
            ),
            "wikilink": wiki_link_markdown(
                child.name, str(meta.get("title") or child.name),
            ),
        })
    out.sort(key=lambda d: str(d.get("title") or d["slug"]).lower())
    return out


def ensure_package(
    workspace: Path,
    slug: str,
    *,
    title: str | None = None,
    summary: str | None = None,
    sources: list[str] | None = None,
    fmt: str = "html",
) -> Path:
    d = package_dir(workspace, slug)
    d.mkdir(parents=True, exist_ok=True)
    (d / "assets").mkdir(exist_ok=True)
    (d / "thumbs").mkdir(exist_ok=True)
    meta = _read_meta(d)
    if title:
        meta["title"] = title
    elif "title" not in meta:
        meta["title"] = slug
    if summary is not None:
        meta["summary"] = summary
    if sources is not None:
        meta["sources"] = list(sources)
    meta["format"] = fmt
    meta.setdefault("created_at", time.time())
    meta["updated_at"] = time.time()
    atomicio.write_json_atomic(d / "report.json", meta)
    return d


def write_html_package(
    workspace: Path,
    slug: str,
    *,
    title: str,
    html: str,
    summary: str = "",
    sources: list[str] | None = None,
) -> dict[str, Any]:
    """Materialize reports/<slug>/index.html + report.json."""
    d = ensure_package(
        workspace, slug, title=title, summary=summary,
        sources=sources, fmt="html",
    )
    (d / "index.html").write_text(html, encoding="utf-8")
    return {
        "ok": True,
        "slug": slug,
        "path": f"{DIRNAME}/{slug}/",
        "title": title,
        "wikilink": wiki_link_markdown(slug, title),
    }


def import_from_ephemeral(
    workspace: Path,
    report_id: str,
    *,
    slug: str | None = None,
) -> dict[str, Any]:
    """Copy a statedir ephemeral report into reports/<slug>/."""
    html = ephemeral_reports.html_of(workspace, report_id)
    meta = ephemeral_reports.meta_of(workspace, report_id) or {}
    if not html:
        raise FileNotFoundError(f"no ephemeral report {report_id!r}")
    title = str(meta.get("title") or report_id)
    use_slug = slug or _slugify(title)
    if not is_valid_slug(use_slug):
        use_slug = _slugify(report_id)
    return write_html_package(
        workspace, use_slug,
        title=title,
        html=html,
        summary=str(meta.get("summary") or ""),
        sources=[],
    )


def wiki_link_markdown(slug: str, display: str | None = None) -> str:
    return f"[[report:{slug}|{display or slug}]]"


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return (s or "report")[:80]
