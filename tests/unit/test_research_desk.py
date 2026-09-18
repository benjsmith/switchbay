"""Explicit Research desk and Auto web-ingest hire the research package."""

from __future__ import annotations

from pathlib import Path

from switchbay.agents.orchestration import plan_from_decision
from switchbay.agents import orchestration_policy as policy
from switchbay.kernel import (
    DESK_AUTO, DESK_RESEARCH, HireRequest, RESEARCH_ID,
    choose_desk, decide_hire, get_package, packages_for_desk, pick_auto_hires,
)
from switchbay.kernel.packages import RESEARCH_TOOLS
from switchbay.kernel.hire import pick_worker_model


def _avail():
    return [
        ("anthropic", "claude-opus-4"),
        ("gemini", "gemini-3.8-flash"),
        ("mlx", "qwen2.5-7b"),
    ]


def test_research_is_a_desk_and_auto_candidate():
    assert packages_for_desk("research") == (RESEARCH_ID,)
    assert RESEARCH_ID in packages_for_desk("auto")
    assert choose_desk(command="research") == DESK_RESEARCH
    assert choose_desk(task_kind="research") == DESK_RESEARCH
    pkg = get_package(RESEARCH_ID)
    assert pkg is not None
    assert set(RESEARCH_TOOLS) <= set(pkg.tools)
    assert "vault-ingest-research" in pkg.needed_skills


def test_auto_web_ingest_hires_research_package(tmp_path: Path):
    hires = pick_auto_hires(
        "search the web and ingest papers into the vault",
        preference=0.5,
        chief=("anthropic", "claude-opus-4"),
        workspace=tmp_path,
        available=_avail(),
        denied=[],
        chief_tools=["search_wiki"],
        web_ingest=True,
    )
    assert [h.package_id for h in hires] == [RESEARCH_ID]
    assert hires[0].accepted is True
    assert "research_search" in (get_package(RESEARCH_ID).tools or ())


def test_research_plan_uses_package_tools(tmp_path: Path):
    feat = policy.extract_features("search the web for Bahdanau")
    assert feat.web_ingest is True
    decision = policy.decide(feat)
    plan = plan_from_decision(
        "search the web for Bahdanau",
        decision, [],
        task_kind="research",
        workspace=tmp_path,
        available=_avail(),
        denied=[],
    )
    assert plan.strategy == "research"
    assert any(n.role == RESEARCH_ID for n in plan.nodes)
    node = next(n for n in plan.nodes if n.role == RESEARCH_ID)
    assert "research_search" in node.tools
    assert "research_fetch" in node.tools


def test_research_hire_honours_workspace_denylist(tmp_path: Path):
    from switchbay.agents import orchestration_policy as pol
    pol.set_denied_models(["claude-opus-4"], workspace=tmp_path)
    try:
        d = decide_hire(
            HireRequest(
                package_id=RESEARCH_ID,
                justification="research desk",
                needed_tools=["research_search"],
                desk_prior=True,
            ),
            preference=0.5,
            chief=("anthropic", "claude-opus-4"),
            org=[],
            workspace=tmp_path,
            available=_avail(),
            denied=None,
            chief_tools=["search_wiki"],
        )
        assert d.accepted is True
        worker = pick_worker_model(
            preference=0.5,
            chief=("anthropic", "claude-opus-4"),
            workspace=tmp_path,
            available=_avail(),
        )
        assert worker != ("anthropic", "claude-opus-4")
        assert d.model != "claude-opus-4" or d.provider != "anthropic"
    finally:
        pol.set_denied_models([], workspace=tmp_path)


def test_auto_web_research_plan_includes_research_node(tmp_path: Path):
    feat = policy.extract_features("open web search and fetch a paper into the vault")
    decision = policy.decide(feat)
    hires = pick_auto_hires(
        "open web search and fetch a paper into the vault",
        preference=decision.preference,
        chief=("anthropic", "claude-opus-4"),
        workspace=tmp_path,
        available=_avail(),
        denied=[],
        chief_tools=["search_wiki"],
        web_ingest=feat.web_ingest,
    )
    plan = plan_from_decision(
        "open web search and fetch a paper into the vault",
        decision, [{"description": "search"}],
        research_hires=[h.to_dict() for h in hires],
        workspace=tmp_path,
        available=_avail(),
        denied=[],
    )
    roles = [n.role for n in plan.nodes]
    assert RESEARCH_ID in roles or any("research" in (n.node_id or "") for n in plan.nodes)
    tools = []
    for n in plan.nodes:
        if n.role == RESEARCH_ID:
            tools.extend(n.tools)
    assert "research_search" in tools
    assert choose_desk(text="open web search", research=True) == DESK_AUTO
