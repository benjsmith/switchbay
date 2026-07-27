"""Fixed design system for durable HTML report packages.

Same philosophy as slideshow_html: agents supply content only;
layout/CSS always come from here so quality is provider-agnostic.
"""

from __future__ import annotations

import html as html_lib
from typing import Any


def _e(s: str) -> str:
    return html_lib.escape(s or "", quote=True)


def render_report(
    *,
    title: str,
    sections: list[dict[str, Any]],
    summary: str = "",
    sources: list[str] | None = None,
    wordmark: str = "Switch Bay",
) -> str:
    """Build a scrollable multi-section HTML document.

    Each section: {heading, body_html?|paragraphs?|bullets?, cite?}
    """
    parts: list[str] = []
    if summary:
        parts.append(f'<p class="lede">{_e(summary)}</p>')
    for i, sec in enumerate(sections):
        h = str(sec.get("heading") or f"Section {i + 1}")
        parts.append(f'<section class="sec" id="s{i + 1}">')
        parts.append(f"<h2>{_e(h)}</h2>")
        body_html = sec.get("body_html")
        if body_html:
            parts.append(f'<div class="prose">{body_html}</div>')
        else:
            for p in sec.get("paragraphs") or []:
                parts.append(f"<p>{_e(str(p))}</p>")
            bullets = sec.get("bullets") or []
            if bullets:
                parts.append("<ul>")
                for b in bullets:
                    parts.append(f"<li>{_e(str(b))}</li>")
                parts.append("</ul>")
        cite = str(sec.get("cite") or "")
        if cite:
            parts.append(f'<p class="cite">{_e(cite)}</p>')
        parts.append("</section>")
    if sources:
        parts.append('<footer class="sources"><h3>Sources</h3><ul>')
        for s in sources:
            parts.append(f"<li>{_e(str(s))}</li>")
        parts.append("</ul></footer>")
    return _SHELL.format(
        title=_e(title),
        wordmark=_e(wordmark),
        body="\n".join(parts),
    )


_SHELL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{title}</title>
<style>
:root {{
  --bg:#0c0f16; --panel:#161b26; --line:#262d3b;
  --ink:#e9edf6; --dim:#9aa4ba; --faint:#616a80;
  --accent:#7b93ff;
  --sans:ui-sans-serif,-apple-system,"SF Pro Text","Segoe UI",Roboto,system-ui,sans-serif;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
}}
@media (prefers-color-scheme:light) {{
  :root {{
    --bg:#f5f4ef; --panel:#fff; --line:#e3dfd4;
    --ink:#1a1e28; --dim:#5a6072; --faint:#8b91a1; --accent:#5566e0;
  }}
}}
* {{ box-sizing:border-box }}
body {{
  margin:0; background:var(--bg); color:var(--ink); font-family:var(--sans);
  line-height:1.55; -webkit-font-smoothing:antialiased;
}}
.top {{
  position:sticky; top:0; z-index:5;
  display:flex; align-items:center; justify-content:space-between;
  padding:12px 28px; background:color-mix(in srgb, var(--bg) 92%, transparent);
  backdrop-filter:blur(8px); border-bottom:1px solid var(--line);
  font-family:var(--mono); font-size:11px; letter-spacing:.12em;
  text-transform:uppercase; color:var(--faint);
}}
.top b {{ color:var(--ink); font-weight:600 }}
main {{
  max-width:720px; margin:0 auto; padding:40px 28px 80px;
}}
h1 {{
  font-size:clamp(28px,4vw,40px); line-height:1.12; letter-spacing:-.02em;
  font-weight:640; margin:0 0 12px;
}}
.lede {{ color:var(--dim); font-size:17px; margin:0 0 36px; max-width:58ch }}
.sec {{
  background:var(--panel); border:1px solid var(--line); border-radius:14px;
  padding:22px 24px; margin:0 0 16px;
  border-left:3px solid var(--accent);
}}
.sec h2 {{
  font-size:18px; margin:0 0 12px; font-weight:620;
}}
.sec p {{ margin:0 0 10px; color:var(--ink) }}
.sec ul {{ margin:0; padding-left:1.2em; color:var(--ink) }}
.sec li {{ margin:0 0 6px }}
.cite {{
  font-family:var(--mono); font-size:11px; color:var(--faint); margin:12px 0 0 !important;
}}
.sources {{ margin-top:40px; color:var(--dim); font-size:13px }}
.sources h3 {{
  font-family:var(--mono); font-size:11px; letter-spacing:.14em;
  text-transform:uppercase; color:var(--faint); font-weight:500;
}}
</style>
</head>
<body>
<div class="top"><span><b>{wordmark}</b> · report</span><span>{title}</span></div>
<main>
  <h1>{title}</h1>
  {body}
</main>
</body>
</html>
"""
