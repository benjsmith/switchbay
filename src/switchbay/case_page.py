"""Case home page: the sections a reasoning case has to carry.

The template is ``templates/case_page.md``. ``render`` fills the title.
``missing_sections`` is what claim lint uses for a page with
``role: case`` or ``type: case``.
"""

from __future__ import annotations

import re
from pathlib import Path

TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "case_page.md"

REQUIRED_SECTIONS: tuple[str, ...] = (
    "Objectives",
    "Constraints",
    "Evaluation methods",
    "Success criteria",
    "System context",
)

_HEADING_RE = re.compile(r"^#{2,3}\s+(.+?)\s*$", re.MULTILINE)


def template_text() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def render(title: str, *, summary: str = "") -> str:
    """Fill the case template. ``title`` is plain text, not markdown."""
    safe = (title or "").strip() or "Case"
    text = template_text()
    text = text.replace("{{title}}", safe)
    text = text.replace("{{summary}}", (summary or "").strip())
    return text


def missing_sections(text: str) -> list[str]:
    """Required headings that ``text`` does not contain."""
    found = {m.group(1).strip().lower() for m in _HEADING_RE.finditer(text or "")}
    return [name for name in REQUIRED_SECTIONS if name.lower() not in found]
