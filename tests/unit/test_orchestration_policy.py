"""Auto policy, diversity, expansion, telemetry, conservative learning."""

from __future__ import annotations

import random
import time

from switchbay.agents import orchestration_policy as policy
from switchbay.agents import orchestration_utility as util
from switchbay.agents.orchestration import plan_from_decision

RESEARCH = (
    "Research the conflicting evidence about scaling laws in this wiki. "
    "Compare sources and say which claims are actually supported. "
    "Why do the pages disagree?"
)


def test_simple_prompt_stays_n1():
    feat = policy.extract_features("summarise this paragraph in one line.", preference=0.5)
    d = policy.decide(feat, state=None)
    assert d.strategy == "single"
    assert d.n_investigators == 1
    assert d.arm_id in ("single", "single_strong")


def test_maximum_broad_curation_uses_multistage_policy():
    feat = policy.extract_features(
        "Run the curator over this workspace.", preference=1.0,
        provider_diversity=1,
    )
    policy.apply_task_context(feat, task_kind="curation", constrained=False)
    decision = policy.decide(feat, state=None)
    assert decision.n_investigators >= 2
    assert decision.include_verify is True
    assert decision.strategy == "investigate_verify_synthesize"


def test_focused_curation_can_remain_single():
    feat = policy.extract_features(
        "Curate notes.", preference=0.0, provider_diversity=1,
    )
    policy.apply_task_context(feat, task_kind="curation", constrained=True)
    decision = policy.decide(feat, state=None)
    assert decision.strategy == "single"


def test_economy_stays_single_even_for_researchy_short():
    feat = policy.extract_features(
        "research the history of X", preference=0.05,
    )
    d = policy._prior_decision(feat)
    assert d.strategy == "single"


def test_research_plus_balanced_fans_out():
    feat = policy.extract_features(
        "Research the conflicting evidence about scaling laws in this wiki. "
        "Compare sources and say which claims are actually supported. "
        "Why do the pages disagree?",
        preference=0.6,
        provider_diversity=2,
    )
    d = policy._prior_decision(feat)
    assert d.n_investigators >= 2
    assert d.strategy in ("parallel_investigate", "investigate_verify_synthesize")


def test_preference_prices_quality_not_n():
    """Maximum is more willing to *buy* quality; it does not mean more agents."""
    text = (
        "Investigate the wiki evidence on topic T, compare conflicting "
        "pages, and verify which claims hold. Also cover related entities."
    )
    low = policy._prior_decision(policy.extract_features(text, preference=0.2))
    high = policy._prior_decision(policy.extract_features(text, preference=0.9))
    # Economy may still verify; Maximum may still be small. The invariant
    # is that λ falls with s, so the same extra cost is cheaper at Maximum.
    assert policy.cost_weight(0.9) < policy.cost_weight(0.2)
    assert policy.cost_weight(1.0) > 0
    assert high.include_verify or high.n_investigators >= 1
    assert low.n_investigators >= 1


def test_independence_low_for_summarize_high_for_research():
    low = policy.estimate_independence(policy.extract_features("summarise the page"))
    high = policy.estimate_independence(policy.extract_features(
        "Research conflicting evidence and make a consequential decision.",
    ))
    assert low == "low"
    assert high == "high"


def test_diversity_falls_back_to_one_provider(tmp_path):
    alloc = policy.allocate_models(
        3, independence="high", preference=0.9,
        default_provider="openai", default_model="gpt",
        workspace=tmp_path,
        available=[("openai", "gpt")],
    )
    assert len(alloc) == 3
    assert all(p == "openai" for p, _ in alloc)


def test_diversity_uses_distinct_providers_when_available(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "switchbay.modestore.resolve_for_difficulty",
        lambda ws, diff: {
            "hard": ("anthropic", "opus"),
            "normal": ("openai", "gpt"),
            "trivial": ("ollama", "llama"),
        }.get(diff, (None, None)),
    )
    alloc = policy.allocate_models(
        3, independence="high", preference=0.8,
        default_provider="anthropic", default_model="opus",
        workspace=tmp_path,
        available=[("anthropic", "opus"), ("openai", "gpt"), ("xai", "grok")],
    )
    providers = [p for p, _ in alloc]
    assert len(set(providers)) >= 2


def test_copilot_intra_provider_uses_distinct_model_families(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "switchbay.modestore.resolve_for_difficulty", lambda *a, **k: (None, None),
    )
    monkeypatch.setattr(
        "switchbay.admin_policy.provider_allowed",
        lambda pid: pid == "github_copilot",
    )
    monkeypatch.setattr(
        "switchbay.model_cache.get_cached",
        lambda pid: (
            (["gpt-5.4", "gpt-5.4-mini", "claude-sonnet-4.6", "gemini-3.5-flash", "grok-4.6"], True)
            if pid == "github_copilot" else ([], False)
        ),
    )
    alloc = policy.allocate_models(
        3, independence="high", preference=0.8,
        default_provider="github_copilot", default_model="gpt-5.4",
        workspace=tmp_path,
        available=[("github_copilot", "gpt-5.4")],
    )
    assert len(alloc) == 3
    assert all(p == "github_copilot" for p, _ in alloc)
    models = [m for _, m in alloc]
    assert len(set(models)) >= 2
    families = {policy.model_family(m) for m in models}
    assert len(families) >= 2
    assert "gpt-5.4" in models  # default stays in the mix


def test_enterprise_policy_blocks_disallowed_provider_models(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "switchbay.modestore.resolve_for_difficulty",
        lambda ws, diff: ("anthropic", "claude-opus-4") if diff == "hard" else (None, None),
    )
    monkeypatch.setattr(
        "switchbay.admin_policy.provider_allowed",
        lambda pid: pid in ("github_copilot", "ollama"),
    )
    monkeypatch.setattr(
        "switchbay.model_cache.get_cached",
        lambda pid: {
            "github_copilot": (["gpt-5.4", "claude-sonnet-4.6"], True),
            "anthropic": (["claude-opus-4-8", "claude-sonnet-4-6"], True),
        }.get(pid, ([], False)),
    )
    alloc = policy.allocate_models(
        3, independence="high", preference=0.9,
        default_provider="github_copilot", default_model="gpt-5.4",
        workspace=tmp_path,
        available=[("github_copilot", "gpt-5.4"), ("anthropic", "claude-opus-4-8")],
    )
    assert all(p == "github_copilot" for p, _ in alloc)
    assert "anthropic" not in {p for p, _ in alloc}


def test_model_family_splits_copilot_catalog():
    assert policy.model_family("gpt-5.4") == "gpt"
    assert policy.model_family("claude-sonnet-4.6") == "claude"
    assert policy.model_family("google/gemini-3.1-pro-preview") == "gemini"
    assert policy.model_family("grok-4.6") == "grok"
    assert policy.model_family("gpt-5.4") != policy.model_family("claude-sonnet-4.6")


def test_single_model_catalog_repeats_fail_soft(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "switchbay.modestore.resolve_for_difficulty", lambda *a, **k: (None, None),
    )
    monkeypatch.setattr(
        "switchbay.model_cache.get_cached",
        lambda pid: (["only-one"], True),
    )
    alloc = policy.allocate_models(
        3, independence="high", preference=0.8,
        default_provider="github_copilot", default_model="only-one",
        workspace=tmp_path,
        available=[("github_copilot", "only-one")],
    )
    assert alloc == [("github_copilot", "only-one")] * 3


def test_method_hints_differ_for_independent_workers():
    hints = policy.method_hints_for(3, "high")
    assert len(hints) == 3
    assert len(set(hints)) >= 2
    none = policy.method_hints_for(1, "low")
    assert none == [""]


def test_expansion_on_conflicts_and_stop_when_supported():
    go = policy.should_expand(
        preference=0.8, independence="high", allow_expand=True,
        verification={"conflicts": 2, "unsupported": 0, "confidence": 0.4, "unresolved": []},
        findings_n=4, expansions_so_far=0, nodes_so_far=5, remaining_nodes=4,
    )
    assert go.expand and go.n_extra >= 1
    stop = policy.should_expand(
        preference=0.8, independence="high", allow_expand=True,
        verification={"conflicts": 0, "unsupported": 0, "confidence": 0.9, "unresolved": []},
        findings_n=4, expansions_so_far=0, nodes_so_far=5, remaining_nodes=4,
    )
    assert not stop.expand


def test_should_continue_requires_stop_token_and_delta_u():
    yes = policy.should_continue(
        preference=0.9, allow_expand=True, objective_met=True,
        gap="", verification={"conflicts": 2, "confidence": 0.2},
        findings_n=4, expansions_so_far=0, nodes_so_far=5, remaining_nodes=20,
        last_wave_new_findings=2,
    )
    assert not yes.expand
    missing = policy.should_continue(
        preference=0.9, allow_expand=True, objective_met=None,
        gap="need 10-K", verification={"conflicts": 2, "confidence": 0.2},
        findings_n=4, expansions_so_far=0, nodes_so_far=5, remaining_nodes=20,
        last_wave_new_findings=2,
    )
    assert not missing.expand
    concat = policy.should_continue(
        preference=0.9, allow_expand=True, objective_met=False,
        findings_n=4, expansions_so_far=0, nodes_so_far=5, remaining_nodes=20,
        last_wave_new_findings=2, concat=True,
    )
    assert not concat.expand
    idle = policy.should_continue(
        preference=0.9, allow_expand=True, objective_met=False,
        gap="need 10-K", verification={"conflicts": 0, "confidence": 0.3},
        findings_n=4, expansions_so_far=0, nodes_so_far=5, remaining_nodes=20,
        last_wave_new_findings=0,
    )
    assert not idle.expand
    go = policy.should_continue(
        preference=0.9, allow_expand=True, objective_met=False,
        gap="need 10-K excerpts", verification={"conflicts": 0, "unsupported": 0, "confidence": 0.9},
        findings_n=4, expansions_so_far=0, nodes_so_far=5, remaining_nodes=20,
        last_wave_new_findings=2,
    )
    assert go.expand and go.n_extra >= 1


def test_expansion_respects_hard_caps_and_zero_gain():
    cap = policy.should_expand(
        preference=0.9, independence="high", allow_expand=True,
        verification={"conflicts": 3, "unsupported": 2, "confidence": 0.1},
        findings_n=4, expansions_so_far=0,
        nodes_so_far=5, remaining_nodes=1,
    )
    assert not cap.expand
    # Modest extra copy with no gap: even Maximum refuses (ΔQ ≈ 0).
    zero = policy.should_expand(
        preference=1.0, independence="high", allow_expand=True,
        verification={"conflicts": 0, "unsupported": 0, "confidence": 0.95, "unresolved": []},
        findings_n=4, expansions_so_far=0, nodes_so_far=5, remaining_nodes=4,
    )
    assert not zero.expand
    disabled = policy.should_expand(
        preference=0.9, independence="high", allow_expand=False,
        verification={"conflicts": 3}, findings_n=4,
        expansions_so_far=0, nodes_so_far=5, remaining_nodes=4,
    )
    assert not disabled.expand


def test_corrupt_policy_state_falls_back_to_priors(tmp_path, monkeypatch):
    monkeypatch.setenv("SWITCHBAY_STATE_DIR", str(tmp_path / "state"))
    p = policy.policy_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json", encoding="utf-8")
    st = policy.load_state()
    assert st["version"] == policy.POLICY_VERSION
    assert st["buckets"] == {}
    feat = policy.extract_features("hi")
    d = policy.decide(feat, state=st, rng=random.Random(0))
    assert d.strategy == "single"


def test_incompatible_version_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("SWITCHBAY_STATE_DIR", str(tmp_path / "state"))
    # statedir already isolated by conftest; write a v99 blob.
    p = policy.policy_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"version": 99, "buckets": {"x": {}}}', encoding="utf-8")
    st = policy.load_state()
    assert st["buckets"] == {}


def test_reset_clears_arms():
    st = policy.empty_state()
    st["buckets"]["k"] = {"arms": {"single": {"n": 4, "sum_reward": 2.0}}}
    policy.save_state(st)
    policy.reset_state()
    loaded = policy.load_state()
    assert loaded["buckets"] == {}
    assert loaded["totals"]["resets"] >= 1


def test_exploration_stays_nearby_and_inside_preference():
    feat = policy.extract_features(
        "Research conflicting wiki evidence about T and verify sources.",
        preference=0.6,
    )
    prior = policy._prior_decision(feat)
    st = policy.empty_state()
    seen_explore = False
    for seed in range(80):
        d = policy.decide(feat, state=st, rng=random.Random(seed))
        if d.explored:
            seen_explore = True
            assert d.arm_id != "swarm_8"
            neighbors = policy._arm_neighbors(prior.arm_id)
            assert d.arm_id in neighbors or d.arm_id == prior.arm_id or d.arm_id == "single"
    assert "swarm_8" not in policy._arm_neighbors("ivs_diverse_3")
    assert len(policy._arm_neighbors("ivs_diverse_2")) <= 5
    _ = seen_explore


def test_learning_never_raises_hard_bounds():
    inspect = policy.inspect_state()
    assert inspect["hard_bounds"]["max_nodes"] == policy.HARD_MAX_NODES
    # record_outcome updates arms, not bounds
    policy.record_outcome({
        "arm_id": "ivs_diverse_2",
        "features": policy.extract_features("research X " * 20, preference=0.7).to_dict(),
        "preference": 0.7,
        "completed": True,
        "tokens": 1000,
        "latency_s": 12,
        "final_nodes": 4,
        "findings_n": 3,
        "verification_conflicts": 0,
        "unsupported_rejected": 0,
    })
    inspect2 = policy.inspect_state()
    assert inspect2["hard_bounds"]["max_nodes"] == policy.HARD_MAX_NODES
    assert inspect2["totals"]["orchestrations"] >= 1


def test_utility_penalizes_cost_more_in_economy():
    q = 1.0
    u_e = policy._utility(quality=q, cost_tokens=40_000, latency_s=100, preference=0.0)
    u_m = policy._utility(quality=q, cost_tokens=40_000, latency_s=100, preference=1.0)
    assert u_e < u_m


def test_quality_proxy_ignores_review_clicks():
    base = {
        "completed": True, "verifier_confidence": 0.8,
        "unsupported_rejected": 0, "verification_conflicts": 0, "findings_n": 3,
    }
    plain = policy.quality_proxy(base)
    accepted = policy.quality_proxy({**base, "proposal_outcome": "accepted"})
    rejected = policy.quality_proxy({**base, "proposal_outcome": "rejected"})
    assert plain == accepted == rejected


def test_quality_proxy_rewards_landed_docs_and_reuse():
    base = {
        "completed": True, "verifier_confidence": 0.8,
        "unsupported_rejected": 0, "verification_conflicts": 0, "findings_n": 3,
    }
    hollow = policy.quality_proxy(base)
    landed = policy.quality_proxy({**base, "wiki_pages_landed": 2, "reports_landed": 1})
    reused = policy.quality_proxy({**base, "reused_desk_sources": 3})
    assert landed > hollow
    assert reused > hollow
    # Reviews clicks still must not outrank adding docs.
    graded = policy.quality_proxy({**base, "proposal_outcome": "accepted"})
    assert landed > graded


def test_quality_proxy_prefers_verification_over_agent_count():
    good = policy.quality_proxy({
        "completed": True, "verifier_confidence": 0.9,
        "unsupported_rejected": 0, "verification_conflicts": 0, "findings_n": 3,
    })
    bloated = policy.quality_proxy({
        "completed": True, "verifier_confidence": 0.9,
        "unsupported_rejected": 3, "verification_conflicts": 3, "findings_n": 3,
    })
    cancelled = policy.quality_proxy({"cancelled": True})
    assert good > bloated
    assert cancelled == 0.0


def test_a2a_metadata_extension_is_optional():
    from switchbay import a2a
    card = a2a.agent_card(
        workspace_name="w", workspace_path="/tmp/w", port=8765,
        version="0.0.0", provider_default="openai",
    )
    assert card["protocolVersion"] == a2a.PROTOCOL_VERSION
    assert "skills" in card
    assert card["metadata"]["switchbay"]["orchestration"] == "auto"
    # Stable core fields still present.
    assert "url" in card and "capabilities" in card


def test_bandit_is_per_workspace(tmp_path):
    ws_a = tmp_path / "desk-a"
    ws_b = tmp_path / "desk-b"
    ws_a.mkdir()
    ws_b.mkdir()
    feat = policy.extract_features(
        "Research conflicting wiki evidence about T and verify sources.",
        preference=0.7,
    )
    row = {
        "arm_id": "ivs_diverse_2",
        "features": feat.to_dict(),
        "preference": 0.7,
        "completed": True,
        "tokens": 2000,
        "latency_s": 8,
        "final_nodes": 4,
        "findings_n": 3,
        "bucket": feat.bucket(),
    }
    policy.record_outcome(row, ws_a)
    a = policy.inspect_state(ws_a)
    b = policy.inspect_state(ws_b)
    assert a["scope"] == "workspace"
    assert (a.get("totals") or {}).get("orchestrations") == 1
    assert (b.get("totals") or {}).get("orchestrations") in (0, None)
    assert policy.policy_path(ws_a) != policy.policy_path(ws_b)
    assert policy.policy_path(ws_a) != policy.policy_path()
    policy.reset_state(ws_a)
    a2 = policy.inspect_state(ws_a)
    assert (a2.get("totals") or {}).get("orchestrations") == 0
    assert (a2.get("totals") or {}).get("resets") >= 1


def test_n1_token_accounting_is_recorded():
    feat = policy.extract_features("hi")
    policy.record_outcome({
        "arm_id": "single",
        "strategy": "single",
        "features": feat.to_dict(),
        "preference": 0.5,
        "completed": True,
        "tokens": 1800,
        "latency_s": 4.0,
        "final_nodes": 1,
        "findings_n": 0,
    })
    inspect = policy.inspect_state()
    assert inspect["totals"]["orchestrations"] >= 1
    # Cost was not recorded as zero.
    costs = [
        a.get("sum_cost")
        for b in inspect["buckets"]
        for a in b["arms"]
        if a["arm"] == "single" and a["n"] >= 1
    ]
    assert any(c and c >= 1800 for c in costs)


def test_quant_desk_prompt_uses_independent_verified_split():
    text = (
        "Overnight research desk: read SEC 10-K and 8-K filings for the "
        "watchlist, extract EPS vs consensus from earnings transcripts, "
        "flag Form 4 insider cluster buys, and synthesize a morning brief "
        "with high-conviction only on 2+ independent evidence paths."
    )
    feat = policy.extract_features(text, preference=0.65)
    assert feat.finance
    d = policy._prior_decision(feat)
    assert d.n_investigators >= 2
    assert d.include_verify
    assert d.independence == "high"
    hints = policy.method_hints_for(d.n_investigators, d.independence, feat)
    assert any("filing" in h or "earnings" in h or "insider" in h for h in hints)


def test_science_experiment_gets_execute_and_verify():
    text = (
        "Scientific investigation: the hypothesis is that compound X raises "
        "yield. Design the assay protocol with controls, then run the "
        "experiment on the lab system and measure replicates."
    )
    feat = policy.extract_features(text, preference=0.7)
    assert feat.science
    assert feat.experiment
    d = policy._prior_decision(feat)
    assert d.n_investigators >= 2
    assert d.include_verify
    assert d.include_execute


def test_decompose_tasks_are_distinct_without_a_planner():
    feat = policy.extract_features(
        "Research conflicting wiki evidence about T and verify sources.",
        preference=0.7,
    )
    tasks = policy.decompose_tasks(
        "Research conflicting wiki evidence about T and verify sources.",
        3, feat,
    )
    assert len(tasks) == 3
    queries = [t["retrieval_query"] for t in tasks]
    assert len(set(queries)) >= 2
    listed = policy.decompose_tasks(
        "1. What do the 10-K filings say about leverage?\n"
        "2. What did earnings guidance do vs consensus?\n"
        "3. Any Form 4 insider clusters?",
        3, feat,
    )
    assert any("10-K" in t["description"] or "leverage" in t["description"] for t in listed)
    assert any("earnings" in t["description"] or "guidance" in t["description"] for t in listed)


def test_allocate_unused_skips_already_assigned(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "switchbay.modestore.resolve_for_difficulty", lambda *a, **k: (None, None),
    )
    monkeypatch.setattr(
        "switchbay.admin_policy.provider_allowed", lambda pid: pid == "github_copilot",
    )
    monkeypatch.setattr(
        "switchbay.model_cache.get_cached",
        lambda pid: (
            (["gpt-5.4", "claude-sonnet-4.6", "gemini-3.5-flash"], True)
            if pid == "github_copilot" else ([], False)
        ),
    )
    used = [("github_copilot", "gpt-5.4")]
    extra = policy.allocate_unused(
        2, used,
        independence="high", preference=0.8,
        default_provider="github_copilot", default_model="gpt-5.4",
        workspace=tmp_path,
        available=[("github_copilot", "gpt-5.4")],
    )
    assert len(extra) == 2
    assert ("github_copilot", "gpt-5.4") not in extra
    families = {policy.model_family(m) for _, m in extra}
    assert "gpt" not in families
    assert len(families) >= 1


def test_quality_proxy_penalizes_correlated_extra_nodes():
    lean = policy.quality_proxy({
        "completed": True, "verifier_confidence": 0.9,
        "unsupported_rejected": 0, "verification_conflicts": 0,
        "findings_n": 3, "final_nodes": 3, "unique_sources": 3,
    })
    fat = policy.quality_proxy({
        "completed": True, "verifier_confidence": 0.9,
        "unsupported_rejected": 0, "verification_conflicts": 0,
        "findings_n": 3, "final_nodes": 8, "unique_sources": 1,
    })
    assert lean > fat
    # Confidence without evidence yield is not treated as quality.
    hollow = policy.quality_proxy({
        "completed": True, "verifier_confidence": 0.95,
        "unsupported_rejected": 4, "verification_conflicts": 0, "findings_n": 4,
    })
    solid = policy.quality_proxy({
        "completed": True, "verifier_confidence": 0.7,
        "unsupported_rejected": 0, "verification_conflicts": 0, "findings_n": 4,
    })
    assert solid > hollow


def test_plan_from_decision_single_is_one_node():
    feat = policy.extract_features("hi")
    d = policy._prior_decision(feat)
    plan = plan_from_decision("hi", d, [])
    assert len(plan.nodes) == 1
    assert plan.strategy == "single"


def test_curation_plan_has_readers_and_one_ce_writer():
    feat = policy.extract_features(RESEARCH, preference=1.0)
    decision = policy.choose_initial_policy(feat)
    tasks = policy.decompose_tasks(RESEARCH, decision.n_investigators, feat)
    plan = plan_from_decision(
        RESEARCH, decision, tasks, task_kind="curation",
    )
    investigators = [n for n in plan.nodes if n.kind == "investigate"]
    curator = next(n for n in plan.nodes if n.role == "curator")
    assert len(investigators) >= 2
    assert all("ce_run" not in n.tools for n in investigators)
    assert "ce_run" in curator.tools
    assert "ce_graph_rebuild" in curator.tools
    assert plan.decision["task_kind"] == "curation"


def test_a_simple_task_n1_at_every_slider():
    """Extra computation has negligible ΔQ — all s choose N=1."""
    for s in (0.0, 0.5, 1.0):
        feat = policy.extract_features("summarise this paragraph in one line.", preference=s)
        d = policy.choose_initial_policy(feat)
        assert d.n_investigators == 1, (s, d.arm_id, d.n_investigators)
        assert not d.include_verify
        assert d.strategy == "single"


def test_b_maximum_buys_cheap_parallelism():
    """Useful ΔQ + low critical-path ΔL → Maximum chooses parallel independents."""
    feat = policy.extract_features(RESEARCH, preference=1.0)
    d = policy.choose_initial_policy(feat)
    assert d.n_investigators >= 2
    assert d.independence == "high"
    cand = util.make_candidate(d.arm_id, feat)
    assert cand is not None
    # Parallelism: latency not ~N× baseline.
    assert cand.lnorm < 1.0 + 0.6 * d.n_investigators


def test_c_diminishing_returns_prefers_three_over_eight():
    feat = policy.extract_features(RESEARCH, preference=1.0)
    p3 = util.make_candidate("ivs_diverse_3", feat)
    p8 = util.make_candidate("swarm_8", feat)
    assert p3 is not None and p8 is not None
    assert p8.q - p3.q < 0.05
    assert p3.u(1.0) > p8.u(1.0)
    d = policy.choose_initial_policy(feat)
    assert d.n_investigators <= 3
    assert d.arm_id != "swarm_8"


def test_d_better_topology_beats_larger_n():
    feat = policy.extract_features(RESEARCH, preference=0.7)
    two = util.make_candidate("ivs_diverse_2", feat)
    four = util.make_candidate("homog_4", feat)
    assert two is not None and four is not None
    assert two.n_investigators < four.n_investigators
    assert two.u(0.7) > four.u(0.7)
    d = policy.choose_initial_policy(feat)
    assert d.arm_id != "homog_4"
    assert d.include_verify or d.n_investigators <= 3


def test_e_economy_can_still_buy_a_verifier():
    """Consequential + conflicting research: Economy buys verify, not a swarm."""
    feat = policy.extract_features(
        "Make a consequential legal decision based on conflicting wiki "
        "evidence. This must be correct; the result is irreversible.",
        preference=0.0,
    )
    d = policy.choose_initial_policy(feat)
    assert d.include_verify
    assert d.n_investigators == 1
    plan = plan_from_decision("consequential", d, [{"description": "case"}])
    kinds = [n.kind for n in plan.nodes]
    assert "verify" in kinds
    assert sum(1 for n in plan.nodes if n.kind == "investigate") == 1


def test_f_maximum_stops_when_delta_q_is_zero():
    stop = policy.should_expand(
        preference=1.0, independence="high", allow_expand=True,
        verification={
            "conflicts": 0, "unsupported": 0, "confidence": 0.95,
            "unresolved": [],
        },
        findings_n=4, expansions_so_far=0, nodes_so_far=5, remaining_nodes=4,
    )
    assert not stop.expand
    dq = util.estimate_marginal_quality(
        action="redundant_copy",
        verification={"conflicts": 0, "unsupported": 0, "confidence": 0.95},
        findings_n=4, consequence=0.1,
    )
    assert dq <= 0.01


def test_g_same_n_different_policies():
    feat = policy.extract_features(RESEARCH, preference=0.6)
    homog = util.make_candidate("parallel_homog_2", feat)
    diverse = util.make_candidate("ivs_diverse_2", feat)
    assert homog is not None and diverse is not None
    assert homog.n_investigators == diverse.n_investigators == 2
    assert homog.include_verify != diverse.include_verify
    assert diverse.u(1.0) > homog.u(1.0)
    # Economy still prices the extra verifier; it may prefer the cheaper pair.
    assert homog.u(0.0) != diverse.u(0.0)


def test_lambda_floors_never_zero():
    assert policy.cost_weight(1.0) == util.LAMBDA_C_FLOOR
    assert policy.latency_weight(1.0) == util.LAMBDA_L_FLOOR
    assert policy.cost_weight(0.0) == util.LAMBDA_C_MAX
    assert policy.cost_weight(0.5) < policy.cost_weight(0.0)
    assert policy.cost_weight(0.5) > policy.cost_weight(1.0)


def test_quality_proxy_ignores_provider_outages():
    """Channel failure must not unlearn a good topology."""
    base = {
        "completed": True, "verifier_confidence": 0.9,
        "unsupported_rejected": 0, "verification_conflicts": 0, "findings_n": 3,
    }
    healthy = policy.quality_proxy(base)
    outage = policy.quality_proxy({**base, "worker_failures": 2})
    assert healthy == outage


def test_allocation_notice_explains_non_picker_workers():
    text = policy.format_allocation_notice(
        [("grok_build", "grok-4.6"), ("claude_code", "claude-sonnet-4-6")],
        rail_provider="grok_build",
        rail_model="grok-4.6",
    )
    assert "Testing provider availability" in text
    assert "grok_build/grok-4.6" in text
    assert "claude_code" in text
    same = policy.format_allocation_notice(
        [("grok_build", "grok-4.6"), ("grok_build", "grok-4.6")],
        rail_provider="grok_build",
        rail_model="grok-4.6",
    )
    assert "Testing provider availability" not in same


def test_allocate_skips_cooled_provider(tmp_path, monkeypatch):
    from switchbay.agents import orchestration_health as health
    monkeypatch.setattr(
        "switchbay.admin_policy.provider_allowed", lambda pid: True,
    )
    monkeypatch.setattr(
        "switchbay.modestore.resolve_for_difficulty", lambda *a, **k: (None, None),
    )
    health.note_failure(
        "claude_code",
        "ProviderError: You've hit your weekly limit - resets Aug 26 at 11pm (Europe/Zurich)",
    )
    assert not health.is_available("claude_code")
    alloc = policy.allocate_models(
        3, independence="high", preference=0.9,
        default_provider="grok_build", default_model="grok-4.6",
        workspace=tmp_path,
        available=[("grok_build", "grok-4.6"), ("claude_code", "claude-sonnet-4-6")],
        playbook_roster=[],
    )
    assert all(p != "claude_code" for p, _ in alloc)
    assert alloc[0] == ("grok_build", "grok-4.6")


def test_credit_error_is_not_a_weekly_limit():
    from switchbay.agents import orchestration_health as health
    assert health.classify_error("insufficient_quota: credit balance") == "credit"
    assert health.classify_error(
        "You've hit your weekly limit - resets Aug 26 at 11pm (Europe/Zurich)"
    ) == "weekly_limit"
    rec = health.note_failure("openai", "OpenAI: insufficient_funds / out of credits")
    assert rec["kind"] == "credit"
    assert rec["until"] > time.time() + 3600
    assert rec["until"] < time.time() + 12 * 3600


def test_weekly_limit_parse_sets_future_until():
    from switchbay.agents import orchestration_health as health
    err = "You've hit your weekly limit - resets Aug 26 at 11pm (Europe/Zurich)"
    ts = health.parse_weekly_until(err, now=1_724_000_000)  # 2024-08-ish
    assert ts is not None
    assert ts > 1_724_000_000


def test_looks_like_outage_is_tight():
    from switchbay.agents import orchestration_health as health
    banner = "You've hit your weekly limit - resets Aug 26 at 11pm (Europe/Zurich)"
    assert health.looks_like_outage(banner) == "weekly_limit"
    assert health.looks_like_outage("Claude Code error: " + banner) == "weekly_limit"
    assert health.looks_like_outage("OpenAI: insufficient_funds / out of credits") == "credit"
    # Research prose on a hedge desk must not kill the worker.
    assert health.looks_like_outage("the fund's spend limit is $2bn") is None
    assert health.looks_like_outage("connection between AAPL and MSFT") is None
    assert health.looks_like_outage("import quota of 10-K line items") is None


def test_playbook_prefers_last_good_roster(tmp_path):
    from switchbay import orchestrator_fs
    orchestrator_fs.remember_success(
        tmp_path,
        policy_id="ivs_diverse_2",
        roster=[("grok_build", "grok-4.6"), ("mlx", "qwen")],
        bucket="r|m|h|c|p2|m|d",
    )
    got = orchestrator_fs.preferred_roster(tmp_path, bucket="r|m|h|c|p2|m|d")
    assert ("mlx", "qwen") in got
    assert got[0][0] == "grok_build"
