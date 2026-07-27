"""High-quality HTML slideshow builder (provider-agnostic).

Sketch decks remain ``kind: deck`` in the Sketch tab. These are a
**different** product surface: self-contained HTML slideshows under
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
import time
from pathlib import Path
from typing import Any

from . import atomicio, html_decks

# Re-export storage helpers under slideshow naming for callers.
slideshows_root = html_decks.decks_root  # will point at slideshows/
ensure_slideshow = html_decks.ensure_deck
list_slideshows = html_decks.list_decks
wiki_link = html_decks.wiki_link_markdown


def _e(s: str) -> str:
    return html_lib.escape(s or "", quote=True)


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

    eye = (
        f'<div class="eyebrow">{_e(eyebrow)}</div>' if eyebrow else ""
    )
    h = f"<h1>{_e(heading)}</h1>" if heading else ""
    ld = f'<p class="lede">{_e(lede)}</p>' if lede else ""
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
        inner = (
            f'<div class="slide-head">{eye}{h}{ld}</div>'
            f'<div class="slide-body">'
            f'<div class="col grow" style="flex:1.1">{media_h}</div>'
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
            t = _e(str(b.get("title") or ""))
            body = _e(str(b.get("body") or b.get("text") or ""))
            items.append(
                f'<li><strong>{t}</strong>'
                f'{f" — {body}" if body else ""}</li>'
            )
        else:
            items.append(f"<li>{_e(str(b))}</li>")
    return f'<ul class="bullets">{"".join(items)}</ul>'


def _cards_html(cards: list[Any]) -> str:
    if not cards:
        return ""
    parts = []
    for c in cards:
        if not isinstance(c, dict):
            continue
        title = _e(str(c.get("title") or ""))
        body = _e(str(c.get("body") or ""))
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
  font-weight:640;margin:0;text-wrap:balance;max-width:22ch;
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
.cite{{
  font-family:var(--mono);font-size:11px;color:var(--faint);line-height:1.4;
  margin:14px 0 0;max-width:70ch;
}}
.audio-wrap{{margin-top:16px;display:flex;flex-direction:column;gap:8px;max-width:420px}}
.audio-wrap .label{{font-family:var(--mono);font-size:10.5px;letter-spacing:.12em;
  text-transform:uppercase;color:var(--faint)}}
audio{{width:100%}}
.notes{{display:none}}
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
