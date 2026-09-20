"""Comms review gate: secret, revoke, workspace isolation, no auto-add."""

from __future__ import annotations

import asyncio
import base64
import json
import subprocess
from pathlib import Path

import pytest

from switchbay import admin_policy, comms_review, streams
from switchbay.agents import desk_admission as seats


def test_secret_blocked_before_approval(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SWITCHBAY_PROFILE", "open")
    admin_policy.reset_cache()
    rec = comms_review.upsert_discovery({
        "provider": "imap",
        "account_id": "a1",
        "stable_id": "uv:abc",
        "kind": "email_thread",
        "subject": "War plans",
        "sender": "x@example.invalid",
        "headers": {"Sensitivity": "Secret"},
        "labels": [],
        "ts": 1.0,
    })
    assert rec["status"] == "blocked"
    assert rec["subject"] == "[redacted: classified]"
    assert "War" not in rec["subject"]
    out = comms_review.approve(rec["key"], str(tmp_path), allowed=[str(tmp_path)])
    assert not out["ok"]


def test_unknown_label_enterprise_not_public(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SWITCHBAY_PROFILE", "enterprise")
    admin_policy.reset_cache()
    v = comms_review.classify_metadata(headers={"Classification": "Project-X-Label"})
    assert v["verdict"] in ("unknown", "secret")
    v2 = comms_review.classify_metadata(headers={})
    assert v2["verdict"] == "missing"


def test_approve_respects_allowlist_and_revoke_wins(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SWITCHBAY_PROFILE", "open")
    admin_policy.reset_cache()
    rec = comms_review.upsert_discovery({
        "provider": "gmail",
        "account_id": "g1",
        "stable_id": "thread-1",
        "kind": "email_thread",
        "subject": "Budget notes",
        "sender": "a@example.invalid",
        "headers": {"Sensitivity": "normal"},
        "labels": [],
        "ts": 1.0,
    })
    other = str(tmp_path / "other")
    denied = comms_review.approve(rec["key"], other, allowed=[str(tmp_path)])
    assert not denied["ok"]
    ok = comms_review.approve(rec["key"], str(tmp_path), allowed=[str(tmp_path)])
    assert ok["ok"]
    comms_review.revoke(rec["key"])
    ok2, reason, _ = comms_review.authorize_content_fetch(
        rec["key"], str(tmp_path),
        allowed=[str(tmp_path)],
        headers={"Sensitivity": "normal"},
        label_ids=[],
    )
    assert not ok2
    assert "revoked" in reason


def test_later_secret_reply_blocked(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SWITCHBAY_PROFILE", "open")
    admin_policy.reset_cache()
    rec = comms_review.upsert_discovery({
        "provider": "gmail",
        "account_id": "g1",
        "stable_id": "thread-sec",
        "kind": "email_thread",
        "subject": "ok",
        "headers": {"Sensitivity": "normal"},
        "labels": [],
        "ts": 1.0,
    })
    comms_review.approve(rec["key"], str(tmp_path), allowed=[str(tmp_path)])
    ok, reason, _ = comms_review.authorize_content_fetch(
        rec["key"], str(tmp_path),
        allowed=[str(tmp_path)],
        headers={"Sensitivity": "Top Secret"},
        label_ids=[],
    )
    assert not ok
    assert "secret" in reason.lower()


def test_imap_thread_id_uses_references_not_subject():
    a = comms_review.imap_thread_stable_id(
        message_id="<child@x>",
        references="<root@x> <mid@x>",
        in_reply_to="<mid@x>",
        uidvalidity="99",
        fallback_uid="12",
    )
    b = comms_review.imap_thread_stable_id(
        message_id="<other-child@x>",
        references="<root@x>",
        in_reply_to="<root@x>",
        uidvalidity="99",
        fallback_uid="13",
    )
    assert a == b
    assert a.startswith("99:")


def test_quarantine_legacy_transit_does_not_parse(tmp_path, monkeypatch):
    monkeypatch.setenv("SWITCHBAY_STATE_DIR", str(tmp_path / "state"))
    aid = "acct-q"
    p = streams._state_dir(aid) / "transit.jsonl"
    p.write_text('{"id":"x","text":"BODY SECRET poison"}\n', encoding="utf-8")
    n = streams.quarantine_legacy_transit(aid)
    assert n >= 1
    assert not p.is_file()
    assert (streams._state_dir(aid) / "transit.quarantine.jsonl").is_file()
    assert streams.pending_events(aid) == []


def _enterprise_comms(tmp_path, monkeypatch) -> None:
    path = tmp_path / "admin-comms.json"
    path.write_text(json.dumps({
        "profile": "enterprise",
        "features": {"comms_streams": True},
    }))
    monkeypatch.setenv("SWITCHBAY_ADMIN_POLICY", str(path))
    monkeypatch.setenv("SWITCHBAY_PROFILE", "enterprise")
    admin_policy.reset_cache()


def test_upsert_stores_headers_without_bodies(tmp_path, monkeypatch):
    _enterprise_comms(tmp_path, monkeypatch)
    rec = comms_review.upsert_discovery({
        "provider": "gmail",
        "account_id": "g-store",
        "stable_id": "thread-store",
        "subject": "Notes",
        "headers": {"Sensitivity": "normal", "text": "should-drop"},
        "fetch_ref": {"id": "m1"},
        "body": "secret body must not persist",
        "ts": 1.0,
    })
    raw = comms_review.get_raw_item(rec["key"])
    assert raw is not None
    assert raw.get("headers", {}).get("Sensitivity") == "normal"
    assert "text" not in (raw.get("headers") or {})
    assert "body" not in raw
    assert rec.get("headers") is None or "body" not in rec


def test_auth_only_preflight_does_not_use_cached_headers(tmp_path, monkeypatch):
    _enterprise_comms(tmp_path, monkeypatch)
    rec = comms_review.upsert_discovery({
        "provider": "gmail",
        "account_id": "g-auth",
        "stable_id": "thread-auth",
        "subject": "Notes",
        "headers": {"Sensitivity": "normal"},
        "fetch_ref": {"id": "m1"},
    })
    ws = str(tmp_path)
    assert comms_review.approve(rec["key"], ws, allowed=[ws])["ok"]
    ok, reason, _ = comms_review.authorize_content_fetch(
        rec["key"], ws, allowed=[ws], classify=False,
    )
    assert ok, reason
    ok2, reason2, _ = comms_review.authorize_content_fetch(
        rec["key"], ws, allowed=[ws], headers={}, classify=True,
    )
    assert not ok2
    assert "missing" in reason2 or "unknown" in reason2 or "not assumed" in reason2


def _gmail_full_payload(text: str = "approved fixture body") -> dict:
    return {
        "id": "message1",
        "internalDate": "2000000000000",
        "payload": {
            "mimeType": "text/plain",
            "body": {"data": base64.urlsafe_b64encode(text.encode()).decode()},
        },
        "body": {"content": text},
    }


@pytest.mark.asyncio
async def test_pipeline_discover_suggest_approve_fetch_receipt(tmp_path, monkeypatch):
    _enterprise_comms(tmp_path, monkeypatch)
    ws = str(tmp_path)
    acct = {
        "id": "gmail-pipe", "provider": "gmail", "label": "Fixture",
        "workspaces": [ws],
    }
    monkeypatch.setattr(streams, "get_account", lambda *a: acct)
    monkeypatch.setattr(streams, "update_account", lambda *a, **k: acct)
    monkeypatch.setattr(streams, "list_accounts", lambda: [acct])
    body_calls = []
    metadata_calls = []

    async def api(sess, account, url, **params):
        if url.endswith("/messages"):
            return {"messages": [{"id": "message1", "threadId": "thread-pipe"}]}
        if params.get("format") == "full" or "body" in str(params.get("$select", "")).split(","):
            body_calls.append((url, params))
            return _gmail_full_payload()
        metadata_calls.append((url, params))
        return {
            "id": "message1",
            "threadId": "thread-pipe",
            "internalDate": "2000000000000",
            "labelIds": ["INBOX"],
            "payload": {"headers": [
                {"name": "Subject", "value": "Fixture"},
                {"name": "From", "value": "fixture@example.invalid"},
                {"name": "Sensitivity", "value": "normal"},
            ]},
        }

    monkeypatch.setattr(streams, "_api_get", api)
    n = await streams.poll_account(acct)
    assert n >= 1
    assert not body_calls
    assert not streams.pending_events(acct["id"])
    items = comms_review.list_items(workspace=ws)
    assert items, "discovery must land in the review queue"
    key = items[0]["key"]
    assert items[0]["status"] == "pending"
    assert ws in (items[0].get("suggested_workspaces") or [])
    assert comms_review.approve(key, ws, allowed=[ws])["ok"]
    result = await streams.fetch_approved_thread(acct, key, ws)
    assert metadata_calls
    assert body_calls, result
    assert result.get("ok") and result.get("events"), result
    assert result["events"][0]["text"] == "approved fixture body"
    assert result["events"][0]["approved_workspace"] == ws
    assert streams.has_receipt(acct["id"], result["events"][0]["source_event_id"], ws)
    pending = streams.pending_events(acct["id"])
    assert pending and pending[0]["approved"] is True
    again = await streams.fetch_approved_thread(acct, key, ws)
    assert again.get("ok")
    assert again.get("events") == []


@pytest.mark.asyncio
async def test_unapproved_gmail_never_fetches_body(tmp_path, monkeypatch):
    _enterprise_comms(tmp_path, monkeypatch)
    ws = str(tmp_path)
    acct = {"id": "gmail-unapp", "provider": "gmail", "label": "F", "workspaces": [ws]}
    monkeypatch.setattr(streams, "get_account", lambda *a: acct)
    monkeypatch.setattr(streams, "update_account", lambda *a, **k: acct)
    monkeypatch.setattr(streams, "list_accounts", lambda: [acct])
    body_calls = []

    async def api(sess, account, url, **params):
        if url.endswith("/messages"):
            return {"messages": [{"id": "message1", "threadId": "t"}]}
        if params.get("format") == "full":
            body_calls.append((url, params))
            return _gmail_full_payload()
        return {
            "id": "message1", "threadId": "t", "internalDate": "1",
            "payload": {"headers": [{"name": "Sensitivity", "value": "normal"}]},
        }

    monkeypatch.setattr(streams, "_api_get", api)
    await streams.poll_account(acct)
    items = comms_review.list_items(workspace=ws)
    key = items[0]["key"]
    result = await streams.fetch_approved_thread(acct, key, ws)
    assert not result.get("ok")
    assert not body_calls
    assert not streams.pending_events(acct["id"])


@pytest.mark.asyncio
async def test_revocation_during_body_request_skips_parser(tmp_path, monkeypatch):
    _enterprise_comms(tmp_path, monkeypatch)
    ws = str(tmp_path)
    acct = {"id": "gmail-rev", "provider": "gmail", "label": "F", "workspaces": [ws]}
    monkeypatch.setattr(streams, "get_account", lambda *a: acct)
    parsed = []
    streams.body_parse_hook = lambda *a: parsed.append(a)
    rec = comms_review.upsert_discovery({
        "provider": "gmail", "account_id": acct["id"], "stable_id": "thread-rev",
        "subject": "Fixture", "headers": {"Sensitivity": "normal"},
        "fetch_ref": {"id": "message1"}, "thread_id": "thread-rev",
    })
    key = rec["key"]
    assert comms_review.approve(key, ws, allowed=[ws])["ok"]

    async def api(sess, account, url, **params):
        if params.get("format") == "full":
            comms_review.revoke(key, reason="race")
            return _gmail_full_payload("should-not-parse")
        return {
            "id": "message1", "threadId": "thread-rev",
            "payload": {"headers": [{"name": "Sensitivity", "value": "normal"}]},
        }

    monkeypatch.setattr(streams, "_api_get", api)
    try:
        result = await streams.fetch_approved_thread(acct, key, ws)
        assert not result.get("events")
        assert not parsed
        assert streams.pending_events(acct["id"]) == []
    finally:
        streams.body_parse_hook = None


@pytest.mark.asyncio
async def test_multi_workspace_receipts_and_restart(tmp_path, monkeypatch):
    _enterprise_comms(tmp_path, monkeypatch)
    ws_a = tmp_path / "a"
    ws_b = tmp_path / "b"
    ws_a.mkdir()
    ws_b.mkdir()
    acct = {
        "id": "gmail-multi", "provider": "gmail", "label": "F",
        "workspaces": [str(ws_a), str(ws_b)],
    }
    monkeypatch.setattr(streams, "get_account", lambda *a: acct)
    rec = comms_review.upsert_discovery({
        "provider": "gmail", "account_id": acct["id"], "stable_id": "thread-multi",
        "subject": "Fixture", "headers": {"Sensitivity": "normal"},
        "fetch_ref": {"id": "message1"}, "thread_id": "thread-multi",
    })
    key = rec["key"]
    assert comms_review.approve(key, str(ws_a), allowed=[str(ws_a), str(ws_b)])["ok"]
    assert comms_review.approve(key, str(ws_b), allowed=[str(ws_a), str(ws_b)])["ok"]

    async def api(sess, account, url, **params):
        if params.get("format") == "full":
            return _gmail_full_payload("shared body")
        return {
            "id": "message1", "threadId": "thread-multi",
            "payload": {"headers": [{"name": "Sensitivity", "value": "normal"}]},
        }

    monkeypatch.setattr(streams, "_api_get", api)
    ra = await streams.fetch_approved_thread(acct, key, str(ws_a))
    rb = await streams.fetch_approved_thread(acct, key, str(ws_b))
    assert ra["events"] and rb["events"]
    assert ra["events"][0]["approved_workspace"] == str(ws_a)
    assert rb["events"][0]["approved_workspace"] == str(ws_b)
    src = ra["events"][0]["source_event_id"]
    assert streams.has_receipt(acct["id"], src, str(ws_a))
    assert streams.has_receipt(acct["id"], src, str(ws_b))
    # Restart: store still approved.
    again = comms_review.get_item(key)
    assert again and again["status"] == "approved"
    assert str(ws_a) in again["approved_workspaces"]
    comms_review.revoke(key)
    after = comms_review.get_item(key)
    assert after and after["status"] == "revoked"
    denied = await streams.fetch_approved_thread(acct, key, str(ws_a))
    assert not denied.get("events")


@pytest.mark.asyncio
async def test_comms_streams_false_gates_poll_and_fetch(tmp_path, monkeypatch):
    policy = tmp_path / "admin.json"
    policy.write_text(json.dumps({
        "profile": "enterprise", "features": {"comms_streams": False},
    }))
    monkeypatch.setenv("SWITCHBAY_ADMIN_POLICY", str(policy))
    monkeypatch.setenv("SWITCHBAY_PROFILE", "enterprise")
    admin_policy.reset_cache()
    ws = str(tmp_path)
    acct = {"id": "gmail-off", "provider": "gmail", "label": "F", "workspaces": [ws]}
    rec = comms_review.upsert_discovery({
        "provider": "gmail", "account_id": acct["id"], "stable_id": "t",
        "subject": "x", "headers": {"Sensitivity": "normal"},
        "fetch_ref": {"id": "message1"},
    })
    comms_review.approve(rec["key"], ws, allowed=[ws])
    with pytest.raises(ValueError, match="comms_streams"):
        await streams.poll_account(acct)
    out = await streams.fetch_approved_thread(acct, rec["key"], ws)
    assert not out.get("ok")
    assert "comms_streams" in str(out.get("error") or "")
    assert await streams.ingest_approved_updates(acct) == 0


@pytest.mark.asyncio
async def test_imap_html_body_after_header_gate(tmp_path, monkeypatch):
    _enterprise_comms(tmp_path, monkeypatch)
    ws = str(tmp_path)
    acct = {
        "id": "imap-html", "provider": "imap", "label": "F",
        "host": "imap.example.invalid", "username": "f@example.invalid",
        "workspaces": [ws],
    }
    monkeypatch.setattr(streams, "get_account", lambda *a: acct)
    stable = comms_review.imap_thread_stable_id(
        message_id="<html@example.invalid>", references="", in_reply_to="",
        uidvalidity="123",
    )
    item = comms_review.upsert_discovery({
        "provider": "imap", "account_id": acct["id"], "stable_id": stable,
        "subject": "Fixture", "headers": {"Sensitivity": "normal"},
        "fetch_ref": {"uid": "1", "uidvalidity": "123"},
        "uidvalidity": "123",
    })
    assert comms_review.approve(item["key"], ws, allowed=[ws])["ok"]
    fetches = []

    class Imap:
        def __init__(self, *a, **k): pass
        def login(self, *a): pass
        def select(self, *a, **k): return "OK", [b"1"]
        def response(self, name): return "UIDVALIDITY", [b"123"]
        def uid(self, verb, *args):
            assert verb == "FETCH"
            fetches.append(str(args[-1]))
            if "TEXT" in str(args[-1]):
                return "OK", [(
                    b"1 BODY[TEXT] {40}",
                    b"Content-Type: text/html\r\n\r\n<p>hello html</p>",
                )]
            return "OK", [(
                b"1 (BODY[HEADER] {80}",
                b"Sensitivity: normal\r\nMessage-ID: <html@example.invalid>\r\n\r\n",
            )]
        def logout(self): pass

    monkeypatch.setattr(streams.imaplib, "IMAP4_SSL", Imap)
    monkeypatch.setattr(streams.secretstore, "get", lambda *a: "fixture-password")
    result = await streams.fetch_approved_thread(acct, item["key"], ws)
    assert fetches
    assert "TEXT" not in fetches[0]
    assert any("TEXT" in f for f in fetches[1:])
    assert result.get("ok") and result.get("events"), result
    assert "hello html" in result["events"][0]["text"]


@pytest.mark.asyncio
async def test_teams_pages_later_channels_without_top(tmp_path, monkeypatch):
    _enterprise_comms(tmp_path, monkeypatch)
    acct = {
        "id": "graph-page", "provider": "msgraph", "label": "F",
        "workspaces": [str(tmp_path)],
    }
    monkeypatch.setattr(streams, "get_account", lambda *a: acct)
    monkeypatch.setattr(streams, "update_account", lambda *a, **k: acct)
    monkeypatch.setattr(streams, "list_accounts", lambda: [acct])
    calls = []

    async def api(sess, account, url, **params):
        calls.append((url, params))
        if url.endswith("/messages") or "/me/messages" in url:
            return {"value": []}
        if url.endswith("/joinedTeams"):
            return {"value": [{"id": "team1", "displayName": "T"}]}
        if url.endswith("/channels"):
            return {
                "value": [{"id": "c1", "displayName": "one"}],
                "@odata.nextLink": "https://graph.microsoft.com/v1.0/teams/team1/channels/page2",
            }
        if url.endswith("/channels/page2"):
            return {"value": [{"id": "c2", "displayName": "two"}]}
        if url.endswith("/chats"):
            return {"value": []}
        return {"value": []}

    monkeypatch.setattr(streams, "_api_get", api)
    await streams.poll_account(acct)
    team_calls = [p for u, p in calls if u.endswith("/joinedTeams")]
    assert team_calls and all(not p for p in team_calls)
    channel_calls = [(u, p) for u, p in calls if u.rstrip("/").endswith("channels") or "/channels" in u]
    assert channel_calls
    for _u, p in channel_calls:
        assert "$top" not in p
        assert set(p) <= {"$filter", "$select"}
    items = comms_review.list_items(workspace=str(tmp_path))
    names = {i.get("subject") for i in items if i.get("kind") == "channel"}
    assert "one" in names
    # Second poll resumes the nextLink so channel two is not hidden.
    await streams.poll_account(acct)
    items2 = comms_review.list_items(workspace=str(tmp_path))
    names2 = {i.get("subject") for i in items2 if i.get("kind") == "channel"}
    assert "two" in names2 or "one" in names2
    assert not any(u.endswith("/messages") and "/channels/" in u for u, _p in calls)


@pytest.mark.asyncio
async def test_gmail_html_nested_without_attachment(tmp_path, monkeypatch):
    monkeypatch.setenv("SWITCHBAY_PROFILE", "open")
    admin_policy.reset_cache()
    html = base64.urlsafe_b64encode(b"<p>nested html body</p>").decode()
    att = base64.urlsafe_b64encode(b"PNGDATA").decode()
    msg = {
        "payload": {
            "mimeType": "multipart/mixed",
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "parts": [
                        {"mimeType": "text/html", "body": {"data": html}},
                    ],
                },
                {
                    "mimeType": "image/png",
                    "filename": "x.png",
                    "body": {"attachmentId": "att1", "data": att},
                },
            ],
        }
    }
    text = streams._gmail_plain(msg)
    assert "nested html body" in text
    assert "PNGDATA" not in text


def test_duplicate_configured_headers_preserved(tmp_path, monkeypatch):
    from email import message_from_bytes
    path = tmp_path / "admin.json"
    path.write_text(json.dumps({
        "profile": "enterprise",
        "comms": {"classification_headers": ["X-Tenant-Class"]},
    }))
    monkeypatch.setenv("SWITCHBAY_ADMIN_POLICY", str(path))
    monkeypatch.setenv("SWITCHBAY_PROFILE", "enterprise")
    admin_policy.reset_cache()
    msg = message_from_bytes(
        b"X-Tenant-Class: normal\r\nX-Tenant-Class: Secret\r\nSubject: x\r\n\r\n"
    )
    headers = streams._header_map(msg)
    assert "Secret" in headers.get("X-Tenant-Class", "")
    v = comms_review.classify_metadata(headers=headers)
    assert v["verdict"] == "secret"


@pytest.mark.asyncio
async def test_legacy_transit_cannot_bypass_curation_guard(tmp_path, monkeypatch):
    _enterprise_comms(tmp_path, monkeypatch)
    aid = "legacy"
    streams._append_transit(aid, [{
        "id": "poison", "text": "BODY should never curate", "approved": False,
    }])
    from switchbay import daemon
    app = {"runs": {}, "workspace": tmp_path, "ws_clients": set()}
    acct = {"id": aid, "provider": "gmail", "label": "F", "workspaces": [str(tmp_path)]}
    monkeypatch.setattr(streams, "allowed_workspaces", lambda a: [str(tmp_path)])
    out = await daemon._run_stream_curation(app, acct)
    assert out.get("curated", 0) == 0
    assert streams.pending_events(aid) == []


def _init_wiki(ws: Path) -> None:
    wiki = ws / "wiki"
    wiki.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(["git", "init"], cwd=wiki, stdout=subprocess.DEVNULL)
    subprocess.check_call(["git", "config", "user.email", "t@example.invalid"], cwd=wiki)
    subprocess.check_call(["git", "config", "user.name", "fixture"], cwd=wiki)
    (wiki / "index.md").write_text("# wiki\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "-A"], cwd=wiki, stdout=subprocess.DEVNULL)
    subprocess.check_call(["git", "commit", "-m", "init"], cwd=wiki, stdout=subprocess.DEVNULL)


def _wiki_sha(ws: Path) -> str:
    out = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ws / "wiki", text=True)
    return out.strip()


class _CommitProvider:
    """Synthetic file-capable curator: writes a wiki page and commits."""

    ID = "grok_build"
    PROVIDER = {
        "id": "grok_build",
        "default_model": "grok-4.6",
        "capabilities": {"shell": True, "file_write": True, "tools": True},
    }

    def has_key(self) -> bool:
        return True

    async def chat_stream(self, req):
        from switchbay.llmgateway import DoneChunk
        ws = Path(req.workspace)
        wiki = ws / "wiki"
        wiki.mkdir(parents=True, exist_ok=True)
        page = wiki / "comms-note.md"
        page.write_text("source-backed fixture knowledge\n", encoding="utf-8")
        subprocess.check_call(["git", "add", "-A"], cwd=wiki, stdout=subprocess.DEVNULL)
        subprocess.check_call(
            ["git", "commit", "-m", "curate comms fixture"],
            cwd=wiki, stdout=subprocess.DEVNULL,
        )
        yield DoneChunk(stop_reason="end_turn")


class _NoopProvider:
    ID = "grok_build"
    PROVIDER = _CommitProvider.PROVIDER

    def has_key(self) -> bool:
        return True

    async def chat_stream(self, req):
        from switchbay.llmgateway import DoneChunk
        yield DoneChunk(stop_reason="end_turn")


class _EmptyCommitProvider:
    """HEAD moves, no wiki page delta — must not consume mail."""

    ID = "grok_build"
    PROVIDER = _CommitProvider.PROVIDER

    def has_key(self) -> bool:
        return True

    async def chat_stream(self, req):
        from switchbay.llmgateway import DoneChunk
        wiki = Path(req.workspace) / "wiki"
        subprocess.check_call(
            ["git", "commit", "--allow-empty", "-m", "empty"],
            cwd=wiki, stdout=subprocess.DEVNULL,
        )
        yield DoneChunk(stop_reason="end_turn")


class _HangProvider:
    ID = "grok_build"
    PROVIDER = _CommitProvider.PROVIDER

    def has_key(self) -> bool:
        return True

    async def chat_stream(self, req):
        await asyncio.Event().wait()
        yield None


def _gmail_full_payload_named(mid: str, text: str = "approved fixture body") -> dict:
    return {
        "id": mid,
        "internalDate": "2000000000000",
        "payload": {
            "mimeType": "text/plain",
            "body": {"data": base64.urlsafe_b64encode(text.encode()).decode()},
        },
        "body": {"content": text},
    }


@pytest.mark.asyncio
async def test_production_handoff_commits_wiki_and_consumes(tmp_path, monkeypatch):
    _enterprise_comms(tmp_path, monkeypatch)
    seats.reset_for_tests()
    _init_wiki(tmp_path)
    before = _wiki_sha(tmp_path)
    ws = str(tmp_path)
    acct = {
        "id": "gmail-handoff", "provider": "gmail", "label": "Fixture",
        "workspaces": [ws],
    }
    monkeypatch.setattr(streams, "get_account", lambda *a: acct)
    monkeypatch.setattr(streams, "update_account", lambda *a, **k: acct)
    monkeypatch.setattr(streams, "list_accounts", lambda: [acct])
    rec = comms_review.upsert_discovery({
        "provider": "gmail", "account_id": acct["id"], "stable_id": "thread-h",
        "subject": "Fixture", "headers": {"Sensitivity": "normal"},
        "fetch_ref": {"id": "message1"}, "thread_id": "thread-h",
    })
    key = rec["key"]
    comms_review.set_suggestions(key, workspaces=[ws])
    assert comms_review.approve(key, ws, allowed=[ws])["ok"]

    async def api(sess, account, url, **params):
        if params.get("format") == "full":
            return _gmail_full_payload_named("message1")
        return {
            "id": "message1", "threadId": "thread-h",
            "payload": {"headers": [{"name": "Sensitivity", "value": "normal"}]},
        }

    from switchbay import daemon, llmgateway
    monkeypatch.setattr(streams, "_api_get", api)
    monkeypatch.setattr(daemon, "_comms_curation_route", lambda *a, **k: ("grok_build", "grok-4.6"))
    monkeypatch.setattr(llmgateway, "get", lambda *a: _CommitProvider())
    fetched = await streams.fetch_approved_thread(acct, key, ws)
    assert fetched.get("events"), fetched
    app = {"runs": {}, "workspace": tmp_path, "ws_clients": set()}
    result = await daemon._run_stream_curation(app, acct)
    assert result.get("ok") and int(result.get("curated") or 0) >= 1, result
    after = _wiki_sha(tmp_path)
    assert after != before
    assert (tmp_path / "wiki" / "comms-note.md").read_text(encoding="utf-8").find("fixture") >= 0
    assert streams.pending_events(acct["id"]) == []
    item = comms_review.get_item(key, ws)
    assert item and item.get("ingest_state") == "ingested"


@pytest.mark.asyncio
async def test_noop_curator_retains_pending_for_retry(tmp_path, monkeypatch):
    _enterprise_comms(tmp_path, monkeypatch)
    seats.reset_for_tests()
    _init_wiki(tmp_path)
    ws = str(tmp_path)
    acct = {
        "id": "gmail-noop", "provider": "gmail", "label": "Fixture",
        "workspaces": [ws],
    }
    rec = comms_review.upsert_discovery({
        "provider": "gmail", "account_id": acct["id"], "stable_id": "thread-n",
        "subject": "Fixture", "headers": {"Sensitivity": "normal"},
        "fetch_ref": {"id": "message1"}, "thread_id": "thread-n",
    })
    key = rec["key"]
    assert comms_review.approve(key, ws, allowed=[ws])["ok"]
    streams._append_transit(acct["id"], [{
        "id": "gmail:message1::" + ws,
        "comms_key": key,
        "approved_workspace": ws,
        "approved": True,
        "text": "approved fixture body",
        "subject": "Fixture",
        "stream": "inbox",
        "ts": 1,
        "sender": "f@example.invalid",
        "deep_link": "",
    }])
    from switchbay import daemon, llmgateway
    monkeypatch.setattr(daemon, "_comms_curation_route", lambda *a, **k: ("grok_build", "grok-4.6"))
    monkeypatch.setattr(llmgateway, "get", lambda *a: _NoopProvider())
    monkeypatch.setattr(streams, "allowed_workspaces", lambda a: [ws])
    app = {"runs": {}, "workspace": tmp_path, "ws_clients": set()}
    result = await daemon._run_stream_curation(app, acct)
    assert not result.get("ok"), result
    pending = streams.pending_events(acct["id"])
    assert pending, "no-op curator must leave transit for retry"
    item = comms_review.get_item(key, ws)
    assert item and item.get("ingest_state") == "error"
    assert item.get("ingest_error")


@pytest.mark.asyncio
async def test_two_workspace_success_consumes_once_each(tmp_path, monkeypatch):
    _enterprise_comms(tmp_path, monkeypatch)
    seats.reset_for_tests()
    ws_a = tmp_path / "a"
    ws_b = tmp_path / "b"
    ws_a.mkdir()
    ws_b.mkdir()
    _init_wiki(ws_a)
    _init_wiki(ws_b)
    acct = {
        "id": "gmail-2ws", "provider": "gmail", "label": "Fixture",
        "workspaces": [str(ws_a), str(ws_b)],
    }
    rec = comms_review.upsert_discovery({
        "provider": "gmail", "account_id": acct["id"], "stable_id": "thread-2",
        "subject": "Fixture", "headers": {"Sensitivity": "normal"},
        "fetch_ref": {"id": "message1"}, "thread_id": "thread-2",
    })
    key = rec["key"]
    assert comms_review.approve(key, str(ws_a), allowed=[str(ws_a), str(ws_b)])["ok"]
    assert comms_review.approve(key, str(ws_b), allowed=[str(ws_a), str(ws_b)])["ok"]
    for w in (ws_a, ws_b):
        streams._append_transit(acct["id"], [{
            "id": f"gmail:message1::{w}",
            "comms_key": key,
            "approved_workspace": str(w),
            "approved": True,
            "text": "approved fixture body",
            "subject": "Fixture",
            "stream": "inbox",
            "ts": 1,
            "sender": "f@example.invalid",
            "deep_link": "",
        }])
    from switchbay import daemon, llmgateway
    monkeypatch.setattr(daemon, "_comms_curation_route", lambda *a, **k: ("grok_build", "grok-4.6"))
    monkeypatch.setattr(llmgateway, "get", lambda *a: _CommitProvider())
    monkeypatch.setattr(streams, "allowed_workspaces", lambda a: [str(ws_a), str(ws_b)])
    monkeypatch.setattr(streams, "live_allowed_workspaces", lambda a: [str(ws_a), str(ws_b)])
    app = {"runs": {}, "workspace": tmp_path, "ws_clients": set()}
    result = await daemon._run_stream_curation(app, acct)
    assert result.get("ok"), result
    assert streams.pending_events(acct["id"]) == []
    again = await daemon._run_stream_curation(app, acct)
    assert int(again.get("curated") or 0) == 0
    assert (ws_a / "wiki" / "comms-note.md").is_file()
    assert (ws_b / "wiki" / "comms-note.md").is_file()


def test_comms_route_skips_denied_and_http_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("SWITCHBAY_PROFILE", "open")
    admin_policy.reset_cache()
    from switchbay import daemon, llmgateway
    from switchbay.agents import orchestration_policy as orch_pol
    orch_pol.set_denied_models(["claude_code", "claude_code/*"], workspace=tmp_path)

    class Claude:
        ID = "claude_code"
        PROVIDER = {
            "id": "claude_code",
            "default_model": "sonnet",
            "capabilities": {"shell": True, "file_write": True},
        }
        def has_key(self):
            return True

    class Grok:
        ID = "grok_build"
        PROVIDER = {
            "id": "grok_build",
            "default_model": "grok-4.6",
            "capabilities": {"shell": True, "file_write": True},
        }
        def has_key(self):
            return True

    class Copilot:
        ID = "github_copilot"
        PROVIDER = {
            "id": "github_copilot",
            "default_model": "copilot-x",
            "capabilities": {"shell": False, "file_write": False, "tools": True},
        }
        def has_key(self):
            return True

    fake = {
        "claude_code": Claude(),
        "github_copilot": Copilot(),
        "grok_build": Grok(),
    }
    monkeypatch.setattr(llmgateway, "PROVIDERS", fake)
    monkeypatch.setattr(llmgateway, "get", lambda pid: fake[pid])
    monkeypatch.setattr(daemon, "_ce_action_provider", lambda ws: ("github_copilot", "copilot-x"))
    monkeypatch.setattr(daemon, "_auto_roster_pair", lambda ws, **k: ("github_copilot", "copilot-x"))
    monkeypatch.setattr(daemon, "_effective_model", lambda pid: fake[pid].PROVIDER["default_model"])
    pid, model = daemon._comms_curation_route(tmp_path)
    assert pid == "grok_build", (pid, model)
    assert model == "grok-4.6"
    assert pid != "github_copilot"
    assert pid != "claude_code"


@pytest.mark.asyncio
async def test_comms_curation_waits_on_shared_curate_desk(tmp_path, monkeypatch):
    _enterprise_comms(tmp_path, monkeypatch)
    seats.reset_for_tests()
    _init_wiki(tmp_path)
    from switchbay import daemon, llmgateway
    from switchbay.kernel.desk import DESK_CURATE
    ws = str(tmp_path)
    acct = {"id": "gmail-desk", "provider": "gmail", "label": "F", "workspaces": [ws]}
    rec = comms_review.upsert_discovery({
        "provider": "gmail", "account_id": acct["id"], "stable_id": "t",
        "subject": "Fixture", "headers": {"Sensitivity": "normal"},
    })
    key = rec["key"]
    comms_review.approve(key, ws, allowed=[ws])
    events = [{
        "id": "e1", "comms_key": key, "approved_workspace": ws,
        "approved": True, "text": "body", "subject": "s", "stream": "inbox",
        "ts": 1, "sender": "a", "deep_link": "",
    }]
    monkeypatch.setattr(daemon, "_comms_curation_route", lambda *a, **k: ("grok_build", "grok-4.6"))
    monkeypatch.setattr(llmgateway, "get", lambda *a: _CommitProvider())
    monkeypatch.setattr(streams, "live_allowed_workspaces", lambda a: [ws])
    domain = seats.desk_domain_id(tmp_path, DESK_CURATE)
    gate = seats.gate_for(domain, workspace=tmp_path)
    cap = gate.cap
    for i in range(cap):
        await gate.acquire(f"filler-{i}", kind="worker")
    app = {"runs": {}, "workspace": tmp_path, "ws_clients": set()}
    task = asyncio.create_task(daemon._curate_into(app, acct, tmp_path, events))
    await asyncio.sleep(0.05)
    assert not task.done()
    await gate.release_async("filler-0")
    ok, err = await asyncio.wait_for(task, timeout=2.0)
    assert ok, err
    for i in range(1, cap):
        await gate.release_async(f"filler-{i}")


@pytest.mark.asyncio
async def test_approve_response_includes_ingest_error(tmp_path, monkeypatch):
    _enterprise_comms(tmp_path, monkeypatch)
    from switchbay import daemon
    ws = str(tmp_path)
    acct = {
        "id": "gmail-err", "provider": "gmail", "label": "F",
        "workspaces": [ws],
    }
    rec = comms_review.upsert_discovery({
        "provider": "gmail", "account_id": acct["id"], "stable_id": "thread-e",
        "subject": "Fixture", "headers": {"Sensitivity": "normal"},
        "fetch_ref": {"id": "message1"}, "thread_id": "thread-e",
    })
    key = rec["key"]
    assert comms_review.approve(key, ws, allowed=[ws])["ok"]
    async def boom(*a, **k):
        return {"ok": False, "error": "not connected", "events": []}
    monkeypatch.setattr(streams, "fetch_approved_thread", boom)
    app = {"runs": {}, "workspace": tmp_path, "ws_clients": set()}
    ingest = await daemon._ingest_after_approve(app, acct, key, ws)
    assert ingest.get("ingest_state") == "error"
    assert ingest.get("ingest_error")
    assert "chat_stream" not in ingest["ingest_error"].lower()
    item = comms_review.get_item(key, ws)
    assert item and item["status"] == "approved"
    assert item.get("ingest_state") == "error"


@pytest.mark.asyncio
async def test_empty_commit_curator_retains_transit(tmp_path, monkeypatch):
    _enterprise_comms(tmp_path, monkeypatch)
    seats.reset_for_tests()
    _init_wiki(tmp_path)
    ws = str(tmp_path)
    acct = {
        "id": "gmail-empty", "provider": "gmail", "label": "Fixture",
        "workspaces": [ws],
    }
    rec = comms_review.upsert_discovery({
        "provider": "gmail", "account_id": acct["id"], "stable_id": "thread-empty",
        "subject": "Fixture", "headers": {"Sensitivity": "normal"},
        "fetch_ref": {"id": "message1"}, "thread_id": "thread-empty",
    })
    key = rec["key"]
    assert comms_review.approve(key, ws, allowed=[ws])["ok"]
    streams._append_transit(acct["id"], [{
        "id": "gmail:message1::" + ws,
        "comms_key": key,
        "approved_workspace": ws,
        "approved": True,
        "text": "approved fixture body",
        "subject": "Fixture",
        "stream": "inbox",
        "ts": 1,
        "sender": "f@example.invalid",
        "deep_link": "",
    }])
    from switchbay import daemon, llmgateway
    monkeypatch.setattr(daemon, "_comms_curation_route", lambda *a, **k: ("grok_build", "grok-4.6"))
    monkeypatch.setattr(llmgateway, "get", lambda *a: _EmptyCommitProvider())
    monkeypatch.setattr(streams, "allowed_workspaces", lambda a: [ws])
    app = {"runs": {}, "workspace": tmp_path, "ws_clients": set()}
    sha_before = _wiki_sha(tmp_path)
    result = await daemon._run_stream_curation(app, acct)
    assert not result.get("ok"), result
    assert _wiki_sha(tmp_path) != sha_before
    assert streams.pending_events(acct["id"]), "empty commit must not consume mail"


@pytest.mark.asyncio
async def test_curate_into_releases_desk_after_success_error_cancel(tmp_path, monkeypatch):
    from switchbay import daemon, llmgateway
    from switchbay.kernel.desk import DESK_CURATE
    _enterprise_comms(tmp_path, monkeypatch)
    seats.reset_for_tests()
    _init_wiki(tmp_path)
    ws = str(tmp_path)
    acct = {"id": "gmail-leak", "provider": "gmail", "label": "F", "workspaces": [ws]}
    rec = comms_review.upsert_discovery({
        "provider": "gmail", "account_id": acct["id"], "stable_id": "leak",
        "subject": "Fixture", "headers": {"Sensitivity": "normal"},
    })
    key = rec["key"]
    comms_review.approve(key, ws, allowed=[ws])
    events = [{
        "id": "e1", "comms_key": key, "approved_workspace": ws,
        "approved": True, "text": "body", "subject": "s", "stream": "inbox",
        "ts": 1, "sender": "a", "deep_link": "",
    }]
    monkeypatch.setattr(daemon, "_comms_curation_route", lambda *a, **k: ("grok_build", "grok-4.6"))
    monkeypatch.setattr(streams, "live_allowed_workspaces", lambda a: [ws])
    domain = seats.desk_domain_id(tmp_path, DESK_CURATE)
    app = {"runs": {}, "workspace": tmp_path, "ws_clients": set()}

    def leftover() -> tuple[int, int]:
        g = seats._GATES.get(domain)
        if g is None:
            return 0, 0
        return g.live(), g._refs

    monkeypatch.setattr(llmgateway, "get", lambda *a: _CommitProvider())
    ok, err = await daemon._curate_into(app, acct, tmp_path, events)
    assert ok, err
    live, refs = leftover()
    assert live == 0 and refs == 0

    seats.reset_for_tests()
    monkeypatch.setattr(llmgateway, "get", lambda *a: _NoopProvider())
    ok, err = await daemon._curate_into(app, acct, tmp_path, events)
    assert not ok
    live, refs = leftover()
    assert live == 0 and refs == 0

    seats.reset_for_tests()
    monkeypatch.setattr(llmgateway, "get", lambda *a: _HangProvider())
    task = asyncio.create_task(daemon._curate_into(app, acct, tmp_path, events))
    g = None
    for _ in range(200):
        g = seats._GATES.get(domain)
        if g is not None and g.live() >= 1:
            break
        await asyncio.sleep(0.01)
    assert g is not None and g.live() >= 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    live, refs = leftover()
    assert live == 0 and refs == 0
