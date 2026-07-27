"""Per-surface UI focus for the rail agent.

Each interactive tab (sheet / table / plot / sketch) publishes a small
JSON blob describing what the user is looking at. MCP tools read these
so the agent can act on the *visible* artifact the way `!fn` / `!sql`
do — without hunting the wiki for "active work".

Stored at `<workspace>/.workbench/state/ui-focus-<surface>.json`.
Distinct from the cross-tab `selection` layer (which is about which
wiki page / CSV / plot *artifact* is selected for navigation).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import atomicio

FOCUS_STALE_SECONDS = 5 * 60
MAX_JSON_CHARS = 12_000  # hard cap on a single focus blob
SURFACES = ("sheet", "table", "plot", "sketch")


def _path(workspace: Path, surface: str) -> Path:
    if surface not in SURFACES and not surface.replace("_", "").isalnum():
        raise ValueError(f"invalid surface: {surface!r}")
    return workspace / ".workbench" / "state" / f"ui-focus-{surface}.json"


def load(workspace: Path, surface: str) -> dict[str, Any] | None:
    p = _path(workspace, surface)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def save(workspace: Path, surface: str, focus: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(focus) if isinstance(focus, dict) else {}
    cleaned["surface"] = surface
    cleaned["updated_at"] = datetime.now(timezone.utc).isoformat()
    # Cap total size so a huge plot spec or SQL result can't blow context.
    raw = json.dumps(cleaned, default=str)
    if len(raw) > MAX_JSON_CHARS:
        # Drop bulky fields first.
        for key in ("preview", "rows", "spec", "elements_summary", "slots"):
            if key in cleaned and len(json.dumps(cleaned, default=str)) > MAX_JSON_CHARS:
                cleaned[key] = {"_truncated": True}
        raw = json.dumps(cleaned, default=str)
        if len(raw) > MAX_JSON_CHARS:
            cleaned = {
                "surface": surface,
                "updated_at": cleaned["updated_at"],
                "error": "focus payload too large; republish a smaller summary",
            }
    p = _path(workspace, surface)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(p, cleaned)
    return cleaned


def is_fresh(focus: dict[str, Any] | None, *, max_age_s: float = FOCUS_STALE_SECONDS) -> bool:
    if not focus:
        return False
    ts = focus.get("updated_at")
    if not isinstance(ts, str) or not ts:
        return False
    try:
        when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - when).total_seconds()
    return 0 <= age <= max_age_s


def load_all_fresh(workspace: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    # Sheet still lives in sheet-focus.json (A1-normalised); dual-read.
    try:
        from . import sheet_focus as _sf
        sf = _sf.load(workspace)
        if is_fresh(sf) and sf is not None:
            out["sheet"] = sf
    except Exception:  # noqa: BLE001
        pass
    for s in SURFACES:
        if s == "sheet":
            continue
        f = load(workspace, s)
        if is_fresh(f) and f is not None:
            out[s] = f
    return out


def combined_prompt_lines(workspace: Path) -> str | None:
    """Short system-prompt appendix covering every fresh surface."""
    lines: list[str] = []
    fresh = load_all_fresh(workspace)
    if not fresh:
        return None

    sheet = fresh.get("sheet")
    if sheet and sheet.get("a1"):
        a1 = sheet["a1"]
        used = sheet.get("used_range") or "?"
        lines.append(
            f"UI focus · Sheet cell {a1} (used {used}). "
            f"Use sheet_context / sheet_set_formula — not the wiki."
        )

    table = fresh.get("table")
    if table and (table.get("sql") or table.get("query")):
        sql = str(table.get("sql") or table.get("query") or "")
        snippet = sql.replace("\n", " ").strip()
        if len(snippet) > 80:
            snippet = snippet[:79] + "…"
        lines.append(
            f"UI focus · Table SQL editor: `{snippet}`. "
            f"Use table_context / table_run_sql (same as !sql)."
        )

    plot = fresh.get("plot")
    if plot and plot.get("id"):
        lines.append(
            f"UI focus · Plot `{plot.get('name') or plot['id']}` "
            f"(id={plot['id']}). Use plot_context / plot_update "
            f"(or save_plot with that id)."
        )

    sketch = fresh.get("sketch")
    if sketch and sketch.get("sketch_id"):
        idx = sketch.get("slide_index")
        deck = sketch.get("deck_title") or sketch.get("analysis_path")
        extra = ""
        if idx is not None:
            extra += f" slide {int(idx) + 1}"
        if deck:
            extra += f" in deck {deck}"
        lines.append(
            f"UI focus · Sketch/slide `{sketch.get('name') or sketch['sketch_id']}`"
            f"{extra} (id={sketch['sketch_id']}). "
            f"Use sketch_context / author_slide(sketch_id=…) for edits."
        )

    if not lines:
        return None
    lines.append(
        "Prefer these live-tab tools over searching the vault for "
        "what the user is looking at."
    )
    return "\n".join(lines)
