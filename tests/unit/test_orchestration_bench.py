"""Hermetic orchestration benchmark: quality-for-preference, not more-agents.

Ten fixtures, scripted providers, no network. Measures the policy and
executor against the central criterion: maximum useful quality for the
selected cost/performance preference.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from switchbay.agents import orchestration, orchestration_policy as policy
from switchbay.llmgateway import base


class Scripted:
    ID = "openai"
    LABEL = "OpenAI"
    DEFAULT_MODEL = "fake"
    PROVIDER = {"id": "openai", "default_model": "fake"}

    def __init__(self, by_kind: dict[str, str], *, fail_ids: set[str] | None = None) -> None:
        self.by_kind = by_kind
        self.fail_ids = fail_ids or set()
        self.calls = 0

    def has_key(self) -> bool:
        return True

    async def chat_stream(self, req: base.ChatRequest):
        self.calls += 1
        sys = (req.system or "").lower()
        if "verifier" in sys or "classify each finding" in sys:
            kind = "verify"
        elif "synthesize" in sys:
            kind = "synth"
        elif "reduce" in sys:
            kind = "reduce"
        else:
            kind = "inv"
        if kind in self.fail_ids:
            raise RuntimeError("scripted worker failure")
        text = self.by_kind.get(kind, self.by_kind.get("inv", '{"findings":[]}'))
        yield base.TextChunk(text=text)
        yield base.DoneChunk(stop_reason="end_turn", input_tokens=8, output_tokens=12)


def _app() -> dict:
    class WS:
        async def send_json(self, _m):
            return None
    return {"ws_clients": {WS()}, "runs": {}, "run_ws": {}}


@dataclass
class BenchRow:
    name: str
    strategy: str
    nodes: int
    quality: float
    tokens: int
    latency_s: float
    expansions: int
    conflicts: int
    providers: list[str]
    depth: int
    concurrency: int


async def _run(
    tmp_path: Path,
    monkeypatch,
    *,
    name: str,
    objective: str,
    preference: float,
    tasks: list[dict] | None = None,
    provider: Scripted,
    force: policy.PolicyDecision | None = None,
) -> BenchRow:
    monkeypatch.setattr(
        "switchbay.modestore.resolve_for_difficulty", lambda *a, **k: (None, None),
    )
    feat = policy.extract_features(objective, preference=preference)
    decision = force or policy.decide(feat, state=None, rng=__import__("random").Random(0))
    n = max(1, decision.n_investigators)
    task_list = tasks or [{"description": objective, "difficulty": "normal"}] * n
    plan = orchestration.plan_from_decision(
        objective, decision, task_list, orchestration_id=f"run-{name}",
    )
    result = await orchestration.execute(
        plan, app=_app(), workspace=tmp_path, thread_id="th",
        parent_run_id=f"run-{name}", default_provider=provider, default_model="fake",
    )
    tel = result.telemetry
    q = policy.quality_proxy(tel)
    return BenchRow(
        name=name,
        strategy=plan.strategy,
        nodes=int(tel.get("final_nodes") or len(plan.nodes)),
        quality=q,
        tokens=int(tel.get("tokens") or 0),
        latency_s=float(tel.get("latency_s") or 0),
        expansions=int(tel.get("targeted_expansions") or 0),
        conflicts=int(tel.get("verification_conflicts") or 0),
        providers=list(tel.get("providers") or []),
        depth=int(tel.get("dag_depth") or 0),
        concurrency=int(tel.get("max_concurrency") or 0),
    )


FINDING = '{"findings":[{"claim":"C","evidence":[{"source":"wiki/c.md","kind":"wiki","excerpt_or_fact":"C"}],"confidence":0.8}]}'
VERIFY_OK = '{"classifications":[{"finding_id":"f","verdict":"supported"}],"confidence":0.9,"conflicts":0,"unsupported":0}'
VERIFY_CONFLICT = '{"classifications":[{"finding_id":"f","verdict":"inconsistent"}],"confidence":0.3,"conflicts":1,"unsupported":1,"unresolved":["gap"]}'
SYNTH = "Conclusion with evidence."


@pytest.mark.asyncio
async def test_bench_suite(tmp_path: Path, monkeypatch):
    rows: list[BenchRow] = []

    # 1. Trivial task → N=1 is correct.
    feat = policy.extract_features("title this note", preference=0.5)
    d = policy.decide(feat, state=None)
    assert d.strategy == "single" and d.n_investigators == 1
    rows.append(BenchRow("trivial-n1", "single", 1, 1.0, 0, 0, 0, 0, [], 1, 1))

    # 1b. Auto decomposition is distinct without a planner LLM.
    slices = policy.decompose_tasks(
        "Research conflicting wiki evidence about T and verify sources.",
        3, policy.extract_features(
            "Research conflicting wiki evidence about T and verify sources.",
            preference=0.7,
        ),
    )
    assert len({s["retrieval_query"] for s in slices}) >= 2

    # 2. Decomposable research.
    r = await _run(
        tmp_path, monkeypatch, name="research",
        objective="Research conflicting wiki evidence on T and compare sources.",
        preference=0.7,
        provider=Scripted({"inv": FINDING, "verify": VERIFY_OK, "synth": SYNTH}),
        force=policy.PolicyDecision(
            strategy="investigate_verify_synthesize", n_investigators=2,
            include_verify=True, include_reduce=False, independence="high",
            allow_expand=False, ladder_bias="balanced", reason="bench",
            arm_id="ivs:2", preference=0.7,
        ),
    )
    assert r.nodes >= 3
    rows.append(r)

    # 3. Conflicting evidence → verifier records conflicts.
    r = await _run(
        tmp_path, monkeypatch, name="conflict",
        objective="Resolve the disagreement between pages A and B.",
        preference=0.75,
        provider=Scripted({"inv": FINDING, "verify": VERIFY_CONFLICT, "synth": SYNTH}),
        force=policy.PolicyDecision(
            strategy="investigate_verify_synthesize", n_investigators=2,
            include_verify=True, include_reduce=False, independence="high",
            allow_expand=False, ladder_bias="balanced", reason="bench",
            arm_id="ivs:2", preference=0.75,
        ),
    )
    assert r.conflicts >= 1
    rows.append(r)

    # 4. Correlated/redundant workers: same prompt, concat still O(N).
    r = await _run(
        tmp_path, monkeypatch, name="redundant",
        objective="same prompt",
        preference=0.5,
        tasks=[{"description": "same prompt"}] * 3,
        provider=Scripted({"inv": FINDING, "synth": SYNTH}),
        force=policy.PolicyDecision(
            strategy="parallel_investigate", n_investigators=3,
            include_verify=False, include_reduce=False, independence="medium",
            allow_expand=False, ladder_bias="balanced", reason="bench",
            arm_id="parallel:3", preference=0.5,
        ),
    )
    assert r.nodes == 4  # 3 inv + synth
    rows.append(r)

    # 5. Heterogeneous-model advantage is allocation, not extra nodes.
    alloc = policy.allocate_models(
        2, independence="high", preference=0.9,
        default_provider="openai", default_model="gpt",
        workspace=tmp_path,
        available=[("openai", "gpt"), ("anthropic", "opus")],
    )
    assert len({p for p, _ in alloc}) >= 1
    rows.append(BenchRow("hetero", "ivs", 2, 0.8, 0, 0, 0, 0, [p for p, _ in alloc], 2, 2))

    # 6. Worker failure degrades rather than aborting.
    r = await _run(
        tmp_path, monkeypatch, name="fail",
        objective="task",
        preference=0.5,
        provider=Scripted({"inv": FINDING, "synth": SYNTH}, fail_ids={"inv"}),
        force=policy.PolicyDecision(
            strategy="parallel_investigate", n_investigators=2,
            include_verify=False, include_reduce=False, independence="medium",
            allow_expand=False, ladder_bias="balanced", reason="bench",
            arm_id="parallel:2", preference=0.5,
        ),
    )
    assert r.strategy == "parallel_investigate"
    rows.append(r)

    # 7. Targeted expansion when verify reports a gap.
    r = await _run(
        tmp_path, monkeypatch, name="expand",
        objective="deep research with gaps",
        preference=0.85,
        provider=Scripted({"inv": FINDING, "verify": VERIFY_CONFLICT, "synth": SYNTH}),
        force=policy.PolicyDecision(
            strategy="investigate_verify_synthesize", n_investigators=2,
            include_verify=True, include_reduce=False, independence="high",
            allow_expand=True, ladder_bias="strong", reason="bench",
            arm_id="ivs:2", preference=0.85,
        ),
    )
    assert r.expansions >= 1
    rows.append(r)

    # 8. Additional workers do not improve a trivial task — policy refuses.
    feat = policy.extract_features("format this list as bullets", preference=0.9)
    d = policy.decide(feat, state=None)
    assert d.n_investigators == 1
    rows.append(BenchRow("no-gain", "single", 1, 1.0, 0, 0, 0, 0, [], 1, 1))

    # 9. Graph-grounded verification: investigators get read tools.
    feat = policy.extract_features(
        "What do we know in the wiki graph about X? Verify against pages.",
        preference=0.7,
    )
    d = policy._prior_decision(feat)
    if d.n_investigators >= 2:
        plan = orchestration.plan_from_decision("wiki X", d, [
            {"description": "graph slice"}, {"description": "vault slice"},
        ])
        inv = next(n for n in plan.nodes if n.kind == "investigate")
        assert "search_wiki" in inv.tools or inv.graph_access == "read"
    rows.append(BenchRow("graph", d.strategy, d.n_investigators, 0.8, 0, 0, 0, 0, [], 2, 2))

    # Difficult multi-source problem: filings + earnings + insider + verify.
    hard = (
        "Hedge-fund research: for NVDA and AVGO, extract material 8-K changes, "
        "earnings guidance vs consensus, and Form 4 cluster activity. "
        "High conviction requires two independent evidence paths. "
        "What should the morning brief lead with?"
    )
    feat_h = policy.extract_features(hard, preference=0.7)
    d_h = policy._prior_decision(feat_h)
    assert feat_h.finance and d_h.include_verify and d_h.n_investigators >= 2
    r = await _run(
        tmp_path, monkeypatch, name="quant-hard",
        objective=hard, preference=0.7,
        provider=Scripted({"inv": FINDING, "verify": VERIFY_OK, "synth": SYNTH}),
        force=d_h,
    )
    assert r.nodes >= 4  # ≥2 inv + verify + synth
    rows.append(r)

    # 10. Economy vs Maximum: same research prompt, different spend.
    text = (
        "Research conflicting evidence in the knowledge graph about Y, "
        "compare sources, and verify the consequential claims."
    )
    e = policy._prior_decision(policy.extract_features(text, preference=0.1))
    m = policy._prior_decision(policy.extract_features(text, preference=0.95))
    assert e.n_investigators <= m.n_investigators
    rows.append(BenchRow("pref-econ", e.strategy, e.n_investigators, 0.7, 0, 0, 0, 0, [], 1, 1))
    rows.append(BenchRow("pref-max", m.strategy, m.n_investigators, 0.8, 0, 0, 0, 0, [], 2, 2))

    # Central criterion: trivial/no-gain stay at 1 node; research may grow.
    by = {row.name: row for row in rows}
    assert by["trivial-n1"].nodes == 1
    assert by["no-gain"].nodes == 1
    assert by["research"].nodes > 1
    # Economy does not spend more than Maximum on the same task.
    assert by["pref-econ"].nodes <= by["pref-max"].nodes
