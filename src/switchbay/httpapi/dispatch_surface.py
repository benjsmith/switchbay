"""Verb dispatch and the shared dispatch error surface.

Split out of switchbay.daemon so this concept has its own module.
The daemon re-exports every name; tests that monkeypatch
switchbay.daemon still apply, because patched helpers are read
back through _daemon_ns at call time.

Run: python -m switchbay serve --workspace PATH
"""
from __future__ import annotations

from pathlib import Path
import asyncio
import logging
from aiohttp import web
from switchbay import plots
from switchbay import protocol
from switchbay import sketches
from switchbay import verbs

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

def _make_dispatch_error_surface(
    app: web.Application,
    target: web.WebSocketResponse | str | None,
):
    """Return a `add_done_callback` that converts unhandled
    exceptions in dispatch tasks into rail-visible notices.

    `target` is a WebSocket (that one client), a run_id string, or
    None for a headless launch — both of the last two broadcast.

    Without this, an exception that escapes _dispatch_chat or
    _dispatch_fanout BEFORE their internal try/except blocks
    (e.g. a synchronous raise during setup, or an exception from
    a notice/broadcast call inside the except handler itself) ends
    up as a swallowed asyncio task error — the user sees the input
    cursor blink and nothing else. Surfacing each task's terminal
    state to the rail closes that gap."""
    def _on_done(task: asyncio.Task) -> None:
        try:
            exc = task.exception()
        except (asyncio.CancelledError, asyncio.InvalidStateError):
            return
        if exc is None:
            return
        log.exception("dispatch task crashed", exc_info=exc)
        notice = protocol.notice(
            f"dispatch crashed: {type(exc).__name__}: {exc}",
            kind="chat",
        )
        async def _send():
            try:
                if target is None or isinstance(target, str):
                    await _daemon_ns._broadcast(app, notice)
                else:
                    await target.send_json(notice)
            except Exception:  # noqa: BLE001
                pass
        try:
            asyncio.create_task(_send())
        except RuntimeError:
            pass
    return _on_done

async def _dispatch_verb(
    app: web.Application, ws: web.WebSocketResponse, verb: verbs.Verb, query: str,
) -> None:
    """Run a verb against the workspace and route the result to the
    right tab (single match) or list candidates (multiple/zero).

    Same registry will power agent tool calls when the MCP bridge
    lands, so verbs stay deterministic and side-effect-free here:
    they only return Match candidates; the dispatcher decides what
    to do with them."""
    workspace: Path = app["workspace"]
    pages = (app.get("graph_data") or {}).get("pages")
    files = _daemon_ns._walk_tree(workspace)
    ctx = verbs.VerbContext(
        workspace=workspace,
        query=query.strip(),
        pages=pages if isinstance(pages, dict) else None,
        files=files,
        plots=plots.list_plots(workspace),
        sketches=sketches.list_sketches(workspace),
    )
    if not ctx.query:
        await ws.send_json(protocol.notice(
            f"/{verb.name} needs a query, e.g. /{verb.name} sales pipeline",
            kind="slash",
        ))
        return
    result = verb.handler(ctx)
    summary_text = f"/{verb.name} {ctx.query}"
    if not result.matches:
        _daemon_ns._log_event(
            app, "slash", f"{summary_text} → no match",
            source="rail", actor="user",
            payload={"verb": verb.name, "query": ctx.query, "matches": []},
        )
        await ws.send_json(protocol.notice(
            f"no matches for /{verb.name} {ctx.query!r}",
            kind="slash",
        ))
        return

    best = result.matches[0]
    runner_up = result.matches[1] if len(result.matches) > 1 else None
    # Auto-pick when there's a clear winner. "Clear" = no other candidate
    # within 0.1 of the top score AND best score is at least 0.45.
    decisive = (
        best.score >= 0.45
        and (runner_up is None or best.score - runner_up.score >= 0.1)
    )
    if decisive:
        _daemon_ns._log_event(
            app, "nav", f"{summary_text} → {best.label}",
            source="rail", actor="user",
            payload={
                "verb": verb.name, "query": ctx.query,
                "tab_kind": best.tab_kind, "match": _daemon_ns._match_to_dict(best),
            },
        )
        await _daemon_ns._broadcast(app, protocol.nav(best.tab_kind, best.payload, best.label))
        return

    # Disambiguation: tell the user, don't navigate.
    top = result.matches[:5]
    lines = [f"matches for /{verb.name} {ctx.query!r}:"]
    for i, m in enumerate(top, 1):
        lines.append(f"  {i}. {m.label}  ·  {m.detail}")
    lines.append("be more specific to disambiguate.")
    _daemon_ns._log_event(
        app, "slash", f"{summary_text} → {len(top)} matches",
        source="rail", actor="user",
        payload={
            "verb": verb.name, "query": ctx.query,
            "matches": [_daemon_ns._match_to_dict(m) for m in top],
        },
    )
    await ws.send_json(protocol.notice("\n".join(lines), kind="slash"))
