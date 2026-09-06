"""Deterministic charts for HTML slideshows.

Numbers come from the caller (wiki tables, evidence pages). This module
does not invent values. Output is inline SVG so a deck stays offline
and print-safe. Agent-supplied SVG is rejected — only these builders
may emit markup.
"""

from __future__ import annotations

import html as html_lib
import re
from pathlib import Path
from typing import Any


def _e(s: str) -> str:
    return html_lib.escape(s or "", quote=True)


def chart_points(raw: Any) -> list[dict[str, Any]]:
    """Normalize [{label, value, unit?}] from agent JSON."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("name") or "").strip()
        if not label:
            continue
        try:
            value = float(item.get("value"))
        except (TypeError, ValueError):
            continue
        unit = str(item.get("unit") or "").strip()
        out.append({"label": label, "value": value, "unit": unit})
    return out


def bar_chart_svg(
    points: list[dict[str, Any]],
    *,
    title: str = "",
    accent: str = "#7b93ff",
    ink: str = "#e9edf6",
    dim: str = "#9aa4ba",
    panel: str = "#161b26",
    line: str = "#262d3b",
    width: int = 840,
    height: int = 420,
) -> str:
    """Horizontal bars. One unit per chart — do not mix BLEU with × speedup."""
    pts = [p for p in points if isinstance(p, dict)]
    if not pts:
        return ""
    left, right, top, bot = 200, 96, 36, 28
    inner_w = max(80, width - left - right)
    row_h = max(36, (height - top - bot) / max(1, len(pts)))
    vmax = max(float(p["value"]) for p in pts) or 1.0
    bars = []
    for i, p in enumerate(pts):
        y = top + i * row_h
        bw = max(4.0, inner_w * (float(p["value"]) / vmax))
        unit = str(p.get("unit") or "")
        val = float(p["value"])
        if unit == "%":
            val_s = f"{val:g}%"
        elif unit in {"×", "x"}:
            val_s = f"{val:g}×"
        else:
            val_s = f"{val:g}{(' ' + unit) if unit else ''}"
        label = _e(str(p.get("label") or ""))
        bars.append(
            f'<text x="{left - 12}" y="{y + row_h * 0.55}" text-anchor="end" '
            f'fill="{dim}" font-size="13" font-family="ui-sans-serif,system-ui,'
            f'sans-serif">{label}</text>'
            f'<rect x="{left}" y="{y + 8}" width="{bw:.1f}" height="{row_h - 16:.1f}" '
            f'rx="6" fill="{accent}"/>'
            f'<text x="{left + bw + 10:.1f}" y="{y + row_h * 0.55}" fill="{ink}" '
            f'font-size="14" font-weight="600" font-family="ui-sans-serif,system-ui,'
            f'sans-serif">{_e(val_s)}</text>'
        )
    title_h = ""
    if title:
        title_h = (
            f'<text x="{left}" y="18" fill="{dim}" font-size="11" '
            f'letter-spacing="0.12em" font-family="ui-monospace,monospace">'
            f'{_e(title.upper())}</text>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'role="img" class="chart-svg">'
        f'<rect width="{width}" height="{height}" fill="{panel}" rx="14"/>'
        f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" '
        f'fill="none" stroke="{line}" rx="14"/>'
        f"{title_h}{''.join(bars)}</svg>"
    )


_QUOTE_LINE = re.compile(r"^>\s?(.*)$")


def extract_quote(text: str) -> str:
    """First markdown blockquote in a wiki/evidence page."""
    chunk: list[str] = []
    for line in (text or "").splitlines():
        m = _QUOTE_LINE.match(line)
        if m:
            chunk.append(m.group(1).strip())
            continue
        if chunk:
            break
    text = " ".join(p for p in chunk if p).strip()
    if not text:
        return ""
    # A slide is not an abstract: keep the first sentence when the
    # blockquote runs on.
    parts = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)
    first = parts[0].strip()
    rest = parts[1].strip() if len(parts) > 1 else ""
    if rest and 40 <= len(first) <= 280:
        return first
    if len(text) <= 280:
        return text
    cut = text[:280].rsplit(" ", 1)[0].strip()
    return cut + "…"


def load_quote(workspace: Path, ref: str) -> str:
    raw = str(ref or "").strip()
    if not raw:
        return ""
    raw = raw.replace("\\", "/").strip("/")
    stem = Path(raw).stem
    candidates = [
        Path(workspace) / raw,
        Path(workspace) / f"{raw}.md",
        Path(workspace) / "wiki" / raw,
        Path(workspace) / "wiki" / f"{raw}.md",
        Path(workspace) / "wiki" / "evidence" / f"{stem}.md",
        Path(workspace) / "wiki" / "analyses" / f"{stem}.md",
        Path(workspace) / "wiki" / "sources" / f"{stem}.md",
    ]
    root = Path(workspace).resolve()
    for p in candidates:
        try:
            rp = p.resolve()
            rp.relative_to(root)
        except (OSError, ValueError):
            continue
        if not rp.is_file():
            continue
        try:
            body = rp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        q = extract_quote(body)
        if q:
            return q
    return ""


LLM_SPEAK_RE = re.compile(
    r"\b("
    r"vault-backed|working set|the claim in three moves|"
    r"wiki_topics|spine analysis|only vault-backed|"
    r"hedge anything that is not|"
    r"do not cite"
    r")\b"
    r"|^\s*act\s*[123]\b"
    r"|\bact\s*[123]\s*[·:]",
    re.I,
)


def llm_speak_hits(text: str) -> list[str]:
    return [m.group(0).strip() for m in LLM_SPEAK_RE.finditer(text or "")]
