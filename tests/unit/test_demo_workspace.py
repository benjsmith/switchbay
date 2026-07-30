"""First-run seeding of the bundled demo workspace.

Guards the three properties that make auto-seeding safe to do on a
user's machine: it runs once, it never overwrites an existing directory,
and it leaves a real workspace alone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from switchbay import demo_workspace, workspaces


@pytest.fixture()
def sandbox(tmp_path: Path, monkeypatch):
    """Redirect home, config dir and the bundled source into tmp."""
    home = tmp_path / "home"
    home.mkdir()
    src = tmp_path / "repo" / "samples" / demo_workspace.DEMO_DIRNAME
    (src / "wiki").mkdir(parents=True)
    (src / "vault").mkdir()
    (src / "wiki" / "index.md").write_text("# demo\n", encoding="utf-8")

    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setattr(workspaces, "config_dir", lambda: home / ".config" / "switchbay")
    monkeypatch.setattr(demo_workspace, "bundled_source", lambda: src)
    return {"home": home, "src": src, "dest": home / "Workspaces" / demo_workspace.DEMO_DIRNAME}


def test_seeds_on_first_run(sandbox):
    dest = demo_workspace.maybe_seed(register=False)
    assert dest == sandbox["dest"]
    assert (dest / "wiki" / "index.md").is_file()
    assert demo_workspace.already_seeded()


def test_is_once_only(sandbox):
    demo_workspace.maybe_seed(register=False)
    # User deletes it; we must NOT silently restore it.
    import shutil

    shutil.rmtree(sandbox["dest"])
    assert demo_workspace.maybe_seed(register=False) is None
    assert not sandbox["dest"].exists()


def test_never_clobbers_existing_directory(sandbox):
    dest = sandbox["dest"]
    dest.mkdir(parents=True)
    (dest / "wiki").mkdir()
    (dest / "wiki" / "index.md").write_text("MINE\n", encoding="utf-8")
    demo_workspace.maybe_seed(register=False)
    assert (dest / "wiki" / "index.md").read_text() == "MINE\n"


def test_no_partial_dir_left_behind(sandbox):
    demo_workspace.maybe_seed(register=False)
    partial = sandbox["dest"].with_name(sandbox["dest"].name + ".partial")
    assert not partial.exists()


def test_marks_when_install_has_no_samples(sandbox, monkeypatch):
    monkeypatch.setattr(
        demo_workspace, "bundled_source", lambda: sandbox["home"] / "nope")
    assert demo_workspace.maybe_seed(register=False) is None
    # Marked, so we don't re-stat a missing dir on every boot.
    assert demo_workspace.already_seeded()


def test_should_prefer_only_for_wiki_less_launch_dir(tmp_path: Path):
    plain = tmp_path / "checkout"
    plain.mkdir()
    real = tmp_path / "ws"
    (real / "wiki").mkdir(parents=True)
    assert demo_workspace.should_prefer(plain) is True
    assert demo_workspace.should_prefer(real) is False
