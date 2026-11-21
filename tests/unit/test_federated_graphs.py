"""Mounted graphs, citations, classification, and source fakes.

The live server in this file speaks the ce-graph/1 operations the
client uses. It is not the curiosity-engine reference server. The
reference server is covered by curiosity-engine's own tests, and
scripts/enterprise_graph_demo.py runs against that server.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import pytest

from switchbay import claim_lint, mcpstore, tools
from switchbay.federation import broker, classify, outbox
from switchbay.federation.adapters import FakeTransport
from switchbay.federation.mounts import Mount, Source, load
from switchbay.federation.tools_reg import add_mount, add_source
from switchbay.llmgateway import grok_build


def _page(path: Path, body: str, **fm: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["---"]
    for key, value in fm.items():
        lines.append(f"{key}: {value}")
    lines += ["---", "", body]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class _Graph(BaseHTTPRequestHandler):
    rev = "abc123"
    token = "tok-test"
    codes: dict = {}

    def log_message(self, fmt, *args):
        return

    def _send(self, code, payload, headers=None):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode())

    def do_GET(self):
        path = urlparse(self.path).path
        if path.endswith("oauth-protected-resource"):
            host = self.headers.get("Host")
            self._send(200, {"resource": f"http://{host}/mcp", "authorization_servers": [f"http://{host}"]})
            return
        if path.endswith("oauth-authorization-server"):
            host = self.headers.get("Host")
            origin = f"http://{host}"
            self._send(200, {
                "issuer": origin,
                "authorization_endpoint": origin + "/oauth/authorize",
                "token_endpoint": origin + "/oauth/token",
                "code_challenge_methods_supported": ["S256"],
            })
            return
        if path == "/oauth/authorize":
            qs = parse_qs(urlparse(self.path).query)
            code = "code-1"
            self.server.codes[code] = qs.get("code_challenge", [""])[0]
            loc = qs["redirect_uri"][0] + "?" + urlencode({"code": code, "state": qs.get("state", [""])[0]})
            self.send_response(302)
            self.send_header("Location", loc)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/ce-graph/1/info":
            self._auth()
            self._send(200, {
                "graph_id": "ceg://kg.example/eng", "rev": self.rev,
                "classification": "confidential",
                "rights": {"read": True, "write": "propose", "direct_granted": False},
            })
            return
        self._send(404, {"error": "no"})

    def _auth(self):
        if self.headers.get("Authorization") != f"Bearer {self.token}":
            raise AssertionError("missing bearer")

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._json()
        if path == "/oauth/token":
            self._send(200, {"access_token": self.token, "token_type": "Bearer", "expires_in": 3600})
            return
        self._auth()
        if path.endswith("/search"):
            self._send(200, {"results": [{
                "path": "concepts/widget", "title": "Widget", "type": "concept",
                "score": 10, "snippet": "sealed bearing", "rev": self.rev,
                "classification": "confidential",
            }], "rev": self.rev})
            return
        if path.endswith("/page"):
            self._send(200, {
                "path": "concepts/widget", "title": "Widget", "type": "concept",
                "frontmatter": {"title": "Widget", "type": "concept", "classification": "confidential"},
                "body": "The widget uses a sealed bearing.\n",
                "rev": self.rev, "classification": "confidential",
                "graph_id": "ceg://kg.example/eng",
            })
            return
        if path.endswith("/propose"):
            self._send(200, {"proposal_id": "p1", "state": "proposed", "note": "queued"})
            return
        self._send(404, {"error": path, "body": body})


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("SWITCHBAY_STATE_DIR", str(tmp_path / "state"))
    _page(tmp_path / "wiki" / "concepts" / "local-alloy.md",
          "The local alloy is a workshop mix.", title="Local alloy", type="concept")
    snap = tmp_path / "public-wiki"
    _page(snap / "wiki" / "concepts" / "standard.md",
          "The public standard covers fasteners.", title="Standard", type="concept",
          classification="public")
    (snap / "wiki").mkdir(exist_ok=True)
    add_mount(tmp_path, Mount(
        id="pub", graph_id="ceg://git/example/standard", kind="snapshot",
        url=str(snap), ref="", read=True, write="propose", trust="external",
        ceiling="public",
    ))
    cfg = load(tmp_path)
    cfg.read_default = ["local", "pub"]
    from switchbay.federation.mounts import save
    save(tmp_path, cfg)
    return tmp_path


def test_search_reads_local_and_snapshot_and_cites_the_pinned_revision(workspace):
    found = tools.execute("search_wiki", workspace, {"query": "fasteners alloy", "graphs": "all"})
    graphs = {row["graph"] for row in found["results"]}
    assert "local" in graphs
    assert "pub" in graphs
    remote = next(row for row in found["results"] if row["graph"] == "pub")
    assert remote["rev"]
    assert remote["untrusted"] is True
    page = tools.execute("read_wiki_page", workspace, {"page": "pub:concepts/standard"})
    assert "UNTRUSTED REMOTE CONTENT" in page["content"]
    assert page["citation"] == f"(graph:pub/concepts/standard@{page['rev']})"
    _page(
        workspace / "wiki" / "facts" / "fastener.md",
        f"Fasteners follow the public standard. {page['citation']}",
        title="Fastener fact", type="fact", classification="public",
    )
    violations = claim_lint.lint_path(workspace)
    assert violations == []


def test_public_mount_refuses_a_confidential_page(workspace):
    secret = "---\nclassification: confidential\ntype: concept\n---\n\nSealed.\n"
    result = outbox.submit(
        workspace, mount_id="pub", path="concepts/leak", content=secret,
        base_rev="", mode="remote",
    )
    assert result["ok"] is False
    assert "confidential" in result["error"]
    from switchbay.federation import audit
    assert any(row["event"] == "refused_write" for row in audit.read(workspace))


def test_live_mount_oauth_and_claim(workspace):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Graph)
    server.codes = {}
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        add_mount(workspace, Mount(
            id="acme", graph_id="ceg://kg.example/eng", kind="live",
            url=f"http://127.0.0.1:{port}/mcp", auth="dev",
            read=True, write="propose", trust="org", ceiling="confidential",
        ))
        from switchbay.federation import oauth
        token = oauth.obtain(f"http://127.0.0.1:{port}/mcp", "acme")
        assert token == "tok-test"
        found = tools.execute("search_wiki", workspace, {"query": "bearing", "graphs": ["acme"]})
        assert found["results"][0]["page"] == "acme:concepts/widget"
        page = tools.execute("read_wiki_page", workspace, {"page": "acme:concepts/widget"})
        assert page["rev"] == "abc123"
        assert "sealed bearing" in page["content"]
        _page(
            workspace / "wiki" / "facts" / "bearing.md",
            f"The bearing is sealed. {page['citation']}",
            title="Bearing", type="fact", classification="confidential",
        )
        assert claim_lint.lint_path(workspace / "wiki" / "facts" / "bearing.md") == []
        # A citation at the wrong revision does not pass.
        text = (workspace / "wiki" / "facts" / "bearing.md").read_text(encoding="utf-8")
        (workspace / "wiki" / "facts" / "bearing.md").write_text(
            text.replace("@abc123", "@deadbeef"), encoding="utf-8",
        )
        bad = claim_lint.lint_path(workspace / "wiki" / "facts" / "bearing.md")
        assert any(item.code == "unresolved-citation" for item in bad)
        proposed = tools.execute("propose_graph_write", workspace, {
            "mount": "acme", "path": "concepts/note",
            "content": "---\nclassification: internal\ntype: note\n---\n\nA note.\n",
            "base_rev": "abc123", "mode": "remote",
        })
        assert proposed["ok"] is True
        assert proposed["state"] == "proposed"
    finally:
        server.shutdown()


def test_source_broker_records_a_fake_and_keeps_the_label(workspace):
    add_source(workspace, Source(
        id="genie", kind="databricks-genie", url="https://example.invalid/mcp",
        classification="confidential",
    ))
    transport = FakeTransport({"genie_ask": {
        "text": "revenue is 10",
        "deep_links": ["https://example.invalid/q/1"],
        "labels": ["confidential"],
    }})
    result = broker.call(
        workspace, "genie", "genie_ask", {"question": "revenue"},
        transport=transport, snapshot=True,
    )
    assert result["ok"] is True
    assert result["classification"] == "confidential"
    assert result["citation"].startswith("(capture:")
    snap = workspace / result["snapshot"]
    assert "BEGIN FETCHED CONTENT" in snap.read_text(encoding="utf-8")
    assert "untrusted: true" in snap.read_text(encoding="utf-8")
    denied = broker.call(
        workspace, "genie", "genie_ask", {"question": "x"},
        transport=FakeTransport({"genie_ask": {"policy_outcome": "denied", "message": "no"}}),
    )
    assert denied["policy_outcome"] == "denied"
    act = broker.call(workspace, "genie", "create_entity", {}, transport=transport)
    assert act["ok"] is False


def test_declassify_requires_edit_access_and_is_audited(workspace, monkeypatch):
    import getpass
    from switchbay import admin_policy
    _page(workspace / "wiki" / "facts" / "secret.md", "Hidden. (vault:missing.md)",
          title="Secret", type="fact", classification="confidential")
    locked = workspace / "wiki" / "facts" / "locked.md"
    _page(locked, "Hidden.", title="Locked", type="fact", classification="confidential",
          source_ref="readonly:sharepoint:9")
    refused = classify.declassify(workspace, "wiki/facts/locked.md")
    assert refused["ok"] is False
    assert "edit" in refused["error"]
    done = classify.declassify(workspace, "wiki/facts/secret.md")
    assert done["ok"] is True
    assert done["before"] == "confidential"
    assert done["after"] == "public"
    text = (workspace / "wiki" / "facts" / "secret.md").read_text(encoding="utf-8")
    assert "classification: public" in text
    from switchbay.federation import audit
    row = next(item for item in audit.read(workspace) if item["event"] == "declassify")
    assert row["path"] == "wiki/facts/secret.md"
    assert row["before"] == "confidential"
    assert row["after"] == "public"
    assert row["user"] == getpass.getuser()
    assert row["ts"]
    monkeypatch.setattr(admin_policy, "profile", lambda: "enterprise")
    _page(workspace / "wiki" / "facts" / "secret.md", "Hidden again.",
          title="Secret", type="fact", classification="confidential")
    again = classify.declassify(workspace, "facts/secret.md")
    assert again["ok"] is True


def test_unbound_mcp_server_is_not_offered_to_a_published_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(mcpstore.workspaces, "config_dir", lambda: tmp_path)
    mcpstore._save([{
        "name": "personal", "transport": "stdio", "command": "x",
        "args": [], "env": {}, "enabled": True,
    }])
    private = tmp_path / "private"
    private.mkdir()
    shared = tmp_path / "shared"
    (shared / ".workbench").mkdir(parents=True)
    (shared / ".workbench" / "share.json").write_text("{}")
    assert [row["name"] for row in mcpstore.enabled_servers(private)] == ["personal"]
    assert mcpstore.enabled_servers(shared) == []
    bound = tmp_path / "bound"
    bound.mkdir()
    mcpstore._save([{
        "name": "personal", "transport": "http", "url": "http://127.0.0.1:9/mcp",
        "headers": {}, "enabled": True,
        "allowed_workspaces": [str(bound.resolve())],
    }])
    assert mcpstore.enabled_servers(private) == []
    assert [row["name"] for row in mcpstore.enabled_servers(bound)] == ["personal"]


def test_grok_http_mcp_is_written_into_project_config(tmp_path):
    cfg = tmp_path / ".grok" / "config.toml"
    grok_build._write_http_mcp(cfg, {
        "name": "workiq", "url": "https://example.invalid/mcp",
        "headers": {"Authorization": "Bearer secret"},
    })
    text = cfg.read_text(encoding="utf-8")
    assert 'url = "https://example.invalid/mcp"' in text
    assert "Bearer secret" in text
    grok_build._write_http_mcp(cfg, {"name": "workiq", "url": "https://example.invalid/mcp"})
    assert cfg.read_text(encoding="utf-8").count("[mcp_servers.workiq]") == 1


def test_share_preview_reports_classified_pages(workspace):
    from switchbay import share
    _page(workspace / "wiki" / "facts" / "secret.md", "Hidden.",
          title="Secret", type="fact", classification="confidential")
    preview = share.preview(workspace, include_vault=False)
    paths = {item["path"] for item in preview["classification_blocks"]}
    assert "wiki/facts/secret.md" in paths
