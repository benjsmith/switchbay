"""Independent second-pass acceptance probes; no provider/account calls."""
import asyncio
import base64
import json
from email import message_from_bytes

import pytest

from switchbay import admin_policy, comms_review, streams
from switchbay.agents import orchestration as orch, desk_admission as seats


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("SWITCHBAY_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("SWITCHBAY_PROFILE", "enterprise")
    path = tmp_path / "admin.json"
    path.write_text(json.dumps({"profile": "enterprise", "features": {"comms_streams": True}}))
    monkeypatch.setenv("SWITCHBAY_ADMIN_POLICY", str(path))
    monkeypatch.delenv("SWITCHBAY_INSTALL_ROOT", raising=False)
    admin_policy.reset_cache()
    seats.reset_for_tests()
    yield path
    admin_policy.reset_cache()
    seats.reset_for_tests()


def test_custom_headers_extend_mandatory_secret_detection(isolated):
    isolated.write_text(json.dumps({"profile": "enterprise", "comms": {"classification_headers": ["X-Tenant-Class"], "secret_names": ["Restricted-Tenant"]}}))
    admin_policy.reset_cache()
    result = comms_review.classify_metadata(headers={"Sensitivity": "Secret", "X-Tenant-Class": "normal"})
    assert result["verdict"] == "secret", result


def test_gmail_system_labels_do_not_block_normal_classification():
    result = comms_review.classify_metadata(headers={"Sensitivity": "normal"}, label_ids=["INBOX", "UNREAD"])
    assert result["verdict"] == "clear", result


def test_tenant_secret_id_embedded_in_msip_header(isolated):
    label_id = "a3a2f242-b872-42f3-89a6-ffffeeeedddd"
    isolated.write_text(json.dumps({"profile": "enterprise", "comms": {"tenant_label_ids": [label_id]}}))
    admin_policy.reset_cache()
    result = comms_review.classify_metadata(headers={"MSIP_Labels": f"MSIP_Label_{label_id}_Enabled=True; MSIP_Label_{label_id}_SiteId=tenant"})
    assert result["verdict"] == "secret", result


def test_duplicate_secret_header_cannot_be_hidden_by_normal_header():
    msg = message_from_bytes(b"Sensitivity: normal\r\nSensitivity: Secret\r\nSubject: Fixture\r\n\r\n")
    headers = streams._header_map(msg)
    result = comms_review.classify_metadata(headers=headers)
    assert result["verdict"] == "secret", result


def test_thousand_curate_waves_keep_unique_ids_after_compaction():
    plan = orch.OrchestrationPlan(orchestration_id="continuous-fixture", strategy="ce_curate", objective="Continuous fixture", nodes=[])
    completed = set()
    for i in range(1005):
        new = orch._add_curate_package_wave(plan)
        assert new, f"Wave {i} stopped prematurely"
        for node in new:
            assert node.node_id not in completed, f"Completed node ID reused after compaction at wave {i}: {node.node_id}"
            completed.add(node.node_id)
        orch.compact_plan_nodes(plan, completed, set(), set())
    assert len(completed) == 1005
    assert len(plan.nodes) < 40


def test_completed_single_use_worker_leaves_actual_parent_graph():
    old = orch.PlanNode(node_id="retired", kind="investigate", objective="Completed source work")
    current = orch.PlanNode(node_id="current", kind="investigate", objective="Current source work")
    plan = orch.OrchestrationPlan(orchestration_id="roster-fixture", strategy="parallel_investigate", objective="Fixture", nodes=[old, current])
    rows = orch._plan_nodes_view(plan, {"retired"}, set(), {"current"})
    assert [r["node_id"] for r in rows] == ["current"], rows


@pytest.mark.asyncio
async def test_increasing_live_cap_wakes_waiting_worker():
    gate = seats.DeskGate("live-change-fixture", cap=4)
    for name in ("chief", "specialist", "verifier", "synthesizer"):
        await gate.acquire(name)
    waiter = asyncio.create_task(gate.acquire("queued-specialist"))
    await asyncio.sleep(0)
    assert not waiter.done()
    gate.set_cap(5)
    await asyncio.wait_for(waiter, timeout=0.25)
    assert gate.live() == 5


@pytest.mark.asyncio
async def test_teams_metadata_queries_use_supported_parameters_only(tmp_path, monkeypatch):
    calls = []
    acct = {"id": "graph-fixture", "provider": "msgraph", "label": "Graph fixture", "workspaces": [str(tmp_path)]}
    monkeypatch.setattr(streams, "get_account", lambda *a: acct)
    monkeypatch.setattr(streams, "update_account", lambda *a, **k: acct)
    async def api(sess, account, url, **params):
        calls.append((url, params))
        if url.endswith("/joinedTeams"):
            return {"value": [{"id": "team1", "displayName": "Fixture team"}]}
        if url.endswith("/channels"):
            return {"value": [{"id": "channel1", "displayName": "Fixture channel"}]}
        return {"value": []}
    monkeypatch.setattr(streams, "_api_get", api)
    await streams.poll_account(acct)
    team_calls = [p for u, p in calls if u.endswith("/joinedTeams")]
    assert team_calls, calls
    assert all(not p for p in team_calls), "joinedTeams does not support OData query parameters"
    channel_calls = [p for u, p in calls if u.endswith("/channels")]
    assert channel_calls, calls
    assert all(set(p) <= {"$filter", "$select"} for p in channel_calls), channel_calls
    assert not any(("/chats/" in u or "/channels/" in u) and u.endswith("/messages") for u, p in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["gmail", "msgraph"])
@pytest.mark.parametrize("fresh_headers", [{}, {"Sensitivity": "Tenant-Unknown"}, {"Sensitivity": "Secret"}, {"Sensitivity": "normal"}])
async def test_approved_email_unknown_fresh_classification_never_fetches_body(tmp_path, monkeypatch, provider, fresh_headers):
    acct = {"id": f"{provider}-fresh", "provider": provider, "label": "Fixture", "workspaces": [str(tmp_path)]}
    monkeypatch.setattr(streams, "get_account", lambda *a: acct)
    record = {"provider": provider, "account_id": acct["id"], "stable_id": "thread-fresh", "subject": "Fixture", "headers": {"Sensitivity": "normal"}, "labels": [], "fetch_ref": {"id": "message1"}, "thread_id": "thread-fresh"}
    item = comms_review.upsert_discovery(record)
    assert comms_review.approve(item["key"], str(tmp_path), allowed=[str(tmp_path)])["ok"]
    body_calls = []
    metadata_calls = []
    async def api(sess, account, url, **params):
        if params.get("format") == "full" or "body" in str(params.get("$select", "")).split(","):
            body_calls.append((url, params))
            return {"id": "message1", "payload": {"mimeType": "text/plain", "body": {"data": base64.urlsafe_b64encode(b"approved fixture body").decode()}}, "body": {"content": "approved fixture body"}}
        metadata_calls.append((url, params))
        hdrs = [{"name": k, "value": v} for k, v in fresh_headers.items()]
        return {"id": "message1", "threadId": "thread-fresh", "payload": {"headers": hdrs}, "internetMessageHeaders": hdrs}
    monkeypatch.setattr(streams, "_api_get", api)
    result = await streams.fetch_approved_thread(acct, item["key"], str(tmp_path))
    assert metadata_calls, ("Approved thread must reach fresh metadata check", result)
    if fresh_headers.get("Sensitivity") == "normal":
        assert body_calls, "Approved, freshly clear email must be retrieved"
        assert result.get("ok") and result.get("events"), result
        assert result["events"][0]["text"] == "approved fixture body"
        assert result["events"][0]["approved_workspace"] == str(tmp_path)
    else:
        assert not body_calls, "A cached normal label must not override protected fresh classification"
        assert not result.get("events")


@pytest.mark.asyncio
async def test_approved_imap_checks_fresh_headers_before_requesting_text(tmp_path, monkeypatch):
    acct = {"id": "imap-fresh", "provider": "imap", "label": "Fixture", "host": "imap.example.invalid", "username": "fixture@example.invalid", "workspaces": [str(tmp_path)]}
    monkeypatch.setattr(streams, "get_account", lambda *a: acct)
    stable = comms_review.imap_thread_stable_id(message_id="<fixture@example.invalid>", references="", in_reply_to="", uidvalidity="123")
    item = comms_review.upsert_discovery({"provider": "imap", "account_id": acct["id"], "stable_id": stable, "subject": "Fixture", "headers": {"Sensitivity": "normal"}, "fetch_ref": {"uid": "1", "uidvalidity": "123"}, "uidvalidity": "123"})
    assert comms_review.approve(item["key"], str(tmp_path), allowed=[str(tmp_path)])["ok"]
    fetches = []
    class Imap:
        def __init__(self, *a, **k): pass
        def login(self, *a): pass
        def select(self, *a, **k): return "OK", [b"1"]
        def response(self, name): return "UIDVALIDITY", [b"123"]
        def uid(self, verb, *args):
            assert verb == "FETCH"
            fetches.append(str(args[-1]))
            return "OK", [(b"1 (BODY[HEADER] {140}", b"Sensitivity: Secret\r\nMessage-ID: <fixture@example.invalid>\r\n\r\n"), (b"1 BODY[TEXT] {10}", b"secret body")]
        def logout(self): pass
    monkeypatch.setattr(streams.imaplib, "IMAP4_SSL", Imap)
    monkeypatch.setattr(streams.secretstore, "get", lambda *a: "fixture-password")
    result = await streams.fetch_approved_thread(acct, item["key"], str(tmp_path))
    assert fetches
    assert all("TEXT" not in f for f in fetches), "Fresh Secret reply body was requested together with headers"
    assert not result.get("events")

@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['revoke', 'remove_allowlist'])
async def test_inflight_comms_authorization_change_prevents_body_parse(tmp_path, monkeypatch, change):
    import base64
    acct = {'id': 'race-fixture', 'provider': 'gmail', 'workspaces': [str(tmp_path)]}
    current = dict(acct)
    monkeypatch.setattr(streams, 'get_account', lambda *a: current)
    item = comms_review.upsert_discovery({'provider': 'gmail', 'account_id': acct['id'], 'stable_id': 'race-thread', 'thread_id': 'race-thread', 'subject': 'Fixture', 'headers': {'Sensitivity': 'normal'}, 'fetch_ref': {'id': 'race-message'}})
    assert comms_review.approve(item['key'], str(tmp_path), allowed=[str(tmp_path)])['ok']
    parsed = []
    monkeypatch.setattr(streams, '_gmail_plain', lambda *a: parsed.append(True) or 'must not parse')
    async def api(sess, account, url, **params):
        if params.get('format') == 'metadata':
            return {'id': 'race-message', 'threadId': 'race-thread', 'payload': {'headers': [{'name': 'Sensitivity', 'value': 'normal'}]}}
        assert params.get('format') == 'full'
        if change == 'revoke':
            comms_review.revoke(item['key'])
        else:
            current['workspaces'] = []
        await asyncio.sleep(0)
        return {'id': 'race-message', 'threadId': 'race-thread', 'payload': {'mimeType': 'text/plain', 'body': {'data': base64.urlsafe_b64encode(b'fixture body').decode()}}}
    monkeypatch.setattr(streams, '_api_get', api)
    result = await streams.fetch_approved_thread(acct, item['key'], str(tmp_path))
    assert not parsed, f'{change} during fetch must prevent parsing'
    assert not result.get('events'), result

@pytest.mark.asyncio
async def test_approval_backfills_all_discovered_messages_in_long_thread(tmp_path, monkeypatch):
    import base64
    acct = {'id': 'long-fixture', 'provider': 'gmail', 'workspaces': [str(tmp_path)]}
    monkeypatch.setattr(streams, 'get_account', lambda *a: acct)
    for i in range(105):
        item = comms_review.upsert_discovery({'provider': 'gmail', 'account_id': acct['id'], 'stable_id': 'long-thread', 'thread_id': 'long-thread', 'subject': 'Fixture', 'headers': {'Sensitivity': 'normal'}, 'fetch_ref': {'id': f'message-{i}'}})
    assert comms_review.approve(item['key'], str(tmp_path), allowed=[str(tmp_path)])['ok']
    body_ids = []
    async def api(sess, account, url, **params):
        mid = url.rsplit('/', 1)[-1]
        if params.get('format') == 'metadata':
            return {'id': mid, 'threadId': 'long-thread', 'payload': {'headers': [{'name': 'Sensitivity', 'value': 'normal'}]}}
        assert params.get('format') == 'full'
        body_ids.append(mid)
        return {'id': mid, 'threadId': 'long-thread', 'payload': {'mimeType': 'text/plain', 'body': {'data': base64.urlsafe_b64encode(b'fixture body').decode()}}}
    monkeypatch.setattr(streams, '_api_get', api)
    result = await streams.fetch_approved_thread(acct, item['key'], str(tmp_path))
    assert set(body_ids) == {f'message-{i}' for i in range(105)}, 'Discovery must not silently discard older references before approval'
    assert len(result.get('events', [])) == 105, result
    repeat = await streams.fetch_approved_thread(acct, item['key'], str(tmp_path))
    assert not repeat.get('events')
    assert len(body_ids) == 105, 'Receipted messages must not fetch content again'

@pytest.mark.asyncio
async def test_revocation_during_curator_preparation_prevents_model_handoff(tmp_path, monkeypatch):
    from switchbay import daemon, llmgateway
    acct = {'id': 'handoff-fixture', 'label': 'Fixture', 'provider': 'gmail', 'workspaces': [str(tmp_path)]}
    monkeypatch.setattr(streams, 'get_account', lambda *a: acct)
    item = comms_review.upsert_discovery({'provider': 'gmail', 'account_id': acct['id'], 'stable_id': 'handoff-thread', 'subject': 'Fixture', 'headers': {'Sensitivity': 'normal'}})
    assert comms_review.approve(item['key'], str(tmp_path), allowed=[str(tmp_path)])['ok']
    events = [{'id': 'handoff-message', 'comms_key': item['key'], 'approved_workspace': str(tmp_path), 'approved': True, 'text': 'fixture body', 'subject': 'Fixture', 'stream': 'fixture', 'ts': 1, 'sender': 'fixture@example.invalid', 'deep_link': ''}]
    calls = []
    class Provider:
        async def chat_stream(self, req):
            calls.append(req)
            yield llmgateway.DoneChunk(stop_reason='end_turn')
    monkeypatch.setattr(daemon, '_comms_curation_route', lambda *_a, **_k: ('fixture', 'fixture'))
    monkeypatch.setattr(llmgateway, 'get', lambda *a: Provider())
    monkeypatch.setattr(daemon, '_effective_model', lambda *a: 'fixture')
    monkeypatch.setattr(daemon, '_effort_for', lambda *a: None)
    monkeypatch.setattr(daemon, '_curator_profile', lambda *a: '')
    monkeypatch.setattr(streams, 'workspace_descriptor', lambda *a: 'fixture')
    def head(*a):
        comms_review.revoke(item['key'])
        return {'sha': 'fixture'}
    monkeypatch.setattr('switchbay.ce_host.wiki_head', head)
    result = await daemon._curate_into({'runs': {}}, acct, tmp_path, events)
    assert not calls, 'Revocation during preparation must stop model handoff'
    assert not result[0]
    assert 'revok' in str(result[1]).lower(), result

@pytest.mark.asyncio
async def test_comms_handoff_preserves_allowed_routed_model(tmp_path, monkeypatch):
    from switchbay import daemon, llmgateway
    acct = {'id': 'model-fixture', 'label': 'Fixture', 'provider': 'gmail', 'workspaces': [str(tmp_path)]}
    monkeypatch.setattr(streams, 'get_account', lambda *a: acct)
    item = comms_review.upsert_discovery({'provider': 'gmail', 'account_id': acct['id'], 'stable_id': 'model-thread', 'subject': 'Fixture', 'headers': {'Sensitivity': 'normal'}})
    assert comms_review.approve(item['key'], str(tmp_path), allowed=[str(tmp_path)])['ok']
    events = [{'id': 'model-message', 'comms_key': item['key'], 'approved_workspace': str(tmp_path), 'approved': True, 'text': 'fixture body', 'subject': 'Fixture', 'stream': 'fixture', 'ts': 1, 'sender': 'fixture@example.invalid', 'deep_link': ''}]
    models = []
    class Provider:
        async def chat_stream(self, req):
            models.append(req.model)
            yield llmgateway.DoneChunk(stop_reason='end_turn')
    monkeypatch.setattr(daemon, '_comms_curation_route', lambda *a: ('fixture', 'allowed-model'))
    monkeypatch.setattr(llmgateway, 'get', lambda *a: Provider())
    monkeypatch.setattr(daemon, '_effective_model', lambda *a: 'forbidden-default')
    monkeypatch.setattr(daemon, '_effort_for', lambda *a: None)
    monkeypatch.setattr(daemon, '_curator_profile', lambda *a: '')
    monkeypatch.setattr(streams, 'workspace_descriptor', lambda *a: 'fixture')
    monkeypatch.setattr('switchbay.ce_host.wiki_head', lambda *a: {'sha': 'unchanged'})
    await asyncio.wait_for(daemon._curate_into({'runs': {}}, acct, tmp_path, events), timeout=2)
    assert models == ['allowed-model'], 'Handoff must retain the model selected by workspace policy'

@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['allowlist', 'admin_disable'])
async def test_comms_rechecks_auth_after_waiting_for_worker_seat(tmp_path, monkeypatch, isolated, change):
    from switchbay import daemon, llmgateway, app_settings
    from switchbay.kernel.desk import DESK_CURATE
    acct = {'id': 'seat-fixture', 'label': 'Fixture', 'provider': 'gmail', 'workspaces': [str(tmp_path)]}
    current = dict(acct)
    monkeypatch.setattr(streams, 'get_account', lambda *a: current)
    item = comms_review.upsert_discovery({'provider': 'gmail', 'account_id': acct['id'], 'stable_id': 'seat-thread', 'subject': 'Fixture', 'headers': {'Sensitivity': 'normal'}})
    assert comms_review.approve(item['key'], str(tmp_path), allowed=[str(tmp_path)])['ok']
    events = [{'id': 'seat-message', 'comms_key': item['key'], 'approved_workspace': str(tmp_path), 'approved': True, 'text': 'fixture body', 'subject': 'Fixture', 'stream': 'fixture', 'ts': 1, 'sender': 'fixture@example.invalid', 'deep_link': ''}]
    calls = []
    class Provider:
        async def chat_stream(self, req):
            calls.append(req)
            yield llmgateway.DoneChunk(stop_reason='end_turn')
    monkeypatch.setattr(daemon, '_comms_curation_route', lambda *a: ('fixture', 'allowed-model'))
    monkeypatch.setattr(llmgateway, 'get', lambda *a: Provider())
    monkeypatch.setattr(daemon, '_effective_model', lambda *a: 'allowed-model')
    monkeypatch.setattr(daemon, '_effort_for', lambda *a: None)
    monkeypatch.setattr(daemon, '_curator_profile', lambda *a: '')
    monkeypatch.setattr(streams, 'workspace_descriptor', lambda *a: 'fixture')
    monkeypatch.setattr('switchbay.ce_host.wiki_head', lambda *a: {'sha': 'unchanged'})
    app_settings.set_desk_max_live_workers(4)
    gate = seats.gate_for(seats.desk_domain_id(tmp_path, DESK_CURATE), workspace=tmp_path)
    for i in range(4):
        await gate.acquire(f'fixture-{i}')
    task = asyncio.create_task(daemon._curate_into({'runs': {}}, acct, tmp_path, events))
    for _ in range(100):
        if gate.snapshot().get('refs', 0):
            break
        await asyncio.sleep(0.01)
    assert gate.snapshot().get('refs', 0), 'Curator must join the actual shared gate'
    assert not task.done(), 'Curator must wait at the live cap'
    if change == 'allowlist':
        current['workspaces'] = []
    else:
        isolated.write_text(json.dumps({'profile': 'enterprise', 'features': {'comms_streams': False}}))
        admin_policy.reset_cache()
    await gate.release_async('fixture-0')
    await asyncio.wait_for(task, timeout=2)
    for i in range(1, 4):
        await gate.release_async(f'fixture-{i}')
    assert not calls, f'{change} while queued must block model handoff'
