"""Rail history purge preview and apply.

Split out of switchbay.daemon so this concept has its own module.
The daemon re-exports every name; tests that monkeypatch
switchbay.daemon still apply, because patched helpers are read
back through _daemon_ns at call time.

Run: python -m switchbay serve --workspace PATH
"""
from __future__ import annotations

from pathlib import Path
import asyncio
import json
import re
from aiohttp import web
from switchbay import conversations
from switchbay import llmgateway
from switchbay import modestore
from switchbay import protocol

from switchbay.httpapi._ns import _daemon_ns

async def handle_purge_preview(request: web.Request) -> web.Response:
    """Candidates for a hard purge — by date cutoff, and optionally
    narrowed by a topic instruction via a small LLM call. The LLM turn
    is maintenance machinery: it is deliberately NOT recorded in the
    rail log. Nothing is deleted here; the frontend shows the list
    with checkboxes and calls /api/history/purge with the survivors."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}
    workspace: Path = request.app["workspace"]
    before = body.get("before")
    before_ts = float(before) if isinstance(before, (int, float)) else None
    instructions = str(body.get("instructions") or "").strip()
    rows = await asyncio.to_thread(
        conversations.purge_candidates, workspace, before=before_ts,
    )
    # Never offer the focused thread or one with a live run.
    running = _daemon_ns._threads_running(request.app)
    focused = request.app.get("thread_id")
    rows = [
        r for r in rows
        if r["thread_id"] != focused and not running.get(r["thread_id"])
    ]
    if not instructions or not rows:
        for r in rows:
            r["selected"] = bool(instructions == "" and (before_ts is not None))
        return web.json_response({"threads": rows, "matched_by": "date" if before_ts else None})
    # Topic narrowing: one un-logged LLM call over compact thread lines.
    listing = "\n".join(
        f"{i + 1}. title={r['title'] or '(untitled)'!r} · kind={r['kind']} · "
        f"opens: {r['first_user'][:120]!r} · last: {r['last_summary'][:120]!r}"
        for i, r in enumerate(rows)
    )
    try:
        pid, model = modestore.resolve_for_difficulty(workspace, "trivial")
        if pid is None:
            pid = _daemon_ns._resolve_default_provider()
            model = _daemon_ns._effective_model(pid)
        provider = llmgateway.get(pid)
        if not provider.has_key():
            raise llmgateway.ProviderError("no key", code="auth")
        req = llmgateway.ChatRequest(
            messages=[{"role": "user", "content": (
                f"{_daemon_ns._PURGE_MATCH_PROMPT}\n\nPurge instructions: "
                f"{instructions}\n\nThreads:\n{listing}"
            )}],
            model=model or provider.PROVIDER.get("default_model"),
            max_tokens=200,
            reasoning_effort=_daemon_ns._effort_for(pid, model, "background"),
            temperature=0.0,
            workspace=str(workspace),
        )
        accumulated = ""
        async for ev in provider.chat_stream(req):
            if isinstance(ev, llmgateway.TextChunk):
                accumulated += ev.text
            if isinstance(ev, llmgateway.DoneChunk):
                break
        m = re.search(r"\[[\d,\s]*\]", accumulated)
        picked = set(json.loads(m.group(0))) if m else set()
    except Exception as e:  # noqa: BLE001 — surface, don't guess
        return web.json_response(
            {"error": f"topic matching failed: {e}"}, status=502,
        )
    for i, r in enumerate(rows):
        r["selected"] = (i + 1) in picked
    return web.json_response({"threads": rows, "matched_by": "topic"})

async def handle_purge(request: web.Request) -> web.Response:
    """HARD-delete the given threads + all their events (rows, FTS,
    embeddings). The explicit opt-out from keep-the-log; only the
    Settings purge panel calls this, after a preview."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    ids = [str(x) for x in (body.get("thread_ids") or []) if str(x).strip()]
    if not ids:
        return web.json_response({"error": "thread_ids required"}, status=400)
    app = request.app
    workspace: Path = app["workspace"]
    running = _daemon_ns._threads_running(app)
    blocked = [t for t in ids if running.get(t) or t == app.get("thread_id")]
    if blocked:
        return web.json_response({
            "error": "refusing to purge the focused thread or one with a "
                     "live run", "blocked": blocked,
        }, status=409)
    for tid in ids:
        await _daemon_ns._kill_thread_pty(app, tid)
        (app.get("llm_sessions") or {}).pop(tid, None)
    counts = await asyncio.to_thread(conversations.purge_threads, workspace, ids)
    await _daemon_ns._broadcast(app, protocol.custom({
        "type": "threads.purged", "thread_ids": ids, **counts,
    }))
    return web.json_response({"ok": True, **counts})
