"""Hermetic-suite isolation from the developer's own machine state.

Several modules resolve user-global paths lazily at call time —
`workspaces.config_dir()` (→ `~/.config/switchbay/settings.json`) and
`statedir.state_root()` (→ `~/Library/Application Support/switchbay` on
macOS). Anything reading or writing *global* scope therefore reached the
real files when the suite ran, which broke isolation in both directions:

  * **Reads leaked in.** `test_micro_model_decoupled_from_ce_ladder`
    asserted an unset rung resolves to `(None, None)`, but
    `micro_model_for_rung` falls through workspace → global, so a
    developer who had ever picked a micro-edit model failed the test on
    their own machine while CI stayed green.
  * **Writes leaked out.** `set_rung("global", ...)` in
    `test_rung_precedence` wrote straight into the developer's real
    `settings.json`. A test run mutated their preferences.

Both roots honour an environment override, so redirecting those two
vars per-test isolates every module that goes through them — no
per-module monkeypatching, and new tests get it for free. Tests that
patch `config_dir` themselves still win; this only changes where the
unpatched default points.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_user_state(tmp_path_factory, monkeypatch):
    """Point user-global config + state at throwaway dirs."""
    base = tmp_path_factory.mktemp("userstate")
    config = base / "config"
    state = base / "state"
    config.mkdir()
    state.mkdir()
    # workspaces.config_dir() → $XDG_CONFIG_HOME/switchbay
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    # statedir.state_root() → $SWITCHBAY_STATE_DIR
    monkeypatch.setenv("SWITCHBAY_STATE_DIR", str(state))
    return {"config": config, "state": state}
