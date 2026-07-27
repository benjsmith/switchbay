"""Intro-tab lifecycle in tabstore: seed (pinned-first), idempotency,
close, and /intro re-add. The Intro tab hosts the bundled intro deck
and is seeded once on first install; these guard the mode.json edits
that back that behaviour."""

from __future__ import annotations

import json
from pathlib import Path

from switchbay import tabstore


def _tabs(ws: Path) -> list[str]:
    data = json.loads((ws / ".workbench" / "mode.json").read_text())
    return [t.get("kind") for t in data["tabs"]]


def test_seed_pinned_first_on_fresh_workspace(tmp_path: Path) -> None:
    # No mode.json yet → seeds DEFAULT_MODE plus the Intro tab leftmost.
    tab = tabstore.add_intro_tab(tmp_path, pin_first=True)
    assert tab is not None and tab["kind"] == "intro"
    kinds = _tabs(tmp_path)
    assert kinds[0] == "intro", kinds
    # The default surfaces still follow it.
    assert "graph" in kinds and "agents" in kinds


def test_add_is_idempotent(tmp_path: Path) -> None:
    tabstore.add_intro_tab(tmp_path, pin_first=True)
    tabstore.add_intro_tab(tmp_path, pin_first=True)
    tabstore.add_intro_tab(tmp_path)  # /intro reopen shape
    assert _tabs(tmp_path).count("intro") == 1


def test_reopen_appends_when_not_pinned(tmp_path: Path) -> None:
    # Seed, close, then /intro-style re-add lands at the end.
    tabstore.add_intro_tab(tmp_path, pin_first=True)
    assert tabstore.remove_intro_tab(tmp_path) is True
    assert "intro" not in _tabs(tmp_path)
    tabstore.add_intro_tab(tmp_path)
    assert _tabs(tmp_path)[-1] == "intro"


def test_remove_is_a_noop_when_absent(tmp_path: Path) -> None:
    # A fresh workspace with a real mode.json but no Intro tab.
    tabstore.add_intro_tab(tmp_path, pin_first=True)
    assert tabstore.remove_intro_tab(tmp_path) is True
    assert tabstore.remove_intro_tab(tmp_path) is False
