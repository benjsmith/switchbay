---
name: html-slideshow
description: >-
  Create or revise high-quality self-contained HTML slideshows for Switch Bay
  workspaces (slideshows/<slug>/, wikilink [[slideshow:slug|title]]). Prefer
  markdown authoring (H1/H2 + lists + image: + figure wikilinks + ### Voiceover)
  via slideshow_from_md. Use when the user asks for an HTML presentation,
  slideshow, media-rich topic deck, or wiki-linked presentation — NOT Sketch
  kind:deck / Excalidraw decks.
---

# HTML slideshow skill (Switch Bay)

## Do not confuse with Sketch decks

| Surface | Where | Open |
|---------|--------|------|
| **Sketch deck** | `kind: deck` analyses + Excalidraw | Sketch tab |
| **HTML slideshow** | `slideshows/<slug>/` | Slideshow tab |

Wikilink for HTML only: **`[[slideshow:slug|title]]`** — never `[[deck:…]]`.

---

## Preferred path: markdown authoring

Write a normal `.md` file, then build:

```bash
# slash (in rail)
/slideshow from-md notes/my-deck.md
/slideshow from-md notes/my-deck.md my-slug --no-media   # structure only
```

Or Python / API:

```python
from switchbay import slideshow_from_md

slideshow_from_md.build_from_markdown(
    workspace,
    "notes/my-deck.md",
    slug="my-deck",          # optional
    generate_media=True,     # image prompts + TTS
)
# POST /api/slideshows/from-md  { "path": "notes/my-deck.md", "open": true }
```

### Markdown conventions

```markdown
# Title slide heading

Optional lede under the H1 (title slide body).

## First content slide

- Bullet one
- Bullet two

image: Prompt for a generated figure (xAI Imagine via media prefs)

[[existing-figure-stem]]

### Voiceover

Spoken script for this slide. TTS is generated and embedded; playback
starts ~3 seconds after the slide becomes active.

## Second slide

- More bullets
- image: Another prompt as a list item works too

![](figures/_assets/some.png)

### TTS

Alternate heading name for the voiceover block (also: Narration, Script).
```

| Construct | Effect |
|-----------|--------|
| `# …` | Title slide (one) |
| `## …` | One content slide each (N H2 ⇒ N content slides) |
| `- item` | Bullet |
| `image:` / `!image:` / `img:` / `generate:` (line or list item) | Generate image |
| `[[figure-stem]]` or `![](figures/_assets/…)` | Embed existing figure PNG |
| `### Voiceover` (or TTS / Narration / Script) | TTS for that slide |

**Audio default:** autoplay with **3s delay** after slide change so narration starts shortly after the visual settles. Switching slides stops the previous clip. Manual audio controls remain available.

**Never hand-author raw bullet HTML** or invent a one-off stylesheet — always go through `slideshow_from_md` or `slideshow_html.write_slideshow`.

---

## Structured path (typed dicts)

When you already have structured content (not a draft MD file):

```python
from switchbay import slideshow_html

slideshow_html.write_slideshow(
    workspace,
    "my-slug",
    title="My title",
    wiki_topics=["transformer"],
    media_files={"hero.mp4": Path("…"), "diagram.png": Path("…")},
    voice_delay_ms=3000,
    slides=[
        {
            "layout": "title",
            "eyebrow": "Topic",
            "heading": "Bold claim",
            "lede": "One-line thesis",
            "audio": "s0-voice.mp3",
        },
        {
            "layout": "split",
            "heading": "How it works",
            "media": "diagram.png",
            "media_kind": "image",
            "bullets": ["…"],
            "audio": "s1-voice.mp3",
        },
    ],
)
```

## Quality bar

- **Palette committed** — intro-grade dark chrome with accent.
- **Every slide has a visual role** — title / media / cards / split / bullets.
- **Typed hierarchy** — eyebrow, large heading, dim lede, panel bullets.
- **Media as siblings** — relative `src` next to `index.html` (no base64).
- **Provider-agnostic** — LLMs supply content only; CSS/layout always from `slideshow_html`.

## Layouts

| layout | Use |
|--------|-----|
| `title` | Opening / closing |
| `media` | Full-bleed video or figure |
| `split` | Media + bullets |
| `cards` | 2–4 concept cards |
| `bullets` | Dense list (still in panels) |
| `close` | Summary |

## Open in product

- `/slideshows` · `/slideshow <slug>` · `/slideshow from-md <path.md>`
- Click `[[slideshow:…]]` in editor preview
- File browser → `slideshows/<slug>/index.html`

## Wiki link after build

```markdown
## Presentations

- [[slideshow:my-slug|My title]]
```
