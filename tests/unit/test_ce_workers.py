"""CE CURATE worker fan-out: provider spawn vs local fallback."""

from __future__ import annotations

from pathlib import Path

import pytest

from switchbay.agents import ce_workers
from switchbay.agents import evidence
from switchbay.agents import orchestration
from switchbay.agents import orchestration_policy as policy
from switchbay.agents.orchestration import plan_from_decision


def test_worker_budget_local_is_zero():
    assert ce_workers.worker_budget(preference=1.0, local=True, configured=10) == 0
    assert ce_workers.worker_budget(preference=0.0, local=True) == 0


def test_worker_budget_slider():
    assert ce_workers.worker_budget(preference=0.1, local=False, configured=10) == 1
    n_bal = ce_workers.worker_budget(preference=0.5, local=False, configured=10)
    n_max = ce_workers.worker_budget(preference=0.95, local=False, configured=10)
    assert 2 <= n_bal <= 4
    assert n_max == min(10, policy.HARD_MAX_CONCURRENCY)
    assert n_max >= n_bal


def test_curator_instructions_provider_vs_local():
    local = ce_workers.curator_worker_instructions(preference=0.8, local=True)
    assert "ARE the worker" in local
    remote = ce_workers.curator_worker_instructions(preference=0.8, local=False)
    assert "ce_dispatch_worker" in remote
    assert "ONE TURN" in remote
    assert "batch_reviewer" in remote


def test_curation_plan_is_still_one_ce_orchestrator():
    feat = policy.extract_features("Run the curator.", preference=1.0)
    policy.apply_task_context(feat, task_kind="curation", constrained=False)
    decision = policy.decide(feat, state=None)
    plan = plan_from_decision("Run the curator.", decision, [], task_kind="curation")
    assert plan.strategy == "ce_curate"
    assert len(plan.nodes) == 1
    assert plan.nodes[0].role == "curator"
    assert "ce_dispatch_worker" in plan.nodes[0].tools


def test_curator_system_prompt_asks_for_fanout(tmp_path: Path):
    node = orchestration.PlanNode(
        node_id="curate", kind="synthesize", objective="curate",
        role="curator",
    )
    text = orchestration._system_for(
        node, preference=0.85, workspace=tmp_path, local=False,
    )
    assert "ce_dispatch_worker" in text
    assert "batch_reviewer" in text
    local = orchestration._system_for(
        node, preference=0.85, workspace=tmp_path, local=True,
    )
    assert "ARE the worker" in local


def test_extra_system_appends_to_package_and_curator():
    node = orchestration.PlanNode(
        node_id="pkg-code-explore", kind="synthesize", objective="map",
        role="code-explore",
    )
    text = orchestration._system_for(node, extra_system="Role lens: sponsor.")
    assert "Role lens: sponsor." in text
    curator = orchestration.PlanNode(
        node_id="curate", kind="synthesize", objective="curate",
        role="curator",
    )
    ctext = orchestration._system_for(
        curator, extra_system="Wave-prime: tables.",
    )
    assert "Wave-prime: tables." in ctext


def test_user_prompt_passes_predecessor_artifacts():
    from switchbay.agents import evidence
    bb = evidence.Blackboard("orch-1")
    bb.append_finding(evidence.Finding(
        claim="repo map",
        node_id="pkg-code-explore",
        notes="src/foo.py owns X",
    ))
    node = orchestration.PlanNode(
        node_id="pkg-code-plan",
        kind="synthesize",
        objective="plan the change",
        role="code-plan",
        dependencies=["pkg-code-explore"],
    )
    prompt = orchestration._user_prompt(node, bb)
    assert "src/foo.py owns X" in prompt
    assert "repo map" in prompt


def test_ce_worker_system_is_not_investigator_json():
    node = orchestration.PlanNode(
        node_id="ce-w0", kind="investigate", objective="brief",
        role="worker", method_hint="ce:worker",
    )
    text = orchestration._system_for(node)
    assert "CURATE worker" in text
    assert '"findings"' not in text


@pytest.mark.asyncio
async def test_run_from_tool_skips_local(tmp_path: Path):
    prompts = tmp_path / ".curator"
    prompts.mkdir()
    (prompts / "prompts.md").write_text(
        "## worker (worker-model)\n\nWrite JSON for <PAGE>.\n",
        encoding="utf-8",
    )
    out = await ce_workers.run_from_tool(
        tmp_path,
        {"role": "worker", "brief": "page A", "substitutions": {"PAGE": "wiki/a.md"}},
        app={},
        parent_run_id="run-x",
        thread_id="th",
        curator_pid="mlx",
        preference=0.8,
    )
    assert out.get("ok")
    assert out.get("spawned") is False
    assert "in-session" in str(out.get("note") or "")
    assert "wiki/a.md" in out.get("prompt", "")


def test_configured_parallel_workers(tmp_path: Path):
    cur = tmp_path / ".curator"
    cur.mkdir()
    (cur / "config.json").write_text(
        '{"parallel_workers": 6}', encoding="utf-8",
    )
    assert ce_workers.configured_parallel_workers(tmp_path) == 6
    assert ce_workers.configured_parallel_workers(tmp_path / "missing") == 10


def _curate_plan() -> orchestration.OrchestrationPlan:
    return orchestration.OrchestrationPlan(
        orchestration_id="o1",
        strategy="curation",
        objective="curate this workspace",
        nodes=[orchestration.PlanNode(
            node_id="curate", kind="synthesize", objective="run CE CURATE",
        )],
    )


def test_cli_dispatch_is_only_the_mcp_shaped_name():
    # The host executes the bare name itself (and spawns a child run);
    # only the CLI-side MCP call needs a dispatch record.
    assert ce_workers.is_cli_dispatch("mcp__switchbay__ce_dispatch_worker")
    assert not ce_workers.is_cli_dispatch("ce_dispatch_worker")
    assert not ce_workers.is_cli_dispatch("ce_wave_prime")
    assert not ce_workers.is_cli_dispatch("")


def test_cli_dispatches_land_on_the_dag_and_the_board():
    plan = _curate_plan()
    parent: dict = {}
    running: set[str] = set()
    completed: set[str] = set()
    ids = [
        ce_workers.register_cli_dispatch(
            plan, parent, {"role": role, "brief": f"do {role}"},
            from_node=plan.nodes[0], running=running,
        )
        for role in ("worker", "worker", "batch_reviewer")
    ]
    assert ids == ["ce-w0", "ce-w1", "ce-rev"]
    orchestration._sync_parent_graph(
        parent, plan, completed=completed, failed=set(), running=running,
    )
    view = {r["node_id"]: r for r in parent["plan_nodes"]}
    assert view["ce-w0"]["kind"] == "investigate"
    assert view["ce-rev"]["kind"] == "verify"       # reviewers verify
    assert view["ce-w1"]["status"] == "running"
    # Each dispatch is visible on the board, which used to sit at zero
    # for the whole run because this path never touched a Blackboard.
    assert parent["blackboard_n"] == 3
    assert len(parent["blackboard_rows"]) == 3
    assert "batch_reviewer" in parent["blackboard_rows"][-1]["claim"]
    # A later DAG sync against the (empty) shared board must keep them.
    orchestration._sync_parent_graph(
        parent, plan, completed=completed, failed=set(), running=running,
        blackboard=evidence.Blackboard("run-ce"),
    )
    assert parent["blackboard_n"] == 3
    assert len(parent["blackboard_rows"]) == 3

    ce_workers.finish_cli_dispatches(ids, running=running, terminal=completed)
    orchestration._sync_parent_graph(
        parent, plan, completed=completed, failed=set(), running=running,
    )
    after = {r["node_id"]: r["status"] for r in parent["plan_nodes"]}
    assert after["ce-w0"] == after["ce-w1"] == after["ce-rev"] == "done"


def test_handback_publishes_findings_or_an_excerpt():
    parent: dict = {}
    ce_workers._publish_handback(
        parent, node_id="ce-w0", role="worker",
        rec={"ok": True, "output": '{"findings": [{"claim": "A is B", '
             '"evidence": [{"source": "wiki/a.md"}]}]}'},
    )
    assert parent["blackboard_n"] == 1
    row = parent["blackboard_rows"][0]
    assert row["claim"] == "A is B"
    assert row["kind"] == "finding"
    assert row["sources"] == 1

    ce_workers._publish_handback(
        parent, node_id="ce-w1", role="worker",
        rec={"ok": True, "output": "plain prose, no findings JSON"},
    )
    assert parent["blackboard_rows"][-1]["kind"] == "handback"
    assert parent["candidate_findings_n"] == 2

    ce_workers._publish_handback(
        parent, node_id="ce-w2", role="worker",
        rec={"ok": False, "error": "provider down"},
    )
    err = parent["blackboard_rows"][-1]
    assert err["kind"] == "error"
    assert "provider down" in err["claim"]
