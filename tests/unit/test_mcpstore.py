"""User MCP server registry: sanitisation, the verify handshake
(against a real minimal stdio MCP server), verified-add rollback, and
the per-CLI fan-out shapes.
"""

from __future__ import annotations

import asyncio
import sys
import textwrap
from pathlib import Path

import pytest

from switchbay import mcpstore


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    """Point config_dir at a tmp dir so tests never touch the real
    ~/.config/switchbay/mcp-servers.json."""
    monkeypatch.setattr(mcpstore.workspaces, "config_dir", lambda: tmp_path)
    return tmp_path


def _good_mcp_script(tmp_path: Path) -> Path:
    """A minimal but real stdio MCP server: answers `initialize` with a
    JSON-RPC result on stdout, newline-delimited (the MCP stdio frame)."""
    p = tmp_path / "fake_mcp.py"
    p.write_text(textwrap.dedent("""
        import sys, json
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            msg = json.loads(line)
            if msg.get("method") == "initialize":
                sys.stdout.write(json.dumps({
                    "jsonrpc": "2.0", "id": msg["id"],
                    "result": {"protocolVersion": "2025-06-18",
                               "capabilities": {},
                               "serverInfo": {"name": "fake", "version": "1"}},
                }) + "\\n")
                sys.stdout.flush()
    """), encoding="utf-8")
    return p


def test_sanitise_rejects_bad_and_reserved_names():
    assert mcpstore._sanitise({"name": "sw itch", "transport": "stdio"}) is None
    assert mcpstore._sanitise({"name": "switchbay", "transport": "stdio"}) is None
    ok = mcpstore._sanitise({"name": "fs", "transport": "stdio", "command": "x"})
    assert ok and ok["name"] == "fs" and ok["enabled"] is True


def test_verify_ok_against_real_stdio_server(tmp_path):
    script = _good_mcp_script(tmp_path)
    ok, detail = asyncio.run(mcpstore.verify(
        {"name": "fake", "transport": "stdio",
         "command": sys.executable, "args": [str(script)], "env": {}}))
    assert ok, detail


def test_verify_fails_on_missing_command():
    ok, detail = asyncio.run(mcpstore.verify(
        {"name": "nope", "transport": "stdio",
         "command": "/definitely/not/a/real/binary/xyz", "args": [], "env": {}}))
    assert not ok


def test_add_rollback_on_failed_verify():
    with pytest.raises(ValueError):
        asyncio.run(mcpstore.add(
            {"name": "broken", "transport": "stdio",
             "command": "/nope/xyz", "args": []}))
    assert mcpstore.load() == []   # nothing persisted


def test_add_then_toggle_then_remove(tmp_path):
    script = _good_mcp_script(tmp_path)
    s = asyncio.run(mcpstore.add(
        {"name": "fake", "transport": "stdio",
         "command": sys.executable, "args": [str(script)]}))
    assert s["name"] == "fake"
    assert [x["name"] for x in mcpstore.load()] == ["fake"]
    assert [x["name"] for x in mcpstore.enabled_servers()] == ["fake"]

    mcpstore.set_enabled("fake", False)
    assert mcpstore.enabled_servers() == []

    assert mcpstore.remove("fake") is True
    assert mcpstore.load() == []


def test_duplicate_name_rejected(tmp_path):
    script = _good_mcp_script(tmp_path)
    spec = {"name": "fake", "transport": "stdio",
            "command": sys.executable, "args": [str(script)]}
    asyncio.run(mcpstore.add(dict(spec)))
    with pytest.raises(ValueError):
        asyncio.run(mcpstore.add(dict(spec)))


def test_claude_fanout_shape(tmp_path):
    script = _good_mcp_script(tmp_path)
    asyncio.run(mcpstore.add(
        {"name": "fs", "transport": "stdio",
         "command": sys.executable, "args": [str(script)], "env": {"A": "b"}}))
    # Inject an http server directly (its verify hits the network — not a
    # unit-test concern here; we only exercise the fan-out shape).
    mcpstore._save(mcpstore.load() + [{
        "name": "web", "transport": "http", "url": "https://x/mcp",
        "headers": {}, "enabled": True}])
    shapes = mcpstore.as_claude_mcp_servers()
    assert shapes["fs"] == {"command": sys.executable,
                            "args": [str(script)], "env": {"A": "b"}}
    assert shapes["web"]["type"] == "http"
    assert shapes["web"]["url"] == "https://x/mcp"
