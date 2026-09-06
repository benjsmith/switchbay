"""Fast wiki-answer path: retrieve + cheap synth + slider-gated check."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from switchbay.agents import fast_lookup
from switchbay.agents import orchestration_policy as policy
from switchbay.agents import orchestration_utility as util
from switchbay.agents.orchestration import plan_from_decision
from switchbay.kernel.hire import (
    CHECK_CONFIRM, CHECK_REVISE, CHECK_SKIP,
    is_fast_class_model, pick_fast_model, pick_kernel_model, strong_check_mode,
)
from switchbay.llmgateway import base


def _avail():
    return [
        ("anthropic", "claude-opus-4"),
        ("gemini", "gemini-3.8-flash"),
        ("mlx", "qwen2.5-7b"),
        ("grok-build", "grok-4.6"),
        ("openai", "gpt-5.6-luna"),
    ]


LOOKUP = "what is FlashAttention?"
WIKI_KNOW = "what do I know about attention?"
VS = "Mamba vs Transformers tradeoffs in this wiki"
RESEARCH = (
    "Search this workspace's knowledge and the open web for Mamba vs Transformer "
    "tradeoffs, fetch one paper-quality URL into the vault, cite vault/ and wiki/ paths."
)


def _write_wiki(workspace: Path, rel: str, body: str) -> None:
    p = workspace / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def test_lookup_features_are_simple_not_research():
    feat = policy.extract_features(LOOKUP, preference=0.0)
    assert feat.lookup is True
    assert feat.research is False
    assert policy.is_fast_lookup_task(feat)
    feat2 = policy.extract_features(WIKI_KNOW, preference=0.5)
    assert feat2.graph is True
    assert policy.is_fast_lookup_task(feat2)
    feat3 = policy.extract_features(
        "search the wiki for FlashAttention", preference=0.2,
    )
    assert feat3.lookup is True
    assert policy.is_fast_lookup_task(feat3)


def test_summarise_is_not_a_lookup():
    feat = policy.extract_features("summarise this paragraph in one line.")
    assert feat.lookup is False
    assert not policy.is_fast_lookup_task(feat)


def test_vs_tradeoff_is_not_a_lookup():
    feat = policy.extract_features(VS, preference=0.6)
    assert feat.research is True
    assert not policy.is_fast_lookup_task(feat)


def test_wiki_web_ingest_is_not_a_lookup():
    feat = policy.extract_features(RESEARCH, preference=1.0)
    assert feat.research is True
    assert not policy.is_fast_lookup_task(feat)


def test_fast_lookup_wins_utility_over_cli_single_and_dag():
    """Design C (retrieve + flash synth) beats A (CLI single) and B (DAG)
    on simple wiki questions; research still prefers a DAG."""
    for s in (0.0, 0.5, 1.0):
        feat = policy.extract_features(WIKI_KNOW, preference=s)
        a = util.make_candidate("single", feat)
        b = util.make_candidate("parallel_diverse_2", feat)
        c = util.make_candidate("fast_lookup", feat)
        assert a and c
        assert c.lnorm < a.lnorm
        assert c.u(s) > a.u(s)
        if b is not None:
            assert c.u(s) > b.u(s)
        d = policy.choose_initial_policy(feat)
        assert d.strategy == "fast_lookup"
        assert d.n_investigators == 1
        assert not d.include_verify

    hard = policy.extract_features(RESEARCH, preference=1.0, provider_diversity=3)
    d = policy.choose_initial_policy(hard)
    assert d.strategy != "fast_lookup"
    assert d.strategy != "single"


def test_plan_from_decision_fast_lookup_is_one_node():
    feat = policy.extract_features(LOOKUP, preference=0.0)
    d = policy.choose_initial_policy(feat)
    plan = plan_from_decision(LOOKUP, d, [])
    assert plan.strategy == "fast_lookup"
    assert len(plan.nodes) == 1


def test_pick_fast_model_prefers_http_flash_over_cli(tmp_path: Path):
    pair = pick_fast_model(workspace=tmp_path, available=_avail(), denied=[])
    assert pair is not None
    assert pair[0] != "grok-build"
    assert is_fast_class_model(pair[1])


def test_pick_fast_model_skips_cli_only_roster(tmp_path: Path):
    pair = pick_fast_model(
        workspace=tmp_path,
        available=[("grok-build", "grok-4.6")],
        denied=[],
    )
    assert pair is None


def test_luna_and_flash_are_fast_class():
    assert is_fast_class_model("gemini-3.8-flash")
    assert is_fast_class_model("gpt-5.6-luna")
    assert not is_fast_class_model("claude-opus-4")
    assert policy.model_strength("gpt-5.6-luna") < policy.model_strength("gpt-5.6")


def test_economy_skips_kernel_check_maximum_does_not(tmp_path: Path):
    synth = ("gemini", "gemini-3.8-flash")
    kernel = pick_kernel_model(workspace=tmp_path, available=_avail(), denied=[])
    assert kernel is not None
    assert kernel != synth
    assert strong_check_mode(0.0, synth=synth, kernel=kernel) == CHECK_SKIP
    assert strong_check_mode(0.5, synth=synth, kernel=kernel) == CHECK_CONFIRM
    assert strong_check_mode(1.0, synth=synth, kernel=kernel) == CHECK_REVISE
    assert strong_check_mode(1.0, synth=synth, kernel=synth) == CHECK_SKIP


def test_apply_check_ok_keeps_draft_rewrite_replaces():
    draft = "FlashAttention tiles the softmax to cut HBM traffic. [[attention]]"
    assert fast_lookup.apply_check(draft, "OK") == draft
    assert fast_lookup.apply_check(draft, "ok.") == draft
    rewritten = fast_lookup.apply_check(
        draft, "REWRITE\nFlashAttention is an IO-aware exact attention. [[flashattention]]",
    )
    assert "IO-aware" in rewritten
    assert rewritten != draft


def test_retrieve_reads_matching_wiki_pages(tmp_path: Path):
    _write_wiki(
        tmp_path, "wiki/concepts/flashattention.md",
        "---\nkind: concept\ntitle: FlashAttention\n---\n\n"
        "# FlashAttention\n\nFlashAttention tiles attention to reduce HBM reads.\n",
    )
    _write_wiki(
        tmp_path, "wiki/concepts/mamba.md",
        "---\nkind: concept\ntitle: Mamba\n---\n\n# Mamba\n\nSelective SSM.\n",
    )
    hits = fast_lookup.retrieve(tmp_path, "what is FlashAttention?")
    assert hits
    pages = {h["page"] for h in hits}
    assert any("flashattention" in p.lower() for p in pages)
    assert any("HBM" in (h.get("content") or "") for h in hits)


def test_retrieve_miss_does_not_invent_hits(tmp_path: Path):
    _write_wiki(
        tmp_path, "wiki/notes/hello.md",
        "---\nkind: note\ntitle: Hello\n---\n\n# Hello\n\nUnrelated note.\n",
    )
    assert fast_lookup.retrieve(tmp_path, "what is FlashAttention?") == []


def test_search_query_drops_stopwords():
    q = fast_lookup.search_query("what do I know about FlashAttention?")
    assert "flashattention" in q.casefold()
    assert "what" not in q.casefold().split()


@pytest.mark.asyncio
async def test_fast_lookup_cancel_marks_run_cancelled(tmp_path: Path, monkeypatch):
    started = asyncio.Event()

    class Hang:
        ID = "openai"
        PROVIDER = {"id": "openai", "default_model": "fake"}

        def has_key(self) -> bool:
            return True

        async def chat_stream(self, req):
            started.set()
            await asyncio.sleep(60)
            yield base.TextChunk(text="late")
            yield base.DoneChunk(stop_reason="end_turn")

    hang = Hang()
    monkeypatch.setattr(
        fast_lookup, "pick_fast_model", lambda **k: ("openai", "fake"),
    )
    monkeypatch.setattr(
        fast_lookup, "pick_kernel_model", lambda **k: ("openai", "fake"),
    )
    monkeypatch.setattr(
        fast_lookup, "strong_check_mode", lambda *a, **k: CHECK_SKIP,
    )
    monkeypatch.setattr(fast_lookup.llmgateway, "get", lambda pid: hang)
    monkeypatch.setattr(
        fast_lookup.conversations, "append_event", lambda *a, **k: None,
    )
    app = {
        "ws_clients": set(), "runs": {}, "run_ws": {}, "thread_id": "th",
    }
    task = asyncio.create_task(fast_lookup.dispatch(
        app, None, "what is attention",
        workspace=tmp_path,
        hits=[{
            "page": "wiki/concepts/attention.md",
            "snippet": "Attention replaced recurrence.",
            "score": 20,
            "wikilink": "[[attention]]",
        }],
        preference=0.0,
        thread_id_override="th",
    ))
    await asyncio.wait_for(started.wait(), timeout=5)
    running = [r for r in app["runs"].values() if r.get("status") == "running"]
    assert running
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    recs = list(app["runs"].values())
    assert recs
    assert recs[0]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_lookup_initial_persistence_failure_settles_run(
    tmp_path: Path, monkeypatch,
):
    from types import SimpleNamespace

    pair = ("openai", "fake")
    provider = SimpleNamespace(
        has_key=lambda: True,
        PROVIDER={"default_model": "fake"},
        ID="openai",
    )
    monkeypatch.setattr(fast_lookup, "pick_fast_model", lambda **k: pair)
    monkeypatch.setattr(fast_lookup, "pick_kernel_model", lambda **k: pair)
    monkeypatch.setattr(fast_lookup, "strong_check_mode", lambda *a, **k: CHECK_SKIP)
    monkeypatch.setattr(fast_lookup.llmgateway, "get", lambda pid: provider)

    def fail_append(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(fast_lookup.conversations, "append_event", fail_append)
    app = {"runs": {}, "ws_clients": set(), "thread_id": "th"}
    result = await fast_lookup.dispatch(
        app, None, "what is attention?",
        workspace=tmp_path, hits=[], preference=0.0,
        thread_id_override="th",
    )
    assert result is None
    assert not any(r.get("status") == "running" for r in app["runs"].values())
    recs = list(app["runs"].values())
    assert recs
    assert recs[0]["status"] == "error"
