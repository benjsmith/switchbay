"""Excalidraw scene templates for the slide-deck skill.

The agent doesn't author Excalidraw element JSON by hand — that's a
lot of boilerplate (id, version, versionNonce, seed, strokeColor,
fillStyle, …). Instead it picks a *layout* and supplies its slots
plus an optional accent colour. Each layout function below produces
a complete Excalidraw scene the SketchTab can mount and the user
can edit.

Design constraints (calibrated against Excalidraw's defaults so
slides remain user-editable without surprise):

  · **Use Excalidraw's stock colour palette only.** Five stroke
    colours are available in the toolbar — black, red, green, blue,
    orange. Layouts pick from these so the user can re-recolour an
    element without finding the original hex by hand. Background
    fills aren't used: rough strokes don't seal cleanly against
    filled regions and the result looks gappy.
  · **Use the hand-drawn font** (Excalifont / Virgil, font family
    1) — the deck looks like a sketch, not an office document, and
    the canvas's static raster matches the edit-mode font without
    the sub-pixel blur the Helvetica raster shows.
  · **White canvas across every slide.** Excalidraw's stock
    background swatches are all pale; saturated colour comes from
    the strokes (text + outlined shapes), never from the canvas.
  · **Hierarchy by size + accent, not by colour fields.** Title
    slides aren't dark-themed — they just use much larger text in
    the accent stroke colour. Section slides use a thick accent
    underline.
  · **Outlined shapes, no filled rectangles.** Cards / two-column
    cells are stroke-only with the accent colour as the outline.
  · **No accent line under titles.** Per the Anthropic pptx skill:
    that horizontal rule is an AI tell. Hierarchy is carried by
    type-size + the bullet markers.

Canvas convention: 960×540 working area. Real Excalidraw is
infinite; this is just the frame we lay text into so each slide's
PNG export reads as a 16:9 deck slide.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

CANVAS_W = 960
CANVAS_H = 540

# Excalidraw font-family ids. 1 = Excalifont / Virgil (the
# handwritten default). 2 = Helvetica. 3 = Cascadia (mono). The
# handwritten font is intentional: matches what the user sees when
# they open the canvas, doesn't look low-res in the static raster
# the way the Helvetica fallback does at small sizes.
FF_HANDWRITTEN = 1
FF_HELVETICA = 2
FF_MONO = 3

DEFAULT_FONT = FF_HANDWRITTEN


# ── Stock palette ───────────────────────────────────────────────────


# Exactly the five stroke colours that appear in Excalidraw's
# toolbar — black, red, green, blue, orange. Pinning to these
# means anything the agent paints can be re-coloured by the user
# without leaving the default palette.
COLORS: dict[str, str] = {
    "black":  "#1e1e1e",
    "red":    "#e03131",
    "green":  "#2f9e44",
    "blue":   "#1971c2",
    "orange": "#f08c00",
}

DEFAULT_ACCENT = "black"
CANVAS_BG = "#ffffff"


def color_for(name: str | None) -> str:
    """Resolve an accent name to a stock hex; falls back to black
    so callers never have to special-case missing input."""
    key = (name or "").strip().lower() or DEFAULT_ACCENT
    return COLORS.get(key, COLORS[DEFAULT_ACCENT])


# ── Element primitives ─────────────────────────────────────────────


def _text(
    text: str, x: float, y: float,
    *,
    w: float = 400, h: float = 40,
    font_size: int = 20, font_family: int = DEFAULT_FONT,
    color: str | None = None,
    align: str = "left",
    auto_resize: bool = False,
) -> dict[str, Any]:
    """One Excalidraw text element with sensible defaults.

    `color` accepts either a hex (used as-is) or None (falls back
    to plain black, the default stroke colour). Text always paints
    in the handwritten font unless the layout overrides it.

    `auto_resize` defaults to False so the element honours the
    `w` cap and wraps to multiple lines instead of marching off
    the right edge of the canvas. Set True for single-line slots
    where the content is short by contract (e.g., the big number
    on a stat slide).
    """
    eid = uuid.uuid4().hex[:16]
    seed = uuid.uuid4().int % (2**31)
    stroke = color or COLORS[DEFAULT_ACCENT]
    return {
        "type": "text",
        "version": 1,
        "versionNonce": uuid.uuid4().int % (2**31),
        "isDeleted": False,
        "id": eid,
        "fillStyle": "solid",
        "strokeWidth": 1,
        "strokeStyle": "solid",
        "roughness": 1,
        "opacity": 100,
        "angle": 0,
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "strokeColor": stroke,
        "backgroundColor": "transparent",
        "seed": seed,
        "groupIds": [],
        "frameId": None,
        "roundness": None,
        "boundElements": None,
        "updated": int(time.time() * 1000),
        "link": None,
        "locked": False,
        "fontSize": font_size,
        "fontFamily": font_family,
        "text": text,
        "textAlign": align,
        "verticalAlign": "top",
        "containerId": None,
        "originalText": text,
        "lineHeight": 1.25,
        "autoResize": auto_resize,
        "baseline": int(font_size * 0.85),
    }


def _line(
    x1: float, y1: float, x2: float, y2: float,
    *, color: str | None = None, stroke_width: float = 1.5,
    roughness: int = 1,
) -> dict[str, Any]:
    """Hand-drawn line. `roughness=1` matches the rest of the
    deck's wobble; pass 0 for a clean rule when needed (rare —
    the design conventions above call for almost no lines)."""
    eid = uuid.uuid4().hex[:16]
    seed = uuid.uuid4().int % (2**31)
    width = abs(x2 - x1)
    height = abs(y2 - y1)
    return {
        "type": "line",
        "version": 1,
        "versionNonce": uuid.uuid4().int % (2**31),
        "isDeleted": False,
        "id": eid,
        "fillStyle": "solid",
        "strokeWidth": stroke_width,
        "strokeStyle": "solid",
        "roughness": roughness,
        "opacity": 100,
        "angle": 0,
        "x": min(x1, x2),
        "y": min(y1, y2),
        "width": width,
        "height": height,
        "strokeColor": color or COLORS[DEFAULT_ACCENT],
        "backgroundColor": "transparent",
        "seed": seed,
        "groupIds": [],
        "frameId": None,
        "roundness": None,
        "boundElements": None,
        "updated": int(time.time() * 1000),
        "link": None,
        "locked": False,
        "startBinding": None,
        "endBinding": None,
        "lastCommittedPoint": None,
        "startArrowhead": None,
        "endArrowhead": None,
        "points": [[0, 0], [x2 - x1, y2 - y1]],
    }


def _rect_outline(
    x: float, y: float, w: float, h: float,
    *,
    stroke: str | None = None,
    stroke_width: float = 1.5,
    rounded: bool = True,
    roughness: int = 1,
) -> dict[str, Any]:
    """Outlined rectangle (no fill). Used for cards / two-column
    cells. We deliberately don't pass a `backgroundColor` because
    rough strokes don't close cleanly against fills and the output
    looks gappy."""
    eid = uuid.uuid4().hex[:16]
    seed = uuid.uuid4().int % (2**31)
    return {
        "type": "rectangle",
        "version": 1,
        "versionNonce": uuid.uuid4().int % (2**31),
        "isDeleted": False,
        "id": eid,
        "fillStyle": "solid",
        "strokeWidth": stroke_width,
        "strokeStyle": "solid",
        "roughness": roughness,
        "opacity": 100,
        "angle": 0,
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "strokeColor": stroke or COLORS[DEFAULT_ACCENT],
        "backgroundColor": "transparent",
        "seed": seed,
        "groupIds": [],
        "frameId": None,
        "roundness": {"type": 3} if rounded else None,
        "boundElements": None,
        "updated": int(time.time() * 1000),
        "link": None,
        "locked": False,
    }


def _ellipse_outline(
    cx: float, cy: float, r: float,
    *,
    stroke: str | None = None,
    stroke_width: float = 1.5,
    roughness: int = 1,
) -> dict[str, Any]:
    """Outlined circle. Used as bullet markers — no fill, just a
    small ring in the accent colour."""
    eid = uuid.uuid4().hex[:16]
    seed = uuid.uuid4().int % (2**31)
    return {
        "type": "ellipse",
        "version": 1,
        "versionNonce": uuid.uuid4().int % (2**31),
        "isDeleted": False,
        "id": eid,
        "fillStyle": "solid",
        "strokeWidth": stroke_width,
        "strokeStyle": "solid",
        "roughness": roughness,
        "opacity": 100,
        "angle": 0,
        "x": cx - r,
        "y": cy - r,
        "width": r * 2,
        "height": r * 2,
        "strokeColor": stroke or COLORS[DEFAULT_ACCENT],
        "backgroundColor": "transparent",
        "seed": seed,
        "groupIds": [],
        "frameId": None,
        "roundness": None,
        "boundElements": None,
        "updated": int(time.time() * 1000),
        "link": None,
        "locked": False,
    }


def _image(
    file_id: str,
    x: float, y: float, w: float, h: float,
) -> dict[str, Any]:
    """Excalidraw image element. Pair with a matching entry in
    scene ``files`` (dataURL). Client Excalidraw mounts these via
    initialData.files — same path as user-dragged images."""
    eid = uuid.uuid4().hex[:16]
    seed = uuid.uuid4().int % (2**31)
    return {
        "type": "image",
        "version": 1,
        "versionNonce": uuid.uuid4().int % (2**31),
        "isDeleted": False,
        "id": eid,
        "fillStyle": "solid",
        "strokeWidth": 1,
        "strokeStyle": "solid",
        "roughness": 0,
        "opacity": 100,
        "angle": 0,
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "strokeColor": "transparent",
        "backgroundColor": "transparent",
        "seed": seed,
        "groupIds": [],
        "frameId": None,
        "roundness": None,
        "boundElements": None,
        "updated": int(time.time() * 1000),
        "link": None,
        "locked": False,
        "fileId": file_id,
        "status": "saved",
        "scale": [1, 1],
    }


def _scene(
    elements: list[dict[str, Any]],
    *,
    name: str,
    background: str = CANVAS_BG,
    files: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "elements": elements,
        "appState": {
            "viewBackgroundColor": background,
            "name": name,
            "gridSize": None,
        },
        "files": files or {},
    }


# ── Layouts ─────────────────────────────────────────────────────────


def title_slide(
    title: str, subtitle: str | None = None,
    accent: str | None = None,
    palette: str | None = None,    # accepted-but-ignored alias
    image_dataurl: str | None = None,
    image_w: float | None = None,
    image_h: float | None = None,
) -> dict[str, Any]:
    """Cover slide. Big handwritten title in the accent colour,
    optional subtitle below in plain black. Optional PNG/JPEG under
    the subtitle via ``image_dataurl`` (Excalidraw files embed)."""
    a = color_for(accent)
    elements: list[dict[str, Any]] = []
    files: dict[str, Any] = {}
    # Shift title up slightly when an icon is present so the stack fits.
    title_y = 140 if image_dataurl else 170
    elements.append(_text(
        title, x=80, y=title_y, w=CANVAS_W - 160, h=88,
        font_size=64, color=a, align="left",
    ))
    sub_y = title_y + 120
    if subtitle:
        # Multi-line subtitles (and failed "ASCII icons") need room —
        # fixed h=44 used to clip anything past the first line.
        n_lines = max(1, str(subtitle).count("\n") + 1)
        sub_h = max(44, min(120, 22 * 1.25 * n_lines + 8))
        elements.append(_text(
            subtitle, x=80, y=sub_y, w=CANVAS_W - 160, h=sub_h,
            font_size=22, align="left",
        ))
        sub_y += sub_h + 16
    if image_dataurl:
        iw = float(image_w or 96)
        ih = float(image_h or 96)
        # Cap so a huge PNG doesn't blow the 16:9 frame.
        max_side = 160.0
        scale = min(1.0, max_side / max(iw, ih, 1.0))
        dw, dh = iw * scale, ih * scale
        fid = uuid.uuid4().hex[:16]
        files[fid] = {
            "mimeType": _mime_from_dataurl(image_dataurl),
            "id": fid,
            "dataURL": image_dataurl,
            "created": int(time.time() * 1000),
            "lastRetrieved": int(time.time() * 1000),
        }
        elements.append(_image(fid, x=80, y=sub_y, w=dw, h=dh))
    return _scene(elements, name=title, files=files)


def _mime_from_dataurl(dataurl: str) -> str:
    if dataurl.startswith("data:") and ";base64," in dataurl:
        return dataurl[5:].split(";", 1)[0] or "image/png"
    return "image/png"


def bullets_slide(
    title: str, bullets: list[str],
    accent: str | None = None,
    palette: str | None = None,
) -> dict[str, Any]:
    """Heading + bullet list. Bullets get a small outlined disc
    marker in the accent colour. Capped at 8; past that the slide
    is overstuffed and should split."""
    a = color_for(accent)
    capped = list(bullets[:8])
    elements: list[dict[str, Any]] = []
    elements.append(_text(
        title, x=64, y=48, w=CANVAS_W - 128, h=80,
        font_size=36, color=a, align="left",
    ))
    # Bullets get generous vertical spacing because wrapping is on
    # (auto_resize=False) and a two-line bullet would otherwise
    # collide with the next row. Slot heights are sized for 2 lines
    # at the chosen font; agents that keep bullets ≤ 8 words mostly
    # stay in 1 line.
    body_top = 140
    row_h = 56
    for i, bullet in enumerate(capped):
        y = body_top + i * row_h
        elements.append(_ellipse_outline(
            82, y + 12, 6,
            stroke=a, stroke_width=1.5,
        ))
        elements.append(_text(
            bullet,
            x=104, y=y,
            w=CANVAS_W - 168, h=row_h - 8,
            font_size=20, align="left",
        ))
    return _scene(elements, name=title)


def two_column_slide(
    title: str,
    left_title: str, left_items: list[str],
    right_title: str, right_items: list[str],
    accent: str | None = None,
    palette: str | None = None,
) -> dict[str, Any]:
    """Compare / contrast. Two outlined card-shaped rectangles
    side by side; headers in accent, body in plain black."""
    a = color_for(accent)
    elements: list[dict[str, Any]] = []
    elements.append(_text(
        title, x=64, y=48, w=CANVAS_W - 128, h=56,
        font_size=34, color=a, align="left",
    ))
    card_y = 130
    card_h = CANVAS_H - card_y - 50
    gap = 24
    card_w = (CANVAS_W - 128 - gap) / 2
    left_x = 64
    right_x = left_x + card_w + gap
    for x_, header, items in (
        (left_x, left_title, left_items),
        (right_x, right_title, right_items),
    ):
        elements.append(_rect_outline(
            x_, card_y, card_w, card_h,
            stroke=a, stroke_width=1.5,
        ))
        elements.append(_text(
            header, x=x_ + 18, y=card_y + 16, w=card_w - 36, h=36,
            font_size=22, color=a, align="left",
        ))
        # Same wrap-aware spacing trade-off as bullets_slide: items
        # wrap (auto_resize=False), so the row gap has to hold 2
        # lines of body text. Keep items ≤ 6 to fit the card height.
        item_row_h = 50
        for i, item in enumerate(items[:6]):
            elements.append(_text(
                f"·  {item}", x=x_ + 22, y=card_y + 60 + i * item_row_h,
                w=card_w - 44, h=item_row_h - 6,
                font_size=17, align="left",
            ))
    return _scene(elements, name=title)


def quote_slide(
    quote: str, attribution: str | None = None,
    accent: str | None = None,
    palette: str | None = None,
) -> dict[str, Any]:
    """Pull-quote. Outsized opening quote-mark in the accent
    colour sits behind the body; quote + attribution in plain
    handwritten."""
    a = color_for(accent)
    elements: list[dict[str, Any]] = []
    elements.append(_text(
        "“",
        x=70, y=80, w=200, h=200,
        font_size=200, color=a, align="left",
        auto_resize=True,
    ))
    elements.append(_text(
        quote,
        x=140, y=200, w=CANVAS_W - 220, h=140,
        font_size=30, align="left",
    ))
    if attribution:
        elements.append(_text(
            f"— {attribution}",
            x=140, y=380, w=CANVAS_W - 220, h=32,
            font_size=20, color=a, align="left",
        ))
    return _scene(elements, name=quote[:80])


def section_break_slide(
    label: str, subtitle: str | None = None,
    accent: str | None = None,
    palette: str | None = None,
) -> dict[str, Any]:
    """Section divider. Big label in the accent colour, with a
    short thick handwritten underline on the LEFT (not under the
    title). Subtitle below in plain handwritten."""
    a = color_for(accent)
    elements: list[dict[str, Any]] = []
    elements.append(_line(
        80, 232, 180, 232,
        color=a, stroke_width=4, roughness=1,
    ))
    elements.append(_text(
        label, x=80, y=246, w=CANVAS_W - 160, h=80,
        font_size=56, color=a, align="left",
    ))
    if subtitle:
        elements.append(_text(
            subtitle, x=80, y=336, w=CANVAS_W - 160, h=40,
            font_size=22, align="left",
        ))
    return _scene(elements, name=label)


def heading_paragraph_slide(
    title: str, body: str,
    accent: str | None = None,
    palette: str | None = None,
) -> dict[str, Any]:
    """Title + a paragraph (no bulleting) for prose-heavy slides
    where bullets would chop the argument unnaturally."""
    a = color_for(accent)
    elements: list[dict[str, Any]] = []
    elements.append(_text(
        title, x=64, y=56, w=CANVAS_W - 128, h=56,
        font_size=40, color=a, align="left",
    ))
    elements.append(_text(
        body, x=64, y=140, w=CANVAS_W - 128, h=CANVAS_H - 200,
        font_size=22, align="left",
    ))
    return _scene(elements, name=title)


def stat_slide(
    stat: str, label: str, context: str | None = None,
    accent: str | None = None,
    palette: str | None = None,
) -> dict[str, Any]:
    """Big-stat layout — one giant number in the accent colour,
    caption below in plain handwritten, optional context paragraph
    in plain handwritten further down."""
    a = color_for(accent)
    elements: list[dict[str, Any]] = []
    elements.append(_text(
        stat,
        x=64, y=130, w=CANVAS_W - 128, h=180,
        font_size=140, color=a, align="left",
        auto_resize=True,
    ))
    elements.append(_text(
        label,
        x=64, y=320, w=CANVAS_W - 128, h=44,
        font_size=28, align="left",
    ))
    if context:
        elements.append(_text(
            context,
            x=64, y=378, w=CANVAS_W - 128, h=80,
            font_size=18, align="left",
        ))
    return _scene(elements, name=label or stat)


def cards_slide(
    title: str, cards: list[dict[str, str]],
    accent: str | None = None,
    palette: str | None = None,
) -> dict[str, Any]:
    """Up to 4 outlined-only mini cards in a 2x2 grid. Header in
    accent, body in plain handwritten. No fill, no left-stripes —
    just the card outline + the type."""
    a = color_for(accent)
    capped = list(cards[:4])
    n = len(capped)
    elements: list[dict[str, Any]] = []
    elements.append(_text(
        title, x=64, y=48, w=CANVAS_W - 128, h=56,
        font_size=34, color=a, align="left",
    ))
    if n == 0:
        return _scene(elements, name=title)
    cols = 2 if n >= 2 else 1
    rows = 1 if n <= 2 else 2
    grid_x = 64
    grid_y = 132
    grid_w = CANVAS_W - 128
    grid_h = CANVAS_H - 132 - 40
    gap = 24
    cell_w = (grid_w - gap * (cols - 1)) / cols
    cell_h = (grid_h - gap * (rows - 1)) / rows
    for i, c in enumerate(capped):
        col = i % cols
        row = i // cols
        cx = grid_x + col * (cell_w + gap)
        cy = grid_y + row * (cell_h + gap)
        elements.append(_rect_outline(
            cx, cy, cell_w, cell_h,
            stroke=a, stroke_width=1.5,
        ))
        elements.append(_text(
            str(c.get("header") or ""),
            x=cx + 18, y=cy + 16, w=cell_w - 36, h=36,
            font_size=22, color=a, align="left",
        ))
        elements.append(_text(
            str(c.get("body") or ""),
            x=cx + 18, y=cy + 56, w=cell_w - 36, h=cell_h - 70,
            font_size=17, align="left",
        ))
    return _scene(elements, name=title)


# Layout dispatch — keyed by the value the agent passes in `layout`.
# Each entry: (function, list of slot names accepted by the function).
LAYOUTS: dict[str, tuple[Any, list[str]]] = {
    "title": (
        title_slide,
        ["title", "subtitle", "accent", "palette",
         "image_dataurl", "image_w", "image_h"],
    ),
    "bullets": (bullets_slide, ["title", "bullets", "accent", "palette"]),
    "two_column": (
        two_column_slide,
        ["title", "left_title", "left_items", "right_title", "right_items", "accent", "palette"],
    ),
    "quote": (quote_slide, ["quote", "attribution", "accent", "palette"]),
    "section": (section_break_slide, ["label", "subtitle", "accent", "palette"]),
    "paragraph": (heading_paragraph_slide, ["title", "body", "accent", "palette"]),
    "stat": (stat_slide, ["stat", "label", "context", "accent", "palette"]),
    "cards": (cards_slide, ["title", "cards", "accent", "palette"]),
}


def render_layout(layout: str, slots: dict[str, Any]) -> dict[str, Any]:
    """Public entry point. Raises KeyError on unknown layout, TypeError
    when a required slot is missing — callers translate those into the
    tool's `{ok: False, error: …}` response."""
    if layout not in LAYOUTS:
        raise KeyError(f"unknown layout: {layout}")
    fn, slot_names = LAYOUTS[layout]
    args = {k: slots.get(k) for k in slot_names}
    cleaned = {k: v for k, v in args.items() if v is not None}
    return fn(**cleaned)


def rasterize_scene_png(scene: dict[str, Any]) -> bytes:
    """Server-side raster of a slide-layouts scene.

    Excalidraw's canonical PNG is produced client-side via
    `exportToBlob` (rough.js stroke, Virgil handwritten font). We
    don't have that runtime in Python. This produces a clean
    Pillow render of the same scene — rectangles, ellipses, lines
    and wrapped text — so the deck doc's `<img src=figures/<id>.png>`
    references resolve as soon as `author_slide` returns, instead
    of showing broken-image placeholders until the user mounts each
    canvas. The Sketch tab's render-on-demand pass still overwrites
    this with the canonical Excalidraw raster the first time the
    user opens the slide.
    """
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (CANVAS_W, CANVAS_H), color=_hex(_bg_of(scene)))
    draw = ImageDraw.Draw(img)
    # Expose underlying image for image-element pastes.
    draw._image = img  # type: ignore[attr-defined]
    files = scene.get("files") if isinstance(scene.get("files"), dict) else {}
    for el in scene.get("elements") or []:
        if not isinstance(el, dict):
            continue
        if el.get("isDeleted"):
            continue
        _draw_element(draw, el, files=files)
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _bg_of(scene: dict[str, Any]) -> str:
    app = scene.get("appState") or {}
    bg = app.get("viewBackgroundColor")
    return bg if isinstance(bg, str) and bg else CANVAS_BG


def _hex(value: str) -> str:
    """Normalise to a Pillow-acceptable colour string."""
    if isinstance(value, str) and value:
        return value
    return "#ffffff"


_FONT_CACHE: dict[int, Any] = {}

# Glyphs that often tofu under narrow system fonts (Helvetica). Used
# as a last-resort rewrite when the chosen font still can't draw them.
_UNICODE_ASCII = str.maketrans({
    "\u2192": "->",   # →
    "\u2190": "<-",   # ←
    "\u2194": "<->",  # ↔
    "\u21d2": "=>",   # ⇒
    "\u2014": "--",   # em dash
    "\u2013": "-",    # en dash
    "\u2022": "*",    # bullet
    "\u00b7": "*",    # middle dot
    "\u2212": "-",    # minus
})


def _sanitize_draw_text(text: str) -> str:
    """ASCII-safe fallbacks for common typography that breaks narrow fonts."""
    return str(text or "").translate(_UNICODE_ASCII)


def _load_font(size: int):
    """Prefer wide Unicode coverage. Helvetica.ttc was first historically
    and produced tofu boxes for arrows (→) in agent-authored deck
    previews — the analysis page showed □ while Excalidraw looked fine.
    """
    from PIL import ImageFont
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    for path in (
        # macOS — broad Unicode (arrows, dashes, bullets)
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        # Linux / common packages
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        # Narrow last — missing many symbols
        "/System/Library/Fonts/Helvetica.ttc",
    ):
        try:
            font = ImageFont.truetype(path, size)
            _FONT_CACHE[size] = font
            return font
        except OSError:
            continue
    font = ImageFont.load_default()
    _FONT_CACHE[size] = font
    return font


def _wrap_text(text: str, font: Any, max_width: float) -> list[str]:
    """Greedy word-wrap to `max_width` px using the font's bbox."""
    out: list[str] = []
    for paragraph in str(text or "").split("\n"):
        words = paragraph.split(" ")
        cur = ""
        for word in words:
            trial = f"{cur} {word}".strip() if cur else word
            bbox = font.getbbox(trial)
            w = bbox[2] - bbox[0]
            if w <= max_width or not cur:
                cur = trial
            else:
                out.append(cur)
                cur = word
        out.append(cur)
    return out


def _draw_element(draw: Any, el: dict[str, Any], *, files: dict[str, Any] | None = None) -> None:
    t = el.get("type")
    try:
        x = float(el.get("x") or 0)
        y = float(el.get("y") or 0)
        w = float(el.get("width") or 0)
        h = float(el.get("height") or 0)
    except (TypeError, ValueError):
        return
    stroke = el.get("strokeColor") or "#1e1e1e"
    stroke_w = max(1, int(round(float(el.get("strokeWidth") or 1))))
    if t == "image":
        # Best-effort Pillow paste for deck PNG previews. Excalidraw
        # canvas still uses the dataURL files map client-side.
        fid = el.get("fileId")
        rec = (files or {}).get(fid) if fid else None
        dataurl = (rec or {}).get("dataURL") if isinstance(rec, dict) else None
        if isinstance(dataurl, str) and dataurl.startswith("data:") and w > 0 and h > 0:
            try:
                import base64
                import io
                from PIL import Image as PILImage
                b64 = dataurl.split(",", 1)[1]
                im = PILImage.open(io.BytesIO(base64.b64decode(b64))).convert("RGBA")
                im = im.resize((max(1, int(w)), max(1, int(h))), PILImage.Resampling.LANCZOS)
                # draw is ImageDraw on RGB parent — paste via the image
                # attribute when present.
                parent = getattr(draw, "_image", None) or getattr(draw, "im", None)
                if parent is not None and hasattr(parent, "paste"):
                    parent.paste(im, (int(x), int(y)), im)
            except Exception:  # noqa: BLE001
                draw.rectangle([x, y, x + w, y + h], outline="#888", width=1)
        return
    if t == "rectangle":
        draw.rectangle([x, y, x + w, y + h], outline=stroke, width=stroke_w)
        return
    if t == "ellipse":
        draw.ellipse([x, y, x + w, y + h], outline=stroke, width=stroke_w)
        return
    if t == "line" or t == "arrow":
        pts_raw = el.get("points") or [[0, 0], [w, h]]
        try:
            pts = [(x + float(p[0]), y + float(p[1])) for p in pts_raw]
        except (TypeError, ValueError):
            return
        if len(pts) >= 2:
            draw.line(pts, fill=stroke, width=stroke_w)
        return
    if t == "text":
        # Prefer Unicode-capable font; still rewrite exotic glyphs so a
        # fallback to Helvetica/default never shows tofu boxes on the
        # deck page while the Sketch tab (Virgil) looks fine.
        text = _sanitize_draw_text(el.get("text") or "")
        font_size = int(el.get("fontSize") or 20)
        font = _load_font(font_size)
        auto_resize = bool(el.get("autoResize", True))
        line_h = int(round(font_size * float(el.get("lineHeight") or 1.25)))
        lines = (
            text.split("\n") if auto_resize or w <= 0
            else _wrap_text(text, font, w)
        )
        for i, line in enumerate(lines):
            draw.text((x, y + i * line_h), line, fill=stroke, font=font)
        return


def display_name(scene: dict[str, Any], fallback: str = "Untitled slide") -> str:
    """Pull a human-readable slide name out of an authored scene —
    used as the sketch's `name` field when the agent doesn't supply
    one explicitly. Looks at appState.name first; falls back to the
    first text element; falls back to the supplied default."""
    app = scene.get("appState") or {}
    nm = app.get("name")
    if isinstance(nm, str) and nm.strip():
        return nm.strip()
    for el in scene.get("elements") or []:
        if el.get("type") == "text":
            t = el.get("text") or ""
            if isinstance(t, str) and t.strip():
                return t.strip().splitlines()[0][:60]
    return fallback
