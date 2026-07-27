"""Per-workspace pasteboard ring.

A small multi-slot clipboard the user can stash arbitrary text or
images into and pull from later — distinct from the OS clipboard
which only holds one thing. Slots persist across sessions in
`<workspace>/.workbench/state/pasteboard.json` so the user's
collected snippets survive restarts.

Slot kinds: `text` and `image` (PNG bytes). Image payloads are
written as separate files at `.workbench/state/pasteboard/<id>.png`
so the index JSON stays cheap to load — the index just records the
filename + dimensions + size.

Ring discipline: newest at the front. When the cap is hit the
oldest slot is evicted on add, no questions asked — the user
explicitly removes anything they want to keep around indefinitely.
"""

from __future__ import annotations

import base64
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any
from . import atomicio

log = logging.getLogger("switchbay.pasteboard")

MAX_SLOTS = 30
PREVIEW_CHARS = 240


def _path(workspace: Path) -> Path:
    return workspace / ".workbench" / "state" / "pasteboard.json"


def _images_dir(workspace: Path) -> Path:
    return workspace / ".workbench" / "state" / "pasteboard"


def _read_raw(workspace: Path) -> list[dict[str, Any]]:
    p = _path(workspace)
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("pasteboard.json unreadable; starting fresh")
        return []
    if not isinstance(data, list):
        return []
    return [s for s in data if isinstance(s, dict)]


def _write_raw(workspace: Path, slots: list[dict[str, Any]]) -> None:
    p = _path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(p, slots)


def _slot_summary(slot: dict[str, Any]) -> dict[str, Any]:
    """Pasteboard rows in the listing carry a preview rather than
    the full text; for long stashed snippets the full body only
    travels when the user picks a specific slot. Keeps the listing
    fetch cheap when the ring has a 50 KB code chunk in it.

    Image slots carry no inline content — the listing reports
    the image filename + size instead so the UI can render a
    thumbnail via /api/pasteboard/image?id=..."""
    kind = str(slot.get("kind") or "text")
    if kind == "image":
        return {
            "id": slot.get("id"),
            "kind": "image",
            "captured_at": slot.get("captured_at"),
            "preview": "",  # listing UI shows a thumbnail instead
            "truncated": False,
            "size": int(slot.get("size") or 0),
            "image_filename": slot.get("image_filename"),
        }
    content = slot.get("content")
    if isinstance(content, str):
        preview = content[:PREVIEW_CHARS]
        truncated = len(content) > PREVIEW_CHARS
    else:
        preview = ""
        truncated = False
    return {
        "id": slot.get("id"),
        "kind": "text",
        "captured_at": slot.get("captured_at"),
        "preview": preview,
        "truncated": truncated,
        "size": len(content) if isinstance(content, str) else 0,
    }


def list_slots(workspace: Path) -> list[dict[str, Any]]:
    return [_slot_summary(s) for s in _read_raw(workspace)]


def get_slot(workspace: Path, slot_id: str) -> dict[str, Any] | None:
    """Full slot record. For text slots the content is inline; for
    image slots the caller should fetch the bytes via image_bytes()."""
    for s in _read_raw(workspace):
        if s.get("id") == slot_id:
            return s
    return None


def image_bytes(workspace: Path, slot_id: str) -> bytes | None:
    """Read the PNG payload for an image slot. Returns None if the
    slot doesn't exist, isn't an image, or the on-disk file is
    missing (e.g. user manually deleted .workbench/state/pasteboard/)."""
    slot = get_slot(workspace, slot_id)
    if slot is None or slot.get("kind") != "image":
        return None
    fname = str(slot.get("image_filename") or "")
    if not fname or "/" in fname or ".." in fname:
        return None
    p = _images_dir(workspace) / fname
    if not p.is_file():
        return None
    try:
        return p.read_bytes()
    except OSError:
        return None


def add_slot(
    workspace: Path,
    *,
    content: str | None = None,
    image_b64: str | None = None,
    kind: str = "text",
) -> dict[str, Any]:
    """Add a new slot. For `kind="text"` pass `content` (a non-empty
    string). For `kind="image"` pass `image_b64` (a base64 PNG, with
    or without a leading `data:image/png;base64,` prefix). The image
    bytes are written to `.workbench/state/pasteboard/<id>.png` and
    the index records the filename + size."""
    if kind == "text":
        if not isinstance(content, str) or not content:
            raise ValueError("content must be a non-empty string")
        sid = uuid.uuid4().hex[:12]
        slot = {
            "id": sid,
            "kind": "text",
            "content": content,
            "captured_at": time.time(),
        }
    elif kind == "image":
        if not isinstance(image_b64, str) or not image_b64:
            raise ValueError("image_b64 must be a non-empty base64 string")
        raw = image_b64.strip()
        if raw.startswith("data:"):
            comma = raw.find(",")
            if comma == -1:
                raise ValueError("malformed data URL")
            raw = raw[comma + 1:]
        try:
            png_bytes = base64.b64decode(raw, validate=False)
        except (ValueError, base64.binascii.Error) as e:
            raise ValueError(f"invalid base64 image: {e}") from e
        sid = uuid.uuid4().hex[:12]
        fname = f"{sid}.png"
        _images_dir(workspace).mkdir(parents=True, exist_ok=True)
        (_images_dir(workspace) / fname).write_bytes(png_bytes)
        slot = {
            "id": sid,
            "kind": "image",
            "image_filename": fname,
            "size": len(png_bytes),
            "captured_at": time.time(),
        }
    else:
        raise ValueError(f"unsupported slot kind: {kind!r}")
    slots = _read_raw(workspace)
    # Newest at the front; cap at MAX_SLOTS by dropping the oldest.
    slots.insert(0, slot)
    if len(slots) > MAX_SLOTS:
        for evicted in slots[MAX_SLOTS:]:
            _evict_image_file(workspace, evicted)
        slots = slots[:MAX_SLOTS]
    _write_raw(workspace, slots)
    return _slot_summary(slot)


def _evict_image_file(workspace: Path, slot: dict[str, Any]) -> None:
    """Remove the on-disk PNG when an image slot is dropped from the
    ring. Best-effort; missing file is fine."""
    if slot.get("kind") != "image":
        return
    fname = str(slot.get("image_filename") or "")
    if not fname:
        return
    try:
        (_images_dir(workspace) / fname).unlink(missing_ok=True)
    except OSError:
        pass


def remove_slot(workspace: Path, slot_id: str) -> bool:
    slots = _read_raw(workspace)
    target = next((s for s in slots if s.get("id") == slot_id), None)
    if target is None:
        return False
    keep = [s for s in slots if s.get("id") != slot_id]
    _write_raw(workspace, keep)
    _evict_image_file(workspace, target)
    return True


def clear(workspace: Path) -> int:
    slots = _read_raw(workspace)
    for s in slots:
        _evict_image_file(workspace, s)
    n = len(slots)
    _write_raw(workspace, [])
    return n
