"""CE run_script bridge + ce_* tool registration."""

from __future__ import annotations

from pathlib import Path

import pytest

from switchbay import cebridge, tools
from switchbay.agents import rail_default


def test_ce_tools_registered_and_allowed():
    names = [
        "ce_vault_search",
        "ce_graph_neighbors",
        "ce_graph_path",
        "ce_shared_sources",
        "ce_bridge_candidates",
    ]
    for n in names:
        assert n in tools.REGISTRY
        assert n in rail_default.ALLOWED_TOOLS
    # Must remain distinct from wiki search (different corpus).
    assert "search_wiki" in tools.REGISTRY
    assert "search_wiki" in rail_default.ALLOWED_TOOLS


def test_run_script_missing_script(tmp_path: Path):
    out = cebridge.run_script("no_such_script_xyz.py", [], cwd=tmp_path)
    assert "error" in out
    assert "not found" in out["error"].lower()


def test_ce_vault_search_invokes_bridge(tmp_path: Path, monkeypatch):
    calls = []

    def fake_run(script, args=None, *, cwd, timeout=120.0):
        calls.append((script, list(args or []), Path(cwd)))
        return {"results": [{"path": "vault/a.md"}], "note": "graph stale"}

    monkeypatch.setattr(cebridge, "run_script", fake_run)
    # tools handler imports cebridge at call time
    out = tools.REGISTRY["ce_vault_search"].handler(
        tmp_path, {"query": "transformers", "limit": 5},
    )
    assert calls
    assert calls[0][0] == "vault_search.py"
    assert "transformers" in calls[0][1]
    assert "--mode" in calls[0][1]
    assert "--graph-expand" in calls[0][1]
    assert out["results"][0]["path"] == "vault/a.md"


def test_ce_graph_neighbors_resolves_page(tmp_path: Path, monkeypatch):
    wiki = tmp_path / "wiki" / "concepts"
    wiki.mkdir(parents=True)
    (wiki / "attention.md").write_text(
        "---\ntitle: Attention\ntype: concept\n---\nbody\n", encoding="utf-8",
    )
    seen = {}

    def fake_run(script, args=None, *, cwd, timeout=120.0):
        seen["args"] = list(args or [])
        return {"neighbors": []}

    monkeypatch.setattr(cebridge, "run_script", fake_run)
    out = tools.REGISTRY["ce_graph_neighbors"].handler(
        tmp_path, {"page": "attention"},
    )
    assert "neighbors" in out or "error" not in out
    # CE wants type/slug.md
    assert any(
        a.endswith("concepts/attention.md") or a == "concepts/attention.md"
        for a in seen["args"]
    )
