"""Per-desk live seats: floor, admin ceiling, chief counted, nested."""

from __future__ import annotations

import asyncio

import pytest

from switchbay import admin_policy, app_settings
from switchbay.agents import desk_admission as seats
from switchbay.agents import orchestration as orch
from switchbay.agents import orchestration_policy as policy
from switchbay.agents.orchestration import PlanNode, OrchestrationPlan


def test_cap_floor_and_admin_tightening(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("SWITCHBAY_STATE_DIR", str(tmp_path / "st"))
    monkeypatch.setenv("SWITCHBAY_PROFILE", "open")
    admin_policy.reset_cache()
    seats.reset_for_tests()
    app_settings.set_desk_max_live_workers(2)
    assert app_settings.get_desk_max_live_workers() >= 4
    assert seats.effective_live_cap() >= 4
    app_settings.set_desk_max_live_workers(8)
    policy = tmp_path / "admin.json"
    policy.write_text('{"orchestration": {"max_live_workers": 5}}', encoding="utf-8")
    monkeypatch.setenv("SWITCHBAY_ADMIN_POLICY", str(policy))
    admin_policy.reset_cache()
    assert seats.effective_live_cap() == 5
    app_settings.set_desk_max_live_workers(8)
    assert seats.effective_live_cap() == 5  # cannot raise above admin


def test_baked_tightens_not_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("SWITCHBAY_INSTALL_ROOT", str(tmp_path / "install"))
    inst = tmp_path / "install"
    inst.mkdir()
    (inst / "admin.baked.json").write_text(
        '{"profile":"enterprise","orchestration":{"max_live_workers": 4}}',
        encoding="utf-8",
    )
    overlay = tmp_path / "admin.json"
    overlay.write_text('{"orchestration": {"max_live_workers": 8}}', encoding="utf-8")
    monkeypatch.setenv("SWITCHBAY_ADMIN_POLICY", str(overlay))
    admin_policy.reset_cache()
    seats.reset_for_tests()
    cap = seats.effective_live_cap()
    assert cap == 4


def test_overlay_zero_does_not_loosen_baked_floor(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("SWITCHBAY_INSTALL_ROOT", str(tmp_path / "install"))
    inst = tmp_path / "install"
    inst.mkdir()
    (inst / "admin.baked.json").write_text(
        '{"profile":"enterprise","orchestration":{"max_live_workers": 4}}',
        encoding="utf-8",
    )
    overlay = tmp_path / "admin.json"
    overlay.write_text('{"orchestration": {"max_live_workers": 0}}', encoding="utf-8")
    monkeypatch.setenv("SWITCHBAY_ADMIN_POLICY", str(overlay))
    admin_policy.reset_cache()
    seats.reset_for_tests()
    app_settings.set_desk_max_live_workers(8)
    assert admin_policy.max_live_workers_ceiling() == 4
    assert seats.effective_live_cap() == 4


def test_chief_counted_and_nested_share_desk():
    seats.reset_for_tests()
    g = seats.gate_for("desk-a", cap=4)
    assert g.try_acquire("chief", kind="chief")
    assert g.try_acquire("curator", kind="worker")
    assert g.try_acquire("nested-1", kind="nested")
    assert g.try_acquire("nested-2", kind="nested")
    assert not g.try_acquire("nested-3", kind="nested")
    assert g.live() == 4
    g.release("nested-1")
    assert g.try_acquire("nested-3", kind="nested")


def test_multi_desk_isolation():
    seats.reset_for_tests()
    a = seats.gate_for("desk-a", cap=4)
    b = seats.gate_for("desk-b", cap=4)
    assert a.try_acquire("chief", kind="chief")
    assert b.try_acquire("chief", kind="chief")
    assert a.live() == 1 and b.live() == 1


def test_continuous_progress_after_compaction():
    nodes = [PlanNode(node_id=f"c-{i}", kind="synthesize", role="curator", objective="w") for i in range(40)]
    plan = OrchestrationPlan(
        orchestration_id="c1", strategy="ce_curate", objective="overnight",
        nodes=list(nodes),
    )
    completed = {n.node_id for n in nodes[:-1]}
    running = {nodes[-1].node_id}
    dropped = orch.compact_plan_nodes(plan, completed, set(), running)
    assert dropped >= 1
    assert len(plan.nodes) < 40
    live = orch.live_plan_nodes(plan, completed, set(), running)
    assert any(n.node_id == nodes[-1].node_id for n in live)


@pytest.mark.asyncio
async def test_set_cap_increase_wakes_waiter():
    seats.reset_for_tests()
    g = seats.DeskGate("wake-cap", cap=4)
    for name in ("chief", "a", "b", "c"):
        await g.acquire(name)
    waiter = asyncio.create_task(g.acquire("queued"))
    await asyncio.sleep(0)
    assert not waiter.done()
    g.set_cap(5)
    await asyncio.wait_for(waiter, timeout=0.5)
    assert g.live() == 5


@pytest.mark.asyncio
async def test_set_cap_decrease_admits_no_extras():
    seats.reset_for_tests()
    g = seats.DeskGate("drain-cap", cap=6)
    for name in ("chief", "a", "b", "c", "d", "e"):
        await g.acquire(name)
    g.set_cap(4)
    assert g.live() == 6
    waiter = asyncio.create_task(g.acquire("extra"))
    await asyncio.sleep(0.05)
    assert not waiter.done()
    await g.release_async("e")
    await g.release_async("d")
    await asyncio.sleep(0.05)
    assert not waiter.done()
    await g.release_async("c")
    await asyncio.wait_for(waiter, timeout=0.5)
    assert g.live() == 4
    waiter.cancel()
    try:
        await waiter
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_refresh_cap_reads_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("SWITCHBAY_STATE_DIR", str(tmp_path / "st"))
    admin_policy.reset_cache()
    seats.reset_for_tests()
    app_settings.set_desk_max_live_workers(4)
    g = seats.gate_for(seats.desk_domain_id(tmp_path, "curate"), workspace=tmp_path)
    assert g.cap == 4
    app_settings.set_desk_max_live_workers(8)
    g.refresh_cap(tmp_path)
    assert g.cap == 8


@pytest.mark.asyncio
async def test_park_parent_unblocks_nested():
    seats.reset_for_tests()
    g = seats.DeskGate("nest-deadlock", cap=4)
    await g.acquire("run:chief", kind="chief")
    await g.acquire("run:parent-a", kind="worker")
    await g.acquire("run:parent-b", kind="worker")
    await g.acquire("run:parent-c", kind="worker")
    assert g.live() == 4
    nested = asyncio.create_task(g.acquire("run:nested", kind="nested"))
    await asyncio.sleep(0)
    assert not nested.done()
    parked = await g.park("run:parent-a")
    assert parked
    assert g.live() == 3
    await asyncio.wait_for(nested, timeout=0.5)
    assert g.live() == 4
    await g.release_async("run:nested")
    restored = await g.unpark("run:parent-a")
    assert restored
    assert "run:parent-a" in g.snapshot()["slots"]


def test_overlapping_runs_share_workspace_desk_domain(tmp_path):
    seats.reset_for_tests()
    a = seats.desk_domain_id(tmp_path, "curate")
    b = seats.desk_domain_id(tmp_path, "curate")
    c = seats.desk_domain_id(tmp_path, "auto")
    assert a == b
    assert a != c
    g1 = seats.gate_for(a, cap=4, workspace=tmp_path)
    g1.retain()
    g2 = seats.gate_for(b, cap=4, workspace=tmp_path)
    g2.retain()
    assert g1 is g2
    g1.drop_ref()
    seats.drop_gate(a)
    assert seats.gate_for(a) is g1
    g2.drop_ref()
    seats.drop_gate(a)


def test_continue_and_expand_ids_survive_compaction():
    plan = OrchestrationPlan(
        orchestration_id="ids", strategy="investigate_verify_synthesize",
        objective="x", nodes=[PlanNode(node_id="inv-0", kind="investigate", objective="a")],
        allow_expand=True, decision={"independence": "high"},
    )
    seen: set[str] = {"inv-0"}
    for i in range(40):
        added = orch._add_expansion_nodes(
            plan,
            policy.ExpansionDecision(True, 1, "gap", ["more"]),
            default_provider="openai", default_model="fake",
        )
        for n in added:
            assert n.node_id not in seen, n.node_id
            seen.add(n.node_id)
        orch.compact_plan_nodes(plan, set(seen) - {added[-1].node_id}, set(), {added[-1].node_id})
    cont = orch._add_continue_wave(
        plan,
        policy.ExpansionDecision(True, 1, "gap", ["again"]),
        default_provider="openai", default_model="fake",
    )
    for n in cont:
        assert n.node_id not in seen
        seen.add(n.node_id)
