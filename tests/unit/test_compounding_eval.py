"""Unit tests for compounding_eval (no network, no wiki).

Covers the pure logic: query loading/hash, curve derivation, retrieval-failure
exclusion, family-diverse judge selection, resumability, and judge JSON parsing.
The LLM + retrieval calls are monkeypatched, so this runs offline.

  PYTHONPATH=src:. uv run --no-sync pytest tests/unit/test_compounding_eval.py -q
"""
from __future__ import annotations

from pathlib import Path

import json

import pytest

from bench.agentic_query_bench import compounding_eval as E


def test_load_queries_hash_stable_and_limit():
    qs, h = E.load_queries()
    assert len(qs) == 8 and all("id" in q and "q" in q for q in qs)
    qs2, h2 = E.load_queries()
    assert h == h2  # deterministic
    qsl, hl = E.load_queries(limit=3)
    assert len(qsl) == 3 and hl != h  # limiting changes the hash


def test_arm_context_closed_book_is_empty():
    ctx, pages = E.arm_context("CB", Path("/nonexistent"), "q")
    assert ctx == "" and pages == []


def test_judge_quality_parses_and_clamps(monkeypatch):
    monkeypatch.setattr(E, "llm_call",
                        lambda *a, **k: ('sure! {"score": 0.7, "reason": "good"}', True))
    assert E.judge_quality("xai", "q", "a") == 0.7
    monkeypatch.setattr(E, "llm_call", lambda *a, **k: ('{"score": 1.9}', True))
    assert E.judge_quality("xai", "q", "a") == 1.0  # clamped
    monkeypatch.setattr(E, "llm_call", lambda *a, **k: ("no json here", True))
    assert E.judge_quality("xai", "q", "a") is None
    monkeypatch.setattr(E, "llm_call", lambda *a, **k: ("", False))  # provider error
    assert E.judge_quality("xai", "q", "a") is None


def test_derive_curves_and_retrieval_failure_exclusion():
    queries = [{"id": "q1"}, {"id": "q2"}]
    snaps = [(1, Path("k1")), (2, Path("k2"))]

    def cell(mean, rf=False):
        return {"answer": "a", "judge_scores": {"j": mean}, "mean": mean,
                "retrieval_failure": rf}

    cells = {}
    for k in (1, 2):
        for arm, m in (("CE", 0.8), ("RAG", 0.6), ("CB", 0.5)):
            for q in ("q1", "q2"):
                cells[E._cell_key(k, arm, q)] = cell(m)
    # one RAG cell at k=1 is a retrieval failure → excluded from that arm's mean
    cells[E._cell_key(1, "RAG", "q2")] = cell(0.0, rf=True)

    d = E._derive(cells, snaps, queries)
    r1 = d["per_k"]["1"]
    assert r1["CE"] == 0.8 and r1["CB"] == 0.5
    assert r1["RAG"] == 0.6 and r1["RAG_n"] == 1  # the rf cell dropped
    assert r1["RAG_retrieval_failures"] == 1
    assert r1["CE_minus_RAG"] == pytest.approx(0.2)
    assert r1["CE_minus_CB"] == pytest.approx(0.3)
    assert d["curves"]["k"] == [1, 2]
    assert d["curves"]["CE_minus_RAG"] == [pytest.approx(0.2), pytest.approx(0.2)]


def test_depth_analysis_pools_fixed_controls_and_measures_noise(tmp_path):
    checkpoints = [
        {"k": 5, "regime": "breadth", "state": {"wiki_pages": 100}},
        {"k": 6, "regime": "depth", "curator": "claude-sonnet-5",
         "state": {"wiki_pages": 102}},
        {"k": 7, "regime": "depth", "curator": "claude-sonnet-5",
         "state": {"wiki_pages": 105}},
    ]
    (tmp_path / "checkpoints.json").write_text(json.dumps(checkpoints))
    per_k = {
        "5": {"CE": 0.70, "RAG": 0.60, "CB": 0.65},
        "6": {"CE": 0.74, "RAG": 0.59, "CB": 0.64},
        "7": {"CE": 0.80, "RAG": 0.61, "CB": 0.66},
    }

    d = E._depth_analysis(per_k, tmp_path)

    assert d["start_k"] == 5 and d["depth_ks"] == [6, 7]
    assert d["ce_gain"] == pytest.approx(0.10)
    assert d["rag_pool"] == pytest.approx(0.60)
    assert d["cb_pool"] == pytest.approx(0.65)
    assert d["end_minus_rag_pool"] == pytest.approx(0.20)
    assert d["gain_exceeds_control_noise_sd"] is True
    assert d["wiki_pages_added"] == 5


def _fake_providers(monkeypatch, avail):
    monkeypatch.setattr(E, "available_providers", lambda *a, **k: list(avail))


def test_run_eval_prefers_ungated_providers_and_resumable(tmp_path, monkeypatch):
    # two fake snapshots (only wiki/ needs to exist for discovery)
    for k in (1, 2):
        (tmp_path / "wiki-snapshots" / f"k{k}" / "wiki").mkdir(parents=True)

    _fake_providers(monkeypatch, ["claude-code", "openai-codex", "openai", "xai"])
    monkeypatch.setattr(E, "arm_context",
                        lambda arm, snap, q: (("ctx" if arm != "CB" else ""), ["p"]))
    calls = {"gen": 0}

    def fake_gen(generator, query, arm, context):
        calls["gen"] += 1
        return f"ans::{arm}", True
    monkeypatch.setattr(E, "generate", fake_gen)
    monkeypatch.setattr(E, "judge_quality",
                        lambda judge, q, ans: {"CE": 0.8, "RAG": 0.6, "CB": 0.5}[ans.split("::")[1]])

    res = E.run_eval(tmp_path, limit_q=2, log=lambda *a: None)

    # generator + judges must AVOID gating subscription CLIs (they rate-limit
    # mid-run) — prefer ungated HTTP (openai / xai here), never claude-code /
    # openai-codex, and keep ≥1 non-generator-family judge (xai).
    assert res["generator"].split("=")[0] not in ("claude-code", "openai-codex")
    jprov = {j.split("=")[0] for j in res["judges"]}
    assert jprov.isdisjoint({"claude-code", "openai-codex"})
    assert "xai" in jprov and len(res["judges"]) == 2
    # curve math flows through
    assert res["per_k"]["1"]["CE_minus_RAG"] == pytest.approx(0.2)
    assert res["curves"]["CE_minus_RAG"] == [pytest.approx(0.2), pytest.approx(0.2)]
    # report + results written
    assert (tmp_path / "eval-report.md").is_file()
    assert (tmp_path / "eval-results.json").is_file()

    # resumable: a second run recomputes nothing (generate never called again)
    calls["gen"] = 0
    E.run_eval(tmp_path, limit_q=2, log=lambda *a: None)
    assert calls["gen"] == 0

    # generator switch INVALIDATES the cache (a curve needs one fixed generator)
    calls["gen"] = 0
    E.run_eval(tmp_path, generator="xai", judges=["openai", "openai-codex"],
               limit_q=2, log=lambda *a: None)
    assert calls["gen"] > 0  # recomputed under the new generator
