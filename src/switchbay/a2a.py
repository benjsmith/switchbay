"""A2A protocol surface — the agent↔agent plane of the stack.

Charter posture (2026-07-04, mirroring the AG-UI adoption): speak the
STABLE CORE of A2A — the Agent Card + JSON-RPC `message/send` /
`tasks/get` — and keep everything switchbay-specific in `metadata`
extensions, so spec drift can't reach our surfaces. No SDK, no
framework: the protocol is a card shape + a JSON-RPC envelope.

Mapping onto the thread model (Workspace → Thread → Run → Turn):

    A2A contextId  ↔  thread_id   (the durable conversation)
    A2A Task id    ↔  run_id      (one dispatch)
    A2A Message    ↔  a Turn's user side
    Task artifact  ↔  the run's assistant prose

`metadata.switchbay` on `message/send` may carry:
    workspace: registered workspace NAME or absolute path — target a
               different workspace's agent (the cross-workspace
               collaboration case). Only REGISTERED workspaces
               resolve; arbitrary paths are refused.
    thread_id: explicit target thread (alternative to contextId).

Who calls this: the `ask_thread` agent tool (inter-thread
collaboration dogfoods this endpoint over localhost), other local
A2A-speaking clients, and — later, once the paired-channel security
design lands (Phase 6 / iPhone companion) — remote switchbay peers.
Until then the endpoint shares the daemon's localhost-only trust
boundary.

This module is pure shaping/validation; the daemon owns the routes
(it has the dispatch machinery and the run registry).
"""

from __future__ import annotations

import time
from typing import Any

PROTOCOL_VERSION = "0.3.0"

# JSON-RPC error codes (A2A uses the standard set + a small range of
# its own; we only need these).
ERR_PARSE = -32700
ERR_INVALID_REQUEST = -32600
ERR_METHOD_NOT_FOUND = -32601
ERR_INVALID_PARAMS = -32602
ERR_INTERNAL = -32603
ERR_TASK_NOT_FOUND = -32001
ERR_BUSY = -32002          # thread already streaming (reject-busy guard)


def agent_card(*, workspace_name: str, workspace_path: str, port: int,
               version: str, provider_default: str) -> dict[str, Any]:
    """The Agent Card served at /.well-known/agent-card.json (and the
    legacy /.well-known/agent.json alias). One card per daemon; the
    focused workspace is advertised, other registered workspaces are
    reachable via the metadata extension."""
    url = f"http://127.0.0.1:{port}/a2a"
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "name": f"switchbay · {workspace_name}",
        "description": (
            "Workspace agent for the switchbay workbench. Sends land as "
            "turns on a thread (contextId = thread id) and run inside "
            "the workspace with its tools, wiki and memory. "
            "Cross-workspace targeting via metadata.switchbay."
        ),
        "url": url,
        "preferredTransport": "JSONRPC",
        "version": version,
        "capabilities": {
            "streaming": False,        # message/stream: deferred
            "pushNotifications": False,
            "stateTransitionHistory": False,
        },
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [
            {
                "id": "workspace-chat",
                "name": "Workspace agent chat",
                "description": (
                    "General agentic chat scoped to the workspace: wiki "
                    "recall, file reads, plots, sketches, analyses."
                ),
                "tags": ["chat", "workspace", "knowledge-base"],
                "examples": [
                    "Summarise what this workspace knows about X",
                    "What did we decide about Y last week?",
                ],
            },
        ],
        "metadata": {
            "switchbay": {
                "workspace": workspace_path,
                "defaultProvider": provider_default,
            },
        },
    }


def text_of_message(message: dict[str, Any]) -> str:
    """Flatten an A2A Message's text parts. Non-text parts (file/data)
    are ignored in v1 — defaultInputModes advertises text/plain."""
    parts = message.get("parts") or []
    chunks = []
    for p in parts:
        if isinstance(p, dict) and p.get("kind") == "text":
            t = p.get("text")
            if isinstance(t, str) and t:
                chunks.append(t)
    return "\n".join(chunks).strip()


def task(*, run_id: str, thread_id: str, state: str,
         reply: str | None = None, message: str | None = None) -> dict[str, Any]:
    """Shape an A2A Task object for responses. `reply` becomes the
    single text artifact on completed tasks; `message` rides on the
    status for failed/rejected states."""
    status: dict[str, Any] = {
        "state": state,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if message:
        status["message"] = {
            "kind": "message",
            "role": "agent",
            "messageId": f"{run_id}-status",
            "parts": [{"kind": "text", "text": message}],
        }
    out: dict[str, Any] = {
        "id": run_id,
        "contextId": thread_id,
        "status": status,
        "kind": "task",
    }
    if reply is not None:
        out["artifacts"] = [{
            "artifactId": f"{run_id}-reply",
            "parts": [{"kind": "text", "text": reply}],
        }]
    return out


def rpc_result(req_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def rpc_error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": code, "message": message}}
