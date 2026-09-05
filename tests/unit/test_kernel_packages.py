"""Coding + projects package families: jobs, not titles; write isolation."""

from __future__ import annotations

from pathlib import Path

from switchbay.agents.orchestration import WRITE_TOOLS, plan_from_decision, validate_plan
from switchbay.agents import orchestration_policy as policy
from switchbay.kernel import (
    CODE_EDIT_ID, CODE_EXPLORE_ID, CODE_PLAN_ID, CODE_REVIEW_ID,
    CODING_FAMILY, DESK_PROJECTS, HireRequest, ORG_SYSTEMS_ID,
    PORTFOLIO_BALANCE_ID, PROJECT_COMMS_ID, PROJECT_PLAN_ID,
    PROJECT_REVIEW_ID, PROJECT_SENSE_ID, PROJECTS_FAMILY,
    decide_hire, family_ids, get_package, packages_for_desk,
    pick_family_hires, seat,
)
from switchbay.kernel.packages import WRITES_NONE
from switchbay.kernel.hire import match_projects_packages


def _avail():
    return [
        ("anthropic", "claude-opus-4"),
        ("gemini", "gemini-3.8-flash"),
        ("mlx", "qwen2.5-7b"),
    ]


def test_coding_family_write_isolation():
    assert family_ids("coding") == CODING_FAMILY
    explore = get_package(CODE_EXPLORE_ID)
    plan = get_package(CODE_PLAN_ID)
    edit = get_package(CODE_EDIT_ID)
    review = get_package(CODE_REVIEW_ID)
    assert explore is not None and plan is not None
    assert edit is not None and review is not None
    assert set(explore.tools) & WRITE_TOOLS == set()
    assert "run_command" not in explore.tools
    assert "run_command" in edit.tools
    assert "run_command" not in review.tools
    assert "run_command" not in plan.tools
    plan_writes = set(plan.tools) & WRITE_TOOLS
    assert plan_writes <= {"update_work_plan", "append_workspace_log", "propose_charter_edit"}
    assert "update_work_plan" not in review.tools
    assert "ask_thread" not in review.tools


def test_projects_family_write_isolation():
    assert family_ids("projects") == PROJECTS_FAMILY
    sense = get_package(PROJECT_SENSE_ID)
    pplan = get_package(PROJECT_PLAN_ID)
    comms = get_package(PROJECT_COMMS_ID)
    review = get_package(PROJECT_REVIEW_ID)
    port = get_package(PORTFOLIO_BALANCE_ID)
    org = get_package(ORG_SYSTEMS_ID)
    assert all(x is not None for x in (sense, pplan, comms, review, port, org))
    assert set(sense.tools) & WRITE_TOOLS == set()
    assert "ask_thread" not in pplan.tools
    assert "create_slideshow" not in pplan.tools
    assert "update_work_plan" not in comms.tools
    assert "propose_charter_edit" not in comms.tools
    assert "ask_thread" in comms.tools
    assert "create_slideshow" in comms.tools
    assert "ask_thread" not in review.tools
    assert "update_work_plan" not in review.tools
    assert "create_slideshow" not in review.tools
    assert "ask_thread" not in port.tools
    assert "ask_thread" not in org.tools
    desk = packages_for_desk("projects")
    assert desk == PROJECTS_FAMILY
    assert PROJECT_SENSE_ID in desk and ORG_SYSTEMS_ID in desk


def test_no_human_job_titles_as_packages():
    ids = set(family_ids("coding")) | set(family_ids("projects"))
    for banned in (
        "frontend", "backend", "architect", "security",
        "project-manager", "sponsor", "controller", "resource-manager",
    ):
        assert banned not in ids
        assert get_package(banned) is None


def test_coding_hire_uses_coverage_gap(tmp_path: Path):
    d = decide_hire(
        HireRequest(package_id=CODE_EXPLORE_ID, justification="map the repo"),
        preference=0.0,
        chief=("anthropic", "claude-opus-4"),
        workspace=tmp_path,
        available=_avail(),
        denied=[],
        chief_tools=["search_wiki", "read_wiki_page", "run_command"],
    )
    assert d.accepted is True
    assert d.package_id == CODE_EXPLORE_ID
    assert (d.provider, d.model) != ("anthropic", "claude-opus-4")


def test_match_projects_routes_jobs_not_titles():
    assert match_projects_packages("tell the team the gate slipped")[0] == PROJECT_COMMS_ID
    assert match_projects_packages("balance the portfolio and real options")[0] == PORTFOLIO_BALANCE_ID
    assert match_projects_packages("bottlenecks in the communication network")[0] == ORG_SYSTEMS_ID
    assert match_projects_packages("set targets and metrics for this work-plan")[0] == PROJECT_PLAN_ID
    assert match_projects_packages("scope drift against the plan")[0] == PROJECT_REVIEW_ID
    assert match_projects_packages("what is going on") == [PROJECT_SENSE_ID]


def test_steer_desk_economy_hires_complementary_kinds(tmp_path: Path):
    """One package cannot hold every write-authority. Economy still
    staffs several *different* kinds, on cheap workers."""
    hires = pick_family_hires(
        "executive deck for the board",
        preference=0.0,
        chief=("anthropic", "claude-opus-4"),
        workspace=tmp_path,
        available=_avail(),
        denied=[],
        chief_tools=["search_wiki"],
        desk_prior=True,
    )
    ids = [h.package_id for h in hires]
    assert PROJECT_SENSE_ID in ids
    assert PROJECT_COMMS_ID in ids
    assert PROJECT_REVIEW_ID in ids
    assert PROJECT_PLAN_ID not in ids
    for h in hires:
        if h.package_id == PROJECT_REVIEW_ID:
            assert (h.provider, h.model) == ("anthropic", "claude-opus-4")
        else:
            assert (h.provider, h.model) != ("anthropic", "claude-opus-4")
            assert h.provider in {"mlx", "gemini"}


def test_steer_desk_staffs_core_on_empty(tmp_path: Path):
    hires = pick_family_hires(
        "",
        preference=0.0,
        chief=("anthropic", "claude-opus-4"),
        workspace=tmp_path,
        available=_avail(),
        denied=[],
        chief_tools=["search_wiki"],
        desk_prior=True,
        staff_desk=True,
    )
    ids = [h.package_id for h in hires]
    assert ids[:3] == [PROJECT_SENSE_ID, PROJECT_PLAN_ID, PROJECT_COMMS_ID]
    assert PROJECT_REVIEW_ID in ids


def test_staff_desk_ignores_canned_prompt_hints(tmp_path: Path):
    """Daemon /steer empty prompt contains 'drift' — must not hire only review."""
    prompt = (
        "Staff the steer desk: ground from evidence, keep the plan of record, "
        "send only due messages, check drift. Do not invent status."
    )
    hires = pick_family_hires(
        prompt,
        preference=0.0,
        chief=("anthropic", "claude-opus-4"),
        workspace=tmp_path,
        available=_avail(),
        denied=[],
        chief_tools=["search_wiki"],
        desk_prior=True,
        staff_desk=True,
    )
    ids = [h.package_id for h in hires]
    assert PROJECT_SENSE_ID in ids
    assert PROJECT_PLAN_ID in ids
    assert PROJECT_COMMS_ID in ids


def test_desk_prior_does_not_bypass_clone_refusal(tmp_path: Path):
    d = decide_hire(
        HireRequest(
            package_id=PROJECT_SENSE_ID,
            justification="another sense",
            desk_prior=True,
        ),
        preference=0.0,
        chief=("anthropic", "claude-opus-4"),
        org=[{"package": PROJECT_SENSE_ID}],
        workspace=tmp_path,
        available=_avail(),
        denied=[],
        chief_tools=["search_wiki"],
    )
    assert d.accepted is False
    assert "clone" in d.reason


def test_explore_cannot_validate_create_report():
    from switchbay.agents.orchestration import PlanNode, OrchestrationPlan
    node = PlanNode(
        node_id="pkg-code-explore",
        kind="synthesize",
        objective="map",
        role=CODE_EXPLORE_ID,
        tools=["search_wiki", "create_report"],
        graph_access="read",
        independence="medium",
        output_contract="synthesis",
    )
    plan = OrchestrationPlan(
        orchestration_id="r1", strategy="code", nodes=[node], objective="map",
    )
    errs = validate_plan(plan)
    assert any("create_report" in e for e in errs)


def test_code_review_is_report_only():
    pkg = get_package(CODE_REVIEW_ID)
    assert pkg is not None
    assert "propose_wiki_page" not in pkg.tools
    assert "append_workspace_log" not in pkg.tools
    assert "create_report" in pkg.tools
    assert "run_command" not in pkg.tools


def test_code_desk_economy_hires_explore_and_edit(tmp_path: Path):
    from switchbay.kernel.packages import CODING_FAMILY
    hires = pick_family_hires(
        "implement the patch",
        preference=0.0,
        chief=("anthropic", "claude-opus-4"),
        workspace=tmp_path,
        available=_avail(),
        denied=[],
        chief_tools=["search_wiki", "run_command"],
        desk_prior=True,
        family=CODING_FAMILY,
    )
    ids = [h.package_id for h in hires]
    assert CODE_EXPLORE_ID in ids
    assert CODE_EDIT_ID in ids
    assert CODE_REVIEW_ID in ids
    for h in hires:
        if h.package_id == CODE_REVIEW_ID:
            assert (h.provider, h.model) == ("anthropic", "claude-opus-4")
        else:
            assert h.provider in {"mlx", "gemini"}


def test_projects_plan_nodes_validate(tmp_path: Path):
    hires = pick_family_hires(
        "cited situation of our projects",
        preference=0.0,
        chief=("anthropic", "claude-opus-4"),
        workspace=tmp_path,
        available=_avail(),
        denied=[],
        chief_tools=["search_wiki"],
    )
    decision = policy.PolicyDecision(
        strategy="projects",
        n_investigators=1,
        include_verify=False,
        include_reduce=False,
        independence="medium",
        allow_expand=False,
        ladder_bias="cheap",
        reason="projects",
        preference=0.0,
    )
    plan = plan_from_decision(
        "ground the projects",
        decision,
        [],
        task_kind="projects",
        project_hires=[h.to_dict() for h in hires],
    )
    assert plan.strategy == "projects"
    assert plan.nodes
    assert plan.nodes[0].role == PROJECT_SENSE_ID
    assert get_package(plan.nodes[0].role).writes == WRITES_NONE
    assert validate_plan(plan) == []


def test_family_dag_review_waits_for_writers(tmp_path: Path):
    from switchbay.kernel.packages import CODING_FAMILY
    hires = pick_family_hires(
        "implement the patch",
        preference=0.0,
        chief=("anthropic", "claude-opus-4"),
        workspace=tmp_path,
        available=_avail(),
        denied=[],
        chief_tools=["search_wiki"],
        family=CODING_FAMILY,
        desk_prior=True,
    )
    decision = policy.PolicyDecision(
        strategy="code",
        n_investigators=1,
        include_verify=False,
        include_reduce=False,
        independence="medium",
        allow_expand=False,
        ladder_bias="cheap",
        reason="code",
        preference=0.0,
    )
    plan = plan_from_decision(
        "implement the patch",
        decision,
        [],
        task_kind="code",
        project_hires=[h.to_dict() for h in hires],
    )
    by_id = {n.node_id: n for n in plan.nodes}
    explore = by_id.get("pkg-code-explore")
    edit = by_id.get("pkg-code-edit")
    review = by_id.get("pkg-code-review")
    assert explore is not None and edit is not None and review is not None
    assert explore.dependencies == []
    assert "pkg-code-explore" in edit.dependencies
    assert "pkg-code-edit" in review.dependencies
    assert validate_plan(plan) == []


def test_projects_desk_seats(tmp_path: Path):
    rec = seat(
        tmp_path, DESK_PROJECTS,
        chief_provider="anthropic", chief_model="opus",
        org=[{"package": PROJECT_SENSE_ID, "reports_to": "chief"}],
    )
    assert rec.desk_id == DESK_PROJECTS
    assert rec.org[0]["package"] == PROJECT_SENSE_ID
