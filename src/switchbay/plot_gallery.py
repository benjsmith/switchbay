"""Plot gallery: figure docs, extracted figures, and thumbnails.

Generated plots live in ``.workbench/plots/``. Each one is also a figure
page under ``wiki/figures/`` (title, caption, axis titles, series legend,
source script, data provenance). Figures extracted from source documents
are the other figure pages in that tree. The Library lists generated
plots only, and serves a cached thumbnail rather than the full image.

Axis titles and legend text are read from the Vega-Lite spec and, when
present, from matplotlib artist metadata. Nothing is read off the pixels.
"""

from __future__ import annotations

import io
import logging
import os
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from . import atomicio, plots

log = logging.getLogger("switchbay.plot_gallery")

THUMB_MAX = 176
ASSET_SIZE = (960, 540)
_PALETTE = (
    "#1d6996", "#38a6a5", "#0f8554", "#edad08",
    "#e17c05", "#cc503e", "#94346e", "#73af48",
)
_LEGEND_CHANNELS = ("color", "shape", "strokeDash", "size", "opacity")
_AXIS_CHANNELS = ("x", "y", "x2", "y2", "theta", "radius")
_FONT_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
)
_fonts: dict[int, ImageFont.ImageFont] = {}


def _unique(items: list[str], *, limit: int = 32) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        text = " ".join(str(raw).split())
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _text(value: Any) -> str:
    if value is None or value is False:
        return ""
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return " ".join(part for part in (_text(item) for item in value) if part)
    if isinstance(value, dict):
        if "text" in value:
            return _text(value.get("text"))
        return ""
    return ""


def _subtitle(value: Any) -> str:
    if isinstance(value, dict):
        return _text(value.get("subtitle"))
    return ""


def _rows(spec: dict[str, Any]) -> list[dict[str, Any]]:
    data = spec.get("data")
    if not isinstance(data, dict):
        return []
    values = data.get("values")
    if not isinstance(values, list):
        return []
    return [row for row in values if isinstance(row, dict)]


def _axis_title(channel: Any) -> str:
    if not isinstance(channel, dict):
        return ""
    axis = channel.get("axis")
    if isinstance(axis, dict):
        titled = _text(axis.get("title"))
        if titled:
            return titled
    return _text(channel.get("title"))


def _discrete(channel: dict[str, Any]) -> bool:
    kind = channel.get("type")
    return kind in (None, "nominal", "ordinal")


def _walk(spec: dict[str, Any], inherited: list[dict[str, Any]]) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    rows = _rows(spec) or inherited
    found = [(spec, rows)]
    for key in ("layer", "hconcat", "vconcat", "concat"):
        children = spec.get(key)
        if isinstance(children, list):
            for child in children:
                if isinstance(child, dict):
                    found.extend(_walk(child, rows))
    inner = spec.get("spec")
    if isinstance(inner, dict):
        found.extend(_walk(inner, rows))
    return found


def chart_text_from_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Titles, caption, axis titles, and legend text from a Vega-Lite spec."""
    if not isinstance(spec, dict):
        return {
            "title": "", "caption": "", "axis_titles": [],
            "legend_titles": [], "legend_entries": [],
        }
    title = ""
    caption = ""
    axes: list[str] = []
    legend_titles: list[str] = []
    entries: list[str] = []
    for unit, rows in _walk(spec, []):
        if not title:
            title = _text(unit.get("title"))
        if not caption:
            caption = _text(unit.get("description")) or _subtitle(unit.get("title"))
        encoding = unit.get("encoding")
        if not isinstance(encoding, dict):
            continue
        for key in _AXIS_CHANNELS:
            label = _axis_title(encoding.get(key))
            if label:
                axes.append(label)
        for key in _LEGEND_CHANNELS:
            channel = encoding.get(key)
            if not isinstance(channel, dict):
                continue
            if "legend" in channel and channel.get("legend") is None:
                continue
            field = channel.get("field")
            if not isinstance(field, str) or not field:
                continue
            legend = channel.get("legend") if isinstance(channel.get("legend"), dict) else {}
            legend_titles.append(_text(legend.get("title")) or field)
            if _discrete(channel):
                for row in rows:
                    if field in row and row[field] not in (None, ""):
                        entries.append(str(row[field]))
    return {
        "title": title,
        "caption": caption,
        "axis_titles": _unique(axes),
        "legend_titles": _unique(legend_titles),
        "legend_entries": _unique(entries, limit=24),
    }


def _artist_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split())
    getter = getattr(value, "get_text", None)
    if callable(getter):
        try:
            return _artist_text(getter())
        except Exception:  # noqa: BLE001 — artist objects are caller-supplied
            return ""
    return ""


def artist_dict_from_figure(fig: Any) -> dict[str, Any]:
    """Read title, axis labels, and legend entries off matplotlib artists.

    ``fig`` is duck-typed (``axes``, ``get_title`` / ``get_xlabel`` /
    ``get_ylabel``, ``get_legend``) so callers do not need matplotlib
    installed to pass a figure-shaped object.
    """
    titles: list[str] = []
    xlabels: list[str] = []
    ylabels: list[str] = []
    legend_titles: list[str] = []
    entries: list[str] = []
    sup = _artist_text(getattr(fig, "get_suptitle", lambda: "")())
    if sup:
        titles.append(sup)
    axes = getattr(fig, "axes", None) or []
    for ax in axes:
        title = _artist_text(ax.get_title() if hasattr(ax, "get_title") else "")
        xlabel = _artist_text(ax.get_xlabel() if hasattr(ax, "get_xlabel") else "")
        ylabel = _artist_text(ax.get_ylabel() if hasattr(ax, "get_ylabel") else "")
        if title:
            titles.append(title)
        if xlabel:
            xlabels.append(xlabel)
        if ylabel:
            ylabels.append(ylabel)
        legend = ax.get_legend() if hasattr(ax, "get_legend") else None
        if legend is None:
            continue
        legend_title = ""
        if hasattr(legend, "get_title"):
            legend_title = _artist_text(legend.get_title())
        if legend_title:
            legend_titles.append(legend_title)
        texts = legend.get_texts() if hasattr(legend, "get_texts") else []
        for item in texts or []:
            label = _artist_text(item)
            if label:
                entries.append(label)
    return {
        "title": titles[0] if titles else "",
        "xlabel": xlabels[0] if xlabels else "",
        "ylabel": ylabels[0] if ylabels else "",
        "xlabels": _unique(xlabels),
        "ylabels": _unique(ylabels),
        "legend_title": legend_titles[0] if legend_titles else "",
        "legend": _unique(entries, limit=24),
    }


def chart_text_from_artists(artists: dict[str, Any]) -> dict[str, Any]:
    axes: list[str] = []
    for key in ("xlabel", "ylabel"):
        if artists.get(key):
            axes.append(str(artists[key]))
    for key in ("xlabels", "ylabels"):
        for item in artists.get(key) or []:
            if item:
                axes.append(str(item))
    legend_title = str(artists.get("legend_title") or "").strip()
    return {
        "title": str(artists.get("title") or "").strip(),
        "caption": str(artists.get("caption") or "").strip(),
        "axis_titles": _unique(axes),
        "legend_titles": _unique([legend_title] if legend_title else []),
        "legend_entries": _unique(
            [str(item) for item in (artists.get("legend") or [])],
            limit=24,
        ),
    }


def _merge_text(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": base.get("title") or extra.get("title") or "",
        "caption": base.get("caption") or extra.get("caption") or "",
        "axis_titles": _unique(list(base.get("axis_titles") or []) + list(extra.get("axis_titles") or [])),
        "legend_titles": _unique(list(base.get("legend_titles") or []) + list(extra.get("legend_titles") or [])),
        "legend_entries": _unique(
            list(base.get("legend_entries") or []) + list(extra.get("legend_entries") or []),
            limit=24,
        ),
    }


def chart_text_for_record(plot: dict[str, Any]) -> dict[str, Any]:
    spec = plot.get("spec") if isinstance(plot.get("spec"), dict) else {}
    text = chart_text_from_spec(spec)
    artists = plot.get("artists")
    if isinstance(artists, dict):
        text = _merge_text(text, chart_text_from_artists(artists))
    if not text["title"]:
        text["title"] = str(plot.get("name") or "").strip()
    if not text["caption"]:
        text["caption"] = str(plot.get("caption") or "").strip()
    return text


def _read_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    head = text[4:end]
    body = text[end + 5:]
    fm: dict[str, Any] = {}
    cur_key: str | None = None
    cur_list: list[str] | None = None
    for raw in head.splitlines():
        if raw.startswith("  - ") and cur_list is not None and cur_key:
            cur_list.append(raw[4:].strip().strip("\"'"))
            continue
        if ":" in raw and not raw.startswith(" "):
            key, _, val = raw.partition(":")
            cur_key = key.strip()
            val = val.strip()
            if val.startswith("[") and val.endswith("]"):
                items = [part.strip().strip("\"'") for part in val[1:-1].split(",")]
                fm[cur_key] = [part for part in items if part]
                cur_list = None
            elif val == "":
                cur_list = []
                fm[cur_key] = cur_list
            else:
                fm[cur_key] = val.strip("\"'")
                cur_list = None
    return fm, body


def _figure_markdown_paths(workspace: Path) -> list[Path]:
    root = workspace / "wiki" / "figures"
    if not root.is_dir():
        return []
    found: list[Path] = []
    for path in root.rglob("*.md"):
        parts = path.relative_to(root).parts
        if any(part.startswith("_") for part in parts):
            continue
        found.append(path)
    return found


def _plot_doc_index(workspace: Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for path in _figure_markdown_paths(workspace):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        fm, _body = _read_frontmatter(text)
        source = str(fm.get("source") or "").strip()
        if source.startswith("plot:"):
            plot_id = source[5:].strip()
            if plot_id:
                index[plot_id] = path
    return index


def _rel(workspace: Path, path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return path.resolve().relative_to(workspace.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _load_plots(workspace: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for meta in plots.list_plots(workspace):
        rec = plots.get_plot(workspace, str(meta.get("id") or ""))
        if isinstance(rec, dict):
            records.append(rec)
    return records


def _asset_file(workspace: Path, asset_name: str) -> Path:
    name = Path(asset_name).name
    return workspace / "wiki" / "figures" / "_assets" / name


def _font(size: int) -> ImageFont.ImageFont:
    cached = _fonts.get(size)
    if cached is not None:
        return cached
    font: ImageFont.ImageFont | None = None
    for path in _FONT_PATHS:
        if os.path.isfile(path):
            try:
                font = ImageFont.truetype(path, size=size)
                break
            except OSError:
                continue
    if font is None:
        font = ImageFont.load_default()
    _fonts[size] = font
    return font


def _mark(spec: dict[str, Any]) -> str:
    mark = spec.get("mark")
    if isinstance(mark, dict):
        mark = mark.get("type")
    return str(mark or "line")


def _series(spec: dict[str, Any]) -> tuple[str, list[tuple[str, list[tuple[Any, float]]]]]:
    """Return (mark, [(series name, [(x, y), ...])])."""
    units = _walk(spec if isinstance(spec, dict) else {}, [])
    chosen: tuple[dict[str, Any], list[dict[str, Any]]] | None = None
    for unit, rows in units:
        encoding = unit.get("encoding")
        if isinstance(encoding, dict) and rows:
            chosen = (unit, rows)
            break
    if chosen is None:
        return "line", []
    unit, rows = chosen
    encoding = unit["encoding"]
    xch = encoding.get("x") if isinstance(encoding.get("x"), dict) else {}
    ych = encoding.get("y") if isinstance(encoding.get("y"), dict) else {}
    cch = encoding.get("color") if isinstance(encoding.get("color"), dict) else {}
    xf = xch.get("field")
    yf = ych.get("field")
    cf = cch.get("field") if isinstance(cch.get("field"), str) else ""
    groups: dict[str, list[tuple[Any, float]]] = {}
    for row in rows:
        if not isinstance(yf, str):
            continue
        try:
            y = float(row.get(yf))
        except (TypeError, ValueError):
            continue
        x = row.get(xf) if isinstance(xf, str) else len(groups.get("", []))
        key = str(row.get(cf)) if cf and row.get(cf) not in (None, "") else ""
        groups.setdefault(key, []).append((x, y))
    ordered = [(name, pts) for name, pts in groups.items() if pts]
    return _mark(unit), ordered


def render_chart_png(plot: dict[str, Any], *, width: int, height: int) -> bytes:
    """Draw a small chart from the spec. Used for the wiki asset and thumbs."""
    width = max(32, int(width))
    height = max(32, int(height))
    image = Image.new("RGB", (width, height), "#fbfcfe")
    draw = ImageDraw.Draw(image)
    info = chart_text_for_record(plot)
    title = str(info.get("title") or plot.get("name") or "Plot")
    title_size = 18 if width >= 480 else 11
    label_size = 13 if width >= 480 else 9
    title_font = _font(title_size)
    label_font = _font(label_size)
    draw.text((16, 10), title[:80], fill="#1a1d22", font=title_font)
    legend_w = 150 if width >= 480 else 0
    left, top = (58 if width >= 480 else 16), 36 if width >= 480 else 26
    right = width - 16 - legend_w
    bottom = height - (36 if width >= 480 else 18)
    if right - left < 20 or bottom - top < 20:
        left, top, right, bottom = 8, 22, width - 8, height - 8
    draw.rectangle((left, top, right, bottom), outline="#d5d9e0", width=1)
    mark, series = _series(plot.get("spec") if isinstance(plot.get("spec"), dict) else {})
    ys = [y for _name, pts in series for _x, y in pts]
    if not ys:
        draw.line((left, bottom, right, top + 8), fill=_PALETTE[0], width=2)
    else:
        ymin, ymax = min(ys), max(ys)
        if mark in {"bar", "rect"}:
            ymin = min(ymin, 0)
            ymax = max(ymax, 0)
        if ymin == ymax:
            ymin -= 1
            ymax += 1
        pad = (ymax - ymin) * 0.08
        ymin -= pad
        ymax += pad
        xs_raw = [x for _name, pts in series for x, _y in pts]
        numeric_x = True
        xnums: list[float] = []
        for x in xs_raw:
            try:
                xnums.append(float(x))
            except (TypeError, ValueError):
                numeric_x = False
                break
        cats: list[Any] = []
        if not numeric_x:
            for x in xs_raw:
                if x not in cats:
                    cats.append(x)

        def x_pos(x: Any, index: int, count: int) -> float:
            span = max(1, right - left)
            if numeric_x and xnums:
                lo, hi = min(xnums), max(xnums)
                if hi == lo:
                    return left + span / 2
                return left + (float(x) - lo) / (hi - lo) * span
            if count <= 1:
                return (left + right) / 2
            slot = cats.index(x) if x in cats else index
            return left + (slot + 0.5) / max(1, len(cats)) * span

        def y_pos(y: float) -> float:
            return bottom - (y - ymin) / (ymax - ymin) * (bottom - top)

        for idx, (name, pts) in enumerate(series):
            color = _PALETTE[idx % len(_PALETTE)]
            coords = [(x_pos(x, i, len(pts)), y_pos(y)) for i, (x, y) in enumerate(pts)]
            if mark in {"bar", "rect"}:
                nseries = max(1, len(series))
                cat_count = max(1, len(cats) if cats else len(coords))
                group = (right - left) / cat_count
                bar_w = max(2.0, group / (nseries + 1))
                offset = (idx - (nseries - 1) / 2) * bar_w
                for cx, cy in coords:
                    draw.rectangle(
                        (cx + offset - bar_w / 2, cy, cx + offset + bar_w / 2, bottom),
                        fill=color,
                    )
            elif len(coords) == 1:
                cx, cy = coords[0]
                r = 4 if width >= 480 else 2
                draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
            else:
                draw.line(coords, fill=color, width=2 if width >= 480 else 1)
                if mark in {"point", "circle"} or len(coords) < 8:
                    r = 3 if width >= 480 else 2
                    for cx, cy in coords:
                        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
            if legend_w and name and idx < 8:
                ly = top + idx * 18
                draw.rectangle((right + 18, ly, right + 30, ly + 10), fill=color)
                draw.text((right + 36, ly - 2), name[:16], fill="#3a3f47", font=label_font)
    axes = list(info.get("axis_titles") or [])
    if width >= 480 and axes:
        draw.text((left, height - 24), str(axes[0])[:40], fill="#5a6068", font=label_font)
        if len(axes) > 1:
            draw.text((8, top), str(axes[1])[:22], fill="#5a6068", font=label_font)
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _write_asset(workspace: Path, plot: dict[str, Any], asset_name: str) -> Path:
    dest = _asset_file(workspace, asset_name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    dest.write_bytes(render_chart_png(plot, width=ASSET_SIZE[0], height=ASSET_SIZE[1]))
    return dest


def ensure_figure_doc(
    workspace: Path,
    plot: dict[str, Any],
    *,
    index: dict[str, Path] | None = None,
) -> Path | None:
    """Write the figure page for a generated plot when one is not there yet.

    A page with ``source: plot:<id>`` and ``managed: true`` is refreshed
    from the current spec. A page the user has taken over (no managed
    flag) is left as written.
    """
    plot_id = str(plot.get("id") or "").strip()
    if not plot_id:
        return None
    if index is None:
        index = _plot_doc_index(workspace)
    today = time.strftime("%Y-%m-%d", time.gmtime())
    existing = index.get(plot_id)
    if existing is not None and existing.is_file():
        try:
            fm, _body = _read_frontmatter(existing.read_text(encoding="utf-8"))
        except OSError:
            fm = {}
        if str(fm.get("managed") or "").lower() != "true":
            return existing
        created = str(fm.get("created") or today)
        asset = str(fm.get("asset") or f"{existing.stem}.png")
        markdown = plots.figure_page_markdown(
            plot, asset_name=Path(asset).name, today=today, created=created,
        )
        atomicio.write_text_atomic(existing, markdown)
        _write_asset(workspace, plot, Path(asset).name)
        return existing
    slug = plots._slugify(str(plot.get("name") or plot_id))
    figures = workspace / "wiki" / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    path = figures / f"{slug}.md"
    if path.exists():
        path = figures / f"{slug}-{plots._slugify(plot_id)}.md"
    asset = f"{path.stem}.png"
    markdown = plots.figure_page_markdown(plot, asset_name=asset, today=today)
    atomicio.write_text_atomic(path, markdown)
    _write_asset(workspace, plot, asset)
    index[plot_id] = path
    return path


def backfill_figure_docs(workspace: Path) -> list[str]:
    """Create figure pages for generated plots that do not have one yet."""
    index = _plot_doc_index(workspace)
    created: list[str] = []
    for plot in _load_plots(workspace):
        plot_id = str(plot.get("id") or "")
        had = plot_id in index and index[plot_id].is_file()
        path = ensure_figure_doc(workspace, plot, index=index)
        if path is not None and not had:
            created.append(plot_id)
    return created


def apply_matplotlib_figure(workspace: Path, plot_id: str, fig: Any) -> dict[str, Any]:
    """Store matplotlib artist text on a plot and refresh its figure page."""
    rec = plots.get_plot(workspace, plot_id)
    if rec is None:
        raise ValueError(f"unknown plot {plot_id}")
    rec["artists"] = artist_dict_from_figure(fig)
    rec["updated_at"] = time.time()
    atomicio.write_json_atomic(plots._path(workspace, plot_id), rec)
    ensure_figure_doc(workspace, rec)
    return rec


def _caption_from_body(body: str) -> str:
    lines: list[str] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("![") or line.startswith("Source script:"):
            if lines:
                break
            continue
        if line.startswith("**") or line.startswith("—") or line.startswith("Created from plot"):
            break
        lines.append(line)
        if len(" ".join(lines)) > 400:
            break
    text = " ".join(lines).strip()
    if text.startswith("*") and text.endswith("*") and len(text) > 2:
        text = text.strip("*").strip()
    return text[:500]


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return _unique([str(item) for item in value])
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def list_extracted_figures(workspace: Path) -> list[dict[str, Any]]:
    """Figure pages that were not written from a workspace plot."""
    out: list[dict[str, Any]] = []
    for path in _figure_markdown_paths(workspace):
        try:
            text = path.read_text(encoding="utf-8")[:65536]
        except OSError:
            continue
        fm, body = _read_frontmatter(text)
        source = str(fm.get("source") or "").strip()
        if source.startswith("plot:"):
            continue
        kind = str(fm.get("type") or "figure").strip().lower()
        if kind and kind != "figure":
            continue
        rel = path.relative_to(workspace / "wiki" / "figures").as_posix()
        figure_id = rel[:-3] if rel.endswith(".md") else rel
        title = str(fm.get("title") or path.stem).strip() or path.stem
        asset = str(fm.get("asset") or "").strip()
        image = f"/figures/{asset.lstrip('/')}" if asset else ""
        if not image:
            for token in ("![[", "]("):
                if token in body and ".png" in body:
                    start = body.find("figures/")
                    if start >= 0:
                        end = start
                        while end < len(body) and body[end] not in "])|\n ":
                            end += 1
                        image = "/" + body[start:end].lstrip("/")
                        if image.startswith("/figures/"):
                            break
                        image = ""
        axes = _string_list(fm.get("axis_titles"))
        for key, label in (("x_title", None), ("y_title", None), ("xlabel", None), ("ylabel", None)):
            if fm.get(key):
                axes.append(str(fm[key]))
        legend_entries = _string_list(fm.get("legend") or fm.get("series"))
        legend_titles = _string_list(fm.get("legend_titles") or fm.get("legend_title"))
        out.append({
            "id": figure_id,
            "title": title,
            "caption": _caption_from_body(body),
            "axis_titles": _unique(axes),
            "legend_titles": legend_titles,
            "legend_entries": legend_entries,
            "image": image,
            "path": _rel(workspace, path),
            "updated_at": path.stat().st_mtime,
        })
    out.sort(key=lambda item: item.get("updated_at") or 0, reverse=True)
    return out


def _plot_entry(workspace: Path, plot: dict[str, Any], index: dict[str, Path]) -> dict[str, Any]:
    info = chart_text_for_record(plot)
    plot_id = str(plot.get("id") or "")
    doc = index.get(plot_id)
    return {
        "id": plot_id,
        "name": plot.get("name") or plot_id,
        "origin": plot.get("origin"),
        "created_at": plot.get("created_at"),
        "updated_at": plot.get("updated_at"),
        "title": info.get("title") or plot.get("name") or plot_id,
        "caption": info.get("caption") or "",
        "axis_titles": list(info.get("axis_titles") or []),
        "legend_titles": list(info.get("legend_titles") or []),
        "legend_entries": list(info.get("legend_entries") or []),
        "thumb": f"/api/plots/{plot_id}/thumb",
        "figure_path": _rel(workspace, doc),
    }


def gallery(workspace: Path) -> dict[str, Any]:
    """Plots plus extracted figures, with the text the Plots tab searches."""
    index = _plot_doc_index(workspace)
    return {
        "plots": [_plot_entry(workspace, plot, index) for plot in _load_plots(workspace)],
        "extracted": list_extracted_figures(workspace),
    }


def library_items(workspace: Path) -> list[dict[str, Any]]:
    """Generated plots for the Library. Thumbnails are the small cached URL."""
    index = _plot_doc_index(workspace)
    items: list[dict[str, Any]] = []
    for plot in _load_plots(workspace):
        entry = _plot_entry(workspace, plot, index)
        items.append({
            "kind": "plot",
            "slug": entry["id"],
            "title": entry["title"],
            "summary": entry["caption"],
            "path": f".workbench/plots/{entry['id']}.json",
            "updated_at": entry.get("updated_at") or 0,
            "thumbs": [entry["thumb"]],
            "n_thumbs": 1,
            "figure_path": entry.get("figure_path") or "",
            "axis_titles": entry.get("axis_titles") or [],
            "legend_titles": entry.get("legend_titles") or [],
            "legend_entries": entry.get("legend_entries") or [],
        })
    return items


def figure_doc_for_plot(workspace: Path, plot_id: str) -> dict[str, Any] | None:
    try:
        rec = plots.get_plot(workspace, plot_id)
    except ValueError:
        return None
    if rec is None:
        return None
    path = _plot_doc_index(workspace).get(plot_id)
    if path is None or not path.is_file():
        return None
    try:
        markdown = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return {
        "id": plot_id,
        "path": _rel(workspace, path),
        "markdown": markdown,
    }


def _downscale_png(data: bytes, max_edge: int) -> bytes:
    with Image.open(io.BytesIO(data)) as image:
        frame = image.convert("RGB")
        frame.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        frame.save(buf, format="PNG", optimize=True)
        return buf.getvalue()


def _asset_for_plot(workspace: Path, plot: dict[str, Any], index: dict[str, Path]) -> Path | None:
    plot_id = str(plot.get("id") or "")
    doc = index.get(plot_id)
    asset_name = ""
    if doc is not None and doc.is_file():
        try:
            fm, _body = _read_frontmatter(doc.read_text(encoding="utf-8"))
        except OSError:
            fm = {}
        asset_name = str(fm.get("asset") or "")
    if not asset_name:
        asset_name = f"{plots._slugify(str(plot.get('name') or plot_id))}.png"
    path = _asset_file(workspace, asset_name)
    return path if path.is_file() else None


def thumbnail_bytes(workspace: Path, plot_id: str) -> bytes | None:
    """Cached thumbnail for a generated plot. Never the full-size asset."""
    try:
        plot = plots.get_plot(workspace, plot_id)
    except ValueError:
        return None
    if plot is None:
        return None
    thumb = plots._dir(workspace) / "thumbs" / f"{plot_id}.png"
    plot_path = plots._path(workspace, plot_id)
    index = _plot_doc_index(workspace)
    asset = _asset_for_plot(workspace, plot, index)
    newest = plot_path.stat().st_mtime if plot_path.is_file() else 0
    use_asset = False
    if asset is not None:
        asset_mtime = asset.stat().st_mtime
        use_asset = asset_mtime + 1e-3 >= newest
        newest = max(newest, asset_mtime)
    if (
        thumb.is_file()
        and thumb.stat().st_size > 0
        and thumb.stat().st_mtime >= newest
    ):
        return thumb.read_bytes()
    if use_asset and asset is not None:
        data = _downscale_png(asset.read_bytes(), THUMB_MAX)
    else:
        data = render_chart_png(plot, width=THUMB_MAX, height=int(THUMB_MAX * 9 / 16))
    thumb.parent.mkdir(parents=True, exist_ok=True)
    thumb.write_bytes(data)
    return data
