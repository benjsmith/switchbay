"""Workspace share preview and publish routes.

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
import logging
import re
from aiohttp import web
from switchbay import protocol
from switchbay import share

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

async def handle_share_status(request: web.Request) -> web.Response:
    """Publish-dialog state: gh presence/auth, whether the active
    workspace already has an origin remote, and the last publish
    task's outcome (publishes run in the background)."""
    workspace: Path = request.app["workspace"]
    st = await share.status(workspace)
    st["workspace_name"] = workspace.name
    last = request.app.get("share_last")
    if isinstance(last, dict) and last.get("workspace") == str(workspace):
        st["last"] = {k: v for k, v in last.items() if k != "workspace"}
    return web.json_response(st)

async def handle_share_preview(request: web.Request) -> web.Response:
    """What would leave the machine on publish: file count, the top-level
    dirs, the largest files, and any secret-shaped strings found in text
    files. Lets the dialog warn before a `git add -A` ships more than the
    user expects (esp. to a public repo). Off-thread — it walks + reads
    the tree."""
    workspace: Path = request.app["workspace"]
    include_vault = request.query.get("include_vault", "1") not in ("0", "false", "no")
    result = await asyncio.to_thread(
        share.preview, workspace, include_vault=include_vault,
    )
    return web.json_response(result)

async def handle_share_publish(request: web.Request) -> web.Response:
    """Kick a background publish of the active workspace (D3 ruling:
    knowledge + vault with vault opt-out; .workbench + curator
    internals always excluded). Returns immediately; the dialog polls
    /api/share/status for the outcome, and a rail notice lands on
    completion either way."""
    blocked = _daemon_ns._policy_block("github_share")
    if blocked:
        return blocked
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    workspace: Path = request.app["workspace"]
    name = re.sub(
        r"[^A-Za-z0-9_.-]+", "-",
        str(body.get("name") or workspace.name).strip(),
    ).strip("-") or workspace.name
    private = bool(body.get("private", True))
    include_vault = bool(body.get("include_vault", True))
    last = request.app.get("share_last")
    if isinstance(last, dict) and last.get("state") == "running":
        return web.json_response({"error": "a publish is already running"}, status=409)
    request.app["share_last"] = {
        "workspace": str(workspace), "state": "running",
        "name": name, "url": None, "error": None,
    }

    async def _worker() -> None:
        rec = request.app["share_last"]
        try:
            url = await share.publish(
                workspace, name=name, private=private,
                include_vault=include_vault,
            )
            rec.update(state="done", url=url)
            _daemon_ns._log_event(
                request.app, "exec", f"workspace published: {url}",
                source="share", actor="user",
                payload={"url": url, "private": private, "vault": include_vault},
            )
            await _daemon_ns._broadcast(request.app, protocol.notice(
                f"workspace published → {url}"
                + (" (private)" if private else " (public)"),
                kind="chat",
            ))
        except share.ShareError as e:
            rec.update(state="error", error=str(e))
            await _daemon_ns._broadcast(request.app, protocol.notice(
                f"publish failed: {e}", kind="chat",
            ))
        except Exception as e:  # noqa: BLE001
            log.exception("publish crashed")
            rec.update(state="error", error=str(e))

    asyncio.create_task(_worker())
    return web.json_response({"ok": True, "started": True, "name": name})
