"""Decision drafts and the decisions heartbeat.

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
import logging
from aiohttp import web
from switchbay import capture
from switchbay import llmgateway
from switchbay import modestore
from switchbay import protocol

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

async def _draft_decision_proposal(
    app: web.Application, ws: Path, entry: dict[str, Any],
) -> bool:
    """One decision → one drafted charter amendment. Leaves the entry
    `pending` on any failure (retried next beat); flips it to
    `proposed` + broadcasts the review card on success."""
    dec_id = str(entry.get("id"))
    rel = capture.charter_rel_for(entry.get("project"))
    charter_text = await asyncio.to_thread(capture.read_charter, ws, rel)
    profile = await asyncio.to_thread(_daemon_ns._curator_profile, ws)
    pid, model = modestore.resolve_for_difficulty(ws, "normal")
    if pid is None:
        pid = _daemon_ns._resolve_default_provider()
        model = _daemon_ns._effective_model(pid)
    provider = llmgateway.get(pid)
    if not provider.has_key():
        return False
    prompt = capture.promotion_prompt(
        entry, charter_text, rel, scope=ws.name, profile=profile,
    )
    req = llmgateway.ChatRequest(
        messages=[{"role": "user", "content": prompt}],
        model=model or provider.PROVIDER.get("default_model"),
        max_tokens=2500,
        reasoning_effort=_daemon_ns._effort_for(pid, model, "background"),
        temperature=0.0,
        workspace=str(ws),
        # One-shot content draft: force reasoning OFF on local models so
        # the token budget produces a body, not an all-reasoning empty
        # draft (quality-trial finding; non-local providers ignore).
        reasoning=False,
    )
    accumulated = ""
    async for ev in provider.chat_stream(req):
        if isinstance(ev, llmgateway.TextChunk):
            accumulated += ev.text
        if isinstance(ev, llmgateway.DoneChunk):
            break
    # Strip a code fence if the model wrapped the page anyway.
    text = accumulated.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0].strip()
    if not capture.looks_like_page(text):
        log.warning("decision %s: drafted proposal failed the page gate", dec_id)
        return False
    updated = await asyncio.to_thread(
        capture.update_decision, ws, dec_id,
        status="proposed", proposal=text, charter_path=rel,
    )
    if updated is None:
        return False
    await _daemon_ns._broadcast(app, protocol.decision_review(updated))
    _daemon_ns._log_event(
        app, "capture", f"charter amendment drafted for decision → {rel}",
        source="heartbeat", actor="system",
        payload={"id": dec_id, "charter_path": rel},
    )
    return True

async def _decisions_heartbeat_loop(app: web.Application) -> None:
    """Background: promote pending /decision captures into drafted
    charter amendments. Sleep-first (the first beat lands one interval
    after boot); every failure contained."""
    while True:
        try:
            await asyncio.sleep(_daemon_ns._DECISIONS_HEARTBEAT_INTERVAL)
            ws: Path = app["workspace"]
            entries = await asyncio.to_thread(capture.list_decisions, ws)
            pending = [e for e in entries if e.get("status") == "pending"]
            for entry in pending[:_daemon_ns._DECISIONS_DRAFTS_PER_BEAT]:
                try:
                    await _draft_decision_proposal(app, ws, entry)
                except Exception:  # noqa: BLE001
                    log.exception(
                        "decision draft failed: %s", entry.get("id"),
                    )
        except asyncio.CancelledError:
            return
        except Exception:  # noqa: BLE001
            log.exception("decisions heartbeat iteration failed")
