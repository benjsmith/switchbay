"""Live Sheet tab focus + compact value preview for the rail agent.

The active cell lives in browser Univer; the frontend POSTs a snapshot
here so MCP tools (`sheet_context`, `sheet_set_formula`) can see what
the user is looking at without parsing opaque Univer workbook JSON.

Stored at `<workspace>/.workbench/state/sheet-focus.json`. Distinct
from the cross-tab `selection` layer — cell clicks must not stomp
page/sketch/plot focus.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import atomicio

# Caps keep agent context small (sheet_context returns this whole blob).
MAX_PREVIEW_ROWS = 30
MAX_PREVIEW_COLS = 12
MAX_CELL_CHARS = 80
FOCUS_STALE_SECONDS = 5 * 60  # system-prompt injection window

_A1_CELL = re.compile(r"^\$?([A-Za-z]+)\$?(\d+)$")
_A1_RANGE = re.compile(
    r"^\$?([A-Za-z]+)\$?(\d+)(?::\$?([A-Za-z]+)\$?(\d+))?$"
)


def _path(workspace: Path) -> Path:
    return workspace / ".workbench" / "state" / "sheet-focus.json"


def load(workspace: Path) -> dict[str, Any] | None:
    p = _path(workspace)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def save(workspace: Path, focus: dict[str, Any]) -> dict[str, Any]:
    """Persist a focus payload. Normalises caps + timestamp."""
    cleaned = _normalise(focus)
    p = _path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(p, cleaned)
    return cleaned


def _normalise(raw: dict[str, Any]) -> dict[str, Any]:
    a1 = str(raw.get("a1") or "").strip().upper()
    rng = str(raw.get("range") or a1 or "").strip().upper()
    sheet_name = str(raw.get("sheet_name") or "").strip() or None
    value = _trunc(raw.get("value"))
    used = str(raw.get("used_range") or "").strip().upper() or None

    headers_in = raw.get("headers")
    headers: list[str] = []
    if isinstance(headers_in, list):
        for h in headers_in[:MAX_PREVIEW_COLS]:
            headers.append(_trunc(h) or "")

    preview_in = raw.get("preview")
    preview: list[list[Any]] = []
    if isinstance(preview_in, list):
        for row in preview_in[:MAX_PREVIEW_ROWS]:
            if not isinstance(row, list):
                continue
            preview.append([
                _cell_val(c) for c in row[:MAX_PREVIEW_COLS]
            ])

    out: dict[str, Any] = {
        "a1": a1 or None,
        "range": rng or None,
        "sheet_name": sheet_name,
        "value": value,
        "used_range": used,
        "headers": headers,
        "preview": preview,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    return out


def _trunc(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v)
    if len(s) > MAX_CELL_CHARS:
        return s[: MAX_CELL_CHARS - 1] + "…"
    return s


def _cell_val(v: Any) -> Any:
    if v is None or isinstance(v, (int, float, bool)):
        return v
    s = str(v)
    if len(s) > MAX_CELL_CHARS:
        return s[: MAX_CELL_CHARS - 1] + "…"
    return s


def col_to_letter(col: int) -> str:
    """0-based column index → A, B, …, Z, AA, …"""
    if col < 0:
        raise ValueError(f"column must be >= 0, got {col}")
    n = col + 1
    letters: list[str] = []
    while n:
        n, rem = divmod(n - 1, 26)
        letters.append(chr(65 + rem))
    return "".join(reversed(letters))


def letter_to_col(letters: str) -> int:
    """A, B, …, Z, AA → 0-based column index."""
    n = 0
    for ch in letters.upper():
        if not ("A" <= ch <= "Z"):
            raise ValueError(f"invalid column letters: {letters!r}")
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def parse_a1_cell(a1: str) -> tuple[int, int]:
    """Parse ``H18`` → (row0, col0). Raises ValueError on bad input."""
    m = _A1_CELL.match(a1.strip())
    if not m:
        raise ValueError(f"invalid A1 cell: {a1!r}")
    col = letter_to_col(m.group(1))
    row = int(m.group(2)) - 1
    if row < 0:
        raise ValueError(f"invalid A1 cell: {a1!r}")
    return row, col


def parse_a1_range(spec: str) -> tuple[int, int, int, int]:
    """Parse ``H18`` or ``C2:H17`` → (r0, c0, n_rows, n_cols)."""
    m = _A1_RANGE.match(spec.strip())
    if not m:
        raise ValueError(f"invalid A1 range: {spec!r}")
    c1 = letter_to_col(m.group(1))
    r1 = int(m.group(2)) - 1
    if m.group(3) is None:
        return r1, c1, 1, 1
    c2 = letter_to_col(m.group(3))
    r2 = int(m.group(4)) - 1
    if r1 < 0 or r2 < 0:
        raise ValueError(f"invalid A1 range: {spec!r}")
    r0, c0 = min(r1, r2), min(c1, c2)
    return r0, c0, abs(r2 - r1) + 1, abs(c2 - c1) + 1


def cell_to_a1(row: int, col: int) -> str:
    return f"{col_to_letter(col)}{row + 1}"


def is_fresh(focus: dict[str, Any] | None, *, max_age_s: float = FOCUS_STALE_SECONDS) -> bool:
    if not focus:
        return False
    ts = focus.get("updated_at")
    if not isinstance(ts, str) or not ts:
        return False
    try:
        when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - when).total_seconds()
    return 0 <= age <= max_age_s


def focus_prompt_line(focus: dict[str, Any] | None) -> str | None:
    """One short system-prompt appendix, or None if nothing useful."""
    if not is_fresh(focus) or not focus:
        return None
    a1 = focus.get("a1")
    if not a1:
        return None
    used = focus.get("used_range") or "?"
    rng = focus.get("range") or a1
    lines = [
        f"UI focus: Sheet cell {a1} selected"
        + (f" (range {rng})" if rng != a1 else "")
        + f". Used range {used}.",
        "Call sheet_context for headers/value preview; "
        "use sheet_set_formula to write formulas (same as user !fn). "
        "Do not search the wiki/deck for the sheet.",
    ]
    return "\n".join(lines)


def normalise_formula(raw: str) -> str:
    s = raw.strip()
    if not s:
        return s
    return s if s.startswith("=") else f"={s}"


def validate_writes(writes: list[Any]) -> list[dict[str, str]]:
    """Validate tool writes → [{cell, formula}, …]. Raises ValueError."""
    if not writes:
        raise ValueError("`writes` must be a non-empty array")
    out: list[dict[str, str]] = []
    for i, item in enumerate(writes):
        if not isinstance(item, dict):
            raise ValueError(f"writes[{i}] must be an object")
        cell = str(item.get("cell") or "").strip().upper()
        formula = normalise_formula(str(item.get("formula") or ""))
        if not cell:
            raise ValueError(f"writes[{i}].cell is required")
        if not formula or formula == "=":
            raise ValueError(f"writes[{i}].formula is required")
        parse_a1_cell(cell)  # raises if bad
        out.append({"cell": cell, "formula": formula})
    return out
