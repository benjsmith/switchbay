"""Mars Hopper easter egg: thrusters tab lifecycle + asset allowlist."""

from __future__ import annotations

import json
from pathlib import Path

from switchbay import tabstore
from switchbay.daemon import _mars_hopper_dir, _MARS_HOPPER_FILES


def _kinds(ws: Path) -> list[str]:
    data = json.loads((ws / ".workbench" / "mode.json").read_text())
    return [t.get("kind") for t in data["tabs"]]


def test_add_thrusters_appends_idempotent(tmp_path: Path) -> None:
    tab = tabstore.add_thrusters_tab(tmp_path)
    assert tab is not None
    assert tab["kind"] == tabstore.THRUSTERS_TAB_KIND
    assert tab["title"] == "Hopper"
    assert _kinds(tmp_path).count("thrusters") == 1
    assert _kinds(tmp_path)[-1] == "thrusters"
    tabstore.add_thrusters_tab(tmp_path)
    assert _kinds(tmp_path).count("thrusters") == 1
    assert tabstore.thrusters_tab_present(tmp_path) is True


def test_remove_thrusters(tmp_path: Path) -> None:
    tabstore.add_thrusters_tab(tmp_path)
    assert tabstore.remove_thrusters_tab(tmp_path) is True
    assert tabstore.thrusters_tab_present(tmp_path) is False
    assert "thrusters" not in _kinds(tmp_path)
    assert tabstore.remove_thrusters_tab(tmp_path) is False


def test_hidden_from_user_tabs_list(tmp_path: Path) -> None:
    tabstore.add_thrusters_tab(tmp_path)
    listed = tabstore.list_user_tabs(tmp_path)
    assert all(t.get("kind") != "thrusters" for t in listed)


def test_assets_bundled_and_allowlisted() -> None:
    root = _mars_hopper_dir()
    assert (root / "index.html").is_file()
    assert (root / "game.js").is_file()
    assert (root / "style.css").is_file()
    # Only these names are servable — no path traversal surface.
    assert set(_MARS_HOPPER_FILES.values()) == {
        "index.html", "game.js", "style.css",
    }
    # HTML must not pull third-party scripts/fonts (GH Pages / CDN).
    html = (root / "index.html").read_text(encoding="utf-8")
    assert "googleapis" not in html
    assert "http://" not in html
    assert "https://" not in html
