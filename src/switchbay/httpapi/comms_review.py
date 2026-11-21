"""Comms review queue routes.

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
from aiohttp import web
from switchbay import admin_policy
from switchbay import protocol
from switchbay import streams
from switchbay import tabstore
from switchbay import workspaces

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

async def handle_comms_review_list(request: web.Request) -> web.Response:
    from switchbay import comms_review
    resolved = _daemon_ns._workspace_from_request(request)
    if isinstance(resolved, web.Response):
        return resolved
    workspace = resolved
    items = await asyncio.to_thread(
        comms_review.list_items, workspace=str(workspace),
    )
    return web.json_response({
        "items": items,
        "pending": sum(1 for i in items if i.get("status") == "pending"),
        "workspace": str(workspace),
        "workspaces": [
            {"path": p, "name": Path(p).name}
            for p in (workspaces.load().get("paths") or [])
        ],
    })

async def handle_comms_review_open(request: web.Request) -> web.Response:
    resolved = _daemon_ns._workspace_from_request(request)
    if isinstance(resolved, web.Response):
        return resolved
    workspace = resolved
    await asyncio.to_thread(tabstore.add_comms_tab, workspace)
    await _daemon_ns._broadcast(request.app, _daemon_ns._hello_payload(request.app))
    await _daemon_ns._broadcast(request.app, protocol.custom({"type": "open_comms"}))
    return web.json_response({"ok": True})

async def _ingest_after_approve(
    app: web.Application,
    acct: dict[str, Any],
    key: str,
    workspace: str,
) -> dict[str, Any]:
    """Fetch + curate an already-approved source. Approval already stuck.

    Returns ingest_state / ingest_error for the HTTP body. Fail-closed
    adapters do not pretend content was pulled.
    """
    from switchbay import comms_review
    cap = str((comms_review.get_item(key) or {}).get("content_capability") or "ok")
    if cap == "fail_closed" or acct.get("provider") not in ("imap", "gmail", "msgraph"):
        msg = "This source can be listed, but message content cannot be retrieved."
        await asyncio.to_thread(
            comms_review.set_ingest_state, key, workspace,
            state="unsupported", error=msg,
        )
        return {"ingest_state": "unsupported", "ingest_error": msg}
    await asyncio.to_thread(
        comms_review.set_ingest_state, key, workspace,
        state="pending", error="",
    )
    fetched = await streams.fetch_approved_thread(acct, key, workspace)
    if not fetched.get("ok"):
        err = _daemon_ns._comms_user_ingest_error(str(fetched.get("error") or "retrieve"))
        await asyncio.to_thread(
            comms_review.set_ingest_state, key, workspace,
            state="error", error=err,
        )
        return {"ingest_state": "error", "ingest_error": err}
    if not fetched.get("events"):
        return {"ingest_state": "pending", "ingest_error": ""}
    curated = await _daemon_ns._run_stream_curation(app, acct)
    if curated.get("ok") and int(curated.get("curated") or 0) > 0:
        await asyncio.to_thread(
            comms_review.set_ingest_state, key, workspace,
            state="ingested", error="",
        )
        return {"ingest_state": "ingested", "ingest_error": ""}
    if curated.get("ok"):
        err = _daemon_ns._comms_user_ingest_error("curation produced no wiki commit")
        await asyncio.to_thread(
            comms_review.set_ingest_state, key, workspace,
            state="error", error=err,
        )
        return {"ingest_state": "error", "ingest_error": err}
    err = _daemon_ns._comms_user_ingest_error(str(curated.get("error") or ""))
    await asyncio.to_thread(
        comms_review.set_ingest_state, key, workspace,
        state="error", error=err,
    )
    return {"ingest_state": "error", "ingest_error": err}

async def handle_comms_review_act(request: web.Request) -> web.Response:
    from switchbay import comms_review
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    key = str(body.get("key") or "").strip()
    action = str(body.get("action") or body.get("decision") or "").strip().lower()
    if not key or action not in ("approve", "reject", "revoke"):
        return web.json_response({"error": "key and action required"}, status=400)
    resolved = _daemon_ns._workspace_from_request(request, body if isinstance(body, dict) else None)
    if isinstance(resolved, web.Response):
        return resolved
    ws = str(resolved)
    item = await asyncio.to_thread(comms_review.get_item, key)
    acct_id = str((item or {}).get("account_id") or "")
    acct = await asyncio.to_thread(streams.get_account, acct_id) if acct_id else None
    if acct is None:
        return web.json_response({"error": "account missing; will not use active workspace"}, status=400)
    allowed = streams.allowed_workspaces(acct)
    if action == "approve":
        if not str(body.get("workspace") or "").strip():
            return web.json_response({"error": "workspace is required"}, status=400)
        ws = str(body.get("workspace") or "").strip()
        out = await asyncio.to_thread(
            comms_review.approve, key, ws, allowed=allowed,
        )
        if out.get("ok"):
            ingest = await _ingest_after_approve(
                request.app, acct, key, ws,
            )
            out.update(ingest)
            item = await asyncio.to_thread(
                comms_review.get_item, key, ws,
            )
            if item:
                out["item"] = item
    elif action == "reject":
        out = await asyncio.to_thread(comms_review.reject, key)
    else:
        out = await asyncio.to_thread(comms_review.revoke, key, reason="user")
    if not out.get("ok"):
        return web.json_response(out, status=400)
    await asyncio.to_thread(tabstore.add_comms_tab, resolved)
    await _daemon_ns._broadcast(request.app, protocol.custom({
        "type": "comms.review", "key": key, "action": action,
    }))
    return web.json_response(out)

async def handle_comms_review_close(request: web.Request) -> web.Response:
    resolved = _daemon_ns._workspace_from_request(request)
    if isinstance(resolved, web.Response):
        return resolved
    workspace = resolved
    removed = await asyncio.to_thread(tabstore.remove_comms_tab, workspace)
    if removed:
        await _daemon_ns._broadcast(request.app, _daemon_ns._hello_payload(request.app))
        await _daemon_ns._broadcast(request.app, protocol.nav("graph", {}, "Graph"))
    return web.json_response({"ok": True, "removed": removed})

async def _stream_poll_loop(app: web.Application) -> None:
    """Background: poll every connected account on an interval;
    auto-curate the ones that opted in. Every failure is contained —
    a dead provider or revoked token must never take the loop down."""
    while True:
        try:
            await asyncio.sleep(_daemon_ns._STREAM_POLL_INTERVAL)
            if not admin_policy.feature_enabled("comms_streams"):
                continue
            for acct in await asyncio.to_thread(streams.list_accounts):
                if streams.account_status(acct) != "connected":
                    continue
                try:
                    await streams.poll_account(acct)
                    # poll_account discovers metadata and ingests already-
                    # approved threads. auto_curate is cadence for the
                    # curator pass only — it never approves sources.
                    if acct.get("auto_curate"):
                        await _daemon_ns._run_stream_curation(app, acct)
                except Exception:  # noqa: BLE001
                    log.exception("stream poll failed: %s", acct.get("label"))
        except asyncio.CancelledError:
            return
        except Exception:  # noqa: BLE001
            log.exception("stream poll loop iteration failed")
