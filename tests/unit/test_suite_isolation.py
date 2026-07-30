"""The hermetic suite must not touch the developer's real user state.

Guards `conftest._isolate_user_state`. Without it, global-scope settings
reads picked up whatever the developer had configured (making tests fail
on their machine but pass in CI) and global-scope writes edited their
real `settings.json`. Both are silent failure modes, so assert the
redirection directly rather than trusting the fixture stays wired up.
"""

from __future__ import annotations

from pathlib import Path

from switchbay import app_settings, micro_edits, statedir, workspaces


def test_config_dir_is_redirected(_isolate_user_state):
    cfg = workspaces.config_dir()
    assert cfg.is_relative_to(_isolate_user_state["config"]), cfg
    assert not cfg.is_relative_to(Path.home() / ".config")


def test_state_root_is_redirected(_isolate_user_state):
    root = statedir.state_root()
    assert root.is_relative_to(_isolate_user_state["state"]), root


def test_global_settings_start_empty():
    """Whatever the developer has configured must not bleed in."""
    assert app_settings.load() == {}


def test_global_writes_land_in_the_sandbox(_isolate_user_state, tmp_path: Path):
    micro_edits.set_rung("global", tmp_path, None, "hard")
    written = _isolate_user_state["config"] / "switchbay" / "settings.json"
    assert written.is_file(), "global write escaped the sandbox"
    assert micro_edits.effective_rung(tmp_path, None) == "hard"
