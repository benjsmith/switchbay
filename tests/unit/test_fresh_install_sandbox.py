"""Simulate a new-Mac install: no Claude Code, CE only in ~/.agents."""

from __future__ import annotations

import os
from pathlib import Path

from switchbay import cebridge, skillkit


def test_ce_root_prefers_agents_without_claude(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    agents = home / ".agents" / "skills" / "curiosity-engine"
    (agents / "scripts").mkdir(parents=True)
    (agents / "scripts" / "setup.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (agents / "SKILL.md").write_text(
        "---\nname: curiosity-engine\ndescription: ce\n---\n", encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("SWITCHBAY_CE_ROOT", raising=False)
    # Path.home() follows HOME on Unix.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    root = cebridge.ce_root()
    assert root == agents
    assert cebridge.skill_is_installed()
    assert not (home / ".claude" / "skills").exists()


def test_skillkit_lists_ce_from_agents_only(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    agents = home / ".agents" / "skills"
    ce = agents / "curiosity-engine"
    ce.mkdir(parents=True)
    (ce / "SKILL.md").write_text(
        "---\nname: curiosity-engine\ndescription: Use when curating.\n---\nbody\n",
        encoding="utf-8",
    )
    extra = agents / "my-helper"
    extra.mkdir()
    (extra / "SKILL.md").write_text(
        "---\nname: my-helper\ndescription: Use when helping.\n---\n# hi\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    ws = tmp_path / "ws"
    (ws / ".workbench").mkdir(parents=True)
    names = {s.name for s in skillkit.list_skills(ws)}
    assert "curiosity-engine" in names
    assert "my-helper" in names
    assert skillkit._user_skills_root() == agents


def test_python_pin_is_313() -> None:
    assert cebridge.CE_PYTHON_PIN == "3.13"
    assert cebridge.venv_python_too_new((3, 14)) is True
    assert cebridge.venv_python_too_new((3, 13)) is False
