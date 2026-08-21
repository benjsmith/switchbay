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


def _each_unit(spec: dict[str, Any], visit) -> None:
    visit(spec)
    for key in ("layer", "hconcat", "vconcat", "concat"):
        arr = spec.get(key)
        if isinstance(arr, list):
            for child in arr:
                if isinstance(child, dict):
                    _each_unit(child, visit)
    inner = spec.get("spec")
    if isinstance(inner, dict):
        _each_unit(inner, visit)


def _wrap_words(text: str, max_chars: int) -> str | list[str]:
    if len(text) <= max_chars:
        return text
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if len(trial) > max_chars and cur:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines if len(lines) > 1 else text


def _wrap_axis_title(channel: dict[str, Any], max_chars: int) -> None:
    raw = channel.get("title")
    if isinstance(raw, str):
        channel["title"] = _wrap_words(raw, max_chars)
    axis = channel.get("axis")
    if isinstance(axis, dict) and isinstance(axis.get("title"), str):
        axis["title"] = _wrap_words(str(axis["title"]), max_chars)


def sanitize_plot_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Fix common agent-authored Vega-Lite foot-guns.

    1. ``color.legend: null`` on any layer of a shared color scale
       removes the *whole* category legend (countries vanish; only
       a stroke-dash key remains).
    2. Row-facet headers default to the left and collide with the
       y-axis title when the facet values are long sentences.
    3. Long axis titles clip the top (y, rotated) or right (x) of
       the card — wrap to a few short lines.
    """
    colors: list[dict[str, Any]] = []

    def collect(unit: dict[str, Any]) -> None:
        enc = unit.get("encoding")
        if not isinstance(enc, dict):
            return
        color = enc.get("color")
        if isinstance(color, dict) and color.get("field"):
            colors.append(color)

    _each_unit(spec, collect)
    hid = [c for c in colors if c.get("legend") is None and "legend" in c]
    kept = [c for c in colors if c.get("legend") is not None or "legend" not in c]
    if hid and kept:
        for c in hid:
            c.pop("legend", None)

    def lift_headers(unit: dict[str, Any]) -> None:
        facet = unit.get("facet")
        if not isinstance(facet, dict):
            return
        row = facet.get("row")
        if not isinstance(row, dict) or isinstance(row.get("header"), dict):
            return
        row["header"] = {
            "labelOrient": "top",
            "labelAnchor": "start",
            "labelAlign": "left",
            "labelPadding": 6,
            "labelLimit": 420,
            "title": None,
        }

    _each_unit(spec, lift_headers)

    def wrap_axes(unit: dict[str, Any]) -> None:
        enc = unit.get("encoding")
        if not isinstance(enc, dict):
            return
        if isinstance(enc.get("y"), dict):
            _wrap_axis_title(enc["y"], 22)
        if isinstance(enc.get("y2"), dict):
            _wrap_axis_title(enc["y2"], 22)
        if isinstance(enc.get("x"), dict):
            _wrap_axis_title(enc["x"], 32)
        if isinstance(enc.get("x2"), dict):
            _wrap_axis_title(enc["x2"], 32)

    _each_unit(spec, wrap_axes)
    return spec


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
    caption: str | None = None,
    sources: list[str] | None = None,
    relates_to: list[str] | None = None,
    analysis: str | None = None,
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
    spec = sanitize_plot_spec(spec)
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
    if caption is None and existing is not None:
        caption = existing.get("caption")
    if not caption and isinstance(spec.get("description"), str):
        caption = spec["description"].strip() or None
    if sources is None and existing is not None:
        sources = existing.get("sources")
    if relates_to is None and existing is not None:
        relates_to = existing.get("relates_to")
    if analysis is None and existing is not None:
        analysis = existing.get("analysis") or existing.get("source_analysis")
    record: dict[str, Any] = {
        "id": plot_id,
        "name": name,
        "spec": spec,
        "created_at": (existing or {}).get("created_at", now),
        "updated_at": now,
    }
    if origin:
        record["origin"] = origin
    if caption:
        record["caption"] = caption
    if isinstance(sources, list) and sources:
        record["sources"] = [str(s) for s in sources if s]
    if isinstance(relates_to, list) and relates_to:
        record["relates_to"] = [str(s) for s in relates_to if s]
    if analysis:
        record["analysis"] = str(analysis)
    atomicio.write_json_atomic(target, record)
    log.info("saved plot %s (%s)", plot_id, name)
    return record


def _stem_ref(raw: str) -> str:
    s = (raw or "").strip().strip("/")
    if s.startswith("wiki/"):
        s = s[5:]
    s = s.split("#", 1)[0]
    if s.endswith(".md"):
        s = s[:-3]
    return Path(s).name


def figure_page_markdown(plot: dict[str, Any], *, asset_name: str, today: str) -> str:
    """CE-shaped figure page: caption + provenance [[wikilinks]]."""
    name = str(plot.get("name") or plot.get("id") or "figure")
    caption = str(plot.get("caption") or "").strip()
    if not caption:
        spec = plot.get("spec") if isinstance(plot.get("spec"), dict) else {}
        caption = str(spec.get("description") or "").strip()
    origin = str(plot.get("origin") or "").strip()
    analysis = str(plot.get("analysis") or plot.get("source_analysis") or "").strip()
    sources = plot.get("sources") if isinstance(plot.get("sources"), list) else []
    relates = plot.get("relates_to") if isinstance(plot.get("relates_to"), list) else []
    relates_stems = [_stem_ref(str(r)) for r in relates if r]
    if origin:
        ostem = _stem_ref(origin)
        if ostem and ostem not in relates_stems and ostem != plot.get("id"):
            relates_stems.append(ostem)
    analysis_stem = _stem_ref(analysis) if analysis else ""
    source_stems = [_stem_ref(str(s)) for s in sources if s]

    fm_lines = [
        "---",
        f'title: "[fig] {name}"',
        "type: figure",
        "origin: created",
        f"asset: {asset_name}",
        f"created: {today}",
        f"updated: {today}",
        f"source: plot:{plot.get('id')}",
    ]
    if analysis_stem:
        fm_lines.append(f"source_analysis: {analysis_stem}")
    if origin:
        fm_lines.append(f"plot_origin: {origin}")
    if source_stems:
        fm_lines.append("sources: [" + ", ".join(source_stems) + "]")
    if relates_stems:
        fm_lines.append("relates_to: [" + ", ".join(relates_stems) + "]")
    fm_lines.append("---")

    body_bits = [
        f"![[figures/_assets/{asset_name}]]",
        "",
    ]
    if caption:
        body_bits.append(f"*{caption}*")
        body_bits.append("")
    prov: list[str] = []
    if analysis_stem:
        prov.append(f"from [[{analysis_stem}]]")
    if origin:
        ostem = _stem_ref(origin)
        if ostem and ostem != analysis_stem:
            prov.append(f"origin [[{ostem}]]")
    for st in source_stems:
        if st and st not in (analysis_stem,):
            prov.append(f"(vault:{st})" if "/" in str(st) or st.endswith(".extracted") else f"[[{st}]]")
    extra_links = [s for s in relates_stems if s and s not in (analysis_stem, _stem_ref(origin))]
    if extra_links:
        prov.append("related " + ", ".join(f"[[{s}]]" for s in extra_links))
    if prov:
        body_bits.append("— " + "; ".join(prov) + ".")
        body_bits.append("")
    body_bits.append(
        f"Created from plot `{plot.get('id')}` in `.workbench/plots/` on {today}."
    )
    return "\n".join(fm_lines) + "\n\n" + "\n".join(body_bits) + "\n"


def delete_plot(workspace: Path, plot_id: str) -> bool:
    p = _path(workspace, plot_id)
    if not p.is_file():
        return False
    p.unlink()
    return True
