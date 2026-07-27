"""Rail input prefix parser. Single source of truth — frontend mirrors the
shape but does not parse; it sends raw text and renders the kind from the
daemon's reply.

Recognised prefixes (order matters — `!fn`/`!sql`/`!py` are checked before
plain `!`):

  (no prefix)   → chat
  !fn  <body>   → spreadsheet formula — pushed into the active Sheet
                  tab's formula bar (legacy `!exc` is still accepted).
  !sql <body>   → SQL against state.db / DuckDB
  !py  <body>   → ad-hoc Python in workspace cwd
  !<body>       → terminal command
  /name <args>  → slash command
"""

from __future__ import annotations

import re
from typing import Literal, TypedDict

Kind = Literal["chat", "cmd", "slash", "formula", "sql", "python"]


class Parsed(TypedDict, total=False):
    kind: Kind
    body: str
    name: str   # slash only
    args: str   # slash only


# `!fn` is the canonical spreadsheet-formula prefix. `!exc` is kept as
# an alias for backwards compatibility — existing rules / muscle
# memory don't break. Either resolves to kind="formula" so the
# downstream dispatch can be one branch.
_LANG_RE = {
    "formula": re.compile(r"^!(?:fn|exc)(?:\s+(.*))?$", re.DOTALL),
    "sql": re.compile(r"^!sql(?:\s+(.*))?$", re.DOTALL),
    "python": re.compile(r"^!py(?:\s+(.*))?$", re.DOTALL),
}
_SLASH_RE = re.compile(r"^/(\S+)\s*(.*)$", re.DOTALL)


def parse(text: str) -> Parsed:
    stripped = text.lstrip()
    if not stripped:
        return {"kind": "chat", "body": ""}

    for kind, pattern in _LANG_RE.items():  # type: ignore[assignment]
        m = pattern.match(stripped)
        if m:
            return {"kind": kind, "body": (m.group(1) or "").strip()}  # type: ignore[typeddict-item]

    if stripped.startswith("!"):
        return {"kind": "cmd", "body": stripped[1:]}

    m = _SLASH_RE.match(stripped)
    if m:
        return {"kind": "slash", "name": m.group(1), "args": m.group(2).strip()}

    return {"kind": "chat", "body": stripped}
