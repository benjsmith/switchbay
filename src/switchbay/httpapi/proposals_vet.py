"""Proposal review and the report-tab opener.

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
import logging
import re
from aiohttp import web
from switchbay import llmgateway
from switchbay import proposals
from switchbay import protocol
from switchbay import tabstore

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

async def _review_page(app: web.Application, workspace: Path,
                       entry: dict[str, Any]) -> dict[str, Any] | None:
    """Run a strong reviewer over a proposed page. Returns the verdict
    dict, or None if no strong provider is available (fail-open: the
    proposal then just waits for the user)."""
    pid = _daemon_ns._strong_provider_for_autotune()
    if not pid:
        return None
    try:
        provider = llmgateway.get(pid)
    except llmgateway.ProviderError:
        return None
    req = llmgateway.ChatRequest(
        messages=[{"role": "user", "content":
                   f"Page kind: {entry.get('kind')} · op: {entry.get('op')}\n\n"
                   f"{entry.get('body') or ''}"}],
        model=_daemon_ns._effective_model(pid) or None,
        system=_daemon_ns._PROPOSAL_REVIEW_SYS, max_tokens=700, workspace=str(workspace),
        reasoning_effort=_daemon_ns._effort_for(
            pid, _daemon_ns._effective_model(pid), "ladder"),
    )
    text = ""
    try:
        async for ev in provider.chat_stream(req):
            if isinstance(ev, llmgateway.TextChunk):
                text += ev.text
    except Exception:  # noqa: BLE001
        log.exception("proposal review failed")
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
        return v if isinstance(v, dict) else None
    except json.JSONDecodeError:
        return None

async def _vet_proposal(app: web.Application, workspace: Path, pid: str,
                        thread_id: str | None, run_id: str | None) -> None:
    """Attach a reviewer card to a provisional page. Never auto-file or
    auto-revert — Reviews is a backlog the user drains when they want.
    Fail-soft throughout."""
    try:
        entry = await asyncio.to_thread(proposals.get, workspace, pid)
        if not entry:
            return
        verdict = await _review_page(app, workspace, entry)
        if verdict is not None:
            await asyncio.to_thread(proposals.update, workspace, pid, review=verdict)
            entry = {**entry, "review": verdict}
        title = entry.get("title") or entry.get("path")
        # Ensure the Reviews tab exists, but do not steal focus and do
        # not put a rail card or notice on the chat. Reviews hydrates
        # when the user switches there.
        await asyncio.to_thread(tabstore.add_report_tab, workspace)
        if _daemon_ns._is_focused_workspace(app, workspace):
            await _daemon_ns._broadcast(app, _daemon_ns._hello_payload(app))
            await _daemon_ns._broadcast(app, protocol.custom({
                "type": "page_proposal_queued", "id": pid,
                "title": title, "path": entry.get("path"),
                "workspace": str(workspace),
            }))
        rel = str(entry.get("path") or "")
        if entry.get("written") and rel:
            _daemon_ns._schedule_after_wiki_write(app, workspace, rel)
    except Exception:  # noqa: BLE001
        log.exception("vet_proposal failed for %s", pid)

async def _open_report_tab(app: web.Application, workspace: Path,
                           report_id: str, title: str) -> None:
    """Ensure the Report tab exists, tell every client the tab set
    changed (hello), then broadcast `open_report` so the tab focuses +
    loads this report. Fail-soft: a report that can't open still left
    the model's summary in the chat."""
    try:
        await asyncio.to_thread(tabstore.add_report_tab, workspace)
        if not _daemon_ns._is_focused_workspace(app, workspace):
            return
        await _daemon_ns._broadcast(app, _daemon_ns._hello_payload(app))
        await _daemon_ns._broadcast(app, protocol.custom({
            "type": "open_report",
            "report_id": report_id,
            "title": title,
            "workspace": str(workspace),
        }))
        await _daemon_ns._broadcast(app, protocol.notice(
            f"↗ Review ready — “{title}” opened in the Reviews tab.",
            kind="chat",
            workspace=str(workspace),
        ))
    except Exception:  # noqa: BLE001
        log.exception("open_report_tab failed for %s", report_id)
