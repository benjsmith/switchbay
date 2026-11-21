"""Scheduled runs and the schedule ticker.

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
from switchbay import schedules
from switchbay import workspaces

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

def _schedule_registry_paths(app: web.Application) -> list[str]:
    data = workspaces.load()
    paths: list[str] = []
    seen: set[str] = set()
    for raw in list(data.get("paths") or []):
        s = str(raw)
        if s and s not in seen:
            seen.add(s)
            paths.append(s)
    for extra in (data.get("active"), app.get("workspace")):
        if extra is None:
            continue
        s = str(extra)
        if s and s not in seen:
            seen.add(s)
            paths.append(s)
    return paths

def _schedule_store_from_body(
    request: web.Request, body: dict[str, Any],
) -> tuple[schedules.Store | None, str | None]:
    """Return (store, error). store is None for global."""
    scope = str(body.get("scope") or "workspace").strip().lower()
    if scope == "global":
        return None, None
    raw = str(body.get("workspace") or "").strip()
    ws = Path(raw).expanduser() if raw else Path(request.app["workspace"])
    if not ws.is_absolute():
        ws = Path(request.app["workspace"])
    if not workspaces.is_within_home(ws) or not ws.is_dir():
        return None, "workspace is not a usable folder"
    return ws, None

async def handle_schedules_list(request: web.Request) -> web.Response:
    paths = await asyncio.to_thread(_schedule_registry_paths, request.app)
    items = await asyncio.to_thread(schedules.list_all, paths)
    ws_rows = [
        {"path": p, "name": Path(p).name}
        for p in paths
        if Path(p).is_dir()
    ]
    return web.json_response({"schedules": items, "workspaces": ws_rows})

async def handle_schedules_create(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    store, err = _schedule_store_from_body(request, body)
    if err:
        return web.json_response({"error": err}, status=400)
    title = str(body.get("title") or "Untitled").strip()
    prompt = str(body.get("prompt") or "")
    freq = str(body.get("frequency") or "daily")
    every = body.get("every_hours")
    pref = body.get("preference")
    try:
        pref_f = float(pref) if pref is not None else None
    except (TypeError, ValueError):
        pref_f = None
    item = await asyncio.to_thread(
        schedules.create, store,
        title=title, prompt=prompt, frequency=freq,
        every_hours=every, enabled=body.get("enabled", True),
        preference=pref_f,
    )
    if body.get("run_now"):
        asyncio.create_task(_fire_schedule(request.app, store, item))
    scope = "global" if store is None else "workspace"
    name = "all workspaces" if store is None else store.name
    return web.json_response({
        "ok": True,
        "schedule": schedules.annotate(
            item, scope=scope, workspace=store, name=name,
        ),
    })

async def handle_schedules_update(request: web.Request) -> web.Response:
    sid = request.match_info.get("sid", "").strip()
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    paths = await asyncio.to_thread(_schedule_registry_paths, request.app)
    located = await asyncio.to_thread(schedules.locate, sid, paths)
    if located is None:
        return web.json_response({"error": "unknown schedule"}, status=404)
    store, _cur = located
    want_scope = body.get("scope")
    if want_scope is not None:
        dest, err = _schedule_store_from_body(request, body)
        if err:
            return web.json_response({"error": err}, status=400)
        if dest != store:
            # Move the row between global and a workspace (or between workspaces).
            patch = {k: v for k, v in body.items() if k not in ("scope", "workspace")}
            merged = dict(_cur)
            merged.update(patch)
            await asyncio.to_thread(schedules.delete, store, sid)
            item = await asyncio.to_thread(
                schedules.create, dest,
                title=str(merged.get("title") or "Untitled"),
                prompt=str(merged.get("prompt") or ""),
                frequency=str(merged.get("frequency") or "daily"),
                every_hours=merged.get("every_hours"),
                enabled=merged.get("enabled", True),
                preference=merged.get("preference"),
            )
            # Preserve id so the UI row stays stable.
            data = await asyncio.to_thread(schedules.load, dest)
            for it in data.get("items") or []:
                if str(it.get("id") or "") == str(item.get("id") or ""):
                    it["id"] = sid
                    item = it
                    break
            await asyncio.to_thread(schedules.save, dest, data)
            store = dest
            item["id"] = sid
            scope = "global" if store is None else "workspace"
            name = "all workspaces" if store is None else store.name
            return web.json_response({
                "ok": True,
                "schedule": schedules.annotate(
                    item, scope=scope, workspace=store, name=name,
                ),
            })
    item = await asyncio.to_thread(schedules.update, store, sid, body)
    if item is None:
        return web.json_response({"error": "unknown schedule"}, status=404)
    scope = "global" if store is None else "workspace"
    name = "all workspaces" if store is None else store.name
    return web.json_response({
        "ok": True,
        "schedule": schedules.annotate(
            item, scope=scope, workspace=store, name=name,
        ),
    })

async def handle_schedules_delete(request: web.Request) -> web.Response:
    sid = request.match_info.get("sid", "").strip()
    paths = await asyncio.to_thread(_schedule_registry_paths, request.app)
    located = await asyncio.to_thread(schedules.locate, sid, paths)
    if located is None:
        return web.json_response({"error": "unknown schedule"}, status=404)
    store, _cur = located
    ok = await asyncio.to_thread(schedules.delete, store, sid)
    if not ok:
        return web.json_response({"error": "unknown schedule"}, status=404)
    return web.json_response({"ok": True})

async def handle_schedules_run(request: web.Request) -> web.Response:
    sid = request.match_info.get("sid", "").strip()
    paths = await asyncio.to_thread(_schedule_registry_paths, request.app)
    located = await asyncio.to_thread(schedules.locate, sid, paths)
    if located is None:
        return web.json_response({"error": "unknown schedule"}, status=404)
    store, item = located
    asyncio.create_task(_fire_schedule(request.app, store, item))
    return web.json_response({"ok": True, "started": True})

async def handle_schedules_stop(request: web.Request) -> web.Response:
    """Disable the schedule and cancel its live Auto run(s)."""
    sid = request.match_info.get("sid", "").strip()
    paths = await asyncio.to_thread(_schedule_registry_paths, request.app)
    located = await asyncio.to_thread(schedules.locate, sid, paths)
    if located is None:
        return web.json_response({"error": "unknown schedule"}, status=404)
    store, item = located
    await asyncio.to_thread(schedules.update, store, sid, {"enabled": False})
    rid = str(item.get("running_run_id") or "")
    cancelled = 0
    if rid and rid != "pending":
        cancelled += _cancel_run_ids(request.app, {rid})
    if store is None:
        # Global: cancel Auto runs whose excerpt matches this prompt
        # across workspaces (best-effort; ids aren't stored per wiki).
        prompt = str(item.get("prompt") or "").strip()
        if prompt:
            cancelled += _cancel_runs_matching(request.app, prompt[:80])
    await asyncio.to_thread(schedules.mark_finished, store, sid)
    return web.json_response({"ok": True, "cancelled": cancelled})

def _cancel_run_ids(
    app: web.Application, ids: set[str], *, dismiss: bool = False,
) -> int:
    runs: dict[str, dict[str, Any]] = app.get("runs") or {}
    extra = {
        rid for rid, rec in runs.items()
        if rec.get("parent_run_id") in ids
    }
    ids = set(ids) | extra
    n = 0
    for run_id in ids:
        rec = runs.get(run_id)
        if rec is None:
            continue
        rec["user_cancel"] = True
        if dismiss:
            rec["user_dismiss"] = True
        parent_id = rec.get("parent_run_id")
        if parent_id and runs.get(parent_id):
            runs[parent_id]["user_cancel"] = True
            if dismiss:
                runs[parent_id]["user_dismiss"] = True
        task = rec.get("task")
        if task is not None:
            try:
                task.cancel()
                n += 1
            except Exception:  # noqa: BLE001
                pass
    return n

def _cancel_runs_matching(app: web.Application, needle: str) -> int:
    if not needle:
        return 0
    runs: dict[str, dict[str, Any]] = app.get("runs") or {}
    n = 0
    low = needle.lower()
    for rec in list(runs.values()):
        excerpt = str(rec.get("input_excerpt") or "").lower()
        if low not in excerpt:
            continue
        rec["user_cancel"] = True
        task = rec.get("task")
        if task is None or task.done():
            continue
        try:
            task.cancel()
            n += 1
        except Exception:  # noqa: BLE001
            pass
    return n

async def _fire_schedule(
    app: web.Application, store: schedules.Store, item: dict[str, Any],
) -> None:
    sid = str(item.get("id") or "")
    prompt = str(item.get("prompt") or "").strip()
    if not sid or not prompt:
        return
    kind, spec, sargs = _daemon_ns._parse_schedule_prompt(prompt)
    if kind == "skip":
        return
    await asyncio.to_thread(schedules.mark_started, store, sid, "pending")
    pref = item.get("preference")
    try:
        pref_f = float(pref) if pref is not None else None
    except (TypeError, ValueError):
        pref_f = None
    targets: list[Path]
    if store is None:
        targets = [Path(p) for p in _schedule_registry_paths(app) if Path(p).is_dir()]
    else:
        targets = [store]
    last_rid: str | None = None
    try:
        for workspace in targets:
            try:
                if kind == "desk" and spec is not None:
                    _daemon_ns._seat_desk_now(workspace, spec, sargs)
                    rid = await _daemon_ns._run_desk(
                        app, spec, prompt=sargs,
                        workspace=workspace, preference=pref_f,
                    )
                else:
                    rid = await _daemon_ns._dispatch_auto(
                        app, None, prompt,
                        preference=pref_f,
                        workspace_override=workspace,
                    )
                if rid:
                    last_rid = rid
                    await asyncio.to_thread(schedules.set_running, store, sid, rid)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("schedule %s failed in %s", sid, workspace)
    finally:
        try:
            if last_rid:
                await asyncio.to_thread(schedules.set_running, store, sid, last_rid)
            await asyncio.to_thread(schedules.mark_finished, store, sid)
        except Exception:  # noqa: BLE001
            log.exception("schedule mark_finished failed")

async def _tick_schedules(app: web.Application) -> None:
    try:
        paths = _schedule_registry_paths(app)
    except Exception:  # noqa: BLE001
        return
    # Global store. until_at is a schedule lifetime — disable, don't
    # guess a desk (global rows have no workspace).
    try:
        live_all = {str(r.get("run_id") or "") for r in (app.get("runs") or {}).values()}
        await asyncio.to_thread(schedules.clear_stale_running, None, live_all)
        await asyncio.to_thread(schedules.expire_windows, None)
        for item in await asyncio.to_thread(schedules.list_items, None):
            if schedules.is_due(item):
                asyncio.create_task(_fire_schedule(app, None, item))
    except Exception:  # noqa: BLE001
        log.exception("global schedule tick failed")
    from switchbay import kernel as sbk
    for raw in paths:
        ws = Path(str(raw))
        if not ws.is_dir():
            continue
        try:
            live_ids = {
                str(r.get("run_id") or "")
                for r in (app.get("runs") or {}).values()
                if r.get("workspace") == str(ws)
            }
            await asyncio.to_thread(schedules.clear_stale_running, ws, live_ids)
            items = await asyncio.to_thread(schedules.list_items, ws)
        except Exception:  # noqa: BLE001
            continue
        try:
            ended = await asyncio.to_thread(schedules.expire_windows, ws)
            for did in ended:
                if did not in sbk.DESK_INFO:
                    continue
                spec = _daemon_ns._desk_spec_from_id(did)
                if spec is not None:
                    _daemon_ns._quiet_desk(app, spec, ws)
                else:
                    sbk.quiet(ws, did, keep_run=True)
        except Exception:  # noqa: BLE001
            log.exception("desk quiet on schedule window failed")
        for item in items:
            if not schedules.is_due(item):
                continue
            asyncio.create_task(_fire_schedule(app, ws, item))
