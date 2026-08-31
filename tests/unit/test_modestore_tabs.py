"""Core tab migration: Agents last among core; Schedules dropped."""

from __future__ import annotations

import json
from pathlib import Path

from switchbay import modestore


def test_default_mode_has_agents_last_core_no_schedules() -> None:
    kinds = [t["kind"] for t in modestore.DEFAULT_MODE["tabs"]]
    assert kinds[-1] == "agents"
    assert "schedules" not in kinds
    agents = modestore.DEFAULT_MODE["tabs"][-1]
    assert agents.get("source") in (None, "", "core")


def test_load_promotes_system_agents_and_drops_schedules(tmp_path: Path) -> None:
    wb = tmp_path / ".workbench"
    wb.mkdir()
    (wb / "mode.json").write_text(json.dumps({
        "name": "old",
        "tabs": [
            {"id": "graph", "title": "Graph", "kind": "graph"},
            {"id": "projects", "title": "Projects", "kind": "projects"},
            {"id": "schedules", "title": "Schedules", "kind": "schedules"},
            {"id": "agents", "title": "Agents", "kind": "agents", "source": "system"},
            {"id": "custom", "title": "Custom", "kind": "vega", "source": "user"},
        ],
    }), encoding="utf-8")
    mode = modestore.load(tmp_path)
    kinds = [t.get("kind") for t in mode["tabs"]]
    ids = [t.get("id") for t in mode["tabs"]]
    assert "schedules" not in kinds
    assert ids.count("agents") == 1
    assert ids.index("agents") == ids.index("projects") + 1
    assert ids[-1] == "custom"
    agents = next(t for t in mode["tabs"] if t.get("id") == "agents")
    assert "source" not in agents or agents.get("source") == "core"
