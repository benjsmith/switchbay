"""Workspace path resolution for live-tab HTTP scoping."""

from __future__ import annotations

import os
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


def test_allowed_roots_always_include_home(tmp_path: Path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.delenv("SWITCHBAY_WORKSPACE_ROOTS", raising=False)
    roots = workspaces.allowed_workspace_roots()
    assert fake_home.resolve() in roots


def test_is_within_home_allows_under_fake_home(tmp_path: Path, monkeypatch):
    fake_home = tmp_path / "home"
    ws = fake_home / "Workspaces" / "proj"
    ws.mkdir(parents=True)
    monkeypatch.setattr(
        workspaces, "allowed_workspace_roots", lambda: [fake_home.resolve()]
    )
    assert workspaces.is_within_home(ws) is True
    assert workspaces.is_within_home(fake_home) is True


def test_is_within_home_refuses_etc(tmp_path: Path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(
        workspaces, "allowed_workspace_roots", lambda: [fake_home.resolve()]
    )
    assert workspaces.is_within_home(Path("/etc")) is False
    assert workspaces.is_within_home(Path("/")) is False
    assert workspaces.is_within_home(Path("/tmp")) is False


def test_is_within_home_allows_workspace_root_when_present(tmp_path: Path, monkeypatch):
    """Stand-in for box `/workspace/...` corpora (tmpdir monkeypatch of roots)."""
    box_root = tmp_path / "workspace"
    corpus = box_root / "ce-cb-biocure"
    corpus.mkdir(parents=True)
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(
        workspaces,
        "allowed_workspace_roots",
        lambda: [fake_home.resolve(), box_root.resolve()],
    )
    assert workspaces.is_within_home(corpus) is True
    assert workspaces.is_within_home(Path("/etc")) is False


def test_switchbay_workspace_roots_env_honored(tmp_path: Path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    extra = tmp_path / "extra-root"
    extra.mkdir()
    missing = tmp_path / "missing-root"
    a_file = tmp_path / "not-a-dir"
    a_file.write_text("x", encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setenv(
        "SWITCHBAY_WORKSPACE_ROOTS",
        os.pathsep.join([str(extra), str(missing), str(a_file)]),
    )
    roots = workspaces.allowed_workspace_roots()
    assert fake_home.resolve() in roots
    assert extra.resolve() in roots
    assert all(r != missing.resolve() for r in roots)
    assert all(r != a_file.resolve() for r in roots)
    assert workspaces.is_within_home(extra / "proj") is True


def test_outside_home_error_names_allowed_roots(tmp_path: Path, monkeypatch):
    fake_home = tmp_path / "home"
    box = tmp_path / "workspace"
    fake_home.mkdir()
    box.mkdir()
    monkeypatch.setattr(
        workspaces,
        "allowed_workspace_roots",
        lambda: [fake_home.resolve(), box.resolve()],
    )
    label = workspaces.home_label()
    assert str(fake_home.resolve()) in label
    assert str(box.resolve()) in label
    assert " or " in label
    with pytest.raises(workspaces.OutsideHomeError, match="must live inside") as ei:
        workspaces.resolve_path("/etc")
    assert str(fake_home.resolve()) in str(ei.value)


def test_real_workspace_root_accepted_when_present():
    """On the Grok Bot box, `/workspace/foo` must pass without bind-mount."""
    ws = Path("/workspace")
    if not ws.is_dir():
        pytest.skip("/workspace not present on this host")
    assert ws.resolve() in workspaces.allowed_workspace_roots()
    assert workspaces.is_within_home(ws / "ce-cb-biocure") is True
