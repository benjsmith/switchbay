"""CE CURATE worker fan-out: provider spawn vs local fallback."""

from __future__ import annotations

from pathlib import Path

import pytest

from switchbay.agents import ce_workers
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
