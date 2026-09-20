"""Fake-provider Curate scheduler: unique IDs, compact, idle, nested park.

These tests are labeled fake: they do not call a live model. The isolated
real-provider smoke is a separate script.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from switchbay import app_settings, ce_host
from switchbay.agents import desk_admission as seats
from switchbay.agents import orchestration as orch
from switchbay.agents.orchestration import OrchestrationPlan, PlanNode
from switchbay.llmgateway import base


def _app() -> dict:
    return {"ws_clients": set(), "runs": {}, "run_ws": {}}


def _curate_plan(oid: str, *, repeat: bool = True, until: float | None = None) -> OrchestrationPlan:
    dec = {"task_kind": "curation", "curate_repeat": repeat}
    if until is not None:
        dec["curate_until"] = until
    return OrchestrationPlan(
        orchestration_id=oid,
        strategy="ce_curate",
        objective="overnight",
        extra_system="Role lens: keep this.",
        nodes=[PlanNode(
            node_id="curate", kind="synthesize", objective="curate",
            role="curator", tools=["ce_wave_prime", "ce_dispatch_worker"],
            output_contract="synthesis",
        )],
        decision=dec,
        allow_expand=True,
        bounds=orch.OrchestrationBounds(max_concurrency=1, max_expansions=0).clamp(),
    )


class ProductiveFake:
    ID = "openai"
    LABEL = "OpenAI"
    DEFAULT_MODEL = "fake"
    PROVIDER = {"id": "openai", "default_model": "fake"}

    def has_key(self) -> bool:
        return True

    async def chat_stream(self, req):
        yield base.TextChunk(text="wave")
        yield base.DoneChunk(stop_reason="end_turn", input_tokens=1, output_tokens=1)


@pytest.mark.asyncio
async def test_thousand_productive_waves_unique_ids_resume(tmp_path: Path, monkeypatch):
    """Fake scheduler: 1005+ execute() completions, unique IDs, bounded live DAG."""
    monkeypatch.setattr(
        "switchbay.modestore.resolve_for_difficulty", lambda *a, **k: (None, None),
    )
    monkeypatch.setattr(
        "switchbay.ce_host.wave_prime",
        lambda *a, **k: {"ok": True, "mode": "repair", "pick_mode": "test"},
    )
    executed: list[str] = []
    run_ids: list[str] = []

    async def fake_node(node, **kwargs):
        executed.append(node.node_id)
        attempt = int(kwargs.get("attempt") or 1)
        rid = orch._node_run_id(kwargs.get("parent_run_id") or "x", node.node_id, attempt)
        run_ids.append(rid)
        rec = {
            "node_id": node.node_id,
            "kind": node.kind,
            "run_id": rid,
            "ok": True,
            "error": None,
            "output": f"did {node.node_id}",
            "provider": "openai",
            "model": "fake",
            "input_tokens": 2,
            "output_tokens": 3,
            "wiki_pages_landed": 1,
            "wiki_pages_changed": ["wiki/concepts/fixture.md"],
            "wiki_committed": True,
            "wiki_head_before": "a" * 40,
            "wiki_head_after": "b" * 40,
            "wiki_commit_diff": " wiki/concepts/fixture.md | 2 ++",
        }
        if len(executed) in (7, 19):
            rec["ok"] = False
            rec["error"] = "timed out after 1s"
            rec["run_id"] = orch._node_run_id(
                kwargs.get("parent_run_id") or "x", node.node_id, 2,
            )
            run_ids[-1] = rec["run_id"]
        return rec

    monkeypatch.setattr(orch, "_run_agent_node", fake_node)
    monkeypatch.setattr(orch, "_apply_work_receipt", lambda rec, *a, **k: rec)
    seats.reset_for_tests()

    oid = "run-thousand"
    plan = _curate_plan(oid)
    app = _app()
    app["runs"][oid] = {
        "run_id": oid, "status": "running", "started_at": 0,
        "provider": "openai", "model": "fake",
    }

    async def stop_after(n: int, current: asyncio.Task) -> None:
        # Count productive fake_node completions on *this* execute task.
        # Closing over the first task made the resume stopper exit immediately.
        while not current.done():
            if len(executed) >= n:
                app["runs"][oid]["user_cancel"] = True
                return
            await asyncio.sleep(0)

    def _assert_live_graph(ck, parent, *, min_results: int) -> None:
        live_plan = ck.get("plan")
        assert type(live_plan) is OrchestrationPlan, type(live_plan)
        assert 1 <= len(live_plan.nodes) < 40, [n.node_id for n in live_plan.nodes]
        parent_nodes = parent.get("plan_nodes")
        assert type(parent_nodes) is list, type(parent_nodes)
        assert len(parent_nodes) < 40, parent_nodes
        ids = []
        for row in parent_nodes:
            assert type(row) is dict, row
            nid = row.get("node_id")
            assert type(nid) is str and nid, row
            ids.append(nid)
        assert len(ids) == len(set(ids)), ids
        results = ck.get("results") or {}
        assert type(results) is dict
        assert len(results) >= min_results, len(results)

    task = asyncio.create_task(orch.execute(
        plan, app=app, workspace=tmp_path, thread_id="th",
        parent_run_id=oid, default_provider=ProductiveFake(), default_model="fake",
    ))
    stopper = asyncio.create_task(stop_after(520, task))
    result1 = await asyncio.wait_for(task, timeout=60)
    await asyncio.wait_for(stopper, timeout=2)
    assert stopper.done() and not stopper.cancelled()
    assert result1.cancelled, result1.telemetry
    assert app["runs"][oid].get("user_cancel") is True
    mid = list(executed)
    assert len(mid) >= 520, len(mid)
    assert len(set(mid)) == len(mid), "node IDs reused before resume"
    ck = orch.load_checkpoint(tmp_path, oid)
    assert ck is not None
    _assert_live_graph(ck, app["runs"][oid], min_results=520)
    results_mid = dict(ck.get("results") or {})
    mid_ids = set(mid)

    app["runs"][oid]["user_cancel"] = False
    app["runs"][oid]["status"] = "running"
    task2 = asyncio.create_task(orch.execute(
        plan, app=app, workspace=tmp_path, thread_id="th",
        parent_run_id=oid, default_provider=ProductiveFake(), default_model="fake",
        resume=True,
    ))
    stopper2 = asyncio.create_task(stop_after(1005, task2))
    result2 = await asyncio.wait_for(task2, timeout=60)
    await asyncio.wait_for(stopper2, timeout=2)
    assert stopper2.done() and not stopper2.cancelled()
    assert result2.cancelled, result2.telemetry
    assert app["runs"][oid].get("user_cancel") is True

    assert len(executed) >= 1005, len(executed)
    assert len(set(executed)) == len(executed), "node IDs reused across resume"
    assert len(set(run_ids)) == len(run_ids)
    assert mid_ids <= set(executed)
    ck2 = orch.load_checkpoint(tmp_path, oid)
    assert ck2 is not None
    _assert_live_graph(ck2, app["runs"][oid], min_results=1005)
    live_plan = ck2.get("plan")
    view = orch._plan_nodes_view(
        live_plan,
        set((ck2["status"].get("completed") or [])),
        set((ck2["status"].get("failed") or [])),
        set(),
    )
    assert len(view) < 40, view
    results = ck2.get("results") or {}
    for nid, rec in results_mid.items():
        assert nid in results, nid
        assert results[nid].get("wiki_commit_diff") == rec.get("wiki_commit_diff")
    with_diff = [
        r for r in results.values()
        if type(r) is dict and r.get("wiki_commit_diff")
    ]
    assert len(with_diff) >= 1000, len(with_diff)
    timeouts = [
        r for r in results.values()
        if type(r) is dict and "timed out" in str(r.get("error") or "")
    ]
    assert len(timeouts) == 2, timeouts


@pytest.mark.asyncio
async def test_noop_curate_waits_without_llm(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "switchbay.modestore.resolve_for_difficulty", lambda *a, **k: (None, None),
    )
    monkeypatch.setattr(
        "switchbay.ce_host.wave_prime",
        lambda *a, **k: {"ok": True, "mode": "repair", "reason": "planner stub"},
    )
    monkeypatch.setattr(
        "switchbay.ce_tools._ce_planner",
        lambda *a, **k: {"ok": True, "mode": "repair"},
    )
    calls = {"n": 0}

    async def fake_node(node, **kwargs):
        calls["n"] += 1
        return {
            "node_id": node.node_id,
            "kind": node.kind,
            "run_id": f"run-{node.node_id}",
            "ok": True,
            "output": "no wiki work this wave",
            "wiki_pages_landed": 0,
            "wiki_pages_changed": [],
            "wiki_head_before": "same",
            "wiki_head_after": "same",
            "input_tokens": 4,
            "output_tokens": 4,
        }

    monkeypatch.setattr(orch, "_run_agent_node", fake_node)
    monkeypatch.setattr(orch, "_apply_work_receipt", lambda rec, *a, **k: rec)
    seats.reset_for_tests()

    oid = "run-idle"
    plan = _curate_plan(oid)
    app = _app()
    app["runs"][oid] = {"run_id": oid, "status": "running", "started_at": 0}
    task = asyncio.create_task(orch.execute(
        plan, app=app, workspace=tmp_path, thread_id="th",
        parent_run_id=oid, default_provider=ProductiveFake(), default_model="fake",
    ))
    for _ in range(80):
        await asyncio.sleep(0.05)
        if calls["n"] >= 2:
            break
    waves_while_idle = calls["n"]
    assert 2 <= waves_while_idle <= 3, waves_while_idle
    await asyncio.sleep(0.2)
    assert calls["n"] == waves_while_idle, "idle wait still invoked the model"
    fp_before = ce_host.work_availability_fingerprint(tmp_path)
    vault = tmp_path / "vault" / "raw"
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "new-source.md").write_text("fresh vault notes\n", encoding="utf-8")
    fp_after = ce_host.work_availability_fingerprint(tmp_path)
    assert fp_after != fp_before, "real source write must change wiki/vault fingerprint"
    for _ in range(80):
        await asyncio.sleep(0.05)
        if calls["n"] > waves_while_idle:
            break
    assert calls["n"] > waves_while_idle, "new work did not wake idle curate"
    app["runs"][oid]["user_cancel"] = True
    result = await asyncio.wait_for(task, timeout=5)
    assert result.cancelled, result.telemetry
    ck = orch.load_checkpoint(tmp_path, oid)
    assert ck is not None
    loaded = ck.get("plan")
    assert type(loaded) is OrchestrationPlan
    lens = loaded.extra_system
    assert type(lens) is str
    assert "Role lens: keep this." in lens, lens
    dec = loaded.decision if type(loaded.decision) is dict else {}
    assert dec.get("_extra_system_base") == "Role lens: keep this.", dec


@pytest.mark.asyncio
async def test_noop_curate_deadline_stops_idle_wait(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "switchbay.modestore.resolve_for_difficulty", lambda *a, **k: (None, None),
    )
    monkeypatch.setattr(
        "switchbay.ce_host.wave_prime",
        lambda *a, **k: {"ok": True, "mode": "repair", "reason": "planner stub"},
    )
    monkeypatch.setattr(
        "switchbay.ce_tools._ce_planner",
        lambda *a, **k: {"ok": True, "mode": "repair"},
    )
    calls = {"n": 0}

    async def fake_node(node, **kwargs):
        calls["n"] += 1
        return {
            "node_id": node.node_id, "kind": node.kind, "ok": True,
            "output": "noop", "wiki_pages_landed": 0, "wiki_pages_changed": [],
            "run_id": node.node_id, "input_tokens": 1, "output_tokens": 1,
        }

    monkeypatch.setattr(orch, "_run_agent_node", fake_node)
    monkeypatch.setattr(orch, "_apply_work_receipt", lambda rec, *a, **k: rec)
    seats.reset_for_tests()
    oid = "run-idle-deadline"
    # Deadline checks in execute() use time.time(); asyncio waits use
    # time.monotonic. Replace orch.time with a local namespace so the
    # process-global time module stays untouched. Freeze wall time so
    # CI startup cannot consume the 0.4s window, then expire after
    # idle wait starts.
    origin = time.time()
    clock = {"now": origin}

    class _OrchTime:
        def time(self) -> float:
            return clock["now"]

        def __getattr__(self, name: str):
            return getattr(time, name)

    monkeypatch.setattr(orch, "time", _OrchTime())
    plan = _curate_plan(oid, until=origin + 0.4)
    app = _app()
    app["runs"][oid] = {"run_id": oid, "status": "running", "started_at": 0}
    task = asyncio.create_task(orch.execute(
        plan, app=app, workspace=tmp_path, thread_id="th",
        parent_run_id=oid, default_provider=ProductiveFake(), default_model="fake",
    ))

    async def _until_idle() -> None:
        while True:
            rec = app["runs"][oid]
            if calls["n"] >= 1 and rec.get("orchestration_stage") == "waiting_work":
                return
            if task.done():
                exc = task.exception()
                if exc is not None:
                    raise exc
                raise AssertionError(
                    "execute finished before idle wait: "
                    f"calls={calls['n']} stage={rec.get('orchestration_stage')} "
                    f"telemetry={task.result().telemetry}"
                )
            await asyncio.sleep(0.01)

    try:
        await asyncio.wait_for(_until_idle(), timeout=5)
        clock["now"] = origin + 1.0
        result = await asyncio.wait_for(task, timeout=5)
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    assert result.telemetry.get("stop_reason") == "curate window ended"
    assert calls["n"] >= 1
    assert calls["n"] <= 4, calls["n"]


@pytest.mark.asyncio
async def test_nested_dispatch_parks_parent_seat(tmp_path: Path, monkeypatch):
    """Native ToolUseChunk ce_dispatch_worker at cap=4; production park."""
    monkeypatch.setattr(
        "switchbay.modestore.resolve_for_difficulty", lambda *a, **k: (None, None),
    )
    monkeypatch.setattr(
        "switchbay.ce_host.dispatch_worker",
        lambda *a, **k: {"ok": True, "role": "deepener", "prompt": "Inspect fixture source"},
    )
    monkeypatch.setattr(
        "switchbay.agents.ce_workers.is_local_pid", lambda *a: False,
    )
    monkeypatch.setattr(
        "switchbay.agents.ce_workers.policy.allocate_unused",
        lambda *a, **k: [("openai", "fake")],
    )
    app_settings.set_desk_max_live_workers(4)
    seats.reset_for_tests()
    domain = seats.desk_domain_id(tmp_path, "curate")
    g = seats.gate_for(domain, workspace=tmp_path)
    assert g.cap == 4
    await g.acquire("dummy-a", kind="worker")
    await g.acquire("dummy-b", kind="worker")

    class NestedProv:
        ID = "openai"
        DEFAULT_MODEL = "fake"
        PROVIDER = {"id": "openai", "default_model": "fake"}

        def has_key(self) -> bool:
            return True

        async def chat_stream(self, req):
            yield base.TextChunk(
                text='{"findings":[{"claim":"nested source-backed finding","confidence":0.9}]}',
            )
            yield base.DoneChunk(stop_reason="end_turn", input_tokens=2, output_tokens=8)

    class CuratorProv:
        ID = "openai"
        DEFAULT_MODEL = "fake"
        PROVIDER = {"id": "openai", "default_model": "fake"}

        def has_key(self) -> bool:
            return True

        async def chat_stream(self, req):
            blob = str(req.messages or "")
            if "nested source-backed finding" in blob or "tool_result" in blob:
                yield base.TextChunk(text="Curator received nested finding.\nOBJECTIVE_MET: yes")
                yield base.DoneChunk(stop_reason="end_turn", input_tokens=3, output_tokens=4)
                return
            yield base.ToolUseChunk(
                id="d1", name="ce_dispatch_worker",
                input={"role": "deepener", "brief": "inspect fixture"},
            )
            yield base.DoneChunk(stop_reason="tool_use", input_tokens=1, output_tokens=1)

    monkeypatch.setattr("switchbay.llmgateway.get", lambda *_a, **_k: NestedProv())
    oid = "run-n"
    plan = _curate_plan(oid, repeat=False)
    plan.nodes[0].tools = ["ce_dispatch_worker"]
    app = _app()
    app["runs"][oid] = {
        "run_id": oid, "status": "running", "started_at": time.time(),
        "provider": "openai", "model": "fake",
    }
    result = await asyncio.wait_for(orch.execute(
        plan, app=app, workspace=tmp_path, thread_id="th",
        parent_run_id=oid, default_provider=CuratorProv(), default_model="fake",
    ), timeout=5)
    assert result.ok, result
    parent = app["runs"][oid]
    claims = [str(r.get("claim") or "") for r in (parent.get("blackboard_rows") or [])]
    assert "nested source-backed finding" in " ".join(claims), (claims, parent)
    assert "Curator received nested finding" in (result.output or ""), result.output
    assert g.cap == 4
    assert g.live() == 2, g.snapshot()
    slots = g.snapshot()["slots"]
    assert "dummy-a" in slots and "dummy-b" in slots
    assert all(not str(s).startswith(f"{oid}:") for s in slots), slots
    await g.release_async("dummy-a")
    await g.release_async("dummy-b")


@pytest.mark.asyncio
async def test_nested_dispatch_cancel_releases_parked_parent(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "switchbay.modestore.resolve_for_difficulty", lambda *a, **k: (None, None),
    )
    monkeypatch.setattr(
        "switchbay.ce_host.dispatch_worker",
        lambda *a, **k: {"ok": True, "role": "deepener", "prompt": "Inspect fixture source"},
    )
    monkeypatch.setattr(
        "switchbay.agents.ce_workers.is_local_pid", lambda *a: False,
    )
    monkeypatch.setattr(
        "switchbay.agents.ce_workers.policy.allocate_unused",
        lambda *a, **k: [("openai", "fake")],
    )
    app_settings.set_desk_max_live_workers(4)
    seats.reset_for_tests()
    domain = seats.desk_domain_id(tmp_path, "curate")
    g = seats.gate_for(domain, workspace=tmp_path)
    await g.acquire("dummy-a", kind="worker")
    await g.acquire("dummy-b", kind="worker")
    started = asyncio.Event()
    release = asyncio.Event()

    class NestedProv:
        ID = "openai"
        DEFAULT_MODEL = "fake"

        def has_key(self) -> bool:
            return True

        async def chat_stream(self, req):
            started.set()
            await release.wait()
            yield base.TextChunk(text="late nested")
            yield base.DoneChunk(stop_reason="end_turn")

    class CuratorProv:
        ID = "openai"
        DEFAULT_MODEL = "fake"

        def has_key(self) -> bool:
            return True

        async def chat_stream(self, req):
            yield base.ToolUseChunk(
                id="d1", name="ce_dispatch_worker",
                input={"role": "deepener", "brief": "inspect fixture"},
            )
            yield base.DoneChunk(stop_reason="tool_use")

    monkeypatch.setattr("switchbay.llmgateway.get", lambda *_a, **_k: NestedProv())
    oid = "run-n-cancel"
    plan = _curate_plan(oid, repeat=False)
    plan.nodes[0].tools = ["ce_dispatch_worker"]
    app = _app()
    app["runs"][oid] = {"run_id": oid, "status": "running", "started_at": time.time()}
    task = asyncio.create_task(orch.execute(
        plan, app=app, workspace=tmp_path, thread_id="th",
        parent_run_id=oid, default_provider=CuratorProv(), default_model="fake",
    ))
    await asyncio.wait_for(started.wait(), timeout=2)
    task.cancel()
    try:
        await asyncio.wait_for(task, timeout=5)
    except asyncio.CancelledError:
        pass
    release.set()
    await asyncio.sleep(0.05)
    slots = g.snapshot()["slots"]
    assert "dummy-a" in slots and "dummy-b" in slots
    assert all(not str(s).startswith(f"{oid}:") for s in slots), slots
    await g.release_async("dummy-a")
    await g.release_async("dummy-b")
