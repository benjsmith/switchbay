"""Resume an interrupted orchestration.

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
import time
from aiohttp import web
from switchbay import conversations
from switchbay import llmgateway
from switchbay import protocol
from switchbay import workspaces
from switchbay.agents import fanout
from switchbay.agents import orchestration

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

def _task_kind_from_plan(plan: Any) -> str | None:
    if plan is None:
        return None
    dec = getattr(plan, "decision", None) or {}
    if isinstance(dec, dict) and dec.get("task_kind"):
        return str(dec["task_kind"])
    strat = str(getattr(plan, "strategy", "") or "")
    return {
        "ce_curate": "curation",
        "research": "research",
        "deck": "deck",
        "projects": "projects",
        "code": "code",
        "auto": "auto",
    }.get(strat)

def _finish_resume_desk(
    workspace: Path, plan: Any, orchestration_id: str, *, cancelled: bool,
) -> None:
    """Quiet this run's desk unless a newer overlapping seat owns it."""
    from switchbay import kernel as sbk
    kind = _task_kind_from_plan(plan)
    if not kind:
        try:
            for rec in sbk.list_standing(workspace):
                if rec.run_id == orchestration_id:
                    kind = {
                        sbk.DESK_CURATE: "curation",
                        sbk.DESK_PROJECTS: "projects",
                        sbk.DESK_CODE: "code",
                        sbk.DESK_DECK: "deck",
                        sbk.DESK_RESEARCH: "research",
                        sbk.DESK_AUTO: "auto",
                    }.get(rec.desk_id)
                    break
        except Exception:  # noqa: BLE001
            kind = None
    if not kind:
        return
    try:
        desk_id = {
            "curation": sbk.DESK_CURATE,
            "projects": sbk.DESK_PROJECTS,
            "code": sbk.DESK_CODE,
            "deck": sbk.DESK_DECK,
            "research": sbk.DESK_RESEARCH,
            "auto": sbk.DESK_AUTO,
        }.get(kind)
        rec = sbk.get(workspace, desk_id) if desk_id else None
        if rec is not None and rec.run_id and rec.run_id != orchestration_id:
            return
    except Exception:  # noqa: BLE001
        pass
    _daemon_ns._finish_desk(workspace, kind, orchestration_id, cancelled=cancelled)

async def _resume_orchestration(
    app: web.Application, orchestration_id: str,
    *,
    workspace: Path | None = None,
) -> None:
    """Continue an interrupted DAG without re-running finished nodes."""
    focused: Path = app["workspace"]
    workspace = workspace or await asyncio.to_thread(
        orchestration.workspace_for_orchestration, orchestration_id, fallback=focused,
    ) or focused
    ck = await asyncio.to_thread(
        orchestration.load_checkpoint, workspace, orchestration_id,
    )
    if ck is None or ck.get("plan") is None:
        log.warning("resume %s: no checkpoint", orchestration_id)
        _finish_resume_desk(workspace, None, orchestration_id, cancelled=False)
        return
    status = ck["status"]
    phase = str(status.get("phase") or "")
    plan = ck["plan"]
    if phase != "quiet" and not orchestration.checkpoint_resumable(status):
        log.info("resume %s: not resumable (phase=%s)", orchestration_id, status.get("phase"))
        _finish_resume_desk(workspace, plan, orchestration_id, cancelled=False)
        return
    thread_id = str(status.get("thread_id") or app.get("thread_id") or "")
    if not thread_id:
        thread_id = await asyncio.to_thread(conversations.new_thread, workspace)
        app["thread_id"] = thread_id
        app["thread_kind"] = "structured-agent"
    pid = str(status.get("default_provider") or "") or _daemon_ns._resolve_default_provider()
    try:
        provider = llmgateway.get(pid)
    except llmgateway.ProviderError as e:
        await _daemon_ns._broadcast(app, protocol.notice(f"resume failed: {e}", kind="chat"))
        _finish_resume_desk(workspace, plan, orchestration_id, cancelled=False)
        return
    if not provider.has_key():
        await _daemon_ns._broadcast(app, protocol.notice(
            f"resume failed: no key for {getattr(provider, 'LABEL', pid)}",
            kind="chat",
        ))
        _finish_resume_desk(workspace, plan, orchestration_id, cancelled=False)
        return
    model = status.get("default_model") or _daemon_ns._effective_model(pid) or provider.PROVIDER.get("default_model")
    runs: dict[str, dict[str, Any]] = app.setdefault("runs", {})
    if orchestration_id in runs and runs[orchestration_id].get("status") in _daemon_ns._ORCH_BUSY_STATUSES:
        return
    runs[orchestration_id] = {
        "run_id": orchestration_id,
        "provider": pid,
        "model": model,
        "input_excerpt": f"[interrupted] {(plan.objective or '')[:100]}",
        "started_at": time.time(),
        "last_chunk_at": time.time(),
        "tool_count": 0,
        "status": "running",
        "task": asyncio.current_task(),
        "workspace": str(workspace),
        "workspace_name": workspace.name,
        "thread_id": thread_id,
        "orchestration_id": orchestration_id,
        "orchestration_strategy": plan.strategy,
        "resumed": True,
        "interrupted": True,
        "workers_running": 0,
        "fanout_n": sum(1 for n in plan.nodes if n.kind == "investigate") or 1,
    }
    _daemon_ns._remember_run_workspace(app, orchestration_id, workspace)
    _daemon_ns._remember_run_thread(app, orchestration_id, thread_id)
    await _daemon_ns._broadcast(app, protocol.run_started(
        thread_id, orchestration_id, pid, str(model), str(workspace),
    ))
    snap = await asyncio.to_thread(
        orchestration.load_snapshot, workspace, orchestration_id,
    )
    inflight = (snap or {}).get("in_flight") or []
    inflight_bits = []
    for rec in inflight[:6]:
        if not isinstance(rec, dict):
            continue
        inflight_bits.append(
            f"{rec.get('node_id')} {rec.get('provider') or ''} "
            f"{rec.get('tool_count') or 0} tools"
        )
    snap_line = (
        (" In flight: " + "; ".join(inflight_bits) + ".")
        if inflight_bits else ""
    )
    if phase == "quiet":
        notice = (
            f"Resuming the quiet desk `{orchestration_id}` — same DAG, "
            f"{len(status.get('completed') or [])} nodes already done."
            f"{snap_line}"
        )
    else:
        notice = (
            f"This Auto run was interrupted. Resuming `{orchestration_id}` "
            f"from snapshot — {len(status.get('completed') or [])} nodes already "
            f"done.{snap_line} Chief of staff keeps the original goal."
        )
    await _daemon_ns._broadcast(app, protocol.notice(
        notice,
        kind="chat",
        workspace=str(workspace),
        run_id=orchestration_id,
        thread_id=thread_id,
    ))
    try:
        result = await orchestration.execute(
            plan, app=app, workspace=workspace, thread_id=thread_id,
            parent_run_id=orchestration_id, default_provider=provider,
            default_model=model, resume=True,
        )
        merged = result.output or ""
        if merged:
            await _daemon_ns._stream_parent_reply(
                app, parent_run_id=orchestration_id, thread_id=thread_id, text=merged,
            )
            fanout.append_to_rail_log(
                workspace, thread_id,
                parent_run_id=orchestration_id, merged=merged,
            )
        await _daemon_ns._broadcast(app, protocol.run_finished(
            thread_id, orchestration_id,
            result.telemetry.get("input_tokens"),
            result.telemetry.get("output_tokens"),
            "end_turn",
        ))
    except asyncio.CancelledError:
        rec = runs.get(orchestration_id)
        if rec is not None:
            rec["status"] = "cancelled"
            rec["user_cancel"] = True
        await _daemon_ns._broadcast(app, protocol.run_error(
            orchestration_id, "cancelled", "resume cancelled", thread_id,
        ))
        raise
    except Exception as e:  # noqa: BLE001
        log.exception("resume %s failed", orchestration_id)
        await _daemon_ns._broadcast(app, protocol.run_error(
            orchestration_id, "server", str(e), thread_id,
        ))
    finally:
        rec = runs.get(orchestration_id) or {}
        cancelled = rec.get("status") == "cancelled" or bool(rec.get("user_cancel"))
        _finish_resume_desk(
            workspace, plan, orchestration_id, cancelled=cancelled,
        )
        runs.pop(orchestration_id, None)

async def _resume_interrupted_on_boot(app: web.Application) -> None:
    """Resume interrupted DAGs in every registered workspace, not just focused."""
    focused: Path = app["workspace"]
    try:
        data = await asyncio.to_thread(workspaces.load)
    except Exception:  # noqa: BLE001
        data = {"paths": [str(focused)], "active": str(focused)}
    paths = [str(p) for p in (data.get("paths") or [])]
    paths.insert(0, str(focused))
    seen: set[str] = set()
    n = 0
    for raw in paths:
        if raw in seen:
            continue
        seen.add(raw)
        ws = Path(raw)
        if not ws.is_dir():
            continue
        items = await asyncio.to_thread(orchestration.list_interrupted, ws)
        for rec in items:
            oid = str(rec.get("orchestration_id") or "")
            if not oid:
                continue
            log.info("auto-resuming interrupted orchestration %s in %s", oid, ws)
            await _resume_orchestration(app, oid, workspace=ws)
            n += 1
            if n >= 4:
                return
