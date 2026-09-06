"""Walkthrough verb + first-run marker path."""

from __future__ import annotations

from pathlib import Path

from switchbay import verbs
from switchbay.daemon import _walkthrough_marker_path


def test_walkthrough_verb_registered() -> None:
    names = {v.name for v in verbs.all_verbs()}
    assert "walkthrough" in names
    v = next(x for x in verbs.all_verbs() if x.name == "walkthrough")
    assert "tour" in v.aliases or "guide" in v.aliases


def test_work_and_code_verbs_registered() -> None:
    names = {v.name for v in verbs.all_verbs()}
    assert "work" in names
    assert "code" in names
    work = next(x for x in verbs.all_verbs() if x.name == "work")
    assert "steer" in work.aliases
    assert "steering" in work.aliases
    assert "project" not in work.aliases
    code = next(x for x in verbs.all_verbs() if x.name == "code")
    assert "coding" in code.aliases


def test_marker_path_under_config(tmp_path: Path, monkeypatch) -> None:
    from switchbay import workspaces

    monkeypatch.setattr(workspaces, "config_dir", lambda: tmp_path)
    p = _walkthrough_marker_path()
    assert p.parent == tmp_path
    assert p.name == "walkthrough-shown"
    assert not p.is_file()
