"""Per-workspace Vega-Lite plot store.

Each plot is a single JSON file at `<workspace>/.workbench/plots/<id>.json`:

    {
      "id":         "<slug>",
      "name":       "Sales pipeline",
      "spec":       { ...vega-lite spec... },
      "created_at": 1234567890.0,
      "updated_at": 1234567890.0
    }

Files are the source of truth — one per plot so git, the file ops left
bar, and the agent can all manipulate them with no extra glue. The
`name` field is the "plot doc-name" the user refers to in chat
("update the scatter in plot-2024-04-26"); the `id` is a slug derived
from the name and stays stable across renames.

The Vega-Lite spec authoring flow is the LLM's job — this module does
not validate the spec beyond "is it a JSON object". A bad spec renders
as an error in the tab; the user (or the agent) edits and resaves.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any
from . import atomicio

log = logging.getLogger("switchbay.plots")


def _dir(workspace: Path) -> Path:
    return workspace / ".workbench" / "plots"


def _slugify(name: str) -> str:
    """Lower-case, hyphen-separated, alnum-only. Falls back to a uuid
    fragment if the name has no usable characters."""
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or uuid.uuid4().hex[:8]


def _path(workspace: Path, plot_id: str) -> Path:
    # Defensive: reject anything that could escape the plots dir.
    if "/" in plot_id or ".." in plot_id or not plot_id:
        raise ValueError(f"invalid plot id: {plot_id!r}")
    return _dir(workspace) / f"{plot_id}.json"


def list_plots(workspace: Path) -> list[dict[str, Any]]:
    """List metadata (no spec) for every plot, newest first. Skips
    files that don't parse — corrupt files surface as missing rather
    than 500'ing the API."""
    d = _dir(workspace)
    if not d.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for f in d.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.warning("skipping unreadable plot file: %s", f.name)
            continue
        if not isinstance(data, dict):
            continue
        out.append({
            "id": data.get("id") or f.stem,
            "name": data.get("name") or f.stem,
            "origin": data.get("origin"),
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
        })
    out.sort(key=lambda p: p.get("updated_at") or 0, reverse=True)
    return out


def get_plot(workspace: Path, plot_id: str) -> dict[str, Any] | None:
    p = _path(workspace, plot_id)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("plot %s unreadable: %s", plot_id, e)
        return None
    if not isinstance(data, dict):
        return None
    return data


def save_plot(
    workspace: Path,
    *,
    name: str,
    spec: dict[str, Any],
    plot_id: str | None = None,
    origin: str | None = None,
) -> dict[str, Any]:
    """Create or update a plot. If `plot_id` is omitted, a slug is
    derived from `name`; collisions are resolved by appending a short
    uuid suffix.

    `origin` is an optional breadcrumb identifying where the plot
    was derived from (e.g. `tables/foo.md#table-1` for a plot
    fanned out from a wiki table). Used by the frontend to skip
    re-generation if the user clicks ↗ Plot on the same table
    twice. When updating an existing plot, omit `origin` to keep
    the prior value; pass an explicit value (or empty string) to
    overwrite it.

    Returns the saved record."""
    if not isinstance(spec, dict):
        raise ValueError("spec must be a JSON object")
    name = (name or "").strip() or "Untitled plot"
    d = _dir(workspace)
    d.mkdir(parents=True, exist_ok=True)
    if plot_id is None:
        plot_id = _slugify(name)
        # Collision-resolve only when *creating*: editing an existing
        # plot reuses its id even if a sibling has the same slug.
        target = d / f"{plot_id}.json"
        while target.exists():
            plot_id = f"{_slugify(name)}-{uuid.uuid4().hex[:4]}"
            target = d / f"{plot_id}.json"
    target = _path(workspace, plot_id)
    now = time.time()
    existing = get_plot(workspace, plot_id) if target.exists() else None
    # Preserve the prior origin on an update unless the caller
    # passed something (including an empty string explicitly).
    if origin is None and existing is not None:
        origin = existing.get("origin")
    record: dict[str, Any] = {
        "id": plot_id,
        "name": name,
        "spec": spec,
        "created_at": (existing or {}).get("created_at", now),
        "updated_at": now,
    }
    if origin:
        record["origin"] = origin
    atomicio.write_json_atomic(target, record)
    log.info("saved plot %s (%s)", plot_id, name)
    return record


def delete_plot(workspace: Path, plot_id: str) -> bool:
    p = _path(workspace, plot_id)
    if not p.is_file():
        return False
    p.unlink()
    return True
