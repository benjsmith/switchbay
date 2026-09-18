"""Protected web egress: shared execute boundary, unforgeable consent."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import URLError

from switchbay import permissions, research, tools, web_policy
from switchbay.llmgateway import claude_code_settings


def test_direct_registry_call_requires_approval(tmp_path: Path, monkeypatch):
    import urllib.request
    web_policy.save(tmp_path, enabled=True)
    monkeypatch.setattr(web_policy, "admin_allows", lambda: True)
    calls = []
    monkeypatch.setattr(research, "search_web", lambda *a, **kw: calls.append(a) or {"ok": True})

    def unavailable(*a, **kw):
        raise URLError("test: approval daemon unavailable")

    monkeypatch.setattr(urllib.request, "urlopen", unavailable)
    out = tools.execute("research_search", tmp_path, {"query": "private query"})
    assert not calls, "search ran without per-call approval"
    assert out.get("ok") is False


def test_payload_approved_flag_is_ignored(tmp_path: Path, monkeypatch):
    import urllib.request
    web_policy.save(tmp_path, enabled=True)
    monkeypatch.setattr(web_policy, "admin_allows", lambda: True)
    calls = []
    monkeypatch.setattr(research, "search_web", lambda *a, **kw: calls.append(a) or {"ok": True})
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda *a, **kw: (_ for _ in ()).throw(URLError("down")),
    )
    out = tools.execute(
        "research_search", tmp_path,
        {"query": "x", "_approved": True, "approved": True},
    )
    assert not calls
    assert out.get("ok") is False


def test_trusted_consent_runs_handler(tmp_path: Path, monkeypatch):
    web_policy.save(tmp_path, enabled=True)
    monkeypatch.setattr(web_policy, "admin_allows", lambda: True)
    monkeypatch.setattr(research, "search_web", lambda *a, **kw: {"ok": True, "hits": []})
    out = tools.execute(
        "research_search", tmp_path, {"query": "x"},
        consent=permissions.trusted_consent(),
    )
    assert out.get("ok") is True


def test_forged_consent_object_is_rejected(tmp_path: Path, monkeypatch):
    import urllib.request
    web_policy.save(tmp_path, enabled=True)
    monkeypatch.setattr(web_policy, "admin_allows", lambda: True)
    calls = []
    monkeypatch.setattr(research, "search_web", lambda *a, **kw: calls.append(1) or {"ok": True})
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda *a, **kw: (_ for _ in ()).throw(URLError("down")),
    )
    out = tools.execute(
        "research_search", tmp_path, {"query": "x"},
        consent=object(),
    )
    assert not calls
    assert out.get("ok") is False


def test_toggle_off_after_consent_prevents_handler(tmp_path: Path, monkeypatch):
    web_policy.save(tmp_path, enabled=True)
    monkeypatch.setattr(web_policy, "admin_allows", lambda: True)
    calls = []
    monkeypatch.setattr(research, "search_web", lambda *a, **kw: calls.append(1) or {"ok": True})
    consent = permissions.trusted_consent()
    web_policy.save(tmp_path, enabled=False)
    out = tools.execute(
        "research_search", tmp_path, {"query": "x"}, consent=consent,
    )
    assert not calls
    assert out.get("ok") is False


def test_ce_identifier_resolve_requires_consent():
    assert permissions.needs_web_consent("ce_run", {
        "script": "identifier_resolve.py", "args": ["run", "--yes"],
    })
    assert not permissions.needs_web_consent("ce_run", {
        "script": "identifier_resolve.py", "args": ["status"],
    })
    assert not permissions.needs_web_consent("ce_run", {
        "script": "identifier_resolve.py", "args": ["review"],
    })


def test_ce_run_url_args_require_consent(tmp_path: Path, monkeypatch):
    import urllib.request
    from switchbay import ce_tools
    web_policy.save(tmp_path, enabled=True)
    monkeypatch.setattr(web_policy, "admin_allows", lambda: True)
    ran = []
    monkeypatch.setattr(
        "switchbay.cebridge.run_script",
        lambda *a, **k: ran.append(1) or {"ok": True},
    )
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda *a, **kw: (_ for _ in ()).throw(URLError("down")),
    )
    out = tools.execute(
        "ce_run", tmp_path,
        {"script": "sweep.py", "args": ["https://example.edu/x"]},
    )
    assert not ran
    assert out.get("ok") is False
    out2 = tools.execute(
        "ce_run", tmp_path,
        {"script": "sweep.py", "args": ["https://example.edu/x"]},
        consent=permissions.trusted_consent(),
    )
    assert ran
    assert "error" not in out2 or out2.get("ok") is not False


def test_ce_ingest_local_path_does_not_need_web_card(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "switchbay.cebridge.run_script",
        lambda *a, **k: {"ok": True},
    )
    monkeypatch.setattr(
        "switchbay.ce_tools._with_ingest_prep",
        lambda *a, **k: (["vault/raw/a.md"], {"ok": True}),
    )
    out = tools.execute("ce_ingest", tmp_path, {"path": "vault/raw/a.md"})
    assert isinstance(out, dict)


def test_ce_cli_research_requires_approval(tmp_path: Path, monkeypatch, capsys):
    import urllib.request
    from switchbay.ce_cli import main
    web_policy.save(tmp_path, enabled=True)
    monkeypatch.setattr(web_policy, "admin_allows", lambda: True)
    calls = []
    monkeypatch.setattr(research, "search_web", lambda *a, **kw: calls.append(a) or {"ok": True})
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda *a, **kw: (_ for _ in ()).throw(URLError("down")),
    )
    rc = main([
        "--workspace", str(tmp_path),
        "--tool", "research_search",
        "--input", json.dumps({"query": "private"}),
    ])
    assert rc != 0
    assert not calls


def test_mcp_call_does_not_pre_card(tmp_path: Path, monkeypatch):
    """MCP server must not card; tools.execute is the single card."""
    from switchbay import mcp_server
    web_policy.save(tmp_path, enabled=True)
    monkeypatch.setattr(web_policy, "admin_allows", lambda: True)
    cards = []
    monkeypatch.setattr(
        mcp_server, "_request_web_approval",
        lambda *a, **k: cards.append(1) or "approve",
    )
    monkeypatch.setattr(
        tools, "execute",
        lambda *a, **k: {"ok": True, "hits": []},
    )
    out = mcp_server._call_tool(tmp_path, "research_search", {"query": "q"})
    assert cards == []
    assert out.get("isError") is False


def test_mute_protected_pending_denies(tmp_path: Path):
    rec = permissions.register(
        workspace=tmp_path, provider="mcp", tool="research_search",
        tool_input={"query": "q"}, run_id=None, origin="~/bench",
    )
    out = permissions.resolve(rec.req_id, decision="skip", remember=False)
    assert out is not None
    assert out.decision == "deny"


def test_hook_mcp_research_passthrough_native_web_denies(tmp_path: Path):
    from tests.unit.test_permission_scoping import _run_hook
    mcp = _run_hook(tmp_path, {
        "tool_name": "mcp__switchbay__research_search",
        "tool_input": {"query": "q"},
        "session_id": "s1", "cwd": str(tmp_path),
    }, port=1)
    assert mcp == {}
    native = _run_hook(tmp_path, {
        "tool_name": "WebSearch",
        "tool_input": {"query": "q"},
        "session_id": "s1", "cwd": str(tmp_path),
    }, port=1)
    assert native.get("decision") == "deny"


def test_unrelated_tool_still_executes(tmp_path: Path):
    out = tools.execute("list_duckdb_starters", tmp_path, {})
    assert isinstance(out, dict)
    assert "starters" in out
