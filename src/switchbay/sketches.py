"""Per-workspace sketch store.

Each sketch is a single JSON file at
`<workspace>/.workbench/sketches/<id>.json` with shape:

    {
      "id":          "<slug>",
      "name":        "Architecture diagram",
      "kind":        "excalidraw" | "drawio",
      "data":        {...} | "<xml string>",   # tool-specific scene/source
      "created_at":  1234567890.0,
      "updated_at":  1234567890.0
    }

PNG exports of every sketch live at `<workspace>/figures/<id>.png`
(NOT under .workbench — `figures/` is a first-class user-visible
directory so other tabs / agents / docs can reference it as a
plain image without going through workbench internals).

Tool format and PNG bytes are produced client-side and POSTed
together — Excalidraw and drawio both have native exporters.
This module just persists what arrives.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any
from . import atomicio

log = logging.getLogger("switchbay.sketches")

VALID_KINDS = ("excalidraw", "drawio")


def _dir(workspace: Path) -> Path:
    return workspace / ".workbench" / "sketches"


def _figures_dir(workspace: Path) -> Path:
    """CE-native asset location (2026-07-05 convention migration):
    figure binaries live INSIDE the wiki tree so curiosity-engine and
    curiosity-merge resolve `figures/_assets/<id>.png` refs natively.
    The old workspace-root `figures/` is read as a legacy fallback
    and auto-migrated on workspace activation."""
    return workspace / "wiki" / "figures" / "_assets"


def _legacy_figures_dir(workspace: Path) -> Path:
    return workspace / "figures"


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or uuid.uuid4().hex[:8]


def _path(workspace: Path, sketch_id: str) -> Path:
    if "/" in sketch_id or ".." in sketch_id or not sketch_id:
        raise ValueError(f"invalid sketch id: {sketch_id!r}")
    return _dir(workspace) / f"{sketch_id}.json"


def _png_path(workspace: Path, sketch_id: str) -> Path:
    if "/" in sketch_id or ".." in sketch_id or not sketch_id:
        raise ValueError(f"invalid sketch id: {sketch_id!r}")
    return _figures_dir(workspace) / f"{sketch_id}.png"


def _legacy_png_path(workspace: Path, sketch_id: str) -> Path:
    return _legacy_figures_dir(workspace) / f"{sketch_id}.png"


def list_sketches(workspace: Path) -> list[dict[str, Any]]:
    """Metadata list sorted by `created_at` ascending (insertion order).

    Previously sorted by `updated_at desc`, which made the deck's slide
    numbering shuffle every time the user clicked through — each
    activation triggered Excalidraw's onChange → autosave, bumping
    `updated_at` and floating the active slide to position 0. Stable
    creation order keeps "slide N" pinned to the same sketch across
    the lifetime of the deck."""
    d = _dir(workspace)
    if not d.is_dir():
        return []
    out: list[dict[str, Any]] = []
    figures = _figures_dir(workspace)
    legacy_figures = _legacy_figures_dir(workspace)
    for f in d.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.warning("skipping unreadable sketch file: %s", f.name)
            continue
        if not isinstance(data, dict):
            continue
        sid = data.get("id") or f.stem
        png = figures / f"{sid}.png"
        if not png.is_file():
            legacy = legacy_figures / f"{sid}.png"
            if legacy.is_file():
                png = legacy
        out.append({
            "id": sid,
            "name": data.get("name") or sid,
            "kind": data.get("kind") or "excalidraw",
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
            "has_png": png.is_file(),
        })
    out.sort(key=lambda s: s.get("created_at") or 0)
    return out


def get_sketch(workspace: Path, sketch_id: str) -> dict[str, Any] | None:
    p = _path(workspace, sketch_id)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def save_sketch(
    workspace: Path,
    *,
    name: str,
    kind: str,
    data: Any,
    sketch_id: str | None = None,
    png_b64: str | None = None,
) -> dict[str, Any]:
    """Create or update a sketch. `data` is opaque (Excalidraw scene
    JSON or drawio XML string). When `png_b64` is supplied (data-URL
    or bare base64), a PNG export is written to `figures/<id>.png`.
    Returns the saved record (sans png bytes)."""
    if kind not in VALID_KINDS:
        raise ValueError(f"kind must be one of {VALID_KINDS}, got {kind!r}")
    name = (name or "").strip() or "Untitled sketch"
    d = _dir(workspace)
    d.mkdir(parents=True, exist_ok=True)
    if sketch_id is None:
        sketch_id = _slugify(name)
        target = d / f"{sketch_id}.json"
        while target.exists():
            sketch_id = f"{_slugify(name)}-{uuid.uuid4().hex[:4]}"
            target = d / f"{sketch_id}.json"
    target = _path(workspace, sketch_id)
    now = time.time()
    existing = get_sketch(workspace, sketch_id) if target.exists() else None
    record = {
        "id": sketch_id,
        "name": name,
        "kind": kind,
        "data": data,
        "created_at": (existing or {}).get("created_at", now),
        "updated_at": now,
    }
    atomicio.write_json_atomic(target, record)
    if png_b64:
        _write_png(workspace, sketch_id, png_b64)
    elif kind == "excalidraw" and isinstance(data, dict):
        # Fall back to a server-side Pillow raster when the caller
        # didn't supply a canonical PNG. Keeps `figures/<id>.png`
        # in sync with the JSON for agent-authored slides
        # (`author_slide` doesn't ship a PNG since it has no canvas
        # mounted); the Sketch tab still overwrites this with the
        # canonical Excalidraw export the next time the slide is
        # opened.
        try:
            from . import slide_layouts
            png_bytes = slide_layouts.rasterize_scene_png(data)
            figures = _figures_dir(workspace)
            figures.mkdir(parents=True, exist_ok=True)
            _png_path(workspace, sketch_id).write_bytes(png_bytes)
        except Exception as e:  # noqa: BLE001
            log.warning(
                "server-side raster failed for sketch %s: %s",
                sketch_id, e,
            )
    log.info("saved sketch %s (%s, %s)", sketch_id, name, kind)
    return record


def _write_png(workspace: Path, sketch_id: str, png_b64: str) -> None:
    """Decode a base64 (or data-URL) PNG payload and write it to
    `figures/<id>.png`. Tolerant of the optional `data:image/png;base64,`
    prefix that some browser exporters emit."""
    raw = png_b64.strip()
    if raw.startswith("data:"):
        comma = raw.find(",")
        if comma == -1:
            raise ValueError("malformed data URL")
        raw = raw[comma + 1:]
    try:
        png_bytes = base64.b64decode(raw, validate=False)
    except (ValueError, base64.binascii.Error) as e:
        raise ValueError(f"invalid base64 PNG: {e}") from e
    figures = _figures_dir(workspace)
    figures.mkdir(parents=True, exist_ok=True)
    _png_path(workspace, sketch_id).write_bytes(png_bytes)


def delete_sketch(workspace: Path, sketch_id: str) -> bool:
    p = _path(workspace, sketch_id)
    existed = p.is_file()
    if existed:
        p.unlink()
    # Best-effort PNG cleanup (both conventions); missing is fine.
    for png in (_png_path(workspace, sketch_id),
                _legacy_png_path(workspace, sketch_id)):
        if png.is_file():
            png.unlink()
    return existed


# ── Legacy-figures migration (2026-07-05 convention change) ────────

_IMG_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}


def migrate_root_figures(workspace: Path) -> dict[str, int] | None:
    """One-shot per-workspace convergence onto the CE-native layout:
    move `<ws>/figures/*` image files into `wiki/figures/_assets/`
    and rewrite wiki refs `figures/<name>` → `figures/_assets/<name>`
    for exactly the moved names. Idempotent (nothing legacy left →
    None); name collisions leave the legacy file in place (the dual
    /figures route still serves it). Returns {moved, pages_rewritten}
    when anything happened."""
    legacy = _legacy_figures_dir(workspace)
    if not legacy.is_dir():
        return None
    assets = _figures_dir(workspace)
    moved: list[str] = []
    for f in sorted(legacy.iterdir()):
        if not f.is_file() or f.suffix.lower() not in _IMG_EXTS:
            continue
        dst = assets / f.name
        if dst.exists():
            continue
        assets.mkdir(parents=True, exist_ok=True)
        shutil.move(str(f), str(dst))
        moved.append(f.name)
    rewritten = 0
    if moved:
        wiki = workspace / "wiki"
        if wiki.is_dir():
            for page in wiki.rglob("*.md"):
                try:
                    text = page.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                new = text
                for name in moved:
                    new = new.replace(f"figures/{name}", f"figures/_assets/{name}")
                if new != text:
                    try:
                        page.write_text(new, encoding="utf-8")
                        rewritten += 1
                    except OSError:
                        log.warning("figures migration: couldn't rewrite %s", page)
    try:
        if legacy.is_dir() and not any(legacy.iterdir()):
            legacy.rmdir()
    except OSError:
        pass
    if not moved:
        return None
    return {"moved": len(moved), "pages_rewritten": rewritten}
