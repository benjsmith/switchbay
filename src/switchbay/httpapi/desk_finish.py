"""Desk completion notices and the provider count.

Split out of switchbay.daemon so this concept has its own module.
The daemon re-exports every name; tests that monkeypatch
switchbay.daemon still apply, because patched helpers are read
back through _daemon_ns at call time.

Run: python -m switchbay serve --workspace PATH
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from aiohttp import web
from switchbay import llmgateway
from switchbay import protocol

from switchbay.httpapi._ns import _daemon_ns

def _keyed_provider_count() -> int:
    return sum(1 for p in llmgateway.list_providers() if p.get("has_key"))

async def _stream_parent_reply(
    app: web.Application, *, parent_run_id: str, thread_id: str, text: str,
) -> None:
    msg_id = protocol.new_message_id()
    await _daemon_ns._broadcast(app, protocol.text_message_start(parent_run_id, msg_id))
    await _daemon_ns._broadcast(app, protocol.text_message_content(parent_run_id, msg_id, text))
    await _daemon_ns._broadcast(app, protocol.text_message_end(parent_run_id, msg_id))

async def _chat_notice(
    app: web.Application, ws: web.WebSocketResponse | None, text: str,
    **kw: Any,
) -> None:
    msg = protocol.notice(text, **kw)
    if ws is not None:
        try:
            await ws.send_json(msg)
            return
        except Exception:  # noqa: BLE001
            pass
    await _daemon_ns._broadcast(app, msg)

def _desk_stopped_notice(task_kind: str | None) -> str:
    kind = str(task_kind or "")
    if kind == "curation":
        return (
            "Stopped — /curate desk is quiet. "
            "Dismiss with /curate dismiss."
        )
    if kind == "deck":
        return (
            "Stopped — Deck desk is quiet. "
            "Dismiss it from Desks."
        )
    if kind == "research":
        return (
            "Stopped — /research desk is quiet. "
            "Dismiss with /research dismiss."
        )
    slash = {"projects": "work", "code": "code"}.get(kind, "")
    if slash:
        return (
            f"Stopped — /{slash} desk is quiet. "
            f"Dismiss with /{slash} dismiss."
        )
    return "Stopped."

def _finish_desk(
    workspace: Path,
    task_kind: str | None,
    run_id: str | None,
    *,
    cancelled: bool,
) -> None:
    """Quiet this run's desk when the wave ends or is stopped.

    Dismiss is never implied here — only ``/work dismiss``,
    ``/code dismiss``, or the Desks button tear a chief down.
    Ignore overlapping seats.
    """
    from switchbay import kernel as sbk
    kind = str(task_kind or "")
    desk_id = {
        "curation": sbk.DESK_CURATE,
        "projects": sbk.DESK_PROJECTS,
        "code": sbk.DESK_CODE,
        "deck": sbk.DESK_DECK,
        "auto": sbk.DESK_AUTO,
        "research": sbk.DESK_RESEARCH,
    }.get(kind)
    if not desk_id:
        return
    try:
        sbk.quiet(
            workspace, desk_id, run_id=run_id, keep_run=bool(cancelled),
        )
    except Exception:  # noqa: BLE001
        pass
