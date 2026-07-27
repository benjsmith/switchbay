"""Markdown → HTML slideshow pipeline.

Author a deck as ordinary markdown::

    # Title slide heading

    Optional lede under the H1.

    ## First content slide

    - Bullet one
    - Bullet two

    image: A diagram of residual connections with labels

    [[media-test-transformers-architecture]]

    ### Voiceover

    Spoken narration for this slide. Generated as TTS and autoplayed
    ~3s after the slide becomes active.

    ## Second slide
    …

Rules
-----
* **H1** → title slide (at most one; deck title + optional lede).
* **Each H2** → one content slide (N H2s ⇒ N content slides).
* **Lists** → bullets (or image prompts when the item starts with
  ``image:`` / ``!image:`` / ``img:`` / ``generate:``).
* **Paragraphs starting with those prefixes** → generate an image.
* **Wikilinks** ``[[name]]`` / ``[[name|label]]`` and markdown images
  resolve to existing figure PNGs under the workspace.
* **### Voiceover** / **### TTS** / **### Narration** / **### Script**
  (case-insensitive) at the end of a slide section → TTS audio.

Media generation uses ``media_gen`` (image + voice prefs). Offline
parse always works; gen is opt-in via ``generate_media=True``.
"""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import html_decks, media_gen, slideshow_html

log = logging.getLogger("switchbay.slideshow_from_md")

_H1 = re.compile(r"^#\s+(.+?)\s*$")
_H2 = re.compile(r"^##\s+(.+?)\s*$")
_H3 = re.compile(r"^###\s+(.+?)\s*$")
_LIST = re.compile(r"^(\s*)([-*+]|\d+\.)\s+(.+)$")
_IMAGE_PREFIX = re.compile(
    r"^(?:!?\s*)?(?:image|img|generate)\s*:\s*(.+)$",
    re.IGNORECASE,
)
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_WIKILINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_VOICE_HEADINGS = frozenset({
    "voiceover", "voice over", "tts", "narration", "script",
    "spoken", "audio", "speak",
})
_SLUG_CLEAN = re.compile(r"[^a-z0-9]+")


@dataclass
class ParsedBlock:
    kind: str  # "bullet" | "image_prompt" | "figure" | "text" | "voice"
    text: str = ""
    path: Path | None = None  # resolved figure path when known


@dataclass
class ParsedSlide:
    heading: str
    is_title: bool = False
    lede: str = ""
    blocks: list[ParsedBlock] = field(default_factory=list)

    @property
    def bullets(self) -> list[str]:
        return [b.text for b in self.blocks if b.kind == "bullet" and b.text]

    @property
    def image_prompts(self) -> list[str]:
        return [b.text for b in self.blocks if b.kind == "image_prompt" and b.text]

    @property
    def figures(self) -> list[Path]:
        return [b.path for b in self.blocks if b.kind == "figure" and b.path]

    @property
    def voiceover(self) -> str:
        parts = [b.text for b in self.blocks if b.kind == "voice" and b.text]
        return "\n\n".join(parts).strip()


@dataclass
class ParsedDeck:
    title: str
    slides: list[ParsedSlide]
    source_path: Path | None = None


def slugify(text: str, *, fallback: str = "slideshow") -> str:
    s = _SLUG_CLEAN.sub("-", (text or "").strip().lower()).strip("-")
    if not s:
        s = fallback
    return s[:80]


def parse_markdown(text: str, *, source: Path | None = None) -> ParsedDeck:
    """Parse author markdown into a typed deck (no I/O, no gen)."""
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    title = ""
    slides: list[ParsedSlide] = []
    cur: ParsedSlide | None = None
    voice_mode = False
    pre_h1_buf: list[str] = []

    def flush_voice_into(slide: ParsedSlide | None, buf: list[str]) -> None:
        if slide is None:
            return
        body = "\n".join(buf).strip()
        if body:
            slide.blocks.append(ParsedBlock(kind="voice", text=body))

    voice_buf: list[str] = []

    def ensure_title_slide() -> ParsedSlide:
        nonlocal cur, title
        if cur is not None and cur.is_title:
            return cur
        if not title:
            title = "Untitled"
        cur = ParsedSlide(heading=title, is_title=True)
        slides.append(cur)
        return cur

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        m1 = _H1.match(line)
        m2 = _H2.match(line)
        m3 = _H3.match(line)

        if m1 and not m2:  # H1 only (not ##)
            if voice_mode:
                flush_voice_into(cur, voice_buf)
                voice_buf = []
                voice_mode = False
            title = m1.group(1).strip()
            # If we already have content slides, H1 is late — treat as deck title only
            if not any(s.is_title for s in slides):
                cur = ParsedSlide(heading=title, is_title=True)
                if pre_h1_buf:
                    # rare: text before H1 ignored for structure
                    pre_h1_buf = []
                slides.insert(0, cur)
            else:
                # rename existing title slide
                for s in slides:
                    if s.is_title:
                        s.heading = title
                        cur = s
                        break
            i += 1
            continue

        if m2:
            if voice_mode:
                flush_voice_into(cur, voice_buf)
                voice_buf = []
                voice_mode = False
            heading = m2.group(1).strip()
            cur = ParsedSlide(heading=heading, is_title=False)
            slides.append(cur)
            i += 1
            continue

        if m3:
            h = m3.group(1).strip().lower()
            if h in _VOICE_HEADINGS:
                if voice_mode:
                    flush_voice_into(cur, voice_buf)
                    voice_buf = []
                voice_mode = True
                if cur is None:
                    ensure_title_slide()
                i += 1
                continue
            # Other H3: end voice mode, treat as a bullet-ish label
            if voice_mode:
                flush_voice_into(cur, voice_buf)
                voice_buf = []
                voice_mode = False
            if cur is None:
                ensure_title_slide()
            assert cur is not None
            cur.blocks.append(ParsedBlock(kind="bullet", text=m3.group(1).strip()))
            i += 1
            continue

        if voice_mode:
            if stripped == "" and not voice_buf:
                i += 1
                continue
            voice_buf.append(line.rstrip())
            i += 1
            continue

        if cur is None and not title:
            # Accumulate until first heading
            if stripped:
                pre_h1_buf.append(stripped)
            i += 1
            continue

        if cur is None:
            ensure_title_slide()

        assert cur is not None

        if not stripped:
            i += 1
            continue

        # List item
        lm = _LIST.match(line)
        if lm:
            item = lm.group(3).strip()
            _ingest_line_content(cur, item)
            i += 1
            continue

        # Standalone image / wikilink / text
        _ingest_line_content(cur, stripped)
        i += 1

    if voice_mode:
        flush_voice_into(cur, voice_buf)

    # Promote free text under title slide into lede when no bullets
    for s in slides:
        if s.is_title and not s.lede:
            texts = [b.text for b in s.blocks if b.kind == "text" and b.text]
            if texts:
                s.lede = " ".join(texts)
                s.blocks = [b for b in s.blocks if b.kind != "text"]

    # Title-slide paragraphs after H1 that weren't classified
    if slides and slides[0].is_title and not slides[0].lede:
        lede_parts: list[str] = []
        keep: list[ParsedBlock] = []
        for b in slides[0].blocks:
            if b.kind == "text":
                lede_parts.append(b.text)
            else:
                keep.append(b)
        if lede_parts:
            slides[0].lede = " ".join(lede_parts)
            slides[0].blocks = keep

    if not title and slides:
        title = slides[0].heading
    if not title:
        title = "Untitled"
    if not any(s.is_title for s in slides) and slides:
        # No H1 — first H2 is not auto-title; create title from filename/title
        slides.insert(0, ParsedSlide(heading=title, is_title=True))
    elif not slides:
        slides = [ParsedSlide(heading=title, is_title=True)]

    return ParsedDeck(title=title, slides=slides, source_path=source)


def _ingest_line_content(slide: ParsedSlide, text: str) -> None:
    """Classify one line (or list item body) into a block on *slide*."""
    # image: prompt
    im = _IMAGE_PREFIX.match(text)
    if im:
        slide.blocks.append(ParsedBlock(kind="image_prompt", text=im.group(1).strip()))
        return

    # markdown image ![alt](path)
    mm = _MD_IMAGE.search(text)
    if mm:
        alt = mm.group(1).strip()
        ref = mm.group(2).strip().strip("<>").split()[0]
        slide.blocks.append(ParsedBlock(
            kind="figure", text=alt or ref, path=Path(ref),
        ))
        rest = (_MD_IMAGE.sub("", text)).strip()
        if rest and not _IMAGE_PREFIX.match(rest):
            slide.blocks.append(ParsedBlock(kind="bullet", text=rest))
        return

    # wikilink(s)
    if _WIKILINK.search(text):
        for wm in _WIKILINK.finditer(text):
            target = wm.group(1).strip()
            label = (wm.group(2) or target).strip()
            # Skip slideshow: links — those are references, not figures
            if ":" in target and target.split(":", 1)[0].lower() in (
                "slideshow", "deck", "page", "wiki", "http", "https",
            ):
                continue
            slide.blocks.append(ParsedBlock(
                kind="figure", text=label, path=Path(target),
            ))
        # leftover text as bullet
        rest = _WIKILINK.sub("", text).strip(" -–—\t")
        if rest:
            slide.blocks.append(ParsedBlock(kind="bullet", text=rest))
        return

    # Title-slide free text → text (promoted to lede later)
    if slide.is_title and not slide.bullets and not slide.blocks:
        slide.blocks.append(ParsedBlock(kind="text", text=text))
        return
    if slide.is_title and all(b.kind in ("text",) for b in slide.blocks):
        slide.blocks.append(ParsedBlock(kind="text", text=text))
        return

    slide.blocks.append(ParsedBlock(kind="bullet", text=text))


def resolve_figure(workspace: Path, ref: str | Path) -> Path | None:
    """Find a figure PNG/JPG for a wikilink target or relative path."""
    raw = str(ref or "").strip()
    if not raw:
        return None
    # Strip common prefixes
    raw = raw.replace("\\", "/")
    for prefix in ("wiki/", "./", "/"):
        if raw.startswith(prefix) and prefix != "/":
            raw = raw[len(prefix):]
    name = Path(raw).name
    stem = Path(raw).stem
    candidates: list[Path] = []

    def add(p: Path) -> None:
        candidates.append(p)

    # Explicit path under workspace
    add(workspace / raw)
    if not raw.startswith("wiki/"):
        add(workspace / "wiki" / raw)

    # CE-native assets
    for base in (
        workspace / "wiki" / "figures" / "_assets",
        workspace / "wiki" / "figures",
        workspace / "figures" / "_assets",
        workspace / "figures",
        workspace / "vault" / "exports" / "media-test",
    ):
        add(base / name)
        add(base / f"{stem}.png")
        add(base / f"{stem}.jpg")
        add(base / f"{stem}.jpeg")
        add(base / f"{stem}.webp")
        add(base / f"{name}.png")

    # figure page md → asset in frontmatter-ish path
    fig_md = workspace / "wiki" / "figures" / f"{stem}.md"
    if fig_md.is_file():
        try:
            body = fig_md.read_text(encoding="utf-8")
        except OSError:
            body = ""
        for m in re.finditer(
            r"(?:asset|path|src|image)\s*[:=]\s*[`\"']?([^\s`\"']+\.(?:png|jpe?g|webp|gif))",
            body,
            re.I,
        ):
            add(workspace / m.group(1))
            add(workspace / "wiki" / m.group(1))
        for m in re.finditer(r"!\[.*?\]\(([^)]+)\)", body):
            p = m.group(1).strip()
            add(workspace / p)
            add(workspace / "wiki" / p)
            if not p.startswith("figures"):
                add(workspace / "wiki" / "figures" / p)

    for c in candidates:
        try:
            if c.is_file() and c.suffix.lower() in (
                ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg",
            ):
                return c.resolve()
        except OSError:
            continue
    return None


def deck_to_slide_dicts(
    deck: ParsedDeck,
    *,
    media_names: dict[int, str] | None = None,
    audio_names: dict[int, str] | None = None,
) -> list[dict[str, Any]]:
    """Convert parsed deck to ``slideshow_html`` slide dicts.

    ``media_names`` / ``audio_names`` map slide index → basename already
    copied beside index.html.
    """
    media_names = media_names or {}
    audio_names = audio_names or {}
    out: list[dict[str, Any]] = []
    for i, s in enumerate(deck.slides):
        media = media_names.get(i)
        audio = audio_names.get(i)
        bullets = s.bullets
        if s.is_title:
            d: dict[str, Any] = {
                "layout": "title",
                "heading": s.heading,
                "lede": s.lede or "",
                "id": "title",
            }
            if audio:
                d["audio"] = audio
            if media:
                d["media"] = media
                d["media_kind"] = "image"
            out.append(d)
            continue

        layout = "bullets"
        if media and bullets:
            layout = "split"
        elif media and not bullets:
            layout = "media"
        elif len(bullets) >= 2 and not media and _looks_like_cards(bullets):
            layout = "cards"

        d = {
            "layout": layout,
            "heading": s.heading,
            "eyebrow": "",
            "id": f"s{i}",
        }
        if s.lede:
            d["lede"] = s.lede
        if bullets:
            if layout == "cards":
                d["cards"] = [
                    {"title": _card_title(b), "body": _card_body(b)}
                    for b in bullets[:6]
                ]
            else:
                d["bullets"] = bullets
        if media:
            d["media"] = media
            d["media_kind"] = "image"
        if audio:
            d["audio"] = audio
        if s.voiceover:
            d["notes"] = s.voiceover
        out.append(d)
    return out


def _looks_like_cards(bullets: list[str]) -> bool:
    if not (2 <= len(bullets) <= 4):
        return False
    # short title-ish bullets → cards
    return all(len(b) < 120 and (":" in b or len(b.split()) <= 12) for b in bullets)


def _card_title(b: str) -> str:
    if ":" in b:
        return b.split(":", 1)[0].strip()
    return b.strip()


def _card_body(b: str) -> str:
    if ":" in b:
        return b.split(":", 1)[1].strip()
    return ""


def build_from_markdown(
    workspace: Path,
    md_path: Path | str | None = None,
    *,
    markdown: str | None = None,
    slug: str | None = None,
    title: str | None = None,
    wiki_topics: list[str] | None = None,
    generate_media: bool = True,
    generate_voice: bool | None = None,
    generate_images: bool | None = None,
    wordmark: str = "Switch Bay",
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Parse MD, optionally generate media/TTS, write ``slideshows/<slug>/``.

    Provide either ``md_path`` (workspace-relative or absolute under
    workspace) or raw ``markdown`` text.
    """
    workspace = Path(workspace)
    src_path: Path | None = None
    if markdown is None:
        if md_path is None:
            raise ValueError("md_path or markdown required")
        src_path = Path(md_path)
        if not src_path.is_absolute():
            src_path = workspace / src_path
        src_path = src_path.resolve()
        try:
            src_path.relative_to(workspace.resolve())
        except ValueError as e:
            raise ValueError(f"markdown path outside workspace: {src_path}") from e
        markdown = src_path.read_text(encoding="utf-8")

    deck = parse_markdown(markdown, source=src_path)
    if title:
        deck.title = title
        if deck.slides and deck.slides[0].is_title:
            deck.slides[0].heading = title

    use_slug = slug or slugify(
        src_path.stem if src_path else deck.title,
        fallback="from-md",
    )
    if not html_decks.is_valid_slug(use_slug):
        use_slug = slugify(use_slug, fallback="from-md")

    gen_img = generate_images if generate_images is not None else generate_media
    gen_voice = generate_voice if generate_voice is not None else generate_media

    def report(msg: str) -> None:
        log.info("%s", msg)
        if progress:
            progress(msg)

    # Resolve figures + plan media
    media_files: dict[str, Path] = {}
    media_names: dict[int, str] = {}
    audio_names: dict[int, str] = {}
    gen_log: list[dict[str, Any]] = []

    staging = workspace / "vault" / "exports" / "slideshow-build" / use_slug
    staging.mkdir(parents=True, exist_ok=True)

    for i, s in enumerate(deck.slides):
        # Existing figures first
        for fig_block in [b for b in s.blocks if b.kind == "figure"]:
            ref = fig_block.path or Path(fig_block.text)
            resolved = resolve_figure(workspace, ref)
            if resolved is None and fig_block.path is not None:
                resolved = resolve_figure(workspace, fig_block.text)
            if resolved is not None:
                fname = f"slide{i}-{resolved.name}"
                # keep short unique
                fname = f"s{i}-{resolved.stem[:40]}{resolved.suffix.lower()}"
                media_files[fname] = resolved
                media_names[i] = fname
                fig_block.path = resolved
                break  # one primary image per slide

        # Generate image if no figure and we have a prompt
        if i not in media_names and gen_img and s.image_prompts:
            prompt = s.image_prompts[0]
            fname = f"s{i}-gen.png"
            dest = staging / fname
            report(f"Generating image for slide {i + 1}: {prompt[:80]}…")
            try:
                # media_gen writes to media-test; we copy afterward
                result = media_gen.generate_image(
                    workspace, prompt, filename=f"ss-{use_slug}-s{i}.png",
                )
                src = Path(result["path"])
                shutil.copy2(src, dest)
                media_files[fname] = dest
                media_names[i] = fname
                gen_log.append({"slide": i, "kind": "image", **result})
            except media_gen.MediaGenError as e:
                log.warning("image gen failed slide %s: %s", i, e)
                gen_log.append({"slide": i, "kind": "image", "ok": False, "error": str(e)})

        # TTS
        script = s.voiceover
        if gen_voice and script:
            fname = f"s{i}-voice.mp3"
            dest = staging / fname
            report(f"Generating voiceover for slide {i + 1}…")
            try:
                result = media_gen.generate_voice(
                    workspace, script,
                    filename=f"ss-{use_slug}-s{i}.mp3",
                )
                src = Path(result["path"])
                shutil.copy2(src, dest)
                media_files[fname] = dest
                audio_names[i] = fname
                gen_log.append({"slide": i, "kind": "voice", **result})
            except media_gen.MediaGenError as e:
                log.warning("voice gen failed slide %s: %s", i, e)
                gen_log.append({"slide": i, "kind": "voice", "ok": False, "error": str(e)})

    slide_dicts = deck_to_slide_dicts(
        deck, media_names=media_names, audio_names=audio_names,
    )
    result = slideshow_html.write_slideshow(
        workspace,
        use_slug,
        title=deck.title,
        slides=slide_dicts,
        wiki_topics=wiki_topics or [],
        media_files=media_files,
        wordmark=wordmark,
        voice_delay_ms=3000,
    )
    result["n_slides"] = len(slide_dicts)
    result["source"] = str(src_path.relative_to(workspace)) if src_path else None
    result["generated"] = gen_log
    result["audio_slides"] = list(audio_names.keys())
    result["media_slides"] = list(media_names.keys())
    report(f"Wrote slideshows/{use_slug}/ ({len(slide_dicts)} slides)")
    return result


def example_markdown() -> str:
    return """# Attention Is All You Need

A short visual tour of the Transformer.

## The big idea

- Sequence modeling without recurrence
- Self-attention as the core primitive
- Parallelizable training

image: Clean technical diagram of a transformer block with multi-head attention and feed-forward layers, dark background, labeled arrows

### Voiceover

The transformer replaced recurrence with self-attention, letting every token look at every other token in parallel.

## Core pieces

- Encoder and decoder stacks
- Multi-head attention
- Positional encodings
- Residual connections and layer norm

## Closing

- Still the backbone of modern LLMs
- Simple recipe, enormous scale

### Voiceover

That simple recipe — attention, feed-forward, residual — still powers nearly every large language model today.
"""
