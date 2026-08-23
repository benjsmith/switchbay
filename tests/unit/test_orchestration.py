"""Plan IR, validation, DAG scheduling, evidence, scoped tools, execute."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from switchbay.agents import evidence, fanout, orchestration, orchestration_policy as policy
from switchbay import orchestrator_fs
from switchbay.llmgateway import base


# ── fakes ──────────────────────────────────────────────────────────


class FakeWS:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_json(self, m: dict) -> None:
        self.messages.append(m)


class ScriptedProvider:
    """Yields scripted TextChunk / ToolUseChunk / DoneChunk sequences."""

    ID = "openai"
    LABEL = "OpenAI"
    DEFAULT_MODEL = "fake"
    PROVIDER = {"id": "openai", "default_model": "fake"}

    def __init__(self, replies: list[str] | dict[str, str] | None = None) -> None:
        self.replies = replies or ["ok"]
        self.calls: list[base.ChatRequest] = []
        self._i = 0

    def has_key(self) -> bool:
        return True

    async def chat_stream(self, req: base.ChatRequest):
        self.calls.append(req)
        user = ""
        if req.messages:
            c = req.messages[-1].get("content")
            user = c if isinstance(c, str) else str(c)
        if isinstance(self.replies, dict):
            text = self.replies.get("default", "ok")
            for k, v in self.replies.items():
                if k != "default" and k.lower() in (req.system or "").lower():
                    text = v
                    break
            if "verify" in (req.system or "").lower() and "classifications" in self.replies:
                text = self.replies["classifications"]
        else:
            text = self.replies[min(self._i, len(self.replies) - 1)]
            self._i += 1
        if text.startswith("TOOL:"):
            # TOOL:name:json
            _, name, payload = text.split(":", 2)
            import json as _json
            yield base.ToolUseChunk(id="t1", name=name, input=_json.loads(payload))
            yield base.DoneChunk(stop_reason="tool_use", input_tokens=3, output_tokens=2)
            return
        yield base.TextChunk(text=text)
        yield base.DoneChunk(stop_reason="end_turn", input_tokens=5, output_tokens=7)


def _app(ws: FakeWS | None = None) -> dict:
    ws = ws or FakeWS()
    return {"ws_clients": {ws}, "runs": {}, "run_ws": {}}


def _node(**kw) -> orchestration.PlanNode:
    defaults = dict(
        node_id="n1", kind="investigate", objective="look into X",
    )
    defaults.update(kw)
    return orchestration.PlanNode(**defaults)


# ── plan validation ────────────────────────────────────────────────


def test_valid_ivs_plan():
    p = orchestration.OrchestrationPlan(
        orchestration_id="run-abc",
        strategy="investigate_verify_synthesize",
        objective="research X",
        nodes=[
            _node(node_id="inv-0"),
            _node(node_id="inv-1"),
            _node(node_id="verify", kind="verify", objective="check",
                  dependencies=["inv-0", "inv-1"], output_contract="verification"),
            _node(node_id="synth", kind="synthesize", objective="research X",
                  dependencies=["verify"], output_contract="synthesis"),
        ],
    )
    assert orchestration.validate_plan(p) == []


def test_cycle_rejected():
    p = orchestration.OrchestrationPlan(
        orchestration_id="run-x",
        strategy="x",
        nodes=[
            _node(node_id="a", dependencies=["b"]),
            _node(node_id="b", dependencies=["a"]),
        ],
    )
    errs = orchestration.validate_plan(p)
    assert any("cycle" in e for e in errs)


def test_duplicate_and_missing_deps():
    p = orchestration.OrchestrationPlan(
        orchestration_id="run-x",
        strategy="x",
        nodes=[
            _node(node_id="a"),
            _node(node_id="a"),
            _node(node_id="b", dependencies=["nope"]),
        ],
    )
    errs = orchestration.validate_plan(p)
    assert any("duplicate" in e for e in errs)
    assert any("missing dependency" in e for e in errs)


def test_unknown_kind_and_write_tool_rejected():
    p = orchestration.OrchestrationPlan(
        orchestration_id="run-x",
        strategy="x",
        nodes=[
            _node(node_id="a", kind="debate"),
            _node(node_id="b", tools=["propose_wiki_page"]),
        ],
    )
    errs = orchestration.validate_plan(p)
    assert any("unknown kind" in e for e in errs)
    assert any("write tool" in e for e in errs)


def test_node_and_depth_bounds():
    if policy.HARD_MAX_NODES > 0:
        nodes = [_node(node_id=f"n{i}") for i in range(policy.HARD_MAX_NODES + 2)]
        p = orchestration.OrchestrationPlan(
            orchestration_id="run-x", strategy="x", nodes=nodes,
            bounds=orchestration.OrchestrationBounds(max_nodes=policy.HARD_MAX_NODES),
        )
        assert any("node count" in e for e in orchestration.validate_plan(p))
    else:
        nodes = [_node(node_id=f"n{i}") for i in range(40)]
        p = orchestration.OrchestrationPlan(
            orchestration_id="run-x", strategy="x", nodes=nodes,
            bounds=orchestration.OrchestrationBounds(max_nodes=0),
        )
        assert not any("node count" in e for e in orchestration.validate_plan(p))

    chain = []
    for i in range(policy.HARD_MAX_DEPTH + 2):
        deps = [f"n{i-1}"] if i else []
        chain.append(_node(node_id=f"n{i}", dependencies=deps))
    p2 = orchestration.OrchestrationPlan(
        orchestration_id="run-x", strategy="x", nodes=chain,
    )
    assert any("dag depth" in e for e in orchestration.validate_plan(p2))


def test_repair_drops_self_dep_and_unknown_tools():
    p = orchestration.OrchestrationPlan(
        orchestration_id="run-x",
        strategy="x",
        nodes=[_node(node_id="a", dependencies=["a", "ghost"], tools=["nope", "search_wiki"])],
    )
    p = orchestration.repair_plan(p)
    assert p.nodes[0].dependencies == []
    assert "search_wiki" in p.nodes[0].tools
    assert "nope" not in p.nodes[0].tools


def test_invalid_planner_fallback_to_single():
    p = orchestration.OrchestrationPlan(
        orchestration_id="run-x",
        strategy="broken",
        objective="hello",
        nodes=[_node(node_id="a", dependencies=["b"]), _node(node_id="b", dependencies=["a"])],
    )
    out = orchestration.ensure_valid(p)
    assert orchestration.validate_plan(out) == []
    assert out.strategy in ("single", "fixed_fanout")
    assert out.nodes


def test_ready_nodes_dependency_order():
    p = orchestration.OrchestrationPlan(
        orchestration_id="run-x", strategy="x",
        nodes=[
            _node(node_id="a"),
            _node(node_id="b"),
            _node(node_id="c", kind="verify", dependencies=["a", "b"],
                  output_contract="verification", objective="v"),
        ],
    )
    ready = orchestration.ready_nodes(p, set(), set())
    assert {n.node_id for n in ready} == {"a", "b"}
    ready2 = orchestration.ready_nodes(p, {"a", "b"}, set())
    assert [n.node_id for n in ready2] == ["c"]


def test_concurrency_bound_slices_ready_set():
    p = orchestration.plan_fixed_fanout(
        "t",
        [{"description": f"w{i}", "difficulty": "normal"} for i in range(5)],
        orchestration_id="run-x",
    )
    p.bounds.max_concurrency = 2
    p.bounds = p.bounds.clamp()
    ready = orchestration.ready_nodes(p, set(), set())
    batch = ready[: p.bounds.max_concurrency]
    assert len(batch) == 2


def test_old_run_without_orchestration_metadata_is_valid():
    rec = {
        "run_id": "run-old",
        "provider": "anthropic",
        "model": "claude",
        "status": "running",
        "task": object(),
    }
    out = {k: v for k, v in rec.items() if k != "task"}
    assert "orchestration_id" not in out
    assert out["run_id"] == "run-old"


def test_hierarchical_reduce_inserted_when_n_large():
    d = policy.PolicyDecision(
        strategy="parallel_investigate", n_investigators=5,
        include_verify=False, include_reduce=True, independence="medium",
        allow_expand=False, ladder_bias="balanced", reason="t",
        arm_id="parallel:5", preference=0.9,
    )
    plan = orchestration.plan_from_decision(
        "big", d, [{"description": f"t{i}"} for i in range(5)],
        orchestration_id="run-r",
    )
    kinds = [n.kind for n in plan.nodes]
    assert kinds.count("reduce") >= 2
    assert orchestration.validate_plan(plan) == []
    assert orchestration.dag_depth(plan.nodes) <= policy.HARD_MAX_DEPTH
    red = next(n for n in plan.nodes if n.kind == "reduce")
    assert red.difficulty == "trivial"
    assert red.ladder_hint == "trivial"
    # Reducers only depend on investigator pairs, not the whole board.
    assert len(red.dependencies) <= 2
    assert all(d.startswith("inv-") for d in red.dependencies)


def test_fixed_fanout_plan_shape_preserves_n():
    tasks = [{"description": "A", "difficulty": "trivial"},
             {"description": "B", "difficulty": "hard"}]
    p = orchestration.plan_fixed_fanout("orig", tasks, orchestration_id="run-1")
    assert p.strategy == "fixed_fanout"
    inv = [n for n in p.nodes if n.kind == "investigate"]
    assert len(inv) == 2
    synth = [n for n in p.nodes if n.kind == "synthesize"]
    assert len(synth) == 1
    assert synth[0].output_contract == "concat"
    assert orchestration.validate_plan(p) == []


# ── evidence ───────────────────────────────────────────────────────


def test_finding_roundtrip_and_provenance():
    f = evidence.Finding(
        claim="X causes Y",
        evidence=[evidence.EvidenceItem(
            source="wiki/concepts/x.md", locator="¶2",
            excerpt_or_fact="X causes Y", kind="wiki",
        )],
        confidence=0.8,
        node_id="inv-0",
    )
    d = f.to_dict()
    back = evidence.Finding.from_dict(d)
    assert back.claim == "X causes Y"
    assert back.evidence[0].kind == "wiki"
    assert back.evidence[0].source.endswith("x.md")


def test_parse_findings_json_and_prose_fallback():
    raw = '{"findings": [{"claim": "A", "evidence": [{"source": "p", "excerpt_or_fact": "e"}], "confidence": 0.9}]}'
    out = evidence.parse_findings(raw, node_id="inv-0")
    assert len(out) == 1 and out[0].claim == "A" and out[0].evidence
    prose = evidence.parse_findings("just a paragraph about X", node_id="inv-1")
    assert len(prose) == 1
    assert "paragraph" in prose[0].claim


def test_blackboard_append_only_and_persist(tmp_path: Path):
    bb = evidence.Blackboard("run-1")
    bb.append_finding(evidence.Finding(claim="one", node_id="a"))
    bb.append_verification(evidence.VerificationRecord(
        node_id="v",
        classifications=[{"finding_id": bb.findings[0].finding_id, "verdict": "supported"}],
        confidence=0.7, conflicts=0, unsupported=0,
    ))
    assert any(f.verdict == "candidate" for f in bb.findings)
    assert any(f.verdict == "supported" for f in bb.findings)
    path = tmp_path / "blackboard.json"
    bb.persist(path)
    loaded = evidence.Blackboard.load(path, "run-1")
    assert len(loaded.findings) == len(bb.findings)
    compact = loaded.compact_for_prompt()
    assert "one" in compact
    assert "verdict" in compact


def test_narrow_tools_strips_writes_and_parent_superset():
    out = orchestration.narrow_tools(
        ["search_wiki", "propose_wiki_page", "run_command", "not_a_tool"],
        parent={"search_wiki", "propose_wiki_page"},
    )
    assert out == ["search_wiki"]
    # Child cannot exceed parent: read-only tool not in parent is dropped.
    out2 = orchestration.narrow_tools(["wiki_neighbors"], parent={"search_wiki"})
    assert out2 == []
    synth_tools = orchestration.narrow_tools(
        ["create_report", "propose_wiki_page", "propose_page_edit", "run_command"],
        parent={
            "create_report", "propose_wiki_page", "propose_page_edit",
            "run_command", "search_wiki",
        },
        allow_synth=True,
    )
    assert "create_report" in synth_tools
    assert "propose_wiki_page" in synth_tools
    assert "propose_page_edit" in synth_tools
    assert "run_command" not in synth_tools


# ── execute ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_fixed_fanout_concat(tmp_path: Path, monkeypatch):
    ws = FakeWS()
    app = _app(ws)
    prov = ScriptedProvider([
        '{"findings":[{"claim":"from A","confidence":0.5}]}',
        '{"findings":[{"claim":"from B","confidence":0.5}]}',
    ])
    monkeypatch.setattr(
        "switchbay.modestore.resolve_for_difficulty", lambda *a, **k: (None, None),
    )
    plan = orchestration.plan_fixed_fanout(
        "do the thing",
        [{"description": "task A", "difficulty": "normal"},
         {"description": "task B", "difficulty": "normal"}],
        orchestration_id="run-fx",
    )
    result = await orchestration.execute(
        plan, app=app, workspace=tmp_path, thread_id="th1",
        parent_run_id="run-fx", default_provider=prov, default_model="fake",
    )
    assert result.ok
    assert "Worker" in result.output or "from A" in result.output or "task A" in result.output
    from switchbay import statedir
    art = statedir.runs_dir(tmp_path, "run-fx")
    assert (art / "plan.json").is_file()
    assert (art / "blackboard.json").is_file()


@pytest.mark.asyncio
async def test_execute_worker_failure_degrades(tmp_path: Path, monkeypatch):
    class Boom(ScriptedProvider):
        async def chat_stream(self, req):
            self.calls.append(req)
            if len(self.calls) == 1:
                raise RuntimeError("boom")
            async for ev in super().chat_stream(req):
                yield ev

    monkeypatch.setattr(
        "switchbay.modestore.resolve_for_difficulty", lambda *a, **k: (None, None),
    )
    plan = orchestration.plan_fixed_fanout(
        "t",
        [{"description": "a"}, {"description": "b"}],
        orchestration_id="run-fail",
    )
    result = await orchestration.execute(
        plan, app=_app(), workspace=tmp_path, thread_id="th",
        parent_run_id="run-fail", default_provider=Boom(["ok"]), default_model="fake",
    )
    # Concat merger still produces output; failed worker is noted.
    assert result.output
    assert result.telemetry["worker_failures"] >= 1


@pytest.mark.asyncio
async def test_execute_ivs_verify_and_tools(tmp_path: Path, monkeypatch):
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "index.md").write_text("# Index\n\nhello graph\n", encoding="utf-8")
    prov = ScriptedProvider({
        "default": '{"findings":[{"claim":"hello graph","evidence":[{"source":"wiki/index.md","excerpt_or_fact":"hello graph","kind":"wiki"}],"confidence":0.8}]}',
        "verifier": '{"classifications":[{"finding_id":"x","verdict":"supported"}],"confidence":0.9,"conflicts":0,"unsupported":0}',
        "synthesize": "The wiki says hello graph.",
    })
    # Route by system prompt keywords.
    async def chat_stream(req):
        sys = req.system or ""
        if "verifier" in sys.lower() or "Verify" in sys or "classify" in sys.lower():
            yield base.TextChunk(text='{"classifications":[{"finding_id":"f","verdict":"supported"}],"confidence":0.85,"conflicts":0,"unsupported":0}')
        elif "synthesize" in sys.lower() or "synthesiz" in sys.lower():
            yield base.TextChunk(text="Supported: hello graph.")
        else:
            yield base.TextChunk(text='{"findings":[{"claim":"hello graph","evidence":[{"source":"wiki/index.md","kind":"wiki","excerpt_or_fact":"hello graph"}],"confidence":0.8}]}')
        yield base.DoneChunk(stop_reason="end_turn", input_tokens=4, output_tokens=6)
    prov.chat_stream = chat_stream  # type: ignore[method-assign]

    monkeypatch.setattr(
        "switchbay.modestore.resolve_for_difficulty", lambda *a, **k: (None, None),
    )
    decision = policy.PolicyDecision(
        strategy="investigate_verify_synthesize",
        n_investigators=2,
        include_verify=True,
        include_reduce=False,
        independence="high",
        allow_expand=False,
        ladder_bias="balanced",
        reason="test",
        arm_id="ivs:2",
        preference=0.7,
        features={"research": True, "preference": 0.7, "prompt_len": 200},
    )
    tasks = [{"description": "slice A"}, {"description": "slice B"}]
    plan = orchestration.plan_from_decision(
        "what does the wiki know?", decision, tasks, orchestration_id="run-ivs",
    )
    assert any(n.kind == "verify" for n in plan.nodes)
    assert all(
        "propose_wiki_page" not in n.tools
        for n in plan.nodes if n.kind == "investigate"
    )
    result = await orchestration.execute(
        plan, app=_app(), workspace=tmp_path, thread_id="th",
        parent_run_id="run-ivs", default_provider=prov, default_model="fake",
    )
    assert result.ok
    assert result.blackboard.verifications
    assert "hello" in result.output.lower() or result.output


@pytest.mark.asyncio
async def test_capability_narrowing_blocks_write_tool_at_runtime(tmp_path: Path, monkeypatch):
    """Even if a plan sneaks a write tool onto the node, the runner
    intersects with the read-only set before calling tools.execute."""
    called: list[str] = []

    def fake_execute(name, workspace, payload):
        called.append(name)
        return {"ok": True}

    monkeypatch.setattr("switchbay.tools.execute", fake_execute)
    monkeypatch.setattr(
        "switchbay.modestore.resolve_for_difficulty", lambda *a, **k: (None, None),
    )

    class ToolThenAnswer(ScriptedProvider):
        def __init__(self) -> None:
            super().__init__()
            self.phase = 0

        async def chat_stream(self, req):
            self.calls.append(req)
            if self.phase == 0:
                self.phase = 1
                yield base.ToolUseChunk(
                    id="c1", name="propose_wiki_page",
                    input={"kind": "note", "title": "X", "body": "nope"},
                )
                yield base.DoneChunk(stop_reason="tool_use")
                return
            yield base.TextChunk(text='{"findings":[{"claim":"blocked write","confidence":0.2}]}')
            yield base.DoneChunk(stop_reason="end_turn")

    node = _node(
        node_id="inv-0", tools=["search_wiki", "propose_wiki_page"],
        graph_access="read",
    )
    plan = orchestration.OrchestrationPlan(
        orchestration_id="run-cap",
        strategy="parallel_investigate",
        objective="x",
        nodes=[
            node,
            _node(node_id="merge", kind="synthesize", objective="x",
                  dependencies=["inv-0"], output_contract="concat"),
        ],
    )
    await orchestration.execute(
        plan, app=_app(), workspace=tmp_path, thread_id="th",
        parent_run_id="run-cap", default_provider=ToolThenAnswer(),
        default_model="fake",
    )
    assert "propose_wiki_page" not in called


@pytest.mark.asyncio
async def test_resume_skips_completed_nodes(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "switchbay.modestore.resolve_for_difficulty", lambda *a, **k: (None, None),
    )
    plan = orchestration.plan_fixed_fanout(
        "research both slices",
        [{"description": "slice A"}, {"description": "slice B"}],
        orchestration_id="run-resume",
    )
    orchestration.persist_plan(tmp_path, plan)
    orchestration.persist_checkpoint(
        tmp_path, "run-resume",
        phase="running",
        completed={"w0"},
        failed=set(),
        expansions=0,
        results={"w0": {
            "node_id": "w0", "kind": "investigate", "ok": True,
            "output": '{"findings":[{"claim":"A done","confidence":0.8}]}',
            "input_tokens": 10, "output_tokens": 20,
            "task": {"description": "slice A", "difficulty": "normal"},
            "worker_index": 0,
        }},
        elapsed_s=5.0,
        thread_id="th",
        extra={"objective": "research both slices", "default_provider": "openai"},
    )
    prov = ScriptedProvider(['{"findings":[{"claim":"B done","confidence":0.7}]}'])
    result = await orchestration.execute(
        plan, app=_app(), workspace=tmp_path, thread_id="th",
        parent_run_id="run-resume", default_provider=prov, default_model="fake",
        resume=True,
    )
    assert result.ok
    assert len(prov.calls) == 1  # only the unfinished investigator
    assert "B done" in (result.output or "") or "slice" in (result.output or "")
    ck = orchestration.load_checkpoint(tmp_path, "run-resume")
    assert ck is not None
    assert ck["status"]["phase"] in ("completed", "interrupted")
    assert "w0" in ck["status"]["completed"]


@pytest.mark.asyncio
async def test_process_stop_checkpoint_is_interrupted_not_cancelled(tmp_path: Path, monkeypatch):
    """Daemon restart cancels the parent task; that must stay resumable."""
    monkeypatch.setattr(
        "switchbay.modestore.resolve_for_difficulty", lambda *a, **k: (None, None),
    )

    class Slow(ScriptedProvider):
        async def chat_stream(self, req):
            self.calls.append(req)
            await asyncio.sleep(60)
            yield base.TextChunk(text="late")
            yield base.DoneChunk(stop_reason="end_turn")

    plan = orchestration.plan_fixed_fanout(
        "t", [{"description": "a"}], orchestration_id="run-int2",
    )
    app = _app()
    app["runs"]["run-int2"] = {
        "run_id": "run-int2", "status": "running", "started_at": 0.0,
        "provider": "openai", "model": "fake",
    }
    task = asyncio.create_task(orchestration.execute(
        plan, app=app, workspace=tmp_path, thread_id="th",
        parent_run_id="run-int2", default_provider=Slow(["ok"]),
        default_model="fake",
    ))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    ck = orchestration.load_checkpoint(tmp_path, "run-int2")
    assert ck is not None
    assert ck["status"]["phase"] == "interrupted"
    assert orchestration.checkpoint_resumable(ck["status"])


@pytest.mark.asyncio
async def test_cancelled_checkpoint_is_not_resumed(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "switchbay.modestore.resolve_for_difficulty", lambda *a, **k: (None, None),
    )
    plan = orchestration.plan_fixed_fanout(
        "t", [{"description": "a"}, {"description": "b"}],
        orchestration_id="run-can",
    )
    orchestration.persist_plan(tmp_path, plan)
    orchestration.persist_checkpoint(
        tmp_path, "run-can",
        phase="cancelled", completed=set(), failed=set(),
        expansions=0, results={}, elapsed_s=1.0, thread_id="th",
    )
    prov = ScriptedProvider(["should not run"])
    result = await orchestration.execute(
        plan, app=_app(), workspace=tmp_path, thread_id="th",
        parent_run_id="run-can", default_provider=prov, default_model="fake",
        resume=True,
    )
    assert result.cancelled
    assert prov.calls == []


def test_list_interrupted_skips_cancelled_and_completed(tmp_path: Path):
    live = orchestration.plan_fixed_fanout(
        "live", [{"description": "a"}, {"description": "b"}],
        orchestration_id="run-live",
    )
    orchestration.persist_plan(tmp_path, live)
    orchestration.persist_checkpoint(
        tmp_path, "run-live", phase="running", completed=set(), failed=set(),
        expansions=0, results={}, elapsed_s=1.0, thread_id="th",
        extra={"objective": "live"},
    )
    dead = orchestration.plan_fixed_fanout(
        "dead", [{"description": "a"}, {"description": "b"}],
        orchestration_id="run-dead",
    )
    orchestration.persist_plan(tmp_path, dead)
    orchestration.persist_checkpoint(
        tmp_path, "run-dead", phase="cancelled", completed=set(), failed=set(),
        expansions=0, results={}, elapsed_s=1.0, thread_id="th",
    )
    items = orchestration.list_interrupted(tmp_path)
    ids = {i["orchestration_id"] for i in items}
    assert "run-live" in ids
    assert "run-dead" not in ids


def test_execute_node_allowed_for_lab_protocol():
    d = policy.PolicyDecision(
        strategy="investigate_verify_synthesize", n_investigators=2,
        include_verify=True, include_reduce=False, include_execute=True,
        independence="high", allow_expand=False, ladder_bias="balanced",
        reason="lab", arm_id="ivs:2", preference=0.7,
        features={"science": True, "experiment": True, "preference": 0.7},
    )
    plan = orchestration.plan_from_decision(
        "run the assay protocol", d,
        [{"description": "hypothesis"}, {"description": "protocol"}],
        orchestration_id="run-lab",
    )
    kinds = [n.kind for n in plan.nodes]
    assert "execute" in kinds
    exec_n = next(n for n in plan.nodes if n.kind == "execute")
    assert orchestration.validate_plan(plan) == []
    # Orthogonal compute path: do not serialize behind investigators.
    assert exec_n.dependencies == []
    verify = next(n for n in plan.nodes if n.kind == "verify")
    assert "exec" in verify.dependencies
    assert {"inv-0", "inv-1"} <= set(verify.dependencies)
    # Shell is parent-subset: rail-default has run_command.
    assert "run_command" in exec_n.tools
    inv = next(n for n in plan.nodes if n.kind == "investigate")
    assert "run_command" not in inv.tools
    synth = next(n for n in plan.nodes if n.kind == "synthesize")
    assert "create_report" in synth.tools
    assert "propose_wiki_page" in synth.tools
    assert "propose_page_edit" in synth.tools
    assert "run_command" not in synth.tools


def test_synth_prompt_requires_inspectable_wiki_trail():
    assert "kind=evidence" in orchestration.SYNTH_SYSTEM
    assert "kind=analysis" in orchestration.SYNTH_SYSTEM
    assert "never invent a number" in orchestration.SYNTH_SYSTEM
    assert "Evidence snapshot" in orchestration.SYNTH_SYSTEM
    assert "OBJECTIVE_MET" in orchestration.SYNTH_SYSTEM
    assert "wiki/tables" in orchestration.SYNTH_SYSTEM
    assert "working set" in orchestration.SYNTH_SYSTEM
    assert "primary source" in orchestration.SYNTH_SYSTEM
    node = orchestration.PlanNode(
        node_id="synth", kind="synthesize", objective="five openers",
    )
    prompt = orchestration._user_prompt(node, evidence.Blackboard("r1"))
    assert "analysis+evidence" in prompt
    assert "Evidence snapshot" in prompt
    assert "gaps" in prompt.lower()


def test_compact_synthesize_dedupes_classified_copies():
    bb = evidence.Blackboard("run-1")
    f = bb.append_finding(evidence.Finding(
        claim="X", node_id="inv-0",
        evidence=[evidence.EvidenceItem(source="wiki/x.md", kind="wiki")],
        confidence=0.8,
    ))
    bb.append_verification(evidence.VerificationRecord(
        node_id="verify",
        classifications=[{"finding_id": f.finding_id, "verdict": "supported"}],
        confidence=0.9, conflicts=0, unsupported=0,
    ))
    compact = bb.compact_for_prompt(role="synthesize")
    assert compact.count('"claim": "X"') == 1
    assert "supported" in compact
    assert "classifications" not in compact
    assert "verification_summary" in compact


def test_compact_verify_hides_prior_verdicts_and_reduce_is_local():
    bb = evidence.Blackboard("run-1")
    a = bb.append_finding(evidence.Finding(claim="A", node_id="inv-0", confidence=0.7))
    bb.append_finding(evidence.Finding(claim="B", node_id="inv-1", confidence=0.6))
    bb.append_verification(evidence.VerificationRecord(
        node_id="verify",
        classifications=[{"finding_id": a.finding_id, "verdict": "supported"}],
        confidence=0.8, unresolved=["gap"], conflicts=0, unsupported=0,
    ))
    bb.append_finding(evidence.Finding(claim="new", node_id="inv-x0", confidence=0.5))
    v = bb.compact_for_prompt(role="verify")
    assert "new" in v
    assert "prior_unresolved" in v
    assert "gap" in v
    # Original classified claim is not re-sent as a candidate; missed
    # candidates (B) and new expansion findings still are.
    assert '"claim": "A"' not in v
    assert "B" in v
    bb.append_finding(evidence.Finding(claim="pair-a", node_id="inv-0"))
    bb.append_finding(evidence.Finding(claim="pair-b", node_id="inv-1"))
    red = bb.compact_for_prompt(role="reduce", from_nodes=["inv-0"])
    assert "pair-a" in red
    assert "pair-b" not in red


def test_compact_synth_drops_reduced_investigator_rows():
    bb = evidence.Blackboard("run-1")
    bb.append_finding(evidence.Finding(claim="old-inv", node_id="inv-0"))
    bb.mark_replaced(["inv-0"])
    bb.append_finding(evidence.Finding(claim="reduced", node_id="red-0"))
    compact = bb.compact_for_prompt(role="synthesize")
    assert "reduced" in compact
    assert "old-inv" not in compact


@pytest.mark.asyncio
async def test_execute_node_can_run_parent_command(tmp_path: Path, monkeypatch):
    called: list[str] = []

    def fake_execute(name, workspace, payload):
        called.append(name)
        return {"ok": True, "stdout": "42"}

    monkeypatch.setattr("switchbay.tools.execute", fake_execute)
    monkeypatch.setattr(
        "switchbay.modestore.resolve_for_difficulty", lambda *a, **k: (None, None),
    )

    class ExecThenAnswer(ScriptedProvider):
        def __init__(self) -> None:
            super().__init__()
            self.exec_turns = 0

        async def chat_stream(self, req):
            self.calls.append(req)
            sys = (req.system or "").lower()
            if "execute one measurement" in sys:
                if self.exec_turns == 0:
                    self.exec_turns = 1
                    yield base.ToolUseChunk(
                        id="e1", name="run_command",
                        input={"argv": ["true"]},
                    )
                    yield base.DoneChunk(stop_reason="tool_use")
                    return
                yield base.TextChunk(text=(
                    '{"findings":[{"claim":"measured 42",'
                    '"evidence":[{"source":"run_command","kind":"compute",'
                    '"excerpt_or_fact":"42"}],"confidence":0.9}]}'
                ))
                yield base.DoneChunk(stop_reason="end_turn")
                return
            if "verifier" in sys or "classify each finding" in sys:
                yield base.TextChunk(text=(
                    '{"classifications":[{"finding_id":"f","verdict":"supported"}],'
                    '"confidence":0.8,"conflicts":0,"unsupported":0}'
                ))
            elif "synthesize" in sys:
                yield base.TextChunk(text="Measured 42.")
            else:
                yield base.TextChunk(text=(
                    '{"findings":[{"claim":"hypothesis","confidence":0.5}]}'
                ))
            yield base.DoneChunk(stop_reason="end_turn")

    d = policy.PolicyDecision(
        strategy="investigate_verify_synthesize", n_investigators=2,
        include_verify=True, include_reduce=False, include_execute=True,
        independence="high", allow_expand=False, ladder_bias="balanced",
        reason="lab", arm_id="ivs:2", preference=0.7,
    )
    plan = orchestration.plan_from_decision(
        "run the assay", d,
        [{"description": "hypothesis"}, {"description": "protocol"}],
        orchestration_id="run-ex",
    )
    result = await orchestration.execute(
        plan, app=_app(), workspace=tmp_path, thread_id="th",
        parent_run_id="run-ex", default_provider=ExecThenAnswer(),
        default_model="fake",
    )
    assert result.ok
    assert "run_command" in called


@pytest.mark.asyncio
async def test_execute_records_plan_nodes_and_handoffs(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "switchbay.modestore.resolve_for_difficulty", lambda *a, **k: (None, None),
    )
    app = _app()
    app["runs"]["run-h"] = {
        "run_id": "run-h", "status": "running", "started_at": 0.0,
        "provider": "openai", "model": "fake",
    }

    class Kinded(ScriptedProvider):
        async def chat_stream(self, req):
            self.calls.append(req)
            sys = (req.system or "").lower()
            if "verifier" in sys or "classify each finding" in sys:
                yield base.TextChunk(text=(
                    '{"classifications":[{"finding_id":"f","verdict":"supported"}],'
                    '"confidence":0.8,"conflicts":0,"unsupported":0}'
                ))
            elif "synthesize" in sys:
                yield base.TextChunk(text="Team answer.")
            else:
                yield base.TextChunk(text=(
                    '{"findings":[{"claim":"from worker",'
                    '"evidence":[{"source":"wiki/x.md","kind":"wiki"}],'
                    '"confidence":0.7}]}'
                ))
            yield base.DoneChunk(stop_reason="end_turn", input_tokens=3, output_tokens=4)

    d = policy.PolicyDecision(
        strategy="investigate_verify_synthesize", n_investigators=2,
        include_verify=True, include_reduce=False, independence="high",
        allow_expand=False, ladder_bias="balanced", reason="bench",
        arm_id="ivs:2", preference=0.7,
    )
    plan = orchestration.plan_from_decision(
        "research T", d,
        [{"description": "slice A"}, {"description": "slice B"}],
        orchestration_id="run-h",
    )
    result = await orchestration.execute(
        plan, app=app, workspace=tmp_path, thread_id="th",
        parent_run_id="run-h", default_provider=Kinded(), default_model="fake",
    )
    assert result.ok
    parent = app["runs"]["run-h"]
    nodes = parent.get("plan_nodes") or []
    assert any(n.get("node_id") == "inv-0" for n in nodes)
    assert any(n.get("kind") == "verify" for n in nodes)
    assert "2 investigators" in (parent.get("decision_reason") or "")
    assert parent.get("arm_reason") == "bench"
    msgs = parent.get("orchestration_messages") or []
    kinds = {m.get("kind") for m in msgs}
    assert "spawn" in kinds
    assert "findings" in kinds
    assert "handoff" in kinds
    assert any(m.get("from") == "chief" for m in msgs)
    assert any(m.get("to") == orchestration.BLACKBOARD_ID for m in msgs)
    org = orchestrator_fs.load_org(tmp_path)
    assert org is not None
    org_ids = {n.get("node_id") for n in org.get("nodes") or []}
    assert "inv-0" in org_ids
    assert "inv-1" in org_ids
    # Dashboard payload is JSON-serialisable (no asyncio.Task).
    import json as _json
    _json.dumps({k: v for k, v in parent.items() if k != "task"}, default=str)


@pytest.mark.asyncio
async def test_weekly_limit_fail_fast_retries_next_provider(tmp_path: Path, monkeypatch):
    from switchbay import llmgateway
    from switchbay.agents import orchestration_health as health

    monkeypatch.setattr(health, "health_path", lambda: tmp_path / "hp.json")
    monkeypatch.setattr(
        "switchbay.modestore.resolve_for_difficulty", lambda *a, **k: (None, None),
    )

    class LimitClaude:
        ID = "claude_code"
        LABEL = "Claude"
        DEFAULT_MODEL = "sonnet"

        def __init__(self) -> None:
            self.calls = 0

        def has_key(self) -> bool:
            return True

        async def chat_stream(self, req):
            self.calls += 1
            yield base.TextChunk(
                text="You've hit your weekly limit - resets Aug 26 at 11pm (Europe/Zurich)",
            )
            yield base.DoneChunk(stop_reason="end_turn")

    claude = LimitClaude()
    ok = ScriptedProvider([
        '{"findings":[{"claim":"from backup","confidence":0.6}]}',
    ])
    ok.ID = "openai"

    def fake_get(pid):
        if pid == "claude_code":
            return claude
        raise llmgateway.ProviderError(f"unknown {pid}", code="unsupported")

    monkeypatch.setattr(llmgateway, "get", fake_get)

    plan = orchestration.OrchestrationPlan(
        orchestration_id="run-lim",
        strategy="parallel_investigate",
        objective="x",
        nodes=[
            _node(
                node_id="inv-0", provider="claude_code", model="sonnet",
            ),
            _node(
                node_id="merge", kind="synthesize", objective="x",
                dependencies=["inv-0"], output_contract="concat",
            ),
        ],
    )
    result = await orchestration.execute(
        plan, app=_app(), workspace=tmp_path, thread_id="th",
        parent_run_id="run-lim", default_provider=ok, default_model="fake",
    )
    assert result.ok
    inv = next(r for r in result.results if r.get("node_id") == "inv-0")
    assert inv["ok"]
    assert inv["provider"] == "openai"
    assert claude.calls == 1
    assert len(ok.calls) == 1
    assert not health.is_available("claude_code")


@pytest.mark.asyncio
async def test_worker_persists_tool_events_for_transcript(tmp_path: Path, monkeypatch):
    from switchbay import conversations

    monkeypatch.setattr(
        "switchbay.modestore.resolve_for_difficulty", lambda *a, **k: (None, None),
    )
    monkeypatch.setattr(
        "switchbay.tools.execute",
        lambda name, workspace, payload: {"ok": True, "hits": []},
    )
    prov = ScriptedProvider([
        'TOOL:search_wiki:{"query":"X"}',
        '{"findings":[{"claim":"from tool","confidence":0.5}]}',
    ])
    plan = orchestration.OrchestrationPlan(
        orchestration_id="run-ev",
        strategy="parallel_investigate",
        objective="x",
        nodes=[
            _node(
                node_id="inv-0", tools=["search_wiki"], graph_access="read",
            ),
            _node(
                node_id="merge", kind="synthesize", objective="x",
                dependencies=["inv-0"], output_contract="concat",
            ),
        ],
    )
    app = _app()
    result = await orchestration.execute(
        plan, app=app, workspace=tmp_path, thread_id="th-ev",
        parent_run_id="run-ev", default_provider=prov, default_model="fake",
    )
    assert result.ok
    evs = conversations.list_events(tmp_path, run_id="run-ev-inv-0", limit=50)
    kinds = {e.get("kind") for e in evs}
    assert "tool_use" in kinds
    assert "tool_result" in kinds
    assert any("search_wiki" in (e.get("summary") or "") for e in evs)


def test_live_org_summary_tracks_roster_not_opening_recipe():
    plan = orchestration.OrchestrationPlan(
        orchestration_id="run-sum",
        strategy="investigate_verify_synthesize",
        objective="research T",
        nodes=[
            _node(node_id="inv-0"),
            _node(node_id="inv-1"),
            _node(node_id="inv-x5"),
            _node(node_id="verify", kind="verify", objective="check",
                  dependencies=["inv-0", "inv-1"]),
            _node(node_id="synth", kind="synthesize", objective="research T",
                  dependencies=["verify"]),
        ],
        decision={"reason": "three diverse investigators then verify"},
    )
    text = orchestration.live_org_summary(
        plan, failed={"inv-1"}, expansions=2, continuations=1,
    )
    assert "2 investigators" in text
    assert "1 verifier" in text
    assert "1 synthesizer" in text
    assert "expanded ×2" in text
    assert "continued ×1" in text
    assert "three diverse" not in text


def test_standing_org_drops_failed_and_pending(tmp_path: Path):
    plan = orchestration.OrchestrationPlan(
        orchestration_id="run-org",
        strategy="investigate_verify_synthesize",
        objective="research T",
        nodes=[
            _node(node_id="inv-0"),
            _node(node_id="inv-1"),
            _node(node_id="verify", kind="verify", objective="check",
                  dependencies=["inv-0", "inv-1"]),
            _node(node_id="synth", kind="synthesize", objective="research T",
                  dependencies=["verify"]),
        ],
    )
    view = orchestration.standing_org_view(
        plan,
        completed={"inv-0", "verify"},
        failed={"inv-1"},
        results={
            "inv-0": {"provider": "grok_build", "model": "g"},
            "inv-1": {"provider": "claude_code", "ok": False},
            "verify": {"provider": "openai"},
        },
        running=set(),
    )
    ids = [n["node_id"] for n in view["nodes"]]
    assert ids == ["inv-0", "verify"]
    assert "inv-1" not in ids
    assert "synth" not in ids  # never started
    orchestrator_fs.save_org(tmp_path, view)
    loaded = orchestrator_fs.load_org(tmp_path)
    assert loaded is not None
    assert [n["node_id"] for n in loaded["nodes"]] == ["inv-0", "verify"]


def test_snapshot_roundtrip_and_prompt(tmp_path: Path):
    payload = {
        "orchestration_id": "run-snap",
        "objective": "overnight desk",
        "phase": "running",
        "interrupted": True,
        "stage": "investigate ×2",
        "completed": ["inv-0"],
        "failed": ["inv-1"],
        "findings_n": 12,
        "unique_sources": 4,
        "in_flight": [{
            "node_id": "inv-x13",
            "kind": "investigate",
            "provider": "grok_build",
            "model": "grok-4.6",
            "tool_count": 50,
            "current_tool": "grep",
            "activity": "reading 10-K/A",
            "recent_tools": ["Read", "grep"],
            "partial_text": "OXY amendment body is open.",
        }],
        "blackboard_excerpt": "claim: OXY 10-K/A not opened",
    }
    orchestration.write_snapshot(tmp_path, "run-snap", payload)
    loaded = orchestration.load_snapshot(tmp_path, "run-snap")
    assert loaded is not None
    assert loaded["interrupted"] is True
    md = (orchestration.artifact_dir(tmp_path, "run-snap") / "SNAPSHOT.md").read_text(
        encoding="utf-8",
    )
    assert "inv-x13" in md
    assert "overnight desk" in md
    block = orchestration.snapshot_prompt_block(loaded, node_id="inv-x13")
    assert "interrupted" in block.lower()
    assert "50" in block
    desk = tmp_path / ".orchestrator" / "state" / "snapshot.md"
    assert desk.is_file()


@pytest.mark.asyncio
async def test_resume_injects_interrupt_snapshot_into_worker(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "switchbay.modestore.resolve_for_difficulty", lambda *a, **k: (None, None),
    )
    plan = orchestration.plan_fixed_fanout(
        "research both slices",
        [{"description": "slice A"}, {"description": "slice B"}],
        orchestration_id="run-int",
    )
    orchestration.persist_plan(tmp_path, plan)
    orchestration.persist_checkpoint(
        tmp_path, "run-int",
        phase="running",
        completed={"w0"},
        failed=set(),
        expansions=0,
        results={"w0": {
            "node_id": "w0", "kind": "investigate", "ok": True,
            "output": '{"findings":[{"claim":"A done","confidence":0.8}]}',
            "input_tokens": 10, "output_tokens": 20,
            "task": {"description": "slice A", "difficulty": "normal"},
            "worker_index": 0,
        }},
        elapsed_s=5.0,
        thread_id="th",
        extra={"objective": "research both slices", "default_provider": "openai"},
    )
    orchestration.write_snapshot(tmp_path, "run-int", {
        "objective": "research both slices",
        "interrupted": True,
        "completed": ["w0"],
        "in_flight": [{
            "node_id": "w1",
            "kind": "investigate",
            "tool_count": 12,
            "activity": "mid-Read of wiki/x.md",
            "recent_tools": ["Read"],
            "partial_text": "found a table",
        }],
    })
    orchestration.write_node_live(tmp_path, "run-int", "w1", {
        "tool_count": 12,
        "activity": "mid-Read of wiki/x.md",
        "recent_tools": ["Read"],
        "partial_text": "found a table",
    }, min_gap_s=0)
    prov = ScriptedProvider(['{"findings":[{"claim":"B continued","confidence":0.7}]}'])
    result = await orchestration.execute(
        plan, app=_app(), workspace=tmp_path, thread_id="th",
        parent_run_id="run-int", default_provider=prov, default_model="fake",
        resume=True,
    )
    assert result.ok
    assert len(prov.calls) == 1
    user = ""
    if prov.calls[0].messages:
        user = str(prov.calls[0].messages[-1].get("content") or "")
    assert "interrupted" in user.lower()
    assert "12" in user or "mid-Read" in user


def test_handoff_protocol_is_tiny():
    import json as _json
    from switchbay import protocol
    msg = protocol.orchestration_handoff(
        "run-x", src="inv-0", dst="chief", kind="findings",
        text="2 findings · hello", ts=1.0,
    )
    assert msg["type"] == "CUSTOM"
    inner = msg["value"]
    assert inner["type"] == "orchestration_handoff"
    assert inner["from"] == "inv-0"
    assert inner["to"] == "chief"
    assert len(_json.dumps(inner)) < 800


def test_desk_landed_pages_are_inventory_not_reviews(tmp_path: Path):
    orchestrator_fs.ensure(tmp_path)
    orchestrator_fs.remember_landed(tmp_path, "wiki/analysis/foo.md")
    orchestrator_fs.remember_landed(tmp_path, "./wiki/analysis/foo.md")
    assert orchestrator_fs.landed_pages(tmp_path) == {"wiki/analysis/foo.md"}
    n = orchestrator_fs.reused_desk_sources(
        tmp_path, {"wiki/analysis/foo.md", "wiki/other.md"},
    )
    assert n == 1
    orchestrator_fs.forget_landed(tmp_path, "wiki/analysis/foo.md")
    assert orchestrator_fs.landed_pages(tmp_path) == set()
    assert orchestrator_fs.reused_desk_sources(
        tmp_path, {"wiki/analysis/foo.md"},
    ) == 0


def test_orchestrator_fs_desk_layout_and_brief(tmp_path: Path):
    root = orchestrator_fs.ensure(tmp_path)
    assert (root / "briefs").is_dir()
    assert (root / "cache" / "filings").is_dir()
    assert (root / "README.md").is_file()
    (root / "watchlist.csv").write_text(
        "ticker,sector,thesis\nAAPL,tech,long\n", encoding="utf-8",
    )
    excerpt = orchestrator_fs.watchlist_excerpt(tmp_path)
    assert "AAPL" in excerpt
    brief = orchestrator_fs.write_brief(
        tmp_path, "run-abc",
        objective="research T", output="Conclusion.",
        findings_n=3, conflicts=0, unsupported=1,
    )
    text = brief.read_text(encoding="utf-8")
    assert "Conclusion." in text
    assert "unsupported: 1" in text
    orchestrator_fs.append_log(tmp_path, "start run-abc")
    log = (root / "log.md").read_text(encoding="utf-8")
    assert "start run-abc" in log
    prompt = orchestration._user_prompt(
        orchestration.PlanNode(
            node_id="inv-0", kind="investigate", objective="look at AAPL",
        ),
        evidence.Blackboard("run-abc"),
        workspace=tmp_path,
    )
    assert "watchlist" in prompt.lower()
    assert "AAPL" in prompt
    (root / "APPROACH.md").write_text("# Overnight sequence\nPhase 1 ingest\n", encoding="utf-8")
    prompt2 = orchestration._user_prompt(
        orchestration.PlanNode(
            node_id="inv-0", kind="investigate", objective="look at AAPL",
        ),
        evidence.Blackboard("run-abc"),
        workspace=tmp_path,
    )
    assert "Desk approach" in prompt2
    assert "Phase 1" in prompt2


def test_fanout_merge_still_concat():
    merged = fanout.merge("req", [
        {"worker_index": 0, "ok": True, "output": "A",
         "task": {"description": "t0"}},
        {"worker_index": 1, "ok": False, "error": "boom",
         "task": {"description": "t1"}},
    ])
    assert "Worker 1" in merged
    assert "A" in merged
    assert "boom" in merged


@pytest.mark.asyncio
async def test_vacuous_verify_does_not_rubber_stamp(tmp_path: Path, monkeypatch):
    """When every investigator fails, do not LLM-verify empty findings
    as confidence=1.0 / unsupported=0 (run-e7a646f8)."""
    class Boom(ScriptedProvider):
        async def chat_stream(self, req):
            self.calls.append(req)
            raise RuntimeError("provider down")
            yield  # noqa: PIE790 — keep this an async generator

    monkeypatch.setattr(
        "switchbay.modestore.resolve_for_difficulty", lambda *a, **k: (None, None),
    )
    d = policy.PolicyDecision(
        strategy="investigate_verify_synthesize", n_investigators=2,
        include_verify=True, include_reduce=False, independence="high",
        allow_expand=False, ladder_bias="balanced", reason="test",
        arm_id="ivs_diverse_2", preference=0.7,
    )
    plan = orchestration.plan_from_decision(
        "research T", d,
        [{"description": "a"}, {"description": "b"}],
        orchestration_id="run-empty",
    )
    boom = Boom()
    result = await orchestration.execute(
        plan, app=_app(), workspace=tmp_path, thread_id="th",
        parent_run_id="run-empty", default_provider=boom, default_model="fake",
    )
    verify = next(r for r in result.results if r.get("kind") == "verify")
    body = json.loads(verify["output"])
    assert body["confidence"] == 0.0
    assert body["unsupported"] >= 1
    assert "no investigator findings" in " ".join(body.get("unresolved") or [])
    verify_calls = [
        c for c in boom.calls
        if "verifier" in (c.system or "").lower()
        or "classify" in (c.system or "").lower()
    ]
    assert verify_calls == []
    assert result.ok is False
    assert result.telemetry["completed"] is False


@pytest.mark.asyncio
async def test_timeout_broadcasts_timeout_not_cancelled(tmp_path: Path, monkeypatch):
    class Slow(ScriptedProvider):
        async def chat_stream(self, req):
            await asyncio.sleep(30)
            yield base.TextChunk(text="late")
            yield base.DoneChunk(stop_reason="end_turn")

    monkeypatch.setattr(
        "switchbay.modestore.resolve_for_difficulty", lambda *a, **k: (None, None),
    )
    monkeypatch.setattr(policy, "HARD_WORKER_TIMEOUT_SEC", 5.5)
    # Floor in clamp() is 5s — keep the test just above it.
    plan = orchestration.plan_single("hi", orchestration_id="run-slow", preference=0.5)
    plan.bounds = orchestration.OrchestrationBounds(
        worker_timeout_sec=5.5, wall_clock_sec=8.0,
    )
    # Bypass clamp's 5s-min against a 900 cap by shrinking after ensure_valid.
    orig_clamp = orchestration.OrchestrationBounds.clamp

    def tiny_clamp(self):
        b = orig_clamp(self)
        b.worker_timeout_sec = 0.05
        b.wall_clock_sec = 2.0
        return b

    monkeypatch.setattr(orchestration.OrchestrationBounds, "clamp", tiny_clamp)
    ws = FakeWS()
    result = await orchestration.execute(
        plan, app=_app(ws), workspace=tmp_path, thread_id="th",
        parent_run_id="run-slow", default_provider=Slow(["x"]), default_model="fake",
    )
    assert result.ok is False
    rec = result.results[0]
    assert "timed out" in (rec.get("error") or "")
    errors = [m for m in ws.messages if m.get("type") == "RUN_ERROR"]
    # Timeout is a timeout, not a user cancel.
    assert any(m.get("code") == "timeout" for m in errors)
    assert not any(
        m.get("code") == "cancelled" and "node cancelled" in str(m.get("message") or "")
        for m in errors
    )


def test_parse_objective_met_and_strip():
    yes, gap = orchestration.parse_objective_met(
        "Here is the brief.\nOBJECTIVE_MET: yes\n",
    )
    assert yes is True
    assert gap == ""
    no, gap = orchestration.parse_objective_met(
        "Need 10-Ks.\nOBJECTIVE_MET: no — missing NVDA 10-K\n",
    )
    assert no is False
    assert "NVDA" in gap
    missing, _ = orchestration.parse_objective_met("just an answer")
    assert missing is None
    stripped = orchestration.strip_objective_met(
        "Answer.\nOBJECTIVE_MET: yes\n",
    )
    assert "OBJECTIVE_MET" not in stripped
    assert "Answer." in stripped


def test_parent_wall_clock_defaults_unlimited():
    b = orchestration.OrchestrationBounds().clamp()
    assert b.wall_clock_sec == 0.0
    assert b.worker_timeout_sec == policy.HARD_WORKER_TIMEOUT_SEC


def test_list_interrupted_keeps_waiting_limits_past_a_day(tmp_path: Path):
    plan = orchestration.plan_single("overnight", orchestration_id="run-wait")
    orchestration.persist_plan(tmp_path, plan)
    old = time.time() - 3 * 86400
    orchestration.persist_checkpoint(
        tmp_path, "run-wait",
        phase="waiting_limits", completed=set(), failed=set(),
        expansions=0, results={}, elapsed_s=10.0, thread_id="th",
        extra={"objective": "overnight", "resume_at": old + 10 * 86400},
    )
    status_path = orchestration.artifact_dir(tmp_path, "run-wait") / "status.json"
    data = json.loads(status_path.read_text(encoding="utf-8"))
    data["updated_at"] = old
    status_path.write_text(json.dumps(data), encoding="utf-8")
    items = orchestration.list_interrupted(tmp_path)
    ids = {i["orchestration_id"] for i in items}
    assert "run-wait" in ids
    row = next(i for i in items if i["orchestration_id"] == "run-wait")
    assert row["phase"] == "waiting_limits"


@pytest.mark.asyncio
async def test_objective_met_yes_does_not_spawn_another_wave(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "switchbay.modestore.resolve_for_difficulty", lambda *a, **k: (None, None),
    )

    class Once(ScriptedProvider):
        async def chat_stream(self, req):
            self.calls.append(req)
            sys = (req.system or "").lower()
            if "verifier" in sys or "classify each finding" in sys:
                yield base.TextChunk(text=(
                    '{"classifications":[{"finding_id":"f","verdict":"supported"}],'
                    '"confidence":0.9,"conflicts":0,"unsupported":0}'
                ))
            elif "synthesize" in sys:
                yield base.TextChunk(text="Done.\nOBJECTIVE_MET: yes")
            else:
                yield base.TextChunk(text=(
                    '{"findings":[{"claim":"from worker",'
                    '"evidence":[{"source":"wiki/x.md","kind":"wiki"}],'
                    '"confidence":0.8}]}'
                ))
            yield base.DoneChunk(stop_reason="end_turn", input_tokens=3, output_tokens=4)

    d = policy.PolicyDecision(
        strategy="investigate_verify_synthesize", n_investigators=1,
        include_verify=True, include_reduce=False, independence="high",
        allow_expand=True, ladder_bias="balanced", reason="bench",
        arm_id="ivs:1", preference=0.9,
    )
    plan = orchestration.plan_from_decision(
        "research T", d, [{"description": "slice A"}],
        orchestration_id="run-met",
    )
    result = await orchestration.execute(
        plan, app=_app(), workspace=tmp_path, thread_id="th",
        parent_run_id="run-met", default_provider=Once(), default_model="fake",
    )
    assert result.ok
    assert "OBJECTIVE_MET" not in (result.output or "")
    assert "Done." in (result.output or "")
    synths = [n for n in result.plan.nodes if n.kind == "synthesize"]
    assert len(synths) == 1
    assert result.telemetry.get("stop_reason") == "OBJECTIVE_MET: yes"


@pytest.mark.asyncio
async def test_objective_met_no_spawns_continue_wave(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "switchbay.modestore.resolve_for_difficulty", lambda *a, **k: (None, None),
    )

    class TwoWave(ScriptedProvider):
        def __init__(self) -> None:
            super().__init__()
            self.synths = 0

        async def chat_stream(self, req):
            self.calls.append(req)
            sys = (req.system or "").lower()
            if "verifier" in sys or "classify each finding" in sys:
                yield base.TextChunk(text=(
                    '{"classifications":[{"finding_id":"f","verdict":"insufficient"}],'
                    '"confidence":0.3,"conflicts":0,"unsupported":1,'
                    '"unresolved":["need filings"]}'
                ))
            elif "synthesize" in sys:
                self.synths += 1
                if self.synths == 1:
                    text = "Draft.\nOBJECTIVE_MET: no — missing 10-K excerpts"
                else:
                    text = "Final.\nOBJECTIVE_MET: yes"
                yield base.TextChunk(text=text)
            else:
                yield base.TextChunk(text=(
                    '{"findings":[{"claim":"from worker",'
                    '"evidence":[{"source":"wiki/x.md","kind":"wiki"}],'
                    '"confidence":0.5}]}'
                ))
            yield base.DoneChunk(stop_reason="end_turn", input_tokens=3, output_tokens=4)

    d = policy.PolicyDecision(
        strategy="investigate_verify_synthesize", n_investigators=1,
        include_verify=True, include_reduce=False, independence="high",
        allow_expand=True, ladder_bias="balanced", reason="bench",
        arm_id="ivs:1", preference=0.9,
        features={"consequence": 0.8, "preference": 0.9},
    )
    plan = orchestration.plan_from_decision(
        "research T", d, [{"description": "slice A"}],
        orchestration_id="run-gap",
    )
    prov = TwoWave()
    result = await orchestration.execute(
        plan, app=_app(), workspace=tmp_path, thread_id="th",
        parent_run_id="run-gap", default_provider=prov, default_model="fake",
    )
    assert result.ok
    assert prov.synths >= 2
    synths = [n for n in result.plan.nodes if n.kind == "synthesize"]
    assert len(synths) >= 2
    assert "Final." in (result.output or "")
    assert "OBJECTIVE_MET" not in (result.output or "")


@pytest.mark.asyncio
async def test_waiting_limits_autoresumes_when_channel_reopens(
    tmp_path: Path, monkeypatch,
):
    from switchbay.agents import orchestration_health as health
    monkeypatch.setattr(
        "switchbay.modestore.resolve_for_difficulty", lambda *a, **k: (None, None),
    )
    monkeypatch.setattr(orchestration, "WAIT_POLL_SEC", 0.02)
    t0 = time.time()

    def _avail(pid, *, now=None):
        return time.time() - t0 > 0.06

    monkeypatch.setattr(health, "is_available", _avail)
    monkeypatch.setattr(health, "earliest_resume_at", lambda **k: t0 + 0.05)
    monkeypatch.setattr(health, "cooling_records", lambda **k: [
        {"provider": "grok_build", "kind": "weekly_limit",
         "until": t0 + 0.05, "until_label": "soon"},
    ])
    ws = FakeWS()
    plan = orchestration.plan_single("hi", orchestration_id="run-wait2")
    result = await orchestration.execute(
        plan, app=_app(ws), workspace=tmp_path, thread_id="th",
        parent_run_id="run-wait2",
        default_provider=ScriptedProvider(["hello"]), default_model="fake",
    )
    assert result.ok
    notices = [
        str(m.get("message") or m.get("text") or "")
        for m in ws.messages if m.get("type") in ("notice", "NOTICE", "custom")
        or m.get("kind") == "chat"
    ]
    blob = " ".join(notices).lower() + " ".join(
        json.dumps(m) for m in ws.messages
    ).lower()
    assert "paused" in blob or "waiting" in blob or "resume" in blob
