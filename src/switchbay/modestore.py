"""Load `<workspace>/.workbench/mode.json`.

A mode declares what the workbench shows: pinned center tabs, nav roots,
agent presets, model ladder, default chat agent.

If `mode.json` is missing, `load()` returns `DEFAULT_MODE` so the UI
degrades gracefully on any folder. CE-detect autoinit (a richer default
that wires up CE's pieces) lands in a later step.

Model ladder
------------
The model ladder is a **CE-curation construct** (2026-07-24 reframe):
it configures the models used by CE actions (curate / ingest) and their
fan-out. Three roles:

  · `hard`    → the curate **orchestrator** — defaults to the picker
    selection when unset (an unset rung means "use the picker"); pin it
    only to run curation on a *different* model than the rail.
  · `normal`  → CE fan-out **workers**.
  · `trivial` → cheap CE **sub-calls**.

Ordinary rail chat always uses the picker, never the ladder. Micro-edits
have their OWN fast-model setting (`micro_edits.models`), also decoupled
from this ladder. See `routing_status` for how these surface in the UI.

The optional `model_ladder` field maps difficulty → `{provider, model, effort?}`:

    "model_ladder": {
        "trivial": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001", "effort": "low"},
        "normal":  {"provider": "anthropic", "model": "claude-sonnet-4-6"},
        "hard":    {"provider": "anthropic", "model": "claude-opus-4-7", "effort": "high"}
    }

`effort` is optional. Same model + lower effort is a valid cheaper
rung (no need to pick a weaker model). Unset effort inherits the
picker / pair default via `routing_status.effort_for`.

Each rung names its own provider so a ladder can MIX providers — e.g.
trivial → a small local Ollama model for cheapness, normal → a hosted
Sonnet, hard → Opus for the heavy lifts. Provider-monomorphic ladders
work too: when a provider only exposes one model (some Ollama configs,
a single-model local setup) all three rungs point to
the same (provider, model) and the planner's difficulty rating
becomes a pure annotation.

Missing rung: falls back to the active default provider + its
effective model. Missing ladder entirely: every difficulty falls
back the same way. Workers from `_dispatch_fanout` call
`resolve_for_difficulty(...)` to pick.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from . import atomicio


DIFFICULTIES = ("trivial", "normal", "hard")


DEFAULT_MODE: dict[str, Any] = {
    "name": "default",
    "tabs": [
        {"id": "graph", "title": "Graph", "kind": "graph"},
        {"id": "editor", "title": "Editor", "kind": "markdown"},
        {"id": "table", "title": "Table", "kind": "duckdb"},
        {"id": "spreadsheet", "title": "Sheet", "kind": "univer"},
        {"id": "plot", "title": "Plot", "kind": "vega"},
        {"id": "sketch", "title": "Sketch", "kind": "sketch"},
        {"id": "library", "title": "Library", "kind": "library"},
        {"id": "projects", "title": "Projects", "kind": "projects"},
        # The Agents dashboard is cross-workspace (it sees + steers runs in
        # every workspace), so it's a `system` tab — the strip pins it to
        # the right, after a separator past all other tabs and before
        # "+ New…". (The frontend also treats kind=="agents" as system, so
        # older mode.json files without this `source` get the same place.)
        {"id": "agents", "title": "Agents", "kind": "agents", "source": "system"},
    ],
    # No default ladder — without one, all difficulties resolve to the
    # active provider's effective model and the user-visible behaviour
    # is identical to pre-ladder. Users opt in by populating mode.json
    # or via the Settings panel.
    "model_ladder": {},
}


def load(workspace: Path) -> dict[str, Any]:
    path = workspace / ".workbench" / "mode.json"
    if not path.is_file():
        return DEFAULT_MODE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_MODE
    if not isinstance(data, dict) or "tabs" not in data:
        return DEFAULT_MODE
    # Older mode.json files may predate the ladder; fill the field so
    # consumers can read it unconditionally.
    data.setdefault("model_ladder", {})
    # Migration: the reveal "slides" tab was removed (the Sketch deck
    # carousel is the single deck surface). Drop any persisted slides
    # tab so existing workspaces don't render a now-unregistered kind.
    tabs = data.get("tabs")
    if isinstance(tabs, list):
        filtered = [
            t for t in tabs
            if not (isinstance(t, dict) and t.get("kind") == "slides")
        ]
        if len(filtered) != len(tabs):
            data["tabs"] = filtered
    return data


def sanitize_ladder(raw) -> dict[str, dict[str, str]]:
    """Drop anything that isn't a `{provider, model}` rung keyed by a
    known difficulty. Optional `effort` is kept when non-empty.
    Shared by the workspace and GLOBAL ladders."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for diff in DIFFICULTIES:
        rung = raw.get(diff)
        if not isinstance(rung, dict):
            continue
        provider = str(rung.get("provider") or "").strip()
        model = str(rung.get("model") or "").strip()
        if not provider or not model:
            continue
        row = {"provider": provider, "model": model}
        effort = str(rung.get("effort") or "").strip()
        if effort:
            row["effort"] = effort
        out[diff] = row
    return out


def get_ladder(workspace: Path) -> dict[str, dict[str, str]]:
    """This workspace's OWN ladder rungs (overrides only — see
    `effective_ladder` for what actually applies). Empty dict = no
    per-workspace overrides."""
    return sanitize_ladder(load(workspace).get("model_ladder"))


def global_ladder() -> dict[str, dict[str, str]]:
    """The app-level default ladder (2026-07-05 ruling: ladders apply
    GLOBALLY by default, adjustable per workspace — e.g. a software
    workspace overrides `hard` to a stronger model while a literature
    workspace keeps the defaults). Stored in settings.json."""
    from . import app_settings

    return sanitize_ladder(app_settings.load().get("model_ladder"))


def set_global_ladder(ladder) -> dict[str, dict[str, str]]:
    from . import app_settings

    sanitised = sanitize_ladder(ladder)
    data = app_settings.load()
    data["model_ladder"] = sanitised
    app_settings.save(data)
    return sanitised


def effective_ladder(workspace: Path) -> dict[str, dict[str, str]]:
    """What actually applies: global defaults, overridden RUNG BY RUNG
    by the workspace's own entries."""
    return {**global_ladder(), **get_ladder(workspace)}


def set_ladder(
    workspace: Path, ladder: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    """Persist a (sanitised) ladder back to mode.json. Creates
    mode.json if it didn't exist (preserving the rest of DEFAULT_MODE).
    Returns the saved ladder so callers don't have to re-load."""
    sanitised = sanitize_ladder(ladder)
    path = workspace / ".workbench" / "mode.json"
    if path.is_file():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            current = dict(DEFAULT_MODE)
    else:
        current = dict(DEFAULT_MODE)
    if not isinstance(current, dict):
        current = dict(DEFAULT_MODE)
    current["model_ladder"] = sanitised
    path.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(path, current)
    return sanitised


def resolve_for_difficulty(
    workspace: Path, difficulty: str | None,
) -> tuple[str | None, str | None]:
    """Map difficulty → (provider_id, model). Returns (None, None) when
    no ladder rung applies — caller falls back to the active default
    provider + its effective model. `difficulty=None` matches the
    "normal" rung (so non-fan-out callers can still consult the ladder
    as a default-model override if they want, though currently we
    only use it from fan-out workers)."""
    ladder = effective_ladder(workspace)
    key = difficulty if difficulty in DIFFICULTIES else "normal"
    rung = ladder.get(key)
    if rung is None:
        return None, None
    return rung["provider"], rung["model"]


def rung_effort(workspace: Path, difficulty: str | None) -> str | None:
    """Pinned reasoning effort on a ladder rung, or None to inherit."""
    ladder = effective_ladder(workspace)
    key = difficulty if difficulty in DIFFICULTIES else "normal"
    rung = ladder.get(key)
    if not rung:
        return None
    effort = str(rung.get("effort") or "").strip()
    return effort or None
