"""Workspace HTML slideshows (outside the wiki tree).

Sketch decks remain ``kind: deck`` in the Sketch tab. These are a
**different** product surface: self-contained HTML slideshows.

Convention::

  <workspace>/slideshows/<slug>/
      index.html          # entry (required)
      *.mp4, *.png, …     # media siblings (relative URLs from HTML)
      deck.json           # optional metadata {title, wiki_topics}

Wiki pages link with (NOT ``deck:`` — that word is reserved for Sketch)::

  [[slideshow:transformers-media-test|Transformers presentation]]

Quality: generate HTML via ``slideshow_html.write_slideshow`` so the
intro-grade design system always applies regardless of which LLM
wrote the copy.

Legacy folder ``decks/`` is still scanned for read/serve.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

from . import atomicio

DIRNAME = "slideshows"
LEGACY_DIRNAME = "decks"
_SLUG_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,80}$")


def decks_root(workspace: Path) -> Path:
    """Primary storage root (canonical: slideshows/)."""
    return workspace / DIRNAME


def _roots(workspace: Path) -> list[Path]:
    """Canonical first, then legacy decks/ for migration."""
    out = [workspace / DIRNAME, workspace / LEGACY_DIRNAME]
    return out


def is_valid_slug(slug: str) -> bool:
    return bool(_SLUG_RE.match(slug or ""))


def deck_dir(workspace: Path, slug: str) -> Path:
    """Directory for writes (always under slideshows/)."""
    if not is_valid_slug(slug):
        raise ValueError(f"invalid slideshow slug: {slug!r}")
    return decks_root(workspace) / slug


def _find_dir(workspace: Path, slug: str) -> Path | None:
    if not is_valid_slug(slug):
        return None
    for root in _roots(workspace):
        d = root / slug
        if d.is_dir():
            return d
    return None


def entry_html(workspace: Path, slug: str) -> Path | None:
    d = _find_dir(workspace, slug)
    if d:
        for name in ("index.html", "index.htm"):
            p = d / name
            if p.is_file():
                return p
    for root in _roots(workspace):
        flat = root / f"{slug}.html"
        if flat.is_file():
            return flat
    return None


def resolve_file(workspace: Path, slug: str, rel: str) -> Path | None:
    """Resolve a path inside a slideshow for HTTP serve."""
    if not is_valid_slug(slug):
        return None
    rel = (rel or "").strip().lstrip("/")
    if not rel or rel in (".", "./"):
        rel = "index.html"
    if ".." in Path(rel).parts:
        return None
    d = _find_dir(workspace, slug)
    if d is not None:
        candidate = (d / rel).resolve()
        try:
            candidate.relative_to(d.resolve())
        except ValueError:
            return None
        return candidate if candidate.is_file() else None
    if rel in ("index.html", "index.htm", f"{slug}.html"):
        for root in _roots(workspace):
            flat = (root / f"{slug}.html").resolve()
            try:
                flat.relative_to(root.resolve())
            except ValueError:
                continue
            if flat.is_file():
                return flat
    return None


def _read_meta(d: Path) -> dict[str, Any]:
    p = d / "deck.json"
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def list_decks(workspace: Path) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for root in _roots(workspace):
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if child.name.startswith("."):
                continue
            if child.is_dir():
                if child.name in seen or not is_valid_slug(child.name):
                    continue
                entry = entry_html(workspace, child.name)
                if not entry:
                    continue
                seen.add(child.name)
                meta = _read_meta(child)
                out.append({
                    "slug": child.name,
                    "title": str(meta.get("title") or child.name),
                    "path": f"{root.name}/{child.name}/",
                    "entry": str(entry.relative_to(workspace)),
                    "has_media": any(
                        f.suffix.lower() in (
                            ".mp4", ".webm", ".png", ".jpg", ".jpeg",
                            ".gif", ".webp", ".mp3", ".wav", ".svg",
                        )
                        for f in child.iterdir() if f.is_file()
                    ),
                    "wiki_topics": meta.get("wiki_topics") or [],
                    "updated_at": child.stat().st_mtime,
                })
            elif (
                child.suffix.lower() in (".html", ".htm")
                and is_valid_slug(child.stem)
                and child.stem not in seen
            ):
                seen.add(child.stem)
                out.append({
                    "slug": child.stem,
                    "title": child.stem,
                    "path": f"{root.name}/{child.name}",
                    "entry": str(child.relative_to(workspace)),
                    "has_media": False,
                    "wiki_topics": [],
                    "updated_at": child.stat().st_mtime,
                })
    out.sort(key=lambda d: str(d.get("title") or d["slug"]).lower())
    return out


def ensure_deck(
    workspace: Path,
    slug: str,
    *,
    title: str | None = None,
    wiki_topics: list[str] | None = None,
) -> Path:
    """Create slideshows/<slug>/ if missing; write/update deck.json."""
    d = deck_dir(workspace, slug)
    d.mkdir(parents=True, exist_ok=True)
    meta = _read_meta(d)
    if title:
        meta["title"] = title
    elif "title" not in meta:
        meta["title"] = slug
    if wiki_topics is not None:
        meta["wiki_topics"] = list(wiki_topics)
    meta.setdefault("created_at", time.time())
    meta["updated_at"] = time.time()
    atomicio.write_json_atomic(d / "deck.json", meta)
    return d


def import_folder(
    workspace: Path,
    src: Path,
    slug: str,
    *,
    title: str | None = None,
    wiki_topics: list[str] | None = None,
) -> dict[str, Any]:
    """Copy a folder (or single html + siblings) into slideshows/<slug>/."""
    src = Path(src)
    d = ensure_deck(workspace, slug, title=title, wiki_topics=wiki_topics)
    if src.is_dir():
        for item in src.iterdir():
            if item.name.startswith("."):
                continue
            dest = d / item.name
            if item.is_file():
                shutil.copy2(item, dest)
            elif item.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(item, dest)
    elif src.is_file() and src.suffix.lower() in (".html", ".htm"):
        shutil.copy2(src, d / "index.html")
    else:
        raise ValueError(f"not a slideshow folder or html file: {src}")
    if not (d / "index.html").is_file():
        for f in d.glob("*.html"):
            f.rename(d / "index.html")
            break
    if not (d / "index.html").is_file():
        raise ValueError(f"no html entry after import into {d}")
    return {
        "ok": True,
        "slug": slug,
        "path": f"{DIRNAME}/{slug}/",
        "title": title or slug,
    }


def wiki_link_markdown(slug: str, display: str | None = None) -> str:
    """Wikilink for HTML slideshows — NOT deck: (Sketch uses that word)."""
    label = display or slug
    return f"[[slideshow:{slug}|{label}]]"


def migrate_legacy_decks(workspace: Path) -> dict[str, Any] | None:
    """One-shot: move workspace ``decks/`` → ``slideshows/``, then remove
    the legacy root so it no longer appears as a stale top-level folder.

    - Slugs only in ``decks/`` are moved into ``slideshows/``.
    - Slugs already under ``slideshows/`` win; the legacy copy is deleted.
    - Flat ``decks/*.html`` files move similarly.
    - Idempotent no-op when ``decks/`` is missing or empty.

    Returns a small summary dict when work was done, else None.
    """
    legacy = workspace / LEGACY_DIRNAME
    if not legacy.is_dir():
        return None
    dest_root = decks_root(workspace)
    dest_root.mkdir(parents=True, exist_ok=True)
    moved = 0
    removed_dupes = 0
    for child in list(legacy.iterdir()):
        if child.name.startswith("."):
            continue
        if child.is_dir():
            if not is_valid_slug(child.name):
                continue
            dest = dest_root / child.name
            if dest.exists():
                shutil.rmtree(child)
                removed_dupes += 1
            else:
                shutil.move(str(child), str(dest))
                moved += 1
        elif child.is_file() and child.suffix.lower() in (".html", ".htm"):
            if not is_valid_slug(child.stem):
                continue
            # Prefer folder form under slideshows/
            dest_dir = dest_root / child.stem
            if dest_dir.is_dir() and (dest_dir / "index.html").is_file():
                child.unlink(missing_ok=True)
                removed_dupes += 1
            elif (dest_root / child.name).is_file():
                child.unlink(missing_ok=True)
                removed_dupes += 1
            else:
                dest_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(child), str(dest_dir / "index.html"))
                moved += 1
    # Drop empty legacy tree (and any leftover empties).
    try:
        for p in sorted(legacy.rglob("*"), reverse=True):
            if p.is_dir():
                try:
                    p.rmdir()
                except OSError:
                    pass
            elif p.name.startswith("."):
                p.unlink(missing_ok=True)
        # leftover non-slideshow junk? leave parent if still non-empty
        remaining = [p for p in legacy.iterdir() if not p.name.startswith(".")]
        if not remaining:
            shutil.rmtree(legacy, ignore_errors=True)
        elif moved or removed_dupes:
            # still something foreign left; keep decks/ but we moved what we could
            pass
    except OSError:
        pass
    if not moved and not removed_dupes and legacy.is_dir():
        # Empty or only-dot leftovers — still try remove
        try:
            remaining = list(legacy.iterdir())
            if not remaining or all(p.name.startswith(".") for p in remaining):
                shutil.rmtree(legacy, ignore_errors=True)
                return {"moved": 0, "removed_dupes": 0, "removed_root": True}
        except OSError:
            pass
        return None
    return {
        "moved": moved,
        "removed_dupes": removed_dupes,
        "removed_root": not legacy.is_dir(),
    }
