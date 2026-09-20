"""Curate desk: live-state, resume finish, duration waves, overlap."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from switchbay.agents.orchestration import (
    PlanNode, OrchestrationPlan, parse_duration_window,
    _add_curate_package_wave, _add_continue_wave,
)
from switchbay.agents import orchestration_policy as policy
from switchbay.kernel import (
    DESK_CURATE, STATE_QUIET, STATE_WORKING, get, quiet, seat,
)


def test_parse_duration_and_continuous():
    now = 1_000_000.0
    repeat, until = parse_duration_window("for 10 mins", now=now)
    assert repeat is True
    assert until == now + 600
    repeat, until = parse_duration_window("overnight", now=now)
    assert repeat is True
    assert until is None
    repeat, until = parse_duration_window("tables", now=now)
    assert repeat is False


def test_curate_continue_is_package_wave_not_generic():
    plan = OrchestrationPlan(
        orchestration_id="run-1",
        strategy="ce_curate",
        objective="for 10 mins",
        nodes=[PlanNode(
            node_id="curate", kind="synthesize", objective="for 10 mins",
            role="curator", tools=["ce_wave_prime", "ce_planner"],
        )],
        decision={"task_kind": "curation", "curate_repeat": True},
        allow_expand=True,
    )
    added = _add_curate_package_wave(plan)
    assert added
    assert added[0].role == "curator"
    assert added[0].kind == "synthesize"
    assert "ce_planner" in added[0].tools or "ce_wave_prime" in added[0].tools
    generic = _add_continue_wave(
        OrchestrationPlan(
            orchestration_id="run-2", strategy="investigate_verify_synthesize",
            objective="why",
            nodes=[PlanNode(node_id="synth", kind="synthesize", objective="why")],
            allow_expand=True, preference=1.0,
        ),
        policy.ExpansionDecision(True, 1, "gap", ["more"]),
        default_provider="anthropic",
        default_model="opus",
    )
    kinds = {n.kind for n in generic}
    assert "investigate" in kinds


def test_quiet_ignores_newer_overlapping_run(tmp_path: Path):
    seat(tmp_path, DESK_CURATE, chief_provider="x", chief_model="y", run_id="old")
    seat(tmp_path, DESK_CURATE, chief_provider="x", chief_model="y", run_id="new")
    q = quiet(tmp_path, DESK_CURATE, run_id="old")
    assert q is not None
    assert q.state == STATE_WORKING
    assert q.run_id == "new"


def test_reconcile_stale_working_without_live_run(tmp_path: Path):
    from switchbay import daemon
    seat(
        tmp_path, DESK_CURATE,
        chief_provider="x", chief_model="y", run_id="gone",
    )
    rec = get(tmp_path, DESK_CURATE)
    app = {"runs": {}, "desk_launches": {}}
    state = daemon._reconcile_desk_state(app, tmp_path, rec)
    assert state == STATE_QUIET
    rec2 = get(tmp_path, DESK_CURATE)
    assert rec2 is not None
    assert rec2.state == STATE_QUIET


def test_stale_running_checkpoint_is_quiet(tmp_path: Path, monkeypatch):
    from switchbay import daemon
    seat(
        tmp_path, DESK_CURATE,
        chief_provider="x", chief_model="y", run_id="stale",
    )
    rec = get(tmp_path, DESK_CURATE)
    monkeypatch.setattr(
        daemon.orchestration, "load_checkpoint",
        lambda *a: {"status": {"phase": "running"}},
    )
    assert daemon._reconcile_desk_state({"runs": {}}, tmp_path, rec) == STATE_QUIET
    rec2 = get(tmp_path, DESK_CURATE)
    assert rec2 is not None
    assert rec2.state == STATE_QUIET
    assert rec2.run_id == "stale"


def test_stale_interrupted_waiting_planning_are_quiet(tmp_path: Path, monkeypatch):
    from switchbay import daemon
    for phase in ("interrupted", "waiting_limits", "planning"):
        seat(
            tmp_path, DESK_CURATE,
            chief_provider="x", chief_model="y", run_id=f"stale-{phase}",
        )
        rec = get(tmp_path, DESK_CURATE)
        monkeypatch.setattr(
            daemon.orchestration, "load_checkpoint",
            lambda *a, p=phase: {"status": {"phase": p}},
        )
        assert daemon._reconcile_desk_state(
            {"runs": {}, "desk_launches": {}}, tmp_path, rec,
        ) == STATE_QUIET
        rec2 = get(tmp_path, DESK_CURATE)
        assert rec2.run_id == f"stale-{phase}"


def test_reconcile_live_run_and_startup_launch_race(tmp_path: Path):
    import asyncio
    from switchbay import daemon
    seat(
        tmp_path, DESK_CURATE,
        chief_provider="x", chief_model="y", run_id="run-live",
    )
    rec = get(tmp_path, DESK_CURATE)

    async def _run():
        app = {
            "runs": {
                "run-live": {
                    "run_id": "run-live",
                    "status": "running",
                    "workspace": str(tmp_path),
                },
            },
            "desk_launches": {},
        }
        assert daemon._reconcile_desk_state(app, tmp_path, rec) == STATE_WORKING
        t = asyncio.create_task(asyncio.sleep(30))
        launch_app = {"runs": {}, "desk_launches": {}}
        daemon._track_desk_launch(launch_app, tmp_path, DESK_CURATE, t)
        assert daemon._reconcile_desk_state(launch_app, tmp_path, rec) == STATE_WORKING
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
        assert daemon._reconcile_desk_state(launch_app, tmp_path, rec) == STATE_QUIET

    asyncio.run(_run())


def test_quiet_stopped_run_then_overlapping_later_run(tmp_path: Path):
    from switchbay import daemon
    seat(
        tmp_path, DESK_CURATE,
        chief_provider="x", chief_model="y", run_id="old",
    )
    rec = get(tmp_path, DESK_CURATE)
    app = {"runs": {}, "desk_launches": {}}
    assert daemon._reconcile_desk_state(app, tmp_path, rec) == STATE_QUIET
    seat(
        tmp_path, DESK_CURATE,
        chief_provider="x", chief_model="y", run_id="new",
    )
    rec2 = get(tmp_path, DESK_CURATE)
    app2 = {
        "runs": {
            "new": {
                "run_id": "new",
                "status": "running",
                "workspace": str(tmp_path),
            },
        },
        "desk_launches": {},
    }
    assert daemon._reconcile_desk_state(app2, tmp_path, rec2) == STATE_WORKING
    assert get(tmp_path, DESK_CURATE).run_id == "new"


def test_expired_resume_is_refused(tmp_path: Path):
    from switchbay import daemon
    from switchbay.agents import orchestration
    seat(
        tmp_path, DESK_CURATE,
        chief_provider="x", chief_model="y", run_id="expired",
    )
    quiet(tmp_path, DESK_CURATE, run_id="expired", keep_run=True)
    orchestration.persist_checkpoint(
        tmp_path, "expired",
        phase="quiet", completed=set(), failed=set(),
        expansions=0, results={}, elapsed_s=1.0,
        extra={"curate_until": time.time() - 30},
    )
    spec = {"desk_id": DESK_CURATE}
    assert daemon._maybe_resume_quiet_desk({"runs": {}}, spec, tmp_path) is None
    rec = get(tmp_path, DESK_CURATE)
    assert rec is not None
    assert rec.run_id == "expired"
    assert rec.state == STATE_QUIET


def test_reconcile_keeps_live_run_working(tmp_path: Path):
    from switchbay import daemon
    seat(
        tmp_path, DESK_CURATE,
        chief_provider="x", chief_model="y", run_id="run-live",
    )
    rec = get(tmp_path, DESK_CURATE)
    app = {
        "runs": {
            "run-live": {
                "run_id": "run-live",
                "status": "running",
                "workspace": str(tmp_path),
            },
        },
        "desk_launches": {},
    }
    assert daemon._reconcile_desk_state(app, tmp_path, rec) == STATE_WORKING


def test_finish_resume_protects_newer_run(tmp_path: Path):
    from switchbay import daemon
    seat(tmp_path, DESK_CURATE, chief_provider="x", chief_model="y", run_id="new")
    plan = SimpleNamespace(strategy="ce_curate", decision={"task_kind": "curation"})
    daemon._finish_resume_desk(tmp_path, plan, "old", cancelled=False)
    rec = get(tmp_path, DESK_CURATE)
    assert rec is not None
    assert rec.state == STATE_WORKING
    assert rec.run_id == "new"


def test_track_desk_launch_cancels_previous():
    import asyncio
    from switchbay import daemon

    async def _run():
        app = {}
        t1 = asyncio.create_task(asyncio.sleep(30))
        t2 = asyncio.create_task(asyncio.sleep(30))
        ws = Path("/tmp/ws-a")
        daemon._track_desk_launch(app, ws, "curate", t1)
        daemon._track_desk_launch(app, ws, "curate", t2)
        t2.cancel()
        for t in (t1, t2):
            try:
                await t
            except asyncio.CancelledError:
                pass
        assert t1.cancelled()
        assert t2.cancelled()

    asyncio.run(_run())


def _curate_plan(oid: str, *, until: float | None = None, repeat: bool = True) -> OrchestrationPlan:
    dec = {"task_kind": "curation", "curate_repeat": repeat}
    if until is not None:
        dec["curate_until"] = until
    return OrchestrationPlan(
        orchestration_id=oid,
        strategy="ce_curate",
        objective="overnight" if until is None else "for 10 mins",
        nodes=[PlanNode(
            node_id="curate", kind="synthesize", objective="curate",
            role="curator", tools=["ce_wave_prime"],
            output_contract="synthesis",
        )],
        decision=dec,
        allow_expand=True,
    )


def _app():
    return {"ws_clients": set(), "runs": {}, "run_ws": {}}


@pytest.mark.asyncio
async def test_local_duration_dispatch_reaches_host_waves(tmp_path: Path, monkeypatch):
    from switchbay import daemon
    from switchbay.agents import orchestration
    from switchbay.llmgateway import base

    executed: list[orchestration.OrchestrationPlan] = []
    chat_calls: list[str] = []

    async def fake_execute(plan, **_kw):
        executed.append(plan)
        return SimpleNamespace(
            cancelled=False, output="ok", results=[],
            telemetry={"stop_reason": None},
        )

    async def fake_chat(*_a, **_k):
        chat_calls.append("chat")
        return "run-chat"

    async def noop(*_a, **_k):
        return None

    class LocalProv:
        ID = "mlx"
        LABEL = "MLX"
        DEFAULT_MODEL = "qwen"
        PROVIDER = {"id": "mlx", "default_model": "qwen", "category": "local"}

        def has_key(self) -> bool:
            return True

        async def chat_stream(self, req):
            yield base.TextChunk(text="ok")
            yield base.DoneChunk(stop_reason="end_turn")

    monkeypatch.setattr(orchestration, "execute", fake_execute)
    monkeypatch.setattr(daemon, "_dispatch_chat", fake_chat)
    monkeypatch.setattr(daemon, "_chat_notice", noop)
    monkeypatch.setattr(daemon, "_broadcast", noop)
    monkeypatch.setattr(daemon, "_append_event", lambda *a, **k: None)
    monkeypatch.setattr(daemon, "_remember_run_workspace", lambda *a, **k: None)
    monkeypatch.setattr(daemon, "_remember_run_thread", lambda *a, **k: None)
    monkeypatch.setattr(daemon, "_finish_desk", lambda *a, **k: None)
    monkeypatch.setattr(daemon, "_stream_parent_reply", noop)
    monkeypatch.setattr(daemon, "_effective_model", lambda *_a, **_k: "qwen")
    monkeypatch.setattr("switchbay.conversations.new_thread", lambda *_a, **_k: "th-local")
    monkeypatch.setattr("switchbay.llmgateway.get", lambda *_a, **_k: LocalProv())
    monkeypatch.setattr(daemon, "_keyed_provider_count", lambda: 1)
    monkeypatch.setattr(
        "switchbay.llmgateway.list_providers",
        lambda: [{"id": "mlx", "has_key": True, "category": "local"}],
    )
    monkeypatch.setattr(
        "switchbay.agents.fanout.append_to_rail_log", lambda *a, **k: None,
    )
    monkeypatch.setattr("switchbay.agents.fanout.write_summary", lambda *a, **k: None)

    app = {
        "workspace": tmp_path,
        "runs": {},
        "run_ws": {},
        "ws_clients": set(),
        "thread_id": "th-local",
        "thread_kind": "structured-agent",
    }
    text = "Worker-curate this workspace. Focus on: for 10 mins."
    rid = await daemon._dispatch_auto(
        app, None, text,
        workspace_override=tmp_path,
        provider_override="mlx",
        model_override="qwen",
        extra_system="prime",
        command="curate",
        task_kind="curation",
        constrained=daemon._curate_constrained(local=True, text="for 10 mins"),
        lock_provider=True,
    )
    assert not chat_calls, "local duration curate must not fall back to _dispatch_chat"
    assert executed, "repeated local curate must reach host waves"
    plan = executed[0]
    assert plan.decision.get("curate_repeat") is True
    assert plan.bounds.max_concurrency == 1
    assert rid


@pytest.mark.asyncio
async def test_local_curate_deadline_cancels_worker(tmp_path: Path, monkeypatch):
    from switchbay.agents import orchestration
    from switchbay.llmgateway import base

    monkeypatch.setattr(
        "switchbay.modestore.resolve_for_difficulty", lambda *a, **k: (None, None),
    )
    cancelled: list[int] = []

    class LocalBlocked:
        ID = "mlx"
        LABEL = "MLX"
        DEFAULT_MODEL = "qwen"
        PROVIDER = {"id": "mlx", "default_model": "qwen", "category": "local"}

        def has_key(self) -> bool:
            return True

        async def chat_stream(self, req):
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled.append(1)
                raise
            yield base.TextChunk(text="late")
            yield base.DoneChunk(stop_reason="end_turn")

    oid = "run-local-deadline"
    plan = _curate_plan(oid, until=time.time() + 0.25)
    plan.bounds = orchestration.OrchestrationBounds(max_concurrency=1).clamp()
    app = _app()
    app["runs"][oid] = {
        "run_id": oid, "status": "running", "started_at": time.time(),
        "provider": "mlx", "model": "qwen",
    }
    t0 = time.time()
    result = await orchestration.execute(
        plan, app=app, workspace=tmp_path, thread_id="th",
        parent_run_id=oid, default_provider=LocalBlocked(), default_model="qwen",
    )
    elapsed = time.time() - t0
    assert elapsed < 5, elapsed
    assert result.telemetry.get("stop_reason") == "curate window ended"
    assert cancelled, "local worker was not cancelled on expiry"


@pytest.mark.asyncio
async def test_short_deadline_cancels_blocked_worker(tmp_path: Path, monkeypatch):
    from switchbay.agents import orchestration
    from switchbay.llmgateway import base

    monkeypatch.setattr(
        "switchbay.modestore.resolve_for_difficulty", lambda *a, **k: (None, None),
    )
    cancelled = []

    class Blocked:
        ID = "openai"
        LABEL = "OpenAI"
        DEFAULT_MODEL = "fake"
        PROVIDER = {"id": "openai", "default_model": "fake"}

        def has_key(self) -> bool:
            return True

        async def chat_stream(self, req):
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled.append(1)
                raise
            yield base.TextChunk(text="late")
            yield base.DoneChunk(stop_reason="end_turn")

    oid = "run-deadline"
    plan = _curate_plan(oid, until=time.time() + 0.25)
    app = _app()
    app["runs"][oid] = {
        "run_id": oid, "status": "running", "started_at": time.time(),
        "provider": "openai", "model": "fake",
    }
    t0 = time.time()
    result = await orchestration.execute(
        plan, app=app, workspace=tmp_path, thread_id="th",
        parent_run_id=oid, default_provider=Blocked(), default_model="fake",
    )
    elapsed = time.time() - t0
    assert elapsed < 5, elapsed
    assert result.telemetry.get("stop_reason") == "curate window ended"
    ck = orchestration.load_checkpoint(tmp_path, oid)
    assert ck is not None
    assert ck["status"]["phase"] == "quiet"
    assert cancelled, "blocked worker was not cancelled"


@pytest.mark.asyncio
async def test_continuous_second_wave_then_stop(tmp_path: Path, monkeypatch):
    from switchbay.agents import orchestration
    from switchbay.llmgateway import base

    monkeypatch.setattr(
        "switchbay.modestore.resolve_for_difficulty", lambda *a, **k: (None, None),
    )
    monkeypatch.setattr(
        "switchbay.ce_host.wave_prime",
        lambda *a, **k: {"ok": True, "pick_mode": "test"},
    )

    class Fast:
        ID = "openai"
        LABEL = "OpenAI"
        DEFAULT_MODEL = "fake"
        PROVIDER = {"id": "openai", "default_model": "fake"}
        calls = 0

        def has_key(self) -> bool:
            return True

        async def chat_stream(self, req):
            type(self).calls += 1
            yield base.TextChunk(text="curated")
            yield base.DoneChunk(stop_reason="end_turn", input_tokens=1, output_tokens=1)

    oid = "run-waves"
    plan = _curate_plan(oid, until=None, repeat=True)
    app = _app()
    app["runs"][oid] = {
        "run_id": oid, "status": "running", "started_at": time.time(),
        "provider": "openai", "model": "fake",
    }
    task = asyncio.create_task(orchestration.execute(
        plan, app=app, workspace=tmp_path, thread_id="th",
        parent_run_id=oid, default_provider=Fast(), default_model="fake",
    ))
    saw_second = False
    for _ in range(80):
        await asyncio.sleep(0.05)
        ck = orchestration.load_checkpoint(tmp_path, oid)
        cont = int((ck or {}).get("status", {}).get("continuations") or 0)
        nodes = list(((ck or {}).get("plan").nodes if ck and ck.get("plan") else []))
        if cont >= 1 or len(nodes) >= 2 or Fast.calls >= 2:
            saw_second = True
            break
        if task.done():
            break
    app["runs"][oid]["user_cancel"] = True
    task.cancel()
    try:
        await asyncio.wait_for(task, timeout=5)
    except (asyncio.CancelledError, TimeoutError):
        pass
    assert saw_second, f"calls={Fast.calls} ck={orchestration.load_checkpoint(tmp_path, oid)}"


@pytest.mark.asyncio
async def test_resume_respects_workspace_model_allowlist(tmp_path: Path, monkeypatch):
    from switchbay.agents import orchestration, orchestration_policy as pol
    from switchbay.llmgateway import base

    monkeypatch.setattr(
        "switchbay.modestore.resolve_for_difficulty", lambda *a, **k: (None, None),
    )
    pol.set_denied_models(["anthropic/opus"], workspace=tmp_path)

    class Fast:
        ID = "openai"
        LABEL = "OpenAI"
        DEFAULT_MODEL = "fake"
        PROVIDER = {"id": "openai", "default_model": "fake"}
        used: list[str] = []

        def has_key(self) -> bool:
            return True

        async def chat_stream(self, req):
            type(self).used.append(getattr(req, "model", None) or "fake")
            yield base.TextChunk(text="ok")
            yield base.DoneChunk(stop_reason="end_turn", input_tokens=1, output_tokens=1)

    oid = "run-allow"
    plan = OrchestrationPlan(
        orchestration_id=oid,
        strategy="ce_curate",
        objective="once",
        nodes=[PlanNode(
            node_id="curate", kind="synthesize", objective="curate",
            role="curator", output_contract="synthesis",
            provider="anthropic", model="opus",
        )],
        decision={"task_kind": "curation"},
    )
    app = _app()
    app["runs"][oid] = {
        "run_id": oid, "status": "running", "started_at": time.time(),
        "provider": "openai", "model": "fake",
    }
    result = await orchestration.execute(
        plan, app=app, workspace=tmp_path, thread_id="th",
        parent_run_id=oid, default_provider=Fast(), default_model="fake",
        resume=True,
    )
    assert Fast.used, result
    assert result.results
    used_provider = result.results[0].get("provider")
    assert used_provider == "openai"
