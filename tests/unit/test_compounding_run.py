"""Unit tests for compounding_run depth-study orchestration (no network, no CLI).

The detached curate itself is proven by real runs; these lock the pure logic:
question batching, k-numbering continuing past the breadth checkpoints, regime
tagging, and resumability.

  PYTHONPATH=src:. uv run --no-sync pytest tests/unit/test_compounding_run.py -q
"""
from __future__ import annotations

import json

import pytest

from bench.agentic_query_bench import compounding_run as C


def test_split_contiguous_balanced():
    assert [len(b) for b in C._split(list(range(8)), 4)] == [2, 2, 2, 2]
    assert [len(b) for b in C._split(list(range(8)), 3)] == [3, 3, 2]
    assert [b for b in C._split([1, 2], 5)] == [[1], [2]]  # clamps rounds ≤ items
    # contiguous, order-preserving, lossless
    flat = [x for b in C._split(list(range(8)), 3) for x in b]
    assert flat == list(range(8))


def test_explore_prompt_is_minimal_native():
    p = C._explore_prompt(["How do X and Y differ?", "What recurs across the papers?"])
    assert "NEW analysis" in p and "Do NOT ingest" in p
    assert "1. How do X and Y differ?" in p and "2. What recurs" in p
    # no page-linking / table micro-instructions (per the design)
    assert "link" not in p.lower() and "table" not in p.lower()


def test_skill_scripts_accepts_explicit_install(tmp_path, monkeypatch):
    skill = tmp_path / "curiosity-engine"
    (skill / "scripts").mkdir(parents=True)
    (skill / "scripts" / "setup.sh").write_text("#!/bin/sh\n")
    monkeypatch.setenv("CURIOSITY_ENGINE_SKILL_DIR", str(skill))
    assert C._skill_scripts() == skill / "scripts"


def _fake_breadth_workspace(tmp_path, k_breadth=5):
    (tmp_path / "workspace" / "wiki" / "analyses").mkdir(parents=True)
    (tmp_path / "workspace" / "vault").mkdir(parents=True)
    ck = [{"k": k, "state": {}, "regime": "breadth"} for k in range(1, k_breadth + 1)]
    (tmp_path / "checkpoints.json").write_text(json.dumps(ck))


def _explore_file(tmp_path, n=4):
    p = tmp_path / "explore.json"
    p.write_text(json.dumps({"queries": [{"id": f"q{i}", "q": f"Q{i}?"} for i in range(n)]}))
    return p


def test_run_depth_continues_k_and_tags_regime(tmp_path, monkeypatch):
    _fake_breadth_workspace(tmp_path, k_breadth=5)
    eq = _explore_file(tmp_path, n=4)
    prompts = []
    monkeypatch.setattr(C, "curate",
                        lambda *a, **k: (prompts.append(k.get("prompt")), True)[1])
    monkeypatch.setattr(C, "_snapshot", lambda work, out, k: out / "wiki-snapshots" / f"k{k}")
    monkeypatch.setattr(C, "snapshot_state",
                        lambda work: {"wiki_pages": 100, "vault_sources": 15})

    r = C.run_depth(out_dir=tmp_path, rounds=2, explore_queries=eq, do_eval=False,
                    log=lambda *a: None)

    ck = json.loads((tmp_path / "checkpoints.json").read_text())
    depth = [c for c in ck if c.get("regime") == "depth"]
    assert [c["k"] for c in depth] == [6, 7]          # continues past breadth k=5
    assert r["depth_checkpoints"] == 2 and r["total_checkpoints"] == 7
    assert len(prompts) == 2 and all("NEW analysis" in p for p in prompts)
    # each round got half the 4 questions
    assert depth[0]["questions"] == ["Q0?", "Q1?"] and depth[1]["questions"] == ["Q2?", "Q3?"]


def test_run_depth_resumable(tmp_path, monkeypatch):
    _fake_breadth_workspace(tmp_path, k_breadth=5)
    eq = _explore_file(tmp_path, n=4)
    monkeypatch.setattr(C, "_snapshot", lambda work, out, k: out / "wiki-snapshots" / f"k{k}")
    monkeypatch.setattr(C, "snapshot_state",
                        lambda work: {"wiki_pages": 100, "vault_sources": 15})
    calls = {"n": 0}

    def fake_curate(*a, **k):
        calls["n"] += 1
        return True
    monkeypatch.setattr(C, "curate", fake_curate)

    C.run_depth(out_dir=tmp_path, rounds=2, explore_queries=eq, do_eval=False, log=lambda *a: None)
    assert calls["n"] == 2
    calls["n"] = 0
    C.run_depth(out_dir=tmp_path, rounds=2, explore_queries=eq, do_eval=False, log=lambda *a: None)
    assert calls["n"] == 0  # both depth checkpoints already done → nothing re-run


def test_run_depth_requires_completed_workspace(tmp_path):
    with pytest.raises(SystemExit):
        C.run_depth(out_dir=tmp_path, rounds=2, log=lambda *a: None)  # no workspace/wiki


def test_rewind_depth_restores_and_drops_depth(tmp_path):
    out = tmp_path
    # pre-depth backup (the rewind point) vs the depth-mutated live workspace
    (out / "workspace.pre-depth" / "wiki").mkdir(parents=True)
    (out / "workspace.pre-depth" / "marker.txt").write_text("PREDEPTH")
    (out / "workspace" / "wiki").mkdir(parents=True)
    (out / "workspace" / "marker.txt").write_text("DEPTHMUTATED")
    for k in (1, 5, 6, 7):
        (out / "wiki-snapshots" / f"k{k}").mkdir(parents=True)
    ck = [{"k": k, "state": {}, "regime": "breadth",
           "snapshot": str(out / "wiki-snapshots" / f"k{k}")} for k in range(1, 6)]
    ck += [{"k": k, "state": {}, "regime": "depth", "curator": "claude-sonnet-5",
            "snapshot": str(out / "wiki-snapshots" / f"k{k}")} for k in (6, 7)]
    (out / "checkpoints.json").write_text(json.dumps(ck))
    cells = {f"k{k}|CE|q1": {"answer": "a", "judge_scores": {"j": 0.5}, "mean": 0.5}
             for k in (1, 5, 6, 7)}
    (out / "eval-results.json").write_text(json.dumps({"cells": cells, "generator": "xai"}))
    (out / "eval-report.md").write_text("# prior depth curve")

    r = C.rewind_depth(out, log=lambda *a: None)

    assert r["rewound"] == 2 and r["back_to_k"] == 5
    assert (out / "workspace" / "marker.txt").read_text() == "PREDEPTH"   # restored
    assert [c["k"] for c in json.loads((out / "checkpoints.json").read_text())] == [1, 2, 3, 4, 5]
    assert not (out / "wiki-snapshots" / "k6").exists()                   # depth snap gone
    assert (out / "wiki-snapshots" / "k5").exists()                       # breadth kept
    kept = set(json.loads((out / "eval-results.json").read_text())["cells"])
    assert kept == {"k1|CE|q1", "k5|CE|q1"}                               # depth cells dropped
    assert (out / "eval-report.depth-claude-sonnet-5.md").is_file()       # prior curve archived
    # idempotent: nothing left to rewind
    assert C.rewind_depth(out, log=lambda *a: None)["rewound"] == 0


def test_rewind_depth_fallback_to_snapshot(tmp_path):
    """A depth run that predates the auto-backup has no workspace.pre-depth — rewind
    must fall back to restoring the wiki from the last-breadth snapshot."""
    out = tmp_path
    # NO workspace.pre-depth; live wiki is depth-mutated
    (out / "workspace" / "wiki").mkdir(parents=True)
    (out / "workspace" / "wiki" / "depth-only.md").write_text("added during depth")
    (out / "workspace" / "vault").mkdir()  # untouched by depth
    # the last-breadth (k5) snapshot holds the pre-depth wiki
    (out / "wiki-snapshots" / "k5" / "wiki").mkdir(parents=True)
    (out / "wiki-snapshots" / "k5" / "wiki" / "base.md").write_text("k5 wiki")
    (out / "wiki-snapshots" / "k6").mkdir(parents=True)
    ck = [{"k": k, "state": {}, "regime": "breadth",
           "snapshot": str(out / "wiki-snapshots" / f"k{k}")} for k in range(1, 6)]
    ck += [{"k": 6, "state": {}, "regime": "depth", "curator": "claude-sonnet-5",
            "snapshot": str(out / "wiki-snapshots" / "k6")}]
    (out / "checkpoints.json").write_text(json.dumps(ck))

    r = C.rewind_depth(out, log=lambda *a: None)

    assert r["back_to_k"] == 5 and r["rewound"] == 1
    assert (out / "workspace" / "wiki" / "base.md").is_file()          # restored from k5
    assert not (out / "workspace" / "wiki" / "depth-only.md").exists() # depth wiki gone
    assert [c["k"] for c in json.loads((out / "checkpoints.json").read_text())] == [1, 2, 3, 4, 5]


def test_run_depth_skips_backup_when_depth_already_exists(tmp_path, monkeypatch):
    """The pre-depth backup must only be made at true pre-depth — never when the
    workspace has already been mutated by earlier depth rounds."""
    _fake_breadth_workspace(tmp_path, k_breadth=5)
    ck = json.loads((tmp_path / "checkpoints.json").read_text())
    ck.append({"k": 6, "regime": "depth", "curator": "claude-sonnet-5", "state": {},
               "snapshot": str(tmp_path / "wiki-snapshots" / "k6")})
    (tmp_path / "checkpoints.json").write_text(json.dumps(ck))
    eq = _explore_file(tmp_path, n=4)
    monkeypatch.setattr(C, "curate", lambda *a, **k: True)
    monkeypatch.setattr(C, "_snapshot", lambda work, out, k: out / "wiki-snapshots" / f"k{k}")
    monkeypatch.setattr(C, "snapshot_state", lambda work: {"wiki_pages": 100, "vault_sources": 15})
    C.run_depth(out_dir=tmp_path, rounds=2, explore_queries=eq, do_eval=False, log=lambda *a: None)
    assert not (tmp_path / "workspace.pre-depth").exists()  # guard held
