"""User-tab metadata + soft-disable state.

Core tabs come from `modestore.DEFAULT_MODE`; pack tabs come from
`packstore.pack_tabs_for(...)`. Anything else in mode.json is a
"user" tab — typically agent-added via "+ New…" or hand-edited.

This module:
  * classifies each tab in `mode.json` as core / pack / user,
  * persists a per-tab enable/disable bit (so users can hide an
    experimental tab without deleting it from mode.json),
  * filters disabled user tabs out of the composed mode.

State file: `<workspace>/.workbench/tabs-state.json`
   { "<tab-id>": false }   # only explicit false entries are recorded
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import modestore
from . import atomicio


_STATE_FILE = "tabs-state.json"


# ── Core-id detection ──────────────────────────────────────────────


def _core_ids() -> set[str]:
    return {
        str(t.get("id"))
        for t in modestore.DEFAULT_MODE.get("tabs", [])
        if isinstance(t, dict) and t.get("id")
    }


def classify_source(tab: dict[str, Any]) -> str:
    """Return 'core' | 'pack' | 'user' | 'system' for one tab dict.
    Honours an explicit `source` if set; otherwise falls back to
    checking against DEFAULT_MODE's ids. `system` marks cross-workspace
    surfaces (the Agents dashboard) the tab strip pins to the right."""
    src = str(tab.get("source") or "").strip()
    if src in ("core", "pack", "user", "system"):
        return src
    return "core" if str(tab.get("id", "")) in _core_ids() else "user"


# ── State persistence ──────────────────────────────────────────────


def _state_path(workspace: Path) -> Path:
    return workspace / ".workbench" / _STATE_FILE


def _load_state(workspace: Path) -> dict[str, bool]:
    p = _state_path(workspace)
    if not p.is_file():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): bool(v) for k, v in raw.items()}


def _save_state(workspace: Path, state: dict[str, bool]) -> None:
    p = _state_path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(p, state)


def is_enabled(workspace: Path, tab_id: str) -> bool:
    state = _load_state(workspace)
    if tab_id in state:
        return state[tab_id]
    return True


def set_enabled(workspace: Path, tab_id: str, enabled: bool) -> None:
    state = _load_state(workspace)
    state[tab_id] = bool(enabled)
    _save_state(workspace, state)


# ── Thread scoping (control surface v1) ───────────────────────────
# A USER tab may carry `"thread": "<thread_id>"` in mode.json: the
# frontend shows it only while that thread is focused, so ad-hoc tabs
# built for one investigation stop crowding every other thread's view.
# Core / pack / system tabs are inherently workspace-level. The field
# flows through _compose_mode untouched (tab dicts pass whole);
# STATE-sync is the eventual richer home for shared tab state.


def set_thread_scope(
    workspace: Path, tab_id: str, thread_id: str | None,
) -> bool:
    """Scope a user tab to a thread, or back to workspace-wide with
    None. Edits mode.json in place. False when the tab is missing or
    isn't user-source."""
    path = workspace / ".workbench" / "mode.json"
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    tabs = data.get("tabs") if isinstance(data, dict) else None
    if not isinstance(tabs, list):
        return False
    for t in tabs:
        if isinstance(t, dict) and str(t.get("id") or "") == tab_id:
            if classify_source(t) != "user":
                return False
            if thread_id:
                t["thread"] = thread_id
            else:
                t.pop("thread", None)
            atomicio.write_json_atomic(path, data)
            return True
    return False


def strip_thread_scopes(workspace: Path) -> int:
    """Unscope every thread-scoped tab. Used by /clear-rail-history —
    the wipe deletes all threads, and reverting tabs to workspace-wide
    beats orphaning them behind ids that can never focus again.
    Returns how many tabs were unscoped."""
    path = workspace / ".workbench" / "mode.json"
    if not path.is_file():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    tabs = data.get("tabs") if isinstance(data, dict) else None
    if not isinstance(tabs, list):
        return 0
    n = 0
    for t in tabs:
        if isinstance(t, dict) and "thread" in t:
            t.pop("thread", None)
            n += 1
    if n:
        atomicio.write_json_atomic(path, data)
    return n


# ── Terminal tabs (popped-out PTY threads) ─────────────────────────
# A terminal tab is a USER tab of kind "terminal" whose
# `payload.thread_id` names an `interactive-pty` thread. There is no
# standing Terminal tab kind in DEFAULT_MODE — each tab exists only
# because the user deliberately popped that terminal out of the rail
# (multi-terminal setups; room for coding-agent TUIs). NOT the same as
# the `thread` scope field: a terminal tab stays visible across thread
# switches — being switchable-to from anywhere is the point.

TERMINAL_TAB_KIND = "terminal"
REPORT_TAB_KIND = "report"
REPORT_TAB_ID = "report"
REPORT_DOC_TAB_KIND = "report-doc"
REPORT_DOC_TAB_ID = "report-doc"
LIBRARY_TAB_KIND = "library"
LIBRARY_TAB_ID = "library"
HTML_DECK_TAB_KIND = "html-deck"
HTML_DECK_TAB_ID = "html-deck"
INTRO_TAB_KIND = "intro"
INTRO_TAB_ID = "intro"
# Easter egg: Settings → "fire thrusters?" opens a temporary Hopper tab
# hosting the bundled Mars Hopper game (static/mars-hopper/).
THRUSTERS_TAB_KIND = "thrusters"
THRUSTERS_TAB_ID = "thrusters"


def add_intro_tab(
    workspace: Path, *, pin_first: bool = False,
) -> dict[str, Any] | None:
    """Ensure the single Intro tab exists — it hosts the bundled
    intro-and-benchmark deck (served at `/api/intro`) in a sandboxed
    iframe. Idempotent. `pin_first` inserts it leftmost (used to greet
    on first install); `/intro` re-adds it (appended) after a close.
    Returns the tab dict, or None when mode.json is unreadable."""
    path = workspace / ".workbench" / "mode.json"
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    else:
        data = json.loads(json.dumps(modestore.DEFAULT_MODE))
    if not isinstance(data, dict):
        return None
    tabs = data.setdefault("tabs", [])
    if not isinstance(tabs, list):
        return None
    for t in tabs:
        if isinstance(t, dict) and t.get("kind") == INTRO_TAB_KIND:
            return t
    tab = {"id": INTRO_TAB_ID, "title": "Intro", "kind": INTRO_TAB_KIND,
           "source": "user", "payload": {}}
    if pin_first:
        tabs.insert(0, tab)
    else:
        tabs.append(tab)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(path, data)
    return tab


def remove_intro_tab(workspace: Path) -> bool:
    """Drop the Intro tab from mode.json (the tab's own ✕ close).
    Returns True if a tab was removed. The global first-install marker
    stays set, so it won't reappear on the next boot — `/intro` is how
    you bring it back."""
    path = workspace / ".workbench" / "mode.json"
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    tabs = data.get("tabs") if isinstance(data, dict) else None
    if not isinstance(tabs, list):
        return False
    kept = [
        t for t in tabs
        if not (isinstance(t, dict) and t.get("kind") == INTRO_TAB_KIND)
    ]
    if len(kept) == len(tabs):
        return False
    data["tabs"] = kept
    atomicio.write_json_atomic(path, data)
    return True


def thrusters_tab_present(workspace: Path) -> bool:
    """True if the Mars Hopper easter-egg tab is in mode.json."""
    mode = modestore.load(workspace)
    for t in mode.get("tabs") or []:
        if isinstance(t, dict) and t.get("kind") == THRUSTERS_TAB_KIND:
            return True
    return False


def add_thrusters_tab(workspace: Path) -> dict[str, Any] | None:
    """Ensure the temporary Hopper tab exists (Settings easter egg).
    Idempotent; appends. Returns the tab dict, or None on unreadable
    mode.json."""
    path = workspace / ".workbench" / "mode.json"
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    else:
        data = json.loads(json.dumps(modestore.DEFAULT_MODE))
    if not isinstance(data, dict):
        return None
    tabs = data.setdefault("tabs", [])
    if not isinstance(tabs, list):
        return None
    for t in tabs:
        if isinstance(t, dict) and t.get("kind") == THRUSTERS_TAB_KIND:
            return t
    # source "user" so it is closable/ephemeral; kind is filtered out of
    # the Settings → User tabs list so the only on-ramp stays the egg.
    tab = {
        "id": THRUSTERS_TAB_ID,
        "title": "Hopper",
        "kind": THRUSTERS_TAB_KIND,
        "source": "user",
        "payload": {},
    }
    tabs.append(tab)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(path, data)
    return tab


def remove_thrusters_tab(workspace: Path) -> bool:
    """Drop the Hopper easter-egg tab. Returns True if removed."""
    path = workspace / ".workbench" / "mode.json"
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    tabs = data.get("tabs") if isinstance(data, dict) else None
    if not isinstance(tabs, list):
        return False
    kept = [
        t for t in tabs
        if not (isinstance(t, dict) and t.get("kind") == THRUSTERS_TAB_KIND)
    ]
    if len(kept) == len(tabs):
        return False
    data["tabs"] = kept
    atomicio.write_json_atomic(path, data)
    return True


def add_report_tab(workspace: Path) -> dict[str, Any] | None:
    """Ensure the single, reusable Report tab exists (a capable model's
    `create_report` output renders here). Idempotent — one tab hosts
    whatever report the latest `open_report` points at. Returns the tab
    dict, or None when mode.json is unreadable."""
    path = workspace / ".workbench" / "mode.json"
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    else:
        data = json.loads(json.dumps(modestore.DEFAULT_MODE))
    if not isinstance(data, dict):
        return None
    tabs = data.setdefault("tabs", [])
    if not isinstance(tabs, list):
        return None
    for t in tabs:
        if isinstance(t, dict) and t.get("kind") == REPORT_TAB_KIND:
            return t
    tab = {"id": REPORT_TAB_ID, "title": "Report", "kind": REPORT_TAB_KIND,
           "source": "user", "payload": {}}
    tabs.append(tab)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(path, data)
    return tab


def add_html_deck_tab(workspace: Path) -> dict[str, Any] | None:
    """Ensure the reusable Slideshow tab exists (workspace
    ``slideshows/`` HTML presentations). Idempotent — one tab hosts
    whichever show the latest ``open_html_deck`` points at."""
    path = workspace / ".workbench" / "mode.json"
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    else:
        data = json.loads(json.dumps(modestore.DEFAULT_MODE))
    if not isinstance(data, dict):
        return None
    tabs = data.setdefault("tabs", [])
    if not isinstance(tabs, list):
        return None
    for t in tabs:
        if isinstance(t, dict) and t.get("kind") == HTML_DECK_TAB_KIND:
            return t
    tab = {
        "id": HTML_DECK_TAB_ID,
        "title": "Slideshow",
        "kind": HTML_DECK_TAB_KIND,
        "source": "user",
        "payload": {},
    }
    tabs.append(tab)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(path, data)
    return tab


def remove_html_deck_tab(workspace: Path) -> bool:
    """Drop the Slideshow tab from mode.json (the tab's own ✕ close).
    Returns True if a tab was removed. Reopen via `/slideshow <slug>`
    or a ``[[slideshow:…]]`` link."""
    path = workspace / ".workbench" / "mode.json"
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    tabs = data.get("tabs") if isinstance(data, dict) else None
    if not isinstance(tabs, list):
        return False
    kept = [
        t for t in tabs
        if not (isinstance(t, dict) and t.get("kind") == HTML_DECK_TAB_KIND)
    ]
    if len(kept) == len(tabs):
        return False
    data["tabs"] = kept
    atomicio.write_json_atomic(path, data)
    return True


def add_report_doc_tab(workspace: Path) -> dict[str, Any] | None:
    """Ensure the durable report-doc viewer tab exists."""
    path = workspace / ".workbench" / "mode.json"
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    else:
        data = json.loads(json.dumps(modestore.DEFAULT_MODE))
    if not isinstance(data, dict):
        return None
    tabs = data.setdefault("tabs", [])
    if not isinstance(tabs, list):
        return None
    for t in tabs:
        if isinstance(t, dict) and t.get("kind") == REPORT_DOC_TAB_KIND:
            return t
    tab = {
        "id": REPORT_DOC_TAB_ID,
        "title": "Report doc",
        "kind": REPORT_DOC_TAB_KIND,
        "source": "user",
        "payload": {},
    }
    tabs.append(tab)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(path, data)
    return tab


def remove_report_doc_tab(workspace: Path) -> bool:
    path = workspace / ".workbench" / "mode.json"
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    tabs = data.get("tabs") if isinstance(data, dict) else None
    if not isinstance(tabs, list):
        return False
    kept = [
        t for t in tabs
        if not (isinstance(t, dict) and t.get("kind") == REPORT_DOC_TAB_KIND)
    ]
    if len(kept) == len(tabs):
        return False
    data["tabs"] = kept
    atomicio.write_json_atomic(path, data)
    return True


def add_library_tab(workspace: Path) -> dict[str, Any] | None:
    """Ensure Library tab exists (core in DEFAULT_MODE; idempotent add)."""
    path = workspace / ".workbench" / "mode.json"
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    else:
        data = json.loads(json.dumps(modestore.DEFAULT_MODE))
    if not isinstance(data, dict):
        return None
    tabs = data.setdefault("tabs", [])
    if not isinstance(tabs, list):
        return None
    for t in tabs:
        if isinstance(t, dict) and t.get("kind") == LIBRARY_TAB_KIND:
            return t
    tab = {
        "id": LIBRARY_TAB_ID,
        "title": "Library",
        "kind": LIBRARY_TAB_KIND,
        "source": "core",
        "payload": {},
    }
    # Insert before projects when present
    idx = next(
        (i for i, t in enumerate(tabs)
         if isinstance(t, dict) and t.get("kind") == "projects"),
        len(tabs),
    )
    tabs.insert(idx, tab)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(path, data)
    return tab


def add_terminal_tab(
    workspace: Path, thread_id: str, title: str | None,
) -> dict[str, Any] | None:
    """Add a user tab hosting a pty thread. Idempotent by thread —
    popping the same terminal out twice returns the existing tab.
    Returns the tab dict, or None when mode.json is unreadable."""
    path = workspace / ".workbench" / "mode.json"
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    else:
        # Deep-copy DEFAULT_MODE — appending to a shallow copy's tabs
        # list would mutate the shared default in-process.
        data = json.loads(json.dumps(modestore.DEFAULT_MODE))
    if not isinstance(data, dict):
        return None
    tabs = data.setdefault("tabs", [])
    if not isinstance(tabs, list):
        return None
    for t in tabs:
        if (
            isinstance(t, dict)
            and t.get("kind") == TERMINAL_TAB_KIND
            and (t.get("payload") or {}).get("thread_id") == thread_id
        ):
            return t
    tab: dict[str, Any] = {
        "id": f"term-{thread_id[:8]}",
        "title": (title or "Terminal").strip()[:24] or "Terminal",
        "kind": TERMINAL_TAB_KIND,
        "source": "user",
        "payload": {"thread_id": thread_id},
    }
    taken = {str(t.get("id")) for t in tabs if isinstance(t, dict)}
    if tab["id"] in taken:
        tab["id"] = f"term-{thread_id[:12]}"
    tabs.append(tab)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(path, data)
    return tab


def remove_terminal_tabs(
    workspace: Path,
    *,
    tab_id: str | None = None,
    thread_id: str | None = None,
) -> list[str]:
    """Remove terminal tab(s): by tab id (the pop-back-in button), by
    thread id (thread archived), or ALL when neither is given
    (/clear-rail-history — every thread is gone). Returns the removed
    tab ids ([] when nothing matched)."""
    path = workspace / ".workbench" / "mode.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    tabs = data.get("tabs") if isinstance(data, dict) else None
    if not isinstance(tabs, list):
        return []
    removed: list[str] = []
    kept: list[Any] = []
    for t in tabs:
        is_term = (
            isinstance(t, dict)
            and t.get("kind") == TERMINAL_TAB_KIND
            and classify_source(t) == "user"
        )
        match = is_term and (
            (tab_id is None and thread_id is None)
            or (tab_id is not None and str(t.get("id") or "") == tab_id)
            or (
                thread_id is not None
                and (t.get("payload") or {}).get("thread_id") == thread_id
            )
        )
        if match:
            removed.append(str(t.get("id") or ""))
        else:
            kept.append(t)
    if removed:
        data["tabs"] = kept
        atomicio.write_json_atomic(path, data)
    return removed


# ── Listing ────────────────────────────────────────────────────────


def _describe(tab: dict[str, Any]) -> str:
    """Auto-generated one-liner for the Settings list. Best-effort:
    uses the tab kind + id; once tab-kinds carry their own
    descriptions we can pull from there."""
    kind = str(tab.get("kind") or "?")
    title = str(tab.get("title") or "(untitled)")
    tid = str(tab.get("id") or "?")
    return f"{title} · kind: {kind} · id: {tid}"


def list_user_tabs(workspace: Path) -> list[dict[str, Any]]:
    """User-source tabs from mode.json with enabled state +
    auto-generated description. Pack tabs are skipped (they're
    managed via the Packs panel)."""
    mode = modestore.load(workspace)
    tabs = mode.get("tabs") or []
    out: list[dict[str, Any]] = []
    for t in tabs:
        if not isinstance(t, dict):
            continue
        if classify_source(t) != "user":
            continue
        # Easter-egg Hopper tab is toggled only via Settings → fire thrusters?
        if t.get("kind") == THRUSTERS_TAB_KIND:
            continue
        tid = str(t.get("id") or "")
        if not tid:
            continue
        out.append({
            "id": tid,
            "title": str(t.get("title") or ""),
            "kind": str(t.get("kind") or ""),
            "description": _describe(t),
            "enabled": is_enabled(workspace, tid),
        })
    return out
