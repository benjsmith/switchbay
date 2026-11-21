"""Desk list/start/dismiss and orchestration org routes.

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
from switchbay import orchestrator_fs
from switchbay import workspaces
from switchbay.agents import orchestration
from switchbay.agents import orchestration_policy

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

async def handle_orchestration_org(request: web.Request) -> web.Response:
    """Standing desk roster for Agent Space when no run is live."""
    workspace = _daemon_ns._workspace_from_request(request)
    if isinstance(workspace, web.Response):
        return workspace
    org = await asyncio.to_thread(orchestrator_fs.load_org, workspace)
    return web.json_response({
        "org": org,
        "workspace": str(workspace),
        "workspace_name": workspace.name,
    })

def _desk_has_live_work(
    app: web.Application, workspace: Path, rec: Any,
) -> bool:
    """True when a real run or tracked launch is still going."""
    runs: dict[str, dict[str, Any]] = app.get("runs") or {}
    rid = getattr(rec, "run_id", None)
    if rid:
        r = runs.get(str(rid))
        if r and r.get("status") in _daemon_ns._ORCH_BUSY_STATUSES:
            ws = str(r.get("workspace") or "")
            if not ws or ws == str(workspace):
                return True
    launches: dict[tuple[str, str], asyncio.Task] = app.get("desk_launches") or {}
    task = launches.get(_daemon_ns._desk_launch_key(workspace, str(rec.desk_id)))
    return bool(task is not None and not task.done())

def _reconcile_desk_state(
    app: web.Application, workspace: Path, rec: Any,
) -> str:
    """Derive working/quiet from live runs and launches only.

    Checkpoints prove resumability, not liveness. A leftover
    running/interrupted/waiting_limits/planning snapshot without a live
    run or tracked launch is quiet, keeping the resumable ID.
    """
    from switchbay import kernel as sbk
    if rec.state == sbk.STATE_DISMISSED:
        return rec.state
    if _desk_has_live_work(app, workspace, rec):
        if rec.state != sbk.STATE_WORKING:
            try:
                sbk.set_working(workspace, rec.desk_id, run_id=rec.run_id)
            except Exception:  # noqa: BLE001
                pass
        return sbk.STATE_WORKING
    if rec.state != sbk.STATE_WORKING:
        return rec.state
    phase = ""
    if rec.run_id:
        try:
            ck = orchestration.load_checkpoint(workspace, rec.run_id)
        except Exception:  # noqa: BLE001
            ck = None
        st = (ck or {}).get("status") if isinstance(ck, dict) else None
        phase = str((st or {}).get("phase") or "")
    try:
        sbk.quiet(
            workspace, rec.desk_id, run_id=rec.run_id,
            keep_run=bool(rec.run_id and phase not in ("completed", "")),
        )
    except Exception:  # noqa: BLE001
        pass
    return sbk.STATE_QUIET

async def handle_desks_list(request: web.Request) -> web.Response:
    """Standing (working + quiet) desks for the dashboard Desks list."""
    from switchbay import kernel as sbk
    workspace = _daemon_ns._workspace_from_request(request)
    org = await asyncio.to_thread(orchestrator_fs.load_org, workspace)
    recs = await asyncio.to_thread(sbk.list_standing, workspace)
    oid = (org or {}).get("orchestration_id")
    desks: list[dict[str, Any]] = []
    for rec in recs:
        info = sbk.DESK_INFO.get(rec.desk_id) or {}
        objective = rec.objective
        if not objective and org and rec.run_id and rec.run_id == oid:
            objective = org.get("objective")
        state = _reconcile_desk_state(request.app, workspace, rec)
        row = rec.to_dict()
        row["state"] = state
        desks.append({
            **row,
            "label": info.get("label") or rec.desk_id,
            "slash": info.get("slash"),
            "objective": objective,
        })
    return web.json_response({
        "desks": desks,
        "workspace": str(workspace),
        "workspace_name": workspace.name,
    })

async def handle_desks_start(request: web.Request) -> web.Response:
    spec = _daemon_ns._desk_spec_from_id(request.match_info.get("desk_id", ""))
    if spec is None:
        return web.json_response({"error": "unknown desk"}, status=404)
    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    workspace = _daemon_ns._workspace_from_request(request)
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        resumed = _daemon_ns._maybe_resume_quiet_desk(request.app, spec, workspace)
        if resumed:
            slash = spec.get("slash") or spec["desk_id"]
            return web.json_response({
                "ok": True, "started": True, "resumed": True, "slash": slash,
            })
    if not prompt and spec.get("desk_id") == "auto":
        org = await asyncio.to_thread(orchestrator_fs.load_org, workspace)
        prompt = str((org or {}).get("objective") or "")
    _daemon_ns._launch_desk(
        request.app, spec, prompt=prompt, workspace=workspace,
    )
    slash = spec.get("slash") or spec["desk_id"]
    return web.json_response({"ok": True, "started": True, "slash": slash})

async def handle_desks_dismiss(request: web.Request) -> web.Response:
    spec = _daemon_ns._desk_spec_from_id(request.match_info.get("desk_id", ""))
    if spec is None:
        return web.json_response({"error": "unknown desk"}, status=404)
    workspace = _daemon_ns._workspace_from_request(request)
    n = _daemon_ns._dismiss_desk(request.app, spec, workspace)
    return web.json_response({"ok": True, "cancelled": n})

async def handle_orchestration_dismiss(request: web.Request) -> web.Response:
    """Drop an interrupted checkpoint so it leaves the Desks list."""
    oid = request.match_info.get("orchestration_id", "").strip()
    if not oid:
        return web.json_response({"error": "orchestration_id required"}, status=400)
    fallback: Path = request.app["workspace"]
    ws = await asyncio.to_thread(
        orchestration.workspace_for_orchestration, oid, fallback=fallback,
    )
    if ws is None:
        ws = fallback
    cp = await asyncio.to_thread(orchestration.load_checkpoint, ws, oid)
    if cp and cp.get("status"):
        st = cp["status"]
        await asyncio.to_thread(
            orchestration.persist_checkpoint,
            ws, oid,
            phase="cancelled",
            completed=st.get("completed") or [],
            failed=st.get("failed") or [],
            expansions=int(st.get("expansions") or 0),
            results=cp.get("results") or {},
            elapsed_s=float(st.get("elapsed_s") or 0),
            thread_id=st.get("thread_id"),
        )
    org = await asyncio.to_thread(orchestrator_fs.load_org, ws)
    if org and org.get("orchestration_id") == oid:
        await asyncio.to_thread(orchestrator_fs.clear_org, ws)
    _daemon_ns._cancel_run_ids(request.app, {oid})
    from switchbay import kernel as sbk
    try:
        sbk.dismiss_run(ws, oid)
    except Exception:  # noqa: BLE001
        log.exception("desk dismiss on orchestration dismiss failed")
    return web.json_response({"ok": True})

async def handle_orchestration_policy_reset(request: web.Request) -> web.Response:
    """Drop learned bandit state for this workspace; priors remain."""
    workspace: Path = request.app["workspace"]
    orchestration_policy.reset_state(workspace)
    return web.json_response({"ok": True, **orchestration_policy.inspect_state(workspace)})

async def handle_orchestration_interrupted(request: web.Request) -> web.Response:
    """Checkpoints that can be resumed after a crash or daemon restart.

    Live parent Runs (including overnight waits) stay in ``/api/runs/active``
    and are omitted here so the dashboard does not list them twice.
    """
    focused: Path = request.app["workspace"]
    try:
        data = workspaces.load()
        paths = [str(p) for p in (data.get("paths") or [])]
    except Exception:  # noqa: BLE001
        paths = []
    paths.insert(0, str(focused))
    items: list[dict[str, Any]] = []
    seen_ws: set[str] = set()
    for raw in paths:
        if raw in seen_ws:
            continue
        seen_ws.add(raw)
        ws = Path(raw)
        if not ws.is_dir():
            continue
        chunk = await asyncio.to_thread(orchestration.list_interrupted, ws)
        for rec in chunk:
            rec = dict(rec)
            rec["workspace"] = str(ws)
            rec["workspace_name"] = ws.name
            items.append(rec)
    items.sort(key=lambda r: float(r.get("updated_at") or 0), reverse=True)
    runs: dict[str, dict[str, Any]] = request.app.get("runs") or {}
    live = {
        rid for rid, rec in runs.items()
        if rec.get("status") in _daemon_ns._ORCH_BUSY_STATUSES
    }
    items = [i for i in items if i.get("orchestration_id") not in live]
    return web.json_response({"runs": items})

async def handle_orchestration_resume(request: web.Request) -> web.Response:
    oid = request.match_info.get("orchestration_id", "").strip()
    if not oid:
        return web.json_response({"error": "orchestration_id required"}, status=400)
    t = asyncio.create_task(_daemon_ns._resume_orchestration(request.app, oid))
    t.add_done_callback(_daemon_ns._make_dispatch_error_surface(request.app, oid))
    return web.json_response({"ok": True, "orchestration_id": oid, "resuming": True})
