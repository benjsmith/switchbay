"""Agent-to-agent card and message routes.

Split out of switchbay.daemon so this concept has its own module.
The daemon re-exports every name; tests that monkeypatch
switchbay.daemon still apply, because patched helpers are read
back through _daemon_ns at call time.

Run: python -m switchbay serve --workspace PATH
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import asyncio
import json
import os
import uuid
from aiohttp import web
from switchbay import a2a
from switchbay import conversations
from switchbay import workspaces

from switchbay.httpapi._ns import _daemon_ns

def _a2a_resolve_workspace(app: web.Application, ref: str | None) -> Path | None:
    """metadata.switchbay.workspace → a REGISTERED workspace path.
    Accepts a registry path verbatim or a workspace basename; anything
    unregistered resolves to None (refused — the registry is the trust
    list, same rule the workspace switcher enforces)."""
    if not ref:
        return app["workspace"]
    reg = workspaces.load()
    for p in reg.get("paths") or []:
        if ref == p or ref == Path(p).name:
            return Path(p)
    current: Path = app["workspace"]
    if ref in (str(current), current.name):
        return current
    return None

async def _a2a_run_reply(app: web.Application, workspace: Path, run_id: str) -> str:
    """The run's assistant prose, joined. Retries briefly: assistant
    events go through the rail-log write-serializer (fire-and-forget
    queue), so a read immediately after run-finish can race the last
    write — found live on the first A2A e2e (completed task, empty
    artifact)."""
    for _ in range(10):
        events = await asyncio.to_thread(
            conversations.list_events, workspace, run_id=run_id, limit=200,
        )
        reply = "\n\n".join(
            e["summary"] for e in events if e.get("kind") == "assistant"
        ).strip()
        if reply:
            return reply
        await asyncio.sleep(0.25)
    return ""

async def handle_agent_card(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    try:
        port = int(os.environ.get("CSWY_DAEMON_PORT") or "8765")
    except ValueError:
        port = 8765
    return web.json_response(a2a.agent_card(
        workspace_name=workspace.name,
        workspace_path=str(workspace),
        port=port,
        version="0.0.1",
        provider_default=_daemon_ns._resolve_default_provider(),
    ))

async def handle_a2a(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response(a2a.rpc_error(None, a2a.ERR_PARSE, "invalid json"))
    req_id = body.get("id")
    if body.get("jsonrpc") != "2.0" or not isinstance(body.get("method"), str):
        return web.json_response(a2a.rpc_error(
            req_id, a2a.ERR_INVALID_REQUEST, "jsonrpc 2.0 request required",
        ))
    method = body["method"]
    params = body.get("params") or {}
    if method == "message/send":
        return await _a2a_message_send(request.app, req_id, params)
    if method == "tasks/get":
        return await _a2a_tasks_get(request.app, req_id, params)
    return web.json_response(a2a.rpc_error(
        req_id, a2a.ERR_METHOD_NOT_FOUND, f"unsupported method: {method}",
    ))

async def _a2a_message_send(
    app: web.Application, req_id: Any, params: dict[str, Any],
) -> web.Response:
    message = params.get("message") or {}
    text = a2a.text_of_message(message)
    if not text:
        return web.json_response(a2a.rpc_error(
            req_id, a2a.ERR_INVALID_PARAMS, "message needs a text part",
        ))
    meta = ((params.get("metadata") or {}).get("switchbay")) or {}
    target_ws = _a2a_resolve_workspace(app, meta.get("workspace"))
    if target_ws is None:
        return web.json_response(a2a.rpc_error(
            req_id, a2a.ERR_INVALID_PARAMS,
            "workspace not in the registry (register it in the switcher first)",
        ))
    tid = str(meta.get("thread_id") or message.get("contextId") or "").strip()
    if tid:
        kind = await asyncio.to_thread(conversations.thread_kind, target_ws, tid)
        if kind is None:
            return web.json_response(a2a.rpc_error(
                req_id, a2a.ERR_INVALID_PARAMS, "no such thread in that workspace",
            ))
        if kind == "interactive-pty":
            return web.json_response(a2a.rpc_error(
                req_id, a2a.ERR_INVALID_PARAMS,
                "target is a shell thread — agents can't type into terminals",
            ))
        # Reject-busy up front so the caller gets a typed error instead
        # of a broadcast notice (the in-dispatch guard would fire later
        # anyway; this is the polite path).
        busy = [
            r for r in (app.get("runs") or {}).values()
            if r.get("thread_id") == tid
            and r.get("status") in _daemon_ns._ORCH_BUSY_STATUSES
        ]
        if busy:
            return web.json_response(a2a.rpc_error(
                req_id, a2a.ERR_BUSY,
                f"thread busy — {busy[0].get('run_id')} is still streaming",
            ))
    else:
        tid = await asyncio.to_thread(conversations.new_thread, target_ws)
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    task = asyncio.get_running_loop().create_task(_daemon_ns._dispatch_chat(
        app, None, text,
        input_excerpt=f"a2a: {text}"[:120],
        run_id=run_id,
        workspace_override=target_ws,
        thread_id_override=tid,
    ))
    task.add_done_callback(_daemon_ns._make_dispatch_error_surface(app, run_id))
    try:
        rid = await asyncio.wait_for(asyncio.shield(task), _daemon_ns._A2A_SEND_TIMEOUT)
    except asyncio.TimeoutError:
        # Long run: hand back a working task; the run continues and
        # tasks/get (or the thread transcript) has the eventual reply.
        return web.json_response(a2a.rpc_result(req_id, a2a.task(
            run_id=run_id, thread_id=tid, state="working",
            message="run still in flight — poll tasks/get",
        )))
    if rid is None:
        # Early bail (no key / guard) or a mid-run provider error. Any
        # persisted partial reply still carries OUR run_id — surface it.
        partial = await _a2a_run_reply(app, target_ws, run_id)
        if partial:
            return web.json_response(a2a.rpc_result(req_id, a2a.task(
                run_id=run_id, thread_id=tid, state="failed", reply=partial,
                message="run errored mid-stream; partial reply attached",
            )))
        return web.json_response(a2a.rpc_error(
            req_id, a2a.ERR_INTERNAL,
            "dispatch declined (no provider key, busy thread, or bad target)",
        ))
    reply = await _a2a_run_reply(app, target_ws, rid)
    return web.json_response(a2a.rpc_result(req_id, a2a.task(
        run_id=rid, thread_id=tid, state="completed", reply=reply,
    )))

async def _a2a_tasks_get(
    app: web.Application, req_id: Any, params: dict[str, Any],
) -> web.Response:
    run_id = str(params.get("id") or "").strip()
    if not run_id:
        return web.json_response(a2a.rpc_error(
            req_id, a2a.ERR_INVALID_PARAMS, "id required",
        ))
    rec = (app.get("runs") or {}).get(run_id)
    if rec is not None and rec.get("status") in _daemon_ns._ORCH_BUSY_STATUSES:
        return web.json_response(a2a.rpc_result(req_id, a2a.task(
            run_id=run_id,
            thread_id=str(rec.get("thread_id") or ""),
            state="working",
        )))
    ws_path = _daemon_ns._run_workspace(app, run_id)
    if ws_path is None:
        return web.json_response(a2a.rpc_error(
            req_id, a2a.ERR_TASK_NOT_FOUND, "unknown task (run too old?)",
        ))
    reply = await _a2a_run_reply(app, ws_path, run_id)
    tid = (app.get("run_thread") or {}).get(run_id, "")
    return web.json_response(a2a.rpc_result(req_id, a2a.task(
        run_id=run_id, thread_id=tid, state="completed", reply=reply,
    )))
