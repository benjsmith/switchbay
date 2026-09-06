"""High-quality HTML slideshow builder (provider-agnostic).

Slideshows are the product's only presentation surface. They are
self-contained HTML packages under
``slideshows/<slug>/``, opened in the Slideshow tab, wikilinked as
``[[slideshow:slug|title]]``.

Design system is adapted from ``docs/intro_and_bench.html`` (the Claude-
authored product deck) plus the same visual QA bar as the pptx skill:
bold palette, typed hierarchy, cards/panels, no plain bullet dumps,
every slide has a visual anchor.

Callers (media pipeline, future rail tools) supply *content* only —
structure and CSS always come from here so quality does not depend on
which LLM wrote the copy.
"""

from __future__ import annotations

import html as html_lib
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from . import atomicio, html_decks, slide_charts

log = logging.getLogger("switchbay.slideshow_html")

_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:\|([^\]]+))?\]\]")
_MD_TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
_MD_TABLE_SEP = re.compile(r"^:?-+:?$")
_META_CLOSE_RE = re.compile(
    r"^\s*(topics?|spine|table|wiki[_ ]topics?)\s*:", re.I,
)
# Ingest punch-lists and "what the deck still needs" — not a story slide.
_BACKLOG_RE = re.compile(
    r"\b("
    r"still missing|remaining gaps?|never ingested|"
    r"not this story|do not invent|"
    r"skipped as (?:needing )?review|"
    r"original PDF is still missing|"
    r"what else (?:the deck |it )?needs|"
    r"to complete this deck|"
    r"further exploration possible"
    r")\b",
    re.I,
)
_TBL_LINK_RE = re.compile(
    r"\[\[\s*((?:wiki/tables/)?tbl-[^\]|#]+)", re.I,
)

# Re-export storage helpers under slideshow naming for callers.
slideshows_root = html_decks.decks_root  # will point at slideshows/
ensure_slideshow = html_decks.ensure_deck
list_slideshows = html_decks.list_decks
wiki_link = html_decks.wiki_link_markdown


def _e(s: str) -> str:
    return html_lib.escape(s or "", quote=True)


def display_text(s: str) -> str:
    """Show wiki links as their label or stem, not ``[[slug]]``."""
    def _sub(m: re.Match[str]) -> str:
        label = (m.group(2) or "").strip()
        if label:
            return label
        return Path(str(m.group(1) or "").strip()).name
    return _WIKILINK_RE.sub(_sub, s or "")


def parse_markdown_table(text: str) -> dict[str, Any] | None:
    """First GitHub-style table in ``text`` → ``{columns, rows}``."""
    rows: list[list[str]] = []
    for line in (text or "").splitlines():
        m = _MD_TABLE_ROW.match(line)
        if not m:
            if rows:
                break
            continue
        cells = [c.strip() for c in m.group(1).split("|")]
        if cells and all(_MD_TABLE_SEP.match(c.replace(" ", "")) for c in cells):
            continue
        rows.append(cells)
    if len(rows) < 2:
        return None
    width = max(len(r) for r in rows)
    padded = [r + [""] * (width - len(r)) for r in rows]
    return {"columns": padded[0], "rows": padded[1:]}


def load_wiki_table(workspace: Path, ref: str) -> dict[str, Any] | None:
    """Read a CE ``wiki/tables/tbl-*.md`` (or stem) into columns/rows."""
    raw = str(ref or "").strip()
    if not raw:
        return None
    raw = raw.replace("\\", "/").strip("/")
    raw = _WIKILINK_RE.sub(lambda m: (m.group(1) or "").strip(), raw)
    stem = Path(raw).stem
    if not stem.startswith("tbl-"):
        stem = f"tbl-{stem}"
    name = Path(raw).name
    candidates = [
        Path(workspace) / raw,
        Path(workspace) / f"{raw}.md",
        Path(workspace) / "wiki" / raw,
        Path(workspace) / "wiki" / f"{raw}.md",
        Path(workspace) / "wiki" / "tables" / f"{stem}.md",
        Path(workspace) / "wiki" / "tables" / name,
        Path(workspace) / "wiki" / "tables" / f"{name}.md",
    ]
    seen: set[Path] = set()
    for p in candidates:
        try:
            rp = p.resolve()
        except OSError:
            continue
        if rp in seen or not rp.is_file():
            continue
        seen.add(rp)
        try:
            body = rp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        parsed = parse_markdown_table(body)
        if parsed:
            parsed["source"] = str(rp.relative_to(Path(workspace).resolve()))
            return parsed
    return None


def _slide_table_view(
    columns: list[str], rows: list[list[str]], *, max_cols: int = 4,
) -> tuple[list[str], list[list[str]]]:
    """Keep a readable subset of a wide wiki table for 16:9."""
    if len(columns) <= max_cols:
        return columns, rows
    lower = [c.casefold().strip() for c in columns]
    keep: list[int] = []
    for want in ("act", "name", "vault-backed number", "number", "metric"):
        if want in lower and lower.index(want) not in keep:
            keep.append(lower.index(want))
    if len(keep) < 3:
        keep = list(range(max_cols))
    keep = keep[:max_cols]
    return (
        [columns[i] for i in keep],
        [[(r[i] if i < len(r) else "") for i in keep] for r in rows],
    )


def _table_from_slide(s: dict[str, Any]) -> tuple[list[str], list[list[str]]]:
    table = s.get("table")
    columns: list[str] = []
    rows: list[list[str]] = []
    if isinstance(table, dict):
        columns = [str(c) for c in (table.get("columns") or table.get("headers") or [])]
        raw_rows = table.get("rows") or []
        for r in raw_rows:
            if isinstance(r, dict):
                keys = columns or [str(k) for k in r.keys()]
                if not columns:
                    columns = keys
                rows.append([str(r.get(k, "")) for k in columns])
            elif isinstance(r, (list, tuple)):
                rows.append([str(c) for c in r])
            else:
                rows.append([str(r)])
    elif isinstance(table, str):
        parsed = parse_markdown_table(table)
        if parsed:
            columns = [str(c) for c in parsed["columns"]]
            rows = [[str(c) for c in r] for r in parsed["rows"]]
    if not columns and s.get("columns"):
        columns = [str(c) for c in s.get("columns") or []]
    if not rows and s.get("rows"):
        for r in s.get("rows") or []:
            if isinstance(r, (list, tuple)):
                rows.append([str(c) for c in r])
    return columns, rows


def _table_html(columns: list[str], rows: list[list[str]]) -> str:
    if not columns and not rows:
        return ""
    head = ""
    if columns:
        cells = "".join(f"<th>{_e(display_text(c))}</th>" for c in columns)
        head = f"<thead><tr>{cells}</tr></thead>"
    body_rows = []
    width = len(columns) if columns else max((len(r) for r in rows), default=0)
    for r in rows:
        padded = list(r) + [""] * max(0, width - len(r))
        tds = "".join(f"<td>{_e(display_text(c))}</td>" for c in padded[:width])
        body_rows.append(f"<tr>{tds}</tr>")
    body = f"<tbody>{''.join(body_rows)}</tbody>" if body_rows else ""
    return f'<div class="sheet-wrap"><table class="sheet">{head}{body}</table></div>'


def slide_is_empty(s: dict[str, Any]) -> bool:
    heading = str(s.get("heading") or "").strip()
    lede = str(s.get("lede") or "").strip()
    media = str(s.get("media") or "").strip()
    bullets = s.get("bullets") or []
    cards = s.get("cards") or []
    cols, rows = _table_from_slide(s)
    return not (
        heading or lede or media or bullets or cards or cols or rows
        or str(s.get("image_prompt") or "").strip()
        or str(s.get("figure") or s.get("wiki_table") or "").strip()
        or str(s.get("quote") or "").strip()
        or s.get("stats") or s.get("chart") or s.get("steps")
        or s.get("left") or s.get("right")
    )


def _is_metadata_line(line: str) -> bool:
    t = str(line or "").strip()
    if not t:
        return True
    if _META_CLOSE_RE.match(t):
        return True
    inner = _WIKILINK_RE.sub("", t).strip(" :·-|")
    return not inner


def _slide_prose_blob(s: dict[str, Any]) -> str:
    parts = [
        str(s.get("heading") or ""),
        str(s.get("lede") or ""),
        str(s.get("cite") or ""),
        str(s.get("quote") or ""),
    ]
    for b in s.get("bullets") or []:
        parts.append(str(b))
    return " ".join(parts)


def slide_is_backlog(s: dict[str, Any]) -> bool:
    """True when the slide is a wiki/ingest punch-list, not the story."""
    return bool(_BACKLOG_RE.search(_slide_prose_blob(s)))


def _strip_backlog_bullets(s: dict[str, Any]) -> dict[str, Any]:
    item = dict(s)
    bullets = item.get("bullets")
    if isinstance(bullets, list):
        kept = [b for b in bullets if not _BACKLOG_RE.search(str(b))]
        if len(kept) != len(bullets):
            item["bullets"] = kept
    return item


def slide_is_metadata_dump(s: dict[str, Any]) -> bool:
    """True when the only prose is Topics/Spine/Table wiki stubs."""
    lede = str(s.get("lede") or "").strip()
    if lede and not _is_metadata_line(lede):
        return False
    cards = s.get("cards") or []
    if cards:
        return False
    cols, rows = _table_from_slide(s)
    if cols or rows:
        return False
    if str(s.get("media") or "").strip():
        return False
    if str(s.get("quote") or "").strip() or s.get("stats") or s.get("chart"):
        return False
    bullets = [str(b) for b in (s.get("bullets") or []) if str(b).strip()]
    if not bullets:
        return bool(lede)
    return all(_is_metadata_line(b) for b in bullets)


def _tbl_refs_in(s: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    explicit = str(s.get("wiki_table") or "").strip()
    if explicit:
        refs.append(explicit)
    blob_parts = [str(s.get("lede") or ""), str(s.get("cite") or "")]
    for b in s.get("bullets") or []:
        blob_parts.append(str(b))
    blob = "\n".join(blob_parts)
    for m in _TBL_LINK_RE.finditer(blob):
        refs.append(m.group(1).strip())
    out: list[str] = []
    seen: set[str] = set()
    for r in refs:
        key = r.casefold()
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def normalize_slide(
    s: dict[str, Any],
    *,
    deck_title: str,
    index: int,
) -> dict[str, Any] | None:
    """Repair empty layouts. Returns None when the slide should be dropped."""
    item = dict(s)
    layout = str(item.get("layout") or "bullets").strip() or "bullets"
    heading = str(item.get("heading") or "").strip()
    if not heading:
        if index == 0 or layout == "title":
            heading = deck_title
            layout = "title"
        elif item.get("eyebrow"):
            heading = str(item.get("eyebrow") or "").strip()
        elif item.get("cards") and isinstance(item["cards"][0], dict):
            heading = str(item["cards"][0].get("title") or "").strip() or heading
        elif item.get("bullets"):
            heading = heading or "Key points"
        item["heading"] = heading
    item["layout"] = layout
    item = _strip_backlog_bullets(item)
    if slide_is_backlog(item):
        return None
    media = str(item.get("media") or "").strip()
    cols, rows = _table_from_slide(item)
    bullets = item.get("bullets") or []
    cards = item.get("cards") or []
    if layout == "split" and not media and not cols and not str(item.get("figure") or ""):
        item["layout"] = "bullets" if bullets or cards else layout
        layout = item["layout"]
    if layout == "media" and not media and not str(item.get("figure") or item.get("image_prompt") or ""):
        if bullets or cards or cols:
            item["layout"] = "table" if cols else ("cards" if cards else "bullets")
        else:
            return None
    if layout == "split" and not media and not bullets and not cards and not cols:
        return None
    if slide_is_empty(item) and not str(item.get("wiki_table") or item.get("image_prompt") or item.get("figure") or ""):
        return None
    return item


def _fill_title_lede(slides: list[dict[str, Any]]) -> None:
    """If the title slide has no thesis, borrow the next cards/bullets."""
    if not slides:
        return
    first = slides[0]
    if str(first.get("layout") or "") not in ("title", ""):
        return
    if str(first.get("lede") or "").strip():
        return
    for s in slides[1:]:
        cards = s.get("cards") or []
        titles = [
            str(c.get("title") or "").strip()
            for c in cards if isinstance(c, dict)
        ]
        titles = [t for t in titles if t]
        if len(titles) >= 2:
            first["lede"] = " · ".join(titles[:4])
            first["layout"] = "title"
            return
        bullets = [
            str(b).strip() for b in (s.get("bullets") or []) if str(b).strip()
        ]
        real = [b for b in bullets if not _is_metadata_line(b)]
        if real:
            first["lede"] = display_text(real[0])[:180]
            first["layout"] = "title"
            return


def quality_errors(slides: list[dict[str, Any]], *, title: str) -> list[str]:
    """Agent-facing refusals. Empty after normalize is a hard fail."""
    errs: list[str] = []
    if len(slides) < 3:
        errs.append(
            f"need at least 3 slides that carry content (got {len(slides)}). "
            "Title (thesis lede) → evidence (table/figure/cards) → close (takeaway)."
        )
    if not slides:
        return errs
    first = slides[0]
    if str(first.get("layout") or "") == "title" and not str(first.get("lede") or "").strip():
        errs.append(
            "title slide needs a lede — one sentence that states the claim, "
            "not just the deck title."
        )
    has_visual = False
    for i, s in enumerate(slides):
        n = i + 1
        if slide_is_empty(s):
            errs.append(f"slide {n} is blank — add heading plus body, table, or figure")
            continue
        cols, rows = _table_from_slide(s)
        if (
            cols or rows or str(s.get("media") or "").strip() or s.get("cards")
            or s.get("stats") or s.get("chart") or str(s.get("quote") or "").strip()
            or s.get("steps")
        ):
            has_visual = True
        layout = str(s.get("layout") or "")
        blob = " ".join([
            str(s.get("heading") or ""),
            str(s.get("lede") or ""),
            str(s.get("quote") or ""),
            " ".join(str(b) for b in (s.get("bullets") or [])),
        ])
        hits = slide_charts.llm_speak_hits(blob)
        if hits:
            errs.append(
                f"slide {n} reads as curator notes ({hits[0]!r}). "
                "Use the paper's own sentence, a number, or a quote — "
                "not 'vault-backed' / 'working set' / 'Act 1'."
            )
        if layout == "split" and not str(s.get("media") or "").strip() and not cols:
            errs.append(
                f"slide {n} is split with no figure/table — use layout bullets "
                "or pass figure / wiki_table / image_prompt"
            )
        if not str(s.get("heading") or "").strip():
            errs.append(f"slide {n} is missing heading")
        if slide_is_backlog(s):
            where = "closing slide" if i == len(slides) - 1 else f"slide {n}"
            errs.append(
                f"{where} is an ingest/TODO punch-list (still missing, "
                "never ingested, remaining gaps). A human deck closes on "
                "the story takeaway, not what the vault still needs."
            )
    last = slides[-1]
    if slide_is_metadata_dump(last):
        errs.append(
            "closing slide dumps wiki metadata (Topics / Spine / Table [[wikilinks]]). "
            "Write the takeaway in prose, and pass wiki_table=tbl-… to inline the table."
        )
    if not has_visual:
        errs.append(
            "deck has no table, figure, quote, chart, or cards. "
            "Inline wiki_table, quote_from an evidence page, stats, or a chart."
        )
    return errs


def prepare_agent_slides(
    workspace: Path,
    title: str,
    slides: list[dict[str, Any]],
    *,
    slug: str = "",
    generate_images: bool = True,
) -> dict[str, Any]:
    """Resolve wiki tables/figures, generate image prompts, drop blanks.

    Returns ``{ok, slides, media_files, error, warnings}``.
    """
    warnings: list[str] = []
    media_files: dict[str, Path] = {}
    prepared: list[dict[str, Any]] = []
    workspace = Path(workspace)

    for i, raw in enumerate(slides):
        if not isinstance(raw, dict):
            return {
                "ok": False, "slides": [], "media_files": {},
                "error": "every slide must be an object", "warnings": warnings,
            }
        item = normalize_slide(raw, deck_title=title, index=i)
        if item is None:
            warnings.append(f"dropped empty slide {i + 1}")
            continue

        for ref in _tbl_refs_in(item):
            parsed = load_wiki_table(workspace, ref)
            if not parsed:
                warnings.append(f"wiki_table {ref!r} not found")
                continue
            was_meta = slide_is_metadata_dump(item)
            cols, rows = _slide_table_view(parsed["columns"], parsed["rows"])
            item.setdefault("table", {"columns": cols, "rows": rows, "source": parsed.get("source")})
            item["columns"] = cols
            item["rows"] = rows
            layout_now = str(item.get("layout") or "")
            if was_meta and layout_now in ("close", "bullets", "title"):
                item["layout"] = "table"
                heading = str(item.get("heading") or "").strip()
                if heading in ("", title, "Key points"):
                    item["heading"] = "What the papers report"
                item["bullets"] = []
            elif layout_now not in ("table", "split", "media"):
                item["layout"] = "table"
            cite = str(item.get("cite") or "").strip()
            src = str(parsed.get("source") or "")
            if src and src not in cite:
                item["cite"] = f"{cite} {src}".strip()
            break

        q_from = str(item.get("quote_from") or "").strip()
        if q_from and not str(item.get("quote") or "").strip():
            pulled = slide_charts.load_quote(workspace, q_from)
            if pulled:
                item["quote"] = pulled
                if str(item.get("layout") or "") in ("bullets", "close", "title", ""):
                    item["layout"] = "quote"
            else:
                warnings.append(f"quote_from {q_from!r} had no blockquote")

        if item.get("chart") and not slide_charts.chart_points(item.get("chart")):
            warnings.append(f"slide {i + 1} chart had no numeric points")

        fig_ref = str(item.get("figure") or item.get("wiki_figure") or "").strip()
        if fig_ref and not str(item.get("media") or "").strip():
            from .slideshow_from_md import resolve_figure
            found = resolve_figure(workspace, fig_ref)
            if found is not None:
                fname = f"s{len(prepared)}-{found.stem[:40]}{found.suffix.lower()}"
                media_files[fname] = found
                item["media"] = fname
                item["media_kind"] = "image"
                if str(item.get("layout") or "") in ("bullets", "cards"):
                    item["layout"] = "split" if (item.get("bullets") or item.get("cards")) else "media"
            else:
                warnings.append(f"figure {fig_ref!r} not found")

        prompt = str(item.get("image_prompt") or "").strip()
        allow_gen = generate_images
        if allow_gen:
            try:
                from . import admin_policy
                allow_gen = admin_policy.feature_enabled("media_generation")
            except Exception:  # noqa: BLE001
                allow_gen = False
        if (
            allow_gen and prompt
            and not str(item.get("media") or "").strip()
        ):
            try:
                from . import media_gen
                fname = f"s{len(prepared)}-gen.png"
                result = media_gen.generate_image(
                    workspace, prompt,
                    filename=f"ss-{(slug or 'deck')}-s{len(prepared)}.png",
                )
                src_p = Path(str(result.get("path") or ""))
                if src_p.is_file():
                    media_files[fname] = src_p
                    item["media"] = fname
                    item["media_kind"] = "image"
                    if str(item.get("layout") or "") in ("bullets", "cards", "title"):
                        item["layout"] = "split" if item.get("bullets") else "media"
            except Exception as e:  # noqa: BLE001
                warnings.append(f"image_prompt on slide {i + 1} failed: {e}")

        if str(item.get("layout") or "") == "split" and not str(item.get("media") or "").strip():
            cols, _rows = _table_from_slide(item)
            if cols:
                item["layout"] = "table"
            elif item.get("bullets") or item.get("cards"):
                item["layout"] = "cards" if item.get("cards") else "bullets"
            else:
                warnings.append(f"dropped empty split slide {i + 1}")
                continue

        if slide_is_empty(item):
            warnings.append(f"dropped empty slide {i + 1}")
            continue
        prepared.append(item)

    _fill_title_lede(prepared)
    errs = quality_errors(prepared, title=title)
    if errs:
        return {
            "ok": False,
            "slides": prepared,
            "media_files": media_files,
            "error": "Slideshow refused — " + " ".join(errs),
            "warnings": warnings,
        }
    return {
        "ok": True,
        "slides": prepared,
        "media_files": media_files,
        "error": "",
        "warnings": warnings,
    }


def render_slideshow(
    *,
    title: str,
    slides: list[dict[str, Any]],
    wordmark: str = "Switch Bay",
    theme: str = "dark",
    voice_delay_ms: int = 3000,
) -> str:
    """Build a full offline-capable HTML document.

    Each slide dict::

      {
        "id": "s1",                 # optional anchor
        "layout": "title" | "media" | "split" | "cards" | "bullets" | "close",
        "eyebrow": "optional mono label",
        "heading": "…",
        "lede": "optional subhead",
        "media": "relative/path.mp4",   # video or image
        "media_kind": "video" | "image",
        "bullets": ["…"],
        "cards": [{"title","body","accent?"}],
        "cite": "wiki sources…",
        "audio": "optional.mp3",
        "notes": "speaker notes",
      }

    When a slide has ``audio``, playback starts ``voice_delay_ms`` after
    that slide becomes active (default 3000). Switching slides stops the
    previous clip. Users can still use the visible controls.
    """
    body_parts: list[str] = []
    n = max(1, len(slides))
    for i, s in enumerate(slides):
        body_parts.append(_render_slide(s, i, n))
    slides_html = "\n".join(body_parts)
    delay = max(0, int(voice_delay_ms))
    return _SHELL.format(
        title=_e(title),
        wordmark=_e(wordmark),
        slides_html=slides_html,
        n_slides=n,
        theme=_e(theme),
        voice_delay_ms=delay,
    )


def _render_slide(s: dict[str, Any], i: int, n: int) -> str:
    layout = str(s.get("layout") or "bullets")
    sid = _e(str(s.get("id") or f"s{i + 1}"))
    eyebrow = str(s.get("eyebrow") or "")
    heading = str(s.get("heading") or "")
    lede = str(s.get("lede") or "")
    cite = str(s.get("cite") or "")
    notes = str(s.get("notes") or "")
    media = str(s.get("media") or "")
    media_kind = str(s.get("media_kind") or "image")
    audio = str(s.get("audio") or "")
    bullets = s.get("bullets") or []
    cards = s.get("cards") or []
    quote = str(s.get("quote") or "").strip()
    quote_attr = str(s.get("attr") or s.get("quote_attr") or "").strip()
    stats = s.get("stats") if isinstance(s.get("stats"), list) else []
    steps = s.get("steps") if isinstance(s.get("steps"), list) else []
    left = s.get("left") if isinstance(s.get("left"), dict) else {}
    right = s.get("right") if isinstance(s.get("right"), dict) else {}
    chart_pts = slide_charts.chart_points(s.get("chart"))

    eye = (
        f'<div class="eyebrow">{_e(display_text(eyebrow))}</div>' if eyebrow else ""
    )
    h = f"<h1>{_e(display_text(heading))}</h1>" if heading else ""
    ld = f'<p class="lede">{_e(display_text(lede))}</p>' if lede else ""
    cite_h = f'<p class="cite">{_e(cite)}</p>' if cite else ""
    notes_h = (
        f'<aside class="notes">{_e(notes)}</aside>' if notes else ""
    )
    audio_h = ""
    if audio:
        audio_h = (
            f'<div class="audio-wrap">'
            f'<span class="label">Narration</span>'
            f'<audio controls src="{_e(audio)}"></audio></div>'
        )

    media_h = ""
    if media:
        if media_kind == "video":
            media_h = (
                f'<div class="media-frame">'
                f'<video controls autoplay muted loop playsinline '
                f'src="{_e(media)}"></video></div>'
            )
        else:
            media_h = (
                f'<div class="media-frame">'
                f'<img src="{_e(media)}" alt="" /></div>'
            )

    if layout == "title":
        inner = (
            f'<div class="slide-head title-center">{eye}{h}{ld}'
            f'{cite_h}{audio_h}</div>{notes_h}'
        )
    elif layout == "media":
        inner = (
            f'<div class="slide-head">{eye}{h}{ld}</div>'
            f'<div class="slide-body col grow">{media_h}{cite_h}{audio_h}</div>'
            f"{notes_h}"
        )
    elif layout == "split":
        bullets_h = _bullets_html(bullets)
        cols, trows = _table_from_slide(s)
        left = media_h or _table_html(cols, trows)
        inner = (
            f'<div class="slide-head">{eye}{h}{ld}</div>'
            f'<div class="slide-body">'
            f'<div class="col grow" style="flex:1.1">{left}</div>'
            f'<div class="col grow" style="flex:1">{bullets_h}{cite_h}{audio_h}</div>'
            f"</div>{notes_h}"
        )
    elif layout == "cards":
        cards_h = _cards_html(cards)
        inner = (
            f'<div class="slide-head">{eye}{h}{ld}</div>'
            f'<div class="slide-body col grow">{cards_h}{cite_h}{audio_h}</div>'
            f"{notes_h}"
        )
    elif layout == "table":
        cols, trows = _table_from_slide(s)
        table_h = _table_html(cols, trows)
        inner = (
            f'<div class="slide-head">{eye}{h}{ld}</div>'
            f'<div class="slide-body col grow">{table_h}{_bullets_html(bullets)}'
            f'{cite_h}{audio_h}</div>{notes_h}'
        )
    elif layout == "quote":
        inner = (
            f'<div class="slide-head">{eye}{h}</div>'
            f'<div class="slide-body col grow title-center">'
            f'<blockquote class="quote">{_e(display_text(quote))}</blockquote>'
            f'{f"<p class=quote-attr>{_e(display_text(quote_attr))}</p>" if quote_attr else ""}'
            f'{cite_h}{audio_h}</div>{notes_h}'
        )
    elif layout == "stats":
        inner = (
            f'<div class="slide-head">{eye}{h}{ld}</div>'
            f'<div class="slide-body col grow">{_stats_html(stats)}'
            f'{cite_h}{audio_h}</div>{notes_h}'
        )
    elif layout == "chart":
        svg = slide_charts.bar_chart_svg(chart_pts, title=str(s.get("chart_title") or ""))
        inner = (
            f'<div class="slide-head">{eye}{h}{ld}</div>'
            f'<div class="slide-body col grow">'
            f'<div class="chart-frame">{svg}</div>'
            f'{cite_h}{audio_h}</div>{notes_h}'
        )
    elif layout == "compare":
        inner = (
            f'<div class="slide-head">{eye}{h}{ld}</div>'
            f'<div class="slide-body">{_compare_html(left, right)}'
            f'</div>{cite_h}{audio_h}{notes_h}'
        )
    elif layout == "timeline":
        inner = (
            f'<div class="slide-head">{eye}{h}{ld}</div>'
            f'<div class="slide-body col grow">{_timeline_html(steps)}'
            f'{cite_h}{audio_h}</div>{notes_h}'
        )
    elif layout == "close":
        inner = (
            f'<div class="slide-head title-center">{eye}{h}{ld}'
            f'{_bullets_html(bullets)}{cite_h}{audio_h}</div>{notes_h}'
        )
    else:  # bullets
        inner = (
            f'<div class="slide-head">{eye}{h}{ld}</div>'
            f'<div class="slide-body col grow">'
            f'{_bullets_html(bullets)}{media_h}{cite_h}{audio_h}</div>'
            f"{notes_h}"
        )

    active = " active" if i == 0 else ""
    return (
        f'<section class="slide{active}" data-i="{i}" id="{sid}">'
        f"{inner}</section>"
    )


def _bullets_html(bullets: list[Any]) -> str:
    if not bullets:
        return ""
    items = []
    for b in bullets:
        if isinstance(b, dict):
            t = str(b.get("title") or "")
            body = str(b.get("body") or b.get("text") or "")
            items.append(
                f'<li><strong>{_e(display_text(t))}</strong>'
                f'{f" — {_e(display_text(body))}" if body else ""}</li>'
            )
        else:
            items.append(f"<li>{_e(display_text(str(b)))}</li>")
    return f'<ul class="bullets">{"".join(items)}</ul>'


def _stats_html(stats: list[Any]) -> str:
    if not stats:
        return ""
    parts = []
    for st in stats:
        if not isinstance(st, dict):
            continue
        value = _e(display_text(str(st.get("value") or "")))
        label = _e(display_text(str(st.get("label") or "")))
        hint = _e(display_text(str(st.get("hint") or "")))
        parts.append(
            f'<div class="stat"><div class="stat-v">{value}</div>'
            f'<div class="stat-l">{label}</div>'
            f'{f"<div class=stat-h>{hint}</div>" if hint else ""}</div>'
        )
    return f'<div class="stats">{"".join(parts)}</div>' if parts else ""


def _compare_html(left: dict[str, Any], right: dict[str, Any]) -> str:
    def col(side: dict[str, Any], cls: str) -> str:
        t = _e(display_text(str(side.get("title") or "")))
        b = _e(display_text(str(side.get("body") or "")))
        return (
            f'<div class="compare-col {cls}">'
            f'{f"<div class=compare-t>{t}</div>" if t else ""}'
            f'{f"<p>{b}</p>" if b else ""}</div>'
        )
    return f'<div class="compare">{col(left, "before")}{col(right, "after")}</div>'


def _timeline_html(steps: list[Any]) -> str:
    if not steps:
        return ""
    parts = []
    for st in steps:
        if not isinstance(st, dict):
            continue
        year = _e(display_text(str(st.get("year") or st.get("when") or "")))
        t = _e(display_text(str(st.get("title") or "")))
        b = _e(display_text(str(st.get("body") or "")))
        parts.append(
            f'<div class="tl-step"><div class="tl-year">{year}</div>'
            f'<div class="tl-t">{t}</div>'
            f'{f"<p class=tl-b>{b}</p>" if b else ""}</div>'
        )
    return f'<div class="timeline">{"".join(parts)}</div>' if parts else ""


def _cards_html(cards: list[Any]) -> str:
    if not cards:
        return ""
    parts = []
    for c in cards:
        if not isinstance(c, dict):
            continue
        title = _e(display_text(str(c.get("title") or "")))
        body = _e(display_text(str(c.get("body") or "")))
        accent = _e(str(c.get("accent") or "var(--accent)"))
        parts.append(
            f'<div class="card" style="--c:{accent}">'
            f'<div class="card-t">{title}</div>'
            f'<div class="card-b">{body}</div></div>'
        )
    return f'<div class="cards">{"".join(parts)}</div>'


def write_slideshow(
    workspace: Path,
    slug: str,
    *,
    title: str,
    slides: list[dict[str, Any]],
    wiki_topics: list[str] | None = None,
    media_files: dict[str, Path] | None = None,
    wordmark: str = "Switch Bay",
    voice_delay_ms: int = 3000,
) -> dict[str, Any]:
    """Materialize ``slideshows/<slug>/index.html`` (+ optional media).

    ``media_files`` maps basename → source path to copy beside index.html.
    ``voice_delay_ms`` is the pause after a slide change before narration
    autoplay (default 3000).
    """
    d = html_decks.ensure_deck(
        workspace, slug, title=title, wiki_topics=wiki_topics or [],
    )
    if media_files:
        for name, src in media_files.items():
            src = Path(src)
            if src.is_file():
                dest = d / Path(name).name
                dest.write_bytes(src.read_bytes())
    doc = render_slideshow(
        title=title,
        slides=slides,
        wordmark=wordmark,
        voice_delay_ms=voice_delay_ms,
    )
    (d / "index.html").write_text(doc, encoding="utf-8")
    meta = {
        "title": title,
        "wiki_topics": wiki_topics or [],
        "updated_at": time.time(),
        "engine": "slideshow_html",
        "n_slides": len(slides),
        "voice_delay_ms": int(voice_delay_ms),
    }
    atomicio.write_json_atomic(d / "deck.json", meta)
    return {
        "ok": True,
        "slug": slug,
        "path": f"slideshows/{slug}/",
        "title": title,
        "wikilink": html_decks.wiki_link_markdown(slug, title),
        "voice_delay_ms": int(voice_delay_ms),
    }


# ── Design shell (intro_and_bench DNA) ─────────────────────────────

_SHELL = """<!doctype html>
<html lang="en" data-theme="{theme}">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{title}</title>
<style>
:root{{
  --bg:#0c0f16; --bg2:#11151e; --panel:#161b26; --panel2:#1c2230;
  --line:#262d3b; --line2:#333c4e;
  --ink:#e9edf6; --dim:#9aa4ba; --faint:#616a80;
  --accent:#7b93ff; --accent-dim:#4d5fb8; --warm:#e6a24a;
  --good:#5fc06d; --bad:#e5695f;
  --shadow:0 20px 60px -20px rgba(0,0,0,.6);
  --sans:ui-sans-serif,-apple-system,"SF Pro Text","Segoe UI",Roboto,Inter,system-ui,sans-serif;
  --mono:ui-monospace,"SF Mono","JetBrains Mono","Cascadia Code",Menlo,Consolas,monospace;
}}
@media (prefers-color-scheme:light){{
  :root{{
    --bg:#f5f4ef; --bg2:#eeece4; --panel:#ffffff; --panel2:#faf9f5;
    --line:#e3dfd4; --line2:#d3cec0;
    --ink:#1a1e28; --dim:#5a6072; --faint:#8b91a1;
    --accent:#5566e0; --accent-dim:#a9b3ee; --warm:#c9832a;
    --shadow:0 18px 50px -22px rgba(40,45,70,.35);
  }}
}}
*{{box-sizing:border-box}}
html,body{{margin:0;height:100%}}
body{{
  background:var(--bg); color:var(--ink); font-family:var(--sans);
  overflow:hidden; -webkit-font-smoothing:antialiased;
}}
.deck{{position:fixed;inset:0}}
.slide{{
  position:absolute;inset:0;opacity:0;visibility:hidden;
  transition:opacity .45s ease, transform .45s ease;
  transform:translateY(8px);
  padding:clamp(28px,4.5vw,72px) clamp(28px,6vw,110px);
  display:flex;flex-direction:column;
}}
.slide.active{{opacity:1;visibility:visible;transform:none;z-index:2}}
.topbar{{
  position:fixed;top:0;left:0;right:0;height:46px;z-index:20;
  display:flex;align-items:center;justify-content:space-between;
  padding:0 clamp(20px,4vw,44px);
  font-family:var(--mono);font-size:11px;letter-spacing:.12em;
  color:var(--faint);text-transform:uppercase;pointer-events:none;
}}
.wordmark{{display:flex;align-items:center;gap:9px;color:var(--dim)}}
.wordmark b{{color:var(--ink);font-weight:600}}
.dot{{width:6px;height:6px;border-radius:50%;background:var(--accent);box-shadow:0 0 10px var(--accent)}}
.counter{{color:var(--dim)}} .counter i{{color:var(--ink);font-style:normal}}
.progress{{position:fixed;left:0;bottom:0;height:3px;background:var(--accent);
  z-index:20;transition:width .45s ease;box-shadow:0 0 12px var(--accent)}}
.ctrls{{position:fixed;bottom:14px;right:20px;z-index:21;display:flex;gap:6px}}
.ctrls button{{
  font-family:var(--mono);font-size:12px;color:var(--dim);
  background:var(--panel);border:1px solid var(--line);border-radius:7px;
  width:30px;height:28px;cursor:pointer;display:grid;place-items:center;
}}
.ctrls button:hover{{color:var(--ink);border-color:var(--line2)}}
.zone{{position:fixed;top:46px;bottom:40px;width:16%;z-index:10;cursor:pointer}}
.zone.left{{left:0}} .zone.right{{right:0;width:22%}}
@media (max-width:760px){{.zone{{display:none}}}}
.eyebrow{{
  font-family:var(--mono);font-size:12px;letter-spacing:.22em;text-transform:uppercase;
  color:var(--accent);display:flex;align-items:center;gap:12px;margin:0 0 20px;
}}
.eyebrow::before{{content:"";width:26px;height:1px;background:var(--accent);opacity:.6}}
h1{{
  font-size:clamp(28px,4.2vw,52px);line-height:1.06;letter-spacing:-.02em;
  font-weight:640;margin:0;text-wrap:balance;max-width:28ch;
}}
.lede{{font-size:clamp(15px,1.45vw,19px);line-height:1.5;color:var(--dim);
  max-width:58ch;margin:16px 0 0;text-wrap:pretty}}
.slide-head{{flex:0 0 auto}}
.slide-body{{flex:1 1 auto;min-height:0;display:flex;gap:clamp(18px,2.8vw,40px);margin-top:clamp(16px,2.2vw,32px)}}
.col{{display:flex;flex-direction:column;min-width:0}}
.grow{{flex:1 1 auto;min-height:0}}
.title-center{{
  flex:1;display:flex;flex-direction:column;justify-content:center;
  max-width:720px;margin:0 auto;text-align:left;width:100%;
}}
.media-frame{{
  flex:1 1 auto;min-height:0;border-radius:16px;overflow:hidden;
  border:1px solid var(--line);background:var(--panel2);
  display:grid;place-items:center;box-shadow:var(--shadow);
}}
.media-frame video,.media-frame img{{
  width:100%;height:100%;max-height:min(58vh,640px);object-fit:contain;display:block;background:#000;
}}
.bullets{{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:12px}}
.bullets li{{
  background:var(--panel);border:1px solid var(--line);border-radius:12px;
  padding:14px 16px;font-size:clamp(14px,1.25vw,16.5px);line-height:1.45;color:var(--ink);
  border-left:3px solid var(--accent);
}}
.bullets li strong{{color:var(--ink)}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;flex:1}}
.card{{
  background:var(--panel);border:1px solid var(--line);border-radius:14px;
  padding:16px;border-top:3px solid var(--c,var(--accent));
  display:flex;flex-direction:column;gap:8px;
}}
.card-t{{font-weight:620;font-size:15px}}
.card-b{{font-size:13px;color:var(--dim);line-height:1.45}}
.sheet-wrap{{
  flex:1 1 auto;min-height:0;overflow:auto;border-radius:14px;
  border:1px solid var(--line);background:var(--panel);box-shadow:var(--shadow);
}}
.sheet{{width:100%;border-collapse:collapse;font-size:clamp(12px,1.15vw,15px)}}
.sheet th,.sheet td{{
  padding:8px 12px;text-align:left;vertical-align:top;line-height:1.35;
  border-bottom:1px solid var(--line);
}}
.sheet th{{
  font-family:var(--mono);font-size:11px;letter-spacing:.08em;
  text-transform:uppercase;color:var(--dim);background:var(--panel2);
  position:sticky;top:0;
}}
.sheet td{{color:var(--ink)}}
.sheet tbody tr:last-child td{{border-bottom:none}}
blockquote.quote{{
  margin:0;font-size:clamp(22px,2.6vw,34px);line-height:1.28;font-weight:520;
  max-width:34ch;text-wrap:pretty;letter-spacing:-.015em;
}}
blockquote.quote::before{{content:"“";color:var(--accent);font-weight:640}}
.quote-attr{{
  font-family:var(--mono);font-size:12px;color:var(--dim);margin:18px 0 0;
  letter-spacing:.04em;
}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
  gap:16px;flex:1;align-content:center}}
.stat{{
  background:var(--panel);border:1px solid var(--line);border-radius:16px;
  padding:22px 18px;border-top:3px solid var(--accent);
}}
.stat-v{{font-size:clamp(36px,5vw,64px);font-weight:650;letter-spacing:-.04em;line-height:1}}
.stat-l{{margin-top:10px;font-size:15px;color:var(--ink)}}
.stat-h{{margin-top:4px;font-size:12px;color:var(--dim)}}
.compare{{display:grid;grid-template-columns:1fr 1fr;gap:20px;flex:1;width:100%}}
.compare-col{{
  background:var(--panel);border:1px solid var(--line);border-radius:16px;
  padding:22px;
}}
.compare-t{{font-weight:620;margin-bottom:10px;font-size:16px}}
.compare-col p{{margin:0;color:var(--dim);line-height:1.45}}
.timeline{{display:flex;gap:14px;flex:1;align-items:stretch}}
.tl-step{{
  flex:1;border-top:2px solid var(--accent);padding-top:14px;
  min-width:0;
}}
.tl-year{{font-family:var(--mono);font-size:12px;color:var(--accent);letter-spacing:.12em}}
.tl-t{{font-weight:620;margin-top:8px;font-size:16px}}
.tl-b{{margin:8px 0 0;color:var(--dim);font-size:13px;line-height:1.4}}
.chart-frame{{
  flex:1;min-height:0;display:flex;align-items:stretch;
}}
.chart-frame svg{{width:100%;height:100%;max-height:min(52vh,520px)}}
.cite{{
  font-family:var(--mono);font-size:11px;color:var(--faint);line-height:1.4;
  margin:14px 0 0;max-width:70ch;
}}
.audio-wrap{{margin-top:16px;display:flex;flex-direction:column;gap:8px;max-width:420px}}
.audio-wrap .label{{font-family:var(--mono);font-size:10.5px;letter-spacing:.12em;
  text-transform:uppercase;color:var(--faint)}}
audio{{width:100%}}
.notes{{display:none}}
@page{{size:13.333in 7.5in;margin:0}}
@media print{{
  html,body{{width:13.333in;height:auto;overflow:visible;background:var(--bg)}}
  .deck{{position:static}}
  .slide,.slide.active{{
    position:relative;inset:auto;width:13.333in;height:7.5in;
    opacity:1;visibility:visible;transform:none;z-index:auto;
    page-break-after:always;break-after:page;overflow:hidden;
    -webkit-print-color-adjust:exact;print-color-adjust:exact;
  }}
  .slide:last-child{{page-break-after:auto;break-after:auto}}
  .topbar,.progress,.ctrls,.zone,audio{{display:none!important}}
}}
</style>
</head>
<body>
<div class="topbar">
  <div class="wordmark"><span class="dot"></span><b>{wordmark}</b></div>
  <div class="counter"><i id="cur">1</i> / {n_slides}</div>
</div>
<div class="deck" id="deck">
{slides_html}
</div>
<div class="progress" id="prog" style="width:0%"></div>
<div class="zone left" id="zL" title="Previous"></div>
<div class="zone right" id="zR" title="Next"></div>
<div class="ctrls">
  <button type="button" id="prev" aria-label="Previous">‹</button>
  <button type="button" id="next" aria-label="Next">›</button>
</div>
<script>
(function(){{
  const VOICE_DELAY_MS={voice_delay_ms};
  const slides=[...document.querySelectorAll('.slide')];
  let i=0;
  let voiceTimer=null;
  function stopVoice(){{
    if(voiceTimer){{clearTimeout(voiceTimer);voiceTimer=null;}}
    document.querySelectorAll('audio').forEach(a=>{{
      try{{a.pause();a.currentTime=0;}}catch(e){{}}
    }});
  }}
  function scheduleVoice(){{
    stopVoice();
    const slide=slides[i];
    if(!slide)return;
    const audio=slide.querySelector('audio');
    if(!audio)return;
    voiceTimer=setTimeout(()=>{{
      voiceTimer=null;
      try{{
        audio.currentTime=0;
        const p=audio.play();
        if(p&&typeof p.catch==='function')p.catch(()=>{{}});
      }}catch(e){{}}
    }},VOICE_DELAY_MS);
  }}
  function go(n){{
    i=Math.max(0,Math.min(slides.length-1,n));
    slides.forEach((s,k)=>s.classList.toggle('active',k===i));
    document.getElementById('cur').textContent=String(i+1);
    document.getElementById('prog').style.width=((i+1)/slides.length*100)+'%';
    location.hash=slides[i].id||('s'+(i+1));
    scheduleVoice();
  }}
  document.getElementById('prev').onclick=()=>go(i-1);
  document.getElementById('next').onclick=()=>go(i+1);
  document.getElementById('zL').onclick=()=>go(i-1);
  document.getElementById('zR').onclick=()=>go(i+1);
  window.addEventListener('keydown',e=>{{
    if(e.key==='ArrowRight'||e.key===' ' ||e.key==='PageDown'){{e.preventDefault();go(i+1);}}
    if(e.key==='ArrowLeft'||e.key==='PageUp'){{e.preventDefault();go(i-1);}}
    if(e.key==='Home')go(0);
    if(e.key==='End')go(slides.length-1);
  }});
  const h=(location.hash||'').replace(/^#/,'');
  const start=h?slides.findIndex(s=>s.id===h):0;
  go(start>=0?start:0);
}})();
</script>
</body>
</html>
"""
