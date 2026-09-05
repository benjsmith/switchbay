"""Curation plan: chief is the parent; curator is a hired worker."""

from __future__ import annotations

from switchbay.agents import orchestration, orchestration_policy as policy
from switchbay.kernel.packages import CURATOR_ID


def test_curator_node_uses_worker_not_chief_model():
    decision = policy.PolicyDecision(
        strategy="ce_curate",
        n_investigators=1,
        include_verify=False,
        include_reduce=False,
        independence="low",
        allow_expand=False,
        ladder_bias="cheap",
        reason="curate",
        preference=0.0,
    )
    plan = orchestration.plan_from_decision(
        "curate the wiki",
        decision,
        [],
        orchestration_id="run-c1",
        task_kind="curation",
        curator_provider="gemini",
        curator_model="gemini-3.8-flash",
        curator_harness="rail",
    )
    assert plan.strategy == "ce_curate"
    assert len(plan.nodes) == 1
    node = plan.nodes[0]
    assert node.role == "curator"
    assert node.provider == "gemini"
    assert node.model == "gemini-3.8-flash"
    assert node.harness == "rail"
    assert "ce_wave_prime" in node.tools or "ce_wiki_commit" in node.tools


def test_pi_harness_round_trips_on_node():
    decision = policy.PolicyDecision(
        strategy="ce_curate",
        n_investigators=1,
        include_verify=False,
        include_reduce=False,
        independence="low",
        allow_expand=False,
        ladder_bias="cheap",
        reason="curate",
        preference=0.5,
    )
    plan = orchestration.plan_from_decision(
        "curate",
        decision,
        [],
        task_kind="curation",
        curator_provider="anthropic",
        curator_model="claude-sonnet",
        curator_harness="pi",
    )
    blob = plan.to_dict()
    back = orchestration.OrchestrationPlan.from_dict(blob)
    assert back.nodes[0].harness == "pi"
    assert CURATOR_ID == "curator"
