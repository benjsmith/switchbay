"""Minimal MCP (Model Context Protocol) server exposing switchbay's
tool registry to subprocess agents like claude-code.

Spawned by claude_code via `--mcp-config` (see claude_code.py). The
workspace path travels in via env var `CSWY_WORKSPACE` so this
process can execute tools against the right directory without a
network round-trip back to the daemon.

Protocol: JSON-RPC 2.0 over stdio, line-delimited (one message per
line). Implements just enough of the MCP spec to expose tools/list
and tools/call — initialize and the `notifications/initialized`
hello are also wired so claude-code completes its handshake.

We don't depend on the `mcp` package: the protocol is small enough
that a few hundred lines of dataclass-free Python keeps the runtime
surface tight (no extra wheel to ship). If we ever need richer
features (resources, prompts, sampling), switching to the official
SDK is mechanical.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

# We import lazily so this module loads cleanly even if the user runs
# `python -m switchbay.mcp_server` without uv-syncing — the import
# error then surfaces on the first tool call rather than at startup.
log = logging.getLogger("switchbay.mcp_server")


PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "switchbay"
SERVER_VERSION = "0.1.0"


def _send(msg: dict[str, Any]) -> None:
    """Write one JSON-RPC line. flush() so claude-code reads
    immediately — buffered stdout would deadlock the handshake."""
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def _err(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": code, "message": message},
    }


def _ok(msg_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _list_tools(allowed: list[str]) -> dict[str, Any]:
    from . import tools  # lazy import; see module docstring

    out: list[dict[str, Any]] = []
    for name in allowed:
        t = tools.REGISTRY.get(name)
        if t is None:
            continue
        out.append({
            "name": t.name,
            "description": t.description,
            "inputSchema": t.input_schema,
        })
    return {"tools": out}


def _call_tool(workspace: Path, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Execute a registry tool and shape the result into MCP's
    content-block contract. Errors come back with isError=True so the
    calling agent sees them as tool failures, not protocol errors."""
    from . import tools  # lazy import

    try:
        result = tools.execute(name, workspace, args or {})
    except KeyError:
        return {
            "content": [{"type": "text", "text": f"unknown tool: {name}"}],
            "isError": True,
        }
    except Exception as e:  # noqa: BLE001
        log.exception("tool %s crashed", name)
        return {
            "content": [{"type": "text", "text": f"error: {e}"}],
            "isError": True,
        }
    text = result if isinstance(result, str) else json.dumps(result, indent=2)
    return {
        "content": [{"type": "text", "text": text}],
        "isError": False,
    }


def _initialize_response(msg_id: Any) -> dict[str, Any]:
    return _ok(msg_id, {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
    })


def main() -> int:
    """Stdio loop. Reads JSON-RPC lines from stdin, dispatches by
    method, writes responses to stdout. Exits cleanly on EOF (claude-
    code closes stdin when the agent's session ends)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        # stderr only — stdout is the JSON-RPC channel.
        stream=sys.stderr,
    )

    workspace_env = os.environ.get("CSWY_WORKSPACE", "")
    if not workspace_env:
        log.error("CSWY_WORKSPACE env var not set; refusing to start")
        return 2
    workspace = Path(workspace_env)
    if not workspace.is_absolute() or not workspace.is_dir():
        log.error("invalid workspace: %s", workspace_env)
        return 2

    # Allowed tools come from the rail-default agent's allowlist by
    # default; can be overridden via CSWY_ALLOWED_TOOLS (comma-
    # separated) for narrower presets later.
    raw_allow = os.environ.get("CSWY_ALLOWED_TOOLS")
    if raw_allow:
        allowed = [t.strip() for t in raw_allow.split(",") if t.strip()]
    else:
        from .agents import rail_default
        allowed = list(rail_default.ALLOWED_TOOLS)
    log.info("mcp server up: workspace=%s allowed=%s", workspace, allowed)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            log.warning("malformed JSON: %s", line[:200])
            continue
        method = msg.get("method")
        msg_id = msg.get("id")
        if method == "initialize":
            _send(_initialize_response(msg_id))
        elif method == "notifications/initialized":
            # No id, no response needed — client handshake completion.
            pass
        elif method == "tools/list":
            _send(_ok(msg_id, _list_tools(allowed)))
        elif method == "tools/call":
            params = msg.get("params") or {}
            tname = str(params.get("name") or "")
            targs = params.get("arguments") or {}
            if not isinstance(targs, dict):
                targs = {}
            if tname not in allowed:
                _send(_ok(msg_id, {
                    "content": [{
                        "type": "text",
                        "text": f"tool {tname!r} not in allowed set",
                    }],
                    "isError": True,
                }))
                continue
            _send(_ok(msg_id, _call_tool(workspace, tname, targs)))
        elif msg_id is not None:
            _send(_err(msg_id, -32601, f"method not found: {method}"))
        # else: notification we don't care about; silent.
    log.info("mcp server: stdin closed; exiting")
    return 0


if __name__ == "__main__":
    sys.exit(main())
