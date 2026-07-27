"""Named Univer workbook packages (outside the wiki).

Convention::

  <workspace>/worksheets/<slug>/
      workbook.json    # Univer snapshot (opaque)
      meta.json        # {title, sheet_names, updated_at}
      thumbs/          # optional sheet previews

Scratch workbook remains ``.workbench/state/sheet.json`` (sheets.py).
Save-as promotes the active snapshot into a named package.
Wikilink: ``[[worksheet:slug|title]]``.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from . import atomicio

DIRNAME = "worksheets"
_SLUG_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,80}$")


def is_valid_slug(slug: str) -> bool:
    return bool(_SLUG_RE.match(slug or ""))


def root(workspace: Path) -> Path:
    return workspace / DIRNAME


def package_dir(workspace: Path, slug: str) -> Path:
    if not is_valid_slug(slug):
        raise ValueError(f"invalid worksheet slug: {slug!r}")
    return root(workspace) / slug


def _read_meta(d: Path) -> dict[str, Any]:
    p = d / "meta.json"
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _sheet_names_from_snapshot(snap: dict[str, Any]) -> list[str]:
    """Best-effort extract sheet names from a Univer workbook snapshot."""
    names: list[str] = []
    # Common shapes: sheets as dict id→{name}, or sheets array
    sheets = snap.get("sheets")
    if isinstance(sheets, dict):
        for _sid, body in sheets.items():
            if isinstance(body, dict) and body.get("name"):
                names.append(str(body["name"]))
            elif isinstance(body, dict) and body.get("id"):
                names.append(str(body.get("name") or body["id"]))
    elif isinstance(sheets, list):
        for body in sheets:
            if isinstance(body, dict) and body.get("name"):
                names.append(str(body["name"]))
    order = snap.get("sheetOrder") or snap.get("sheet_order")
    if isinstance(order, list) and isinstance(sheets, dict):
        ordered: list[str] = []
        for sid in order:
            body = sheets.get(sid)
            if isinstance(body, dict):
                ordered.append(str(body.get("name") or sid))
        if ordered:
            return ordered
    return names


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
        wb = child / "workbook.json"
        if not wb.is_file():
            continue
        meta = _read_meta(child)
        sheet_names = meta.get("sheet_names") or []
        if not isinstance(sheet_names, list):
            sheet_names = []
        thumbs: list[Path] = []
        tdir = child / "thumbs"
        if tdir.is_dir():
            for pat in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
                thumbs.extend(tdir.glob(pat))
        thumbs = sorted(thumbs)
        out.append({
            "kind": "worksheet",
            "slug": child.name,
            "title": str(meta.get("title") or child.name),
            "summary": str(meta.get("summary") or ""),
            "sheet_names": [str(s) for s in sheet_names],
            "path": f"{DIRNAME}/{child.name}/",
            "n_thumbs": len(thumbs),
            "thumbs": [
                f"/api/worksheets/{child.name}/thumbs/{t.name}"
                for t in thumbs[:12]
            ],
            "updated_at": float(
                meta.get("updated_at") or child.stat().st_mtime
            ),
            "wikilink": wiki_link_markdown(
                child.name, str(meta.get("title") or child.name),
            ),
        })
    out.sort(key=lambda d: str(d.get("title") or d["slug"]).lower())
    return out


def load_snapshot(workspace: Path, slug: str) -> dict[str, Any] | None:
    if not is_valid_slug(slug):
        return None
    p = package_dir(workspace, slug) / "workbook.json"
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def save_snapshot(
    workspace: Path,
    slug: str,
    snapshot: dict[str, Any],
    *,
    title: str | None = None,
    summary: str = "",
) -> dict[str, Any]:
    d = package_dir(workspace, slug)
    d.mkdir(parents=True, exist_ok=True)
    (d / "thumbs").mkdir(exist_ok=True)
    atomicio.write_json_atomic(d / "workbook.json", snapshot)
    meta = _read_meta(d)
    meta["title"] = title or meta.get("title") or slug
    if summary:
        meta["summary"] = summary
    meta["sheet_names"] = _sheet_names_from_snapshot(snapshot)
    meta.setdefault("created_at", time.time())
    meta["updated_at"] = time.time()
    atomicio.write_json_atomic(d / "meta.json", meta)
    return {
        "ok": True,
        "slug": slug,
        "path": f"{DIRNAME}/{slug}/",
        "title": meta["title"],
        "sheet_names": meta["sheet_names"],
        "wikilink": wiki_link_markdown(slug, str(meta["title"])),
    }


def resolve_file(workspace: Path, slug: str, rel: str) -> Path | None:
    if not is_valid_slug(slug):
        return None
    rel = (rel or "").strip().lstrip("/")
    if not rel or rel in (".", "./"):
        rel = "workbook.json"
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


def wiki_link_markdown(slug: str, display: str | None = None) -> str:
    return f"[[worksheet:{slug}|{display or slug}]]"


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return (s or "worksheet")[:80]
