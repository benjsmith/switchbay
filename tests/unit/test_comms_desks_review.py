"""Independent regression probes; synthetic data only."""
import asyncio
import json

import pytest

from switchbay.agents import orchestration as orch, evidence
from switchbay.agents import orchestration_health as health
from switchbay.llmgateway import base


@pytest.mark.asyncio
@pytest.mark.parametrize("text", [
    '{"findings":[{"claim":"The API uses 429 for rate limit errors; retries use backoff.","confidence":0.9}]}',
    'Curated failure analysis. The source says "too many requests"; this is evidence, not a transport error.',
    'The protocol returns HTTP 429 when a client exceeds its request allowance. Retry after the documented delay.',
    '{"findings":[{"claim":"Documented error: rate limit exceeded. The source prescribes exponential backoff.","confidence":0.9}]}',
    'The source quotes the banner "You\'ve hit your weekly limit - resets Aug 26 at 11pm (Europe/Zurich)". This page documents how operators respond.',
])
async def test_worker_keeps_valid_failure_domain_research(tmp_path, monkeypatch, text):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("SWITCHBAY_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(health, "health_path", lambda: tmp_path / "health.json")
    monkeypatch.setattr(orch, "_persist_event", lambda *a, **k: None)

    class Provider:
        ID = "openai"
        DEFAULT_MODEL = "fixture"
        async def chat_stream(self, req):
            yield base.TextChunk(text=text)
            yield base.DoneChunk(stop_reason="end_turn", input_tokens=10, output_tokens=30)

    app = {"runs": {}, "run_ws": {}, "ws_clients": set()}
    node = orch.PlanNode(node_id="evidence-1", kind="investigate", objective="Document API failure handling")
    result = await orch._run_agent_node(
        node, provider=Provider(), model="fixture", workspace=tmp_path,
        parent_run_id="review-fixture", thread_id="fixture", app=app,
        blackboard=evidence.Blackboard("independent-review"), worker_index=None,
    )
    for task in app.get("_orch_retire", []):
        task.cancel()
    await asyncio.gather(*app.get("_orch_retire", []), return_exceptions=True)
    assert result["ok"], result
    assert result["output"] == text
    assert result["output_tokens"] == 30


@pytest.mark.asyncio
async def test_real_transport_failure_keeps_partial_output(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("SWITCHBAY_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(health, "health_path", lambda: tmp_path / "health.json")
    monkeypatch.setattr(orch, "_persist_event", lambda *a, **k: None)

    class Provider:
        ID = "openai"
        DEFAULT_MODEL = "fixture"
        async def chat_stream(self, req):
            yield base.TextChunk(text="Verified source-backed partial finding: retry delay is 30 seconds.")
            raise base.ProviderError("connection reset", code="server")

    app = {"runs": {}, "run_ws": {}, "ws_clients": set()}
    node = orch.PlanNode(node_id="partial-1", kind="investigate", objective="Document retry behavior")
    result = await orch._run_agent_node(
        node, provider=Provider(), model="fixture", workspace=tmp_path,
        parent_run_id="partial-fixture", thread_id="fixture", app=app,
        blackboard=evidence.Blackboard("independent-review"), worker_index=None,
    )
    for task in app.get("_orch_retire", []):
        task.cancel()
    await asyncio.gather(*app.get("_orch_retire", []), return_exceptions=True)
    assert not result["ok"]
    assert result["error"]
    assert "retry delay is 30 seconds" in result["output"], result


@pytest.mark.asyncio
async def test_ce_dispatch_reaches_worker_instead_of_constructor_failure(tmp_path, monkeypatch):
    from switchbay import ce_host, llmgateway
    from switchbay.agents import ce_workers
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("SWITCHBAY_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("CSWY_PROFILE", raising=False)
    monkeypatch.setattr(ce_host, "dispatch_worker", lambda *a, **k: {"ok": True, "role": "deepener", "prompt": "Inspect fixture source"})
    monkeypatch.setattr(ce_workers, "is_local_pid", lambda *a: False)
    monkeypatch.setattr(ce_workers.policy, "allocate_unused", lambda *a, **k: [("openai", "fixture")])

    class Provider:
        ID = "openai"
        DEFAULT_MODEL = "fixture"
        def has_key(self): return True
    monkeypatch.setattr(llmgateway, "get", lambda *a: Provider())

    async def worker(*args, **kwargs):
        assert isinstance(kwargs["blackboard"], evidence.Blackboard)
        return {"ok": True, "output": "Preserved useful worker finding", "provider": "openai", "model": "fixture"}
    monkeypatch.setattr(orch, "_run_agent_node", worker)
    result = await ce_workers.run_from_tool(
        tmp_path, {"role": "deepener"}, app={"runs": {}, "run_ws": {}, "ws_clients": set()},
        parent_run_id="nested-fixture", thread_id="fixture", curator_pid="openai", preference=0.5,
    )
    assert result["ok"] and result["spawned"], result
    assert "Preserved useful worker finding" in result["text"]


@pytest.mark.asyncio
async def test_gmail_discovery_requests_no_snippet_or_body(tmp_path, monkeypatch):
    from switchbay import streams, admin_policy
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("SWITCHBAY_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("SWITCHBAY_PROFILE", "open")
    admin_policy.reset_cache()
    calls = []
    acct = {"id": "gmail-review", "provider": "gmail", "label": "Fixture", "workspaces": [str(tmp_path)]}
    monkeypatch.setattr(streams, "get_account", lambda *a: acct)
    monkeypatch.setattr(streams, "update_account", lambda *a, **k: acct)
    async def api(sess, account, url, **params):
        calls.append((url, params))
        if url.endswith("/messages"):
            return {"messages": [{"id": "m1", "threadId": "t1"}]}
        if url.endswith("/labels"):
            return {"labels": []}
        return {"id": "m1", "threadId": "t1", "internalDate": "2000000000000", "payload": {"headers": [{"name": "Subject", "value": "Fixture thread"}, {"name": "From", "value": "fixture@example.invalid"}]}}
    monkeypatch.setattr(streams, "_api_get", api)
    await streams.poll_account(acct)
    msg_calls = [params for url, params in calls if url.endswith("/messages/m1")]
    assert msg_calls, calls
    for params in msg_calls:
        assert params.get("format") == "metadata", calls
        assert params.get("fields"), "Metadata format still includes snippet unless fields projection excludes it"
        assert not any(x in params["fields"].lower() for x in ("snippet", "body", "raw")), params
    assert not streams.pending_events(acct["id"]), "Unapproved metadata must not enter curation transit"


@pytest.mark.asyncio
async def test_imap_discovery_never_fetches_text(tmp_path, monkeypatch):
    from switchbay import streams, admin_policy
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("SWITCHBAY_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("SWITCHBAY_PROFILE", "open")
    admin_policy.reset_cache()
    fetches = []
    acct = {"id": "imap-review", "provider": "imap", "label": "Fixture", "host": "imap.example.invalid", "username": "fixture@example.invalid", "workspaces": [str(tmp_path)]}
    class Imap:
        def __init__(self, *a, **k): pass
        def login(self, *a): pass
        def select(self, *a, **k): return "OK", [b"1"]
        def response(self, name): return "UIDVALIDITY", [b"12345"]
        def uid(self, verb, *args):
            if verb == "SEARCH": return "OK", [b"1"]
            if verb == "FETCH":
                fetches.append(str(args[-1]))
                return "OK", [(b"1 (BODY[HEADER] {140}", b"From: fixture@example.invalid\r\nSubject: Fixture thread\r\nMessage-ID: <fixture-root@example.invalid>\r\nSensitivity: normal\r\n\r\n")]
            raise AssertionError(verb)
        def logout(self): pass
    monkeypatch.setattr(streams.imaplib, "IMAP4_SSL", Imap)
    monkeypatch.setattr(streams.secretstore, "get", lambda *a: "fixture-password")
    monkeypatch.setattr(streams, "get_account", lambda *a: acct)
    monkeypatch.setattr(streams, "update_account", lambda *a, **k: acct)
    await streams.poll_account(acct)
    assert fetches
    assert all("TEXT" not in f and "BODY.PEEK[]" not in f and "RFC822" not in f for f in fetches), fetches
    assert not streams.pending_events(acct["id"]), "Unapproved source must not enter curation transit"


def test_retired_thousand_workers_do_not_remain_live_roster(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("SWITCHBAY_STATE_DIR", str(tmp_path / "state"))
    nodes = [orch.PlanNode(node_id=f"old-{i}", kind="investigate", objective="Completed fixture work") for i in range(1001)]
    current = orch.PlanNode(node_id="current", kind="investigate", objective="Current fixture work")
    completed = {n.node_id for n in nodes}
    plan = orch.OrchestrationPlan(orchestration_id="long-desk", strategy="parallel_investigate", objective="Continuous research", nodes=nodes + [current])
    results = {n.node_id: {"ok": True, "output": "Persisted finding"} for n in nodes}
    view = orch.standing_org_view(plan, completed=completed, failed=set(), results=results, running={"current"})
    assert any(n["node_id"] == "current" for n in view["nodes"])
    assert len(view["nodes"]) <= 8, "Historical workers still balloon standing desk graph"
    assert len(results) == 1001, "Roster cleanup must not erase durable results"
