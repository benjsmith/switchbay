"""User-defined MCP servers — the "bring your own tools" surface.

Switch Bay ships one first-party MCP server (`switchbay.mcp_server`).
This module lets the user register ADDITIONAL MCP servers (a filesystem
server, a Linear server, a local script, …) which are then fanned into
every subprocess-agent CLI we spawn — claude-code (`--mcp-config`
JSON), grok (`.grok/config.toml`), and codex (`-c mcp_servers.*` TOML).
So a tool the user adds once shows up for whichever provider curates.

Design mirrors `streams.py`: providers DECLARE their fields, the
Settings form renders generically, and every entry is **verified at add
time** (a real MCP `initialize` handshake) with rollback on failure —
a broken server never persists. Storage is user-global JSON at
`~/.config/switchbay/mcp-servers.json` (like action-buttons / streams),
so servers roam across workspaces.

Two transports:
  · **stdio** — `{command, args[], env{}}`. The dominant MCP shape; we
    spawn it and speak newline-delimited JSON-RPC.
  · **http** — `{url, headers{}}`. Streamable-HTTP / SSE servers.

Security note: an MCP server is arbitrary code the agent can call, so
this is a trust surface. We only ADD what the user explicitly enters
(never fetched from a catalog), verify it launches, and it inherits the
same per-tool rail approval card as any other tool call.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any

from . import atomicio, workspaces

log = logging.getLogger("switchbay.mcpstore")

_NAME_RE = re.compile(r"^[a-zA-Z0-9_][a-zA-Z0-9_-]*$")
VERIFY_TIMEOUT_S = 8.0


def _path() -> Path:
    return workspaces.config_dir() / "mcp-servers.json"


def load() -> list[dict[str, Any]]:
    """All registered user MCP servers (sanitised). Never raises."""
    p = _path()
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("mcp-servers.json unreadable; starting empty")
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for e in data:
        s = _sanitise(e)
        if s is not None:
            out.append(s)
    return out


def _sanitise(e: Any) -> dict[str, Any] | None:
    if not isinstance(e, dict):
        return None
    name = str(e.get("name") or "").strip()
    if not _NAME_RE.match(name) or name == "switchbay":
        return None
    try:
        from . import admin_policy
        cmd = str(e.get("command") or "")
        url = str(e.get("url") or "")
        if not admin_policy.mcp_entry_allowed(name, cmd, url):
            return None
    except Exception:  # noqa: BLE001
        pass
    transport = str(e.get("transport") or "stdio").strip().lower()
    if transport not in ("stdio", "http"):
        return None
    out: dict[str, Any] = {
        "name": name,
        "transport": transport,
        "enabled": bool(e.get("enabled", True)),
    }
    if transport == "stdio":
        out["command"] = str(e.get("command") or "").strip()
        args = e.get("args")
        out["args"] = [str(a) for a in args] if isinstance(args, list) else []
        env = e.get("env")
        out["env"] = {str(k): str(v) for k, v in env.items()} if isinstance(env, dict) else {}
    else:
        out["url"] = str(e.get("url") or "").strip()
        headers = e.get("headers")
        out["headers"] = (
            {str(k): str(v) for k, v in headers.items()} if isinstance(headers, dict) else {})
    return out


def _save(servers: list[dict[str, Any]]) -> None:
    atomicio.write_json_atomic(_path(), servers)


def enabled_servers() -> list[dict[str, Any]]:
    """Only the servers that should be fanned into the CLIs."""
    return [s for s in load() if s.get("enabled")]


# ── Verify (real MCP initialize handshake) ─────────────────────────

_INIT_REQ = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "switchbay-verify", "version": "1"},
    },
}


async def verify(server: dict[str, Any]) -> tuple[bool, str]:
    """Confirm a server actually launches + speaks MCP. Returns
    (ok, detail). Best-effort but real: for stdio we spawn it and read
    an `initialize` response; for http we POST one. A failure here means
    the entry is NOT persisted (rollback)."""
    if server.get("transport") == "http":
        return await _verify_http(server)
    return await _verify_stdio(server)


async def _verify_stdio(server: dict[str, Any]) -> tuple[bool, str]:
    import os

    command = server.get("command") or ""
    if not command:
        return False, "no command"
    argv = [command, *(server.get("args") or [])]
    env = {**os.environ, **(server.get("env") or {})}
    # Scrub venv leftovers that break foreign uv-projects (same gotcha
    # as the other bridges).
    for k in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "PYTHONPATH"):
        env.pop(k, None)
    env.update({k: str(v) for k, v in (server.get("env") or {}).items()})
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=env, limit=1024 * 1024,
        )
    except (FileNotFoundError, OSError) as e:
        return False, f"couldn't launch: {e}"
    try:
        assert proc.stdin and proc.stdout
        proc.stdin.write((json.dumps(_INIT_REQ) + "\n").encode())
        await proc.stdin.drain()
        line = await asyncio.wait_for(proc.stdout.readline(), timeout=VERIFY_TIMEOUT_S)
        if not line:
            return False, "server exited without responding"
        msg = json.loads(line.decode("utf-8", "replace"))
        if isinstance(msg, dict) and (msg.get("result") is not None or msg.get("id") == 1):
            info = (msg.get("result") or {}).get("serverInfo") or {}
            return True, f"ok — {info.get('name', 'MCP server')}"
        return False, "response was not a valid initialize result"
    except asyncio.TimeoutError:
        return False, f"no response within {VERIFY_TIMEOUT_S:.0f}s"
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False, "response was not JSON-RPC (is this an MCP server?)"
    finally:
        try:
            proc.kill()
            # Reap within this loop so the transport doesn't finalize
            # after the loop closes (noisy ResourceWarning under asyncio.run).
            await proc.wait()
        except (ProcessLookupError, Exception):  # noqa: BLE001
            pass


async def _verify_http(server: dict[str, Any]) -> tuple[bool, str]:
    import urllib.error
    import urllib.request

    url = server.get("url") or ""
    if not url.startswith(("http://", "https://")):
        return False, "url must be http(s)"
    body = json.dumps(_INIT_REQ).encode()
    headers = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}
    headers.update(server.get("headers") or {})
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        resp = await asyncio.to_thread(urllib.request.urlopen, req, None, VERIFY_TIMEOUT_S)
        code = resp.getcode()
        return (200 <= code < 300), f"HTTP {code}"
    except urllib.error.HTTPError as e:
        # A 4xx from a real MCP endpoint (e.g. auth) still proves it's there.
        return (e.code in (400, 401, 403, 405, 406)), f"HTTP {e.code}"
    except (urllib.error.URLError, OSError) as e:
        return False, f"unreachable: {e}"


# ── Mutations (verified add / remove / toggle) ─────────────────────


async def add(server: dict[str, Any]) -> dict[str, Any]:
    """Verify then persist a new server. Raises ValueError on a bad
    shape, duplicate name, or failed verification (rollback)."""
    from . import admin_policy
    name = str((server or {}).get("name") or "")
    if not admin_policy.mcp_entry_allowed(
        name, str((server or {}).get("command") or ""),
        str((server or {}).get("url") or ""),
    ):
        raise ValueError("MCP server is not on the admin allowlist")
    s = _sanitise(server)
    if s is None:
        raise ValueError("invalid server: needs a name and a stdio command or http url")
    existing = load()
    if any(e["name"] == s["name"] for e in existing):
        raise ValueError(f"a server named {s['name']!r} already exists")
    ok, detail = await verify(s)
    if not ok:
        raise ValueError(f"verification failed: {detail}")
    existing.append(s)
    _save(existing)
    return s


def remove(name: str) -> bool:
    servers = load()
    kept = [s for s in servers if s["name"] != name]
    if len(kept) == len(servers):
        return False
    _save(kept)
    return True


def set_enabled(name: str, enabled: bool) -> bool:
    servers = load()
    hit = False
    for s in servers:
        if s["name"] == name:
            s["enabled"] = bool(enabled)
            hit = True
    if hit:
        _save(servers)
    return hit


# ── Fan-out helpers (per-CLI config shapes) ────────────────────────


def as_claude_mcp_servers() -> dict[str, dict[str, Any]]:
    """Entries for claude-code's `mcpServers` JSON (merged alongside the
    switchbay server in build_mcp_config)."""
    out: dict[str, dict[str, Any]] = {}
    for s in enabled_servers():
        if s["transport"] == "stdio" and s.get("command"):
            out[s["name"]] = {"command": s["command"], "args": s.get("args", []),
                              "env": s.get("env", {})}
        elif s["transport"] == "http" and s.get("url"):
            entry: dict[str, Any] = {"type": "http", "url": s["url"]}
            if s.get("headers"):
                entry["headers"] = s["headers"]
            out[s["name"]] = entry
    return out
