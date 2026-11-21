"""Page access is delegated to the system that already owns the item.

Switchbay does not run its own permission server. A page may record
``source_ref`` (a SharePoint item, a Unity Catalog object, and so on).
Before a hit is returned, that system is asked, on behalf of the
caller, whether they can read it. ``same_as`` never adds a hit the
caller cannot read. A page with no source reference uses the
whole-graph read right.

The checker here is a stub. ``deny:`` references are refused.
``readonly:`` references can be read and not written. Anything else is
allowed, which is the whole-graph fallback. A live Work IQ or Unity
Catalog call is not made.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Decision:
    read: bool
    write: bool
    system: str


class SourceChecker:
    """Replace ``check`` with a live on-behalf-of client when one exists."""

    def check(self, source_ref: str, *, write: bool = False) -> Decision:
        ref = (source_ref or "").strip()
        if not ref:
            return Decision(True, True, "whole-graph")
        if ref.startswith("deny:"):
            return Decision(False, False, "source")
        if ref.startswith("readonly:"):
            return Decision(True, False, "source")
        return Decision(True, not write or True, "source-stub")


_CHECKER = SourceChecker()


def checker() -> SourceChecker:
    return _CHECKER


def allows_read(source_ref: str) -> bool:
    return _CHECKER.check(source_ref).read


def allows_write(source_ref: str) -> bool:
    decision = _CHECKER.check(source_ref, write=True)
    if source_ref.strip().startswith("readonly:"):
        return False
    return decision.write and decision.read


def filter_rows(rows: list[dict]) -> list[dict]:
    kept = []
    for row in rows:
        ref = str(row.get("source_ref") or "")
        if ref and not allows_read(ref):
            continue
        also = []
        for extra in row.get("also") or []:
            extra_ref = str(extra.get("source_ref") or "")
            if extra_ref and not allows_read(extra_ref):
                continue
            also.append(extra)
        if "also" in row:
            row = {**row, "also": also}
        kept.append(row)
    return kept


def page_source_ref(workspace: Path, rel: str) -> str:
    path = workspace / rel if rel.startswith("wiki/") else workspace / "wiki" / rel
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    if end < 0:
        return ""
    for line in text[4:end].splitlines():
        if line.startswith("source_ref:"):
            return line.split(":", 1)[1].strip()
    return ""


def may_edit_page(workspace: Path, rel: str) -> tuple[bool, str]:
    ref = page_source_ref(workspace, rel)
    if ref and not allows_write(ref):
        return False, "the source system does not grant edit on this page"
    return True, ""
