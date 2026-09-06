"""Switch Bay research specialist: search + fetch-to-vault + ingest."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import URLError

import pytest

from switchbay import research, tools
from switchbay.kernel.packages import RESEARCH_ID, get_package


def test_research_package_and_tools_registered():
    pkg = get_package(RESEARCH_ID)
    assert pkg is not None
    assert "research_search" in pkg.tools
    assert "research_fetch" in pkg.tools
    assert "ce_ingest" in pkg.tools
    assert "research_search" in tools.REGISTRY
    assert "research_fetch" in tools.REGISTRY
    from switchbay.agents import rail_default
    # Chief hire justification: rail default does not ship these.
    assert "research_search" not in rail_default.ALLOWED_TOOLS
    assert "research_fetch" not in rail_default.ALLOWED_TOOLS


def test_ssrf_blocks_loopback_and_file(monkeypatch):
    def fake_gai(host, port, *a, **k):
        ip = {
            "127.0.0.1": "127.0.0.1",
            "localhost": "127.0.0.1",
            "10.0.0.1": "10.0.0.1",
        }.get(str(host))
        if ip is None:
            raise OSError("unresolved")
        return [(0, 0, 0, "", (ip, port))]

    monkeypatch.setattr(research.socket, "getaddrinfo", fake_gai)
    with pytest.raises(ValueError, match="http"):
        research.assert_public_http_url("file:///etc/passwd")
    with pytest.raises(ValueError, match="blocked"):
        research.assert_public_http_url("http://127.0.0.1/secret")
    with pytest.raises(ValueError, match="blocked"):
        research.assert_public_http_url("http://localhost/x")
    with pytest.raises(ValueError, match="blocked"):
        research.assert_public_http_url("http://10.0.0.1/")


def test_research_search_merges_backends(monkeypatch):
    monkeypatch.setattr(research, "_openalex", lambda q, n: [
        {"title": "Paper", "url": "https://example.edu/p", "snippet": "A", "source": "openalex"},
    ])
    monkeypatch.setattr(research, "_wikipedia", lambda q, n: [
        {"title": "Wiki", "url": "https://en.wikipedia.org/wiki/X", "snippet": "B", "source": "wikipedia"},
    ])
    monkeypatch.setattr(research, "_duckduckgo", lambda q, n: [
        {"title": "Paper", "url": "https://example.edu/p", "snippet": "", "source": "duckduckgo"},
    ])
    out = research.search_web("attention", source="auto", limit=8)
    assert out["ok"] is True
    urls = [h["url"] for h in out["hits"]]
    assert urls[0] == "https://example.edu/p"
    assert "https://en.wikipedia.org/wiki/X" in urls
    assert urls.count("https://example.edu/p") == 1


def test_research_search_requires_query():
    out = research.search_web("  ")
    assert out["ok"] is False


def test_research_fetch_writes_vault_and_ingests(tmp_path: Path, monkeypatch):
    body = b"<html><body>hello paper</body></html>"

    def fake_get(url, *, timeout=25.0):
        return body, "text/html; charset=utf-8", url

    ingested = {}

    def fake_execute(name, workspace, payload):
        ingested["name"] = name
        ingested["payload"] = payload
        ingested["workspace"] = workspace
        return {"ok": True, "path": payload.get("path")}

    monkeypatch.setattr(research, "_get", fake_get)
    monkeypatch.setattr("switchbay.tools.execute", fake_execute)
    out = research.fetch_to_vault(tmp_path, "https://example.edu/paper")
    assert out["ok"] is True
    path = tmp_path / out["path"]
    assert path.is_file()
    assert path.read_bytes() == body
    assert str(path).startswith(str(tmp_path / "vault" / "raw"))
    assert ingested["name"] == "ce_ingest"
    assert ingested["payload"]["path"] == out["path"]


def test_research_fetch_can_skip_ingest(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        research, "_get",
        lambda url, *, timeout=25.0: (b"x", "text/plain", url),
    )
    out = research.fetch_to_vault(tmp_path, "https://example.edu/a.txt", ingest=False)
    assert out["ok"] is True
    assert "ingest" not in out


def test_ce_cli_dry_run_research(tmp_path: Path, capsys):
    from switchbay.ce_cli import main
    rc = main([
        "--workspace", str(tmp_path),
        "--tool", "research_search",
        "--input", json.dumps({"query": "qwen"}),
        "--dry-run",
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["tool"] == "research_search"


def test_fetch_names_include_url_digest(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        research, "_get",
        lambda url, *, timeout=25.0: (b"x", "text/plain", url),
    )
    a = research.fetch_to_vault(
        tmp_path, "https://example.edu/page?q=one", ingest=False,
    )
    b = research.fetch_to_vault(
        tmp_path, "https://example.edu/page?q=two", ingest=False,
    )
    assert a["ok"] and b["ok"]
    assert a["path"] != b["path"]


def test_ingest_failure_marks_fetch_not_ok(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        research, "_get",
        lambda url, *, timeout=25.0: (b"x", "text/plain", url),
    )
    monkeypatch.setattr(
        "switchbay.tools.execute",
        lambda *_a, **_k: {"ok": False, "error": "ingest failed"},
    )
    out = research.fetch_to_vault(tmp_path, "https://example.edu/a.txt")
    assert out["ok"] is False
    assert out["ingest"]["ok"] is False


def test_public_http_target_returns_ips(monkeypatch):
    monkeypatch.setattr(
        research.socket, "getaddrinfo",
        lambda *_a, **_k: [(0, 0, 0, "", ("8.8.8.8", 443))],
    )
    url, host, port, ips = research.public_http_target("https://example.edu/x")
    assert host == "example.edu"
    assert port == 443
    assert ips == ["8.8.8.8"]


def test_pinned_http_connect_uses_validated_ip():
    conn = research._PinnedHTTPConnection("evil.example", 80, pinned_ip="203.0.113.9")
    assert conn._pinned_ip == "203.0.113.9"
    assert conn.host == "evil.example"


def test_research_fetch_rejects_ssrf_without_network(tmp_path: Path):
    out = research.fetch_to_vault(tmp_path, "http://127.0.0.1/x")
    assert out["ok"] is False
    assert "blocked" in out["error"]


def test_research_search_backend_error_is_soft(monkeypatch):
    monkeypatch.setattr(research, "_openalex", lambda q, n: (_ for _ in ()).throw(URLError("down")))
    monkeypatch.setattr(research, "_wikipedia", lambda q, n: [])
    monkeypatch.setattr(research, "_duckduckgo", lambda q, n: [])
    out = research.search_web("x", source="papers")
    assert out["ok"] is True
    assert out["hits"] == []
    assert out["errors"]
