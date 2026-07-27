"""Workspace path resolution for live-tab HTTP scoping."""

from __future__ import annotations

from pathlib import Path

import pytest

from switchbay import workspaces


def test_resolve_path_default(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(workspaces, "is_within_home", lambda p: True)
    got = workspaces.resolve_path(None, default=tmp_path)
    assert got == tmp_path.resolve()


def test_resolve_path_rejects_outside_home():
    with pytest.raises(workspaces.OutsideHomeError):
        workspaces.resolve_path("/etc")


def test_resolve_path_must_exist(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(workspaces, "is_within_home", lambda p: True)
    missing = tmp_path / "nope"
    with pytest.raises(ValueError, match="not a directory"):
        workspaces.resolve_path(str(missing))
    d = tmp_path / "ws"
    d.mkdir()
    assert workspaces.resolve_path(str(d)) == d.resolve()
