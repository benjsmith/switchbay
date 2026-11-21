"""Workspace home, migrate, archive, and page save.

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
import os
from aiohttp import web
from switchbay import app_settings
from switchbay import atomicio
from switchbay import cebridge
from switchbay import file_state
from switchbay import protocol
from switchbay import workspaces

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

def _workspaces_home_body(active: str) -> dict[str, Any]:
    """Shared GET/POST body for the workspaces-home setting: the raw +
    expanded home and which registered workspaces could migrate into
    it (everything registered, outside the home, and not active)."""
    home_raw = app_settings.get_workspaces_home()
    home = app_settings.workspaces_home_path()
    data = workspaces.load()
    candidates = []
    for p in data["paths"]:
        if p == active:
            continue
        if p == str(home) or p.startswith(str(home) + os.sep):
            continue
        candidates.append({"path": p, "name": Path(p).name})
    return {
        "home": home_raw,
        "expanded": str(home),
        "exists": home.is_dir(),
        "candidates": candidates,
        "active": active,
    }

async def handle_workspaces_home_get(request: web.Request) -> web.Response:
    active = str(request.app["workspace"])
    return web.json_response(
        await asyncio.to_thread(_workspaces_home_body, active),
    )

async def handle_workspaces_home_set(request: web.Request) -> web.Response:
    """Set the workspaces home (stage-5 ruling: fixed home, default
    ~/Workspaces; point it at ~/Documents/Workspaces or similar to
    get cloud tracking)."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    raw = str(body.get("home") or "").strip()
    if not raw:
        return web.json_response({"error": "home required"}, status=400)
    expanded = Path(os.path.expanduser(raw))
    if not expanded.is_absolute():
        return web.json_response(
            {"error": "home must be absolute (or ~-relative)"}, status=400,
        )
    if not workspaces.is_within_home(expanded):
        return web.json_response(
            {"error": f"home must live inside {workspaces.home_label()}"},
            status=400,
        )
    await asyncio.to_thread(app_settings.set_workspaces_home, raw)
    active = str(request.app["workspace"])
    return web.json_response(
        await asyncio.to_thread(_workspaces_home_body, active),
    )

async def _post_migrate_env_rebuild(app: web.Application, dest: Path) -> None:
    """After a successful migrate copy, recreate the CE `.venv` and
    rebuild the graph viewer bundle so edges (kuzu) work at the new
    path. Migrate deliberately skips `.venv`/`uv-cache`; regenerating
    is correct. Non-blocking background task — fail-soft with rail
    notices. Network-heavy (setup downloads deps)."""
    dest = Path(dest)
    label = dest.name
    try:
        await _daemon_ns._broadcast(app, protocol.notice(
            f"Moved workspace «{label}»: rebuilding environment "
            f"(setup.sh + graph) in the background…",
            kind="chat",
        ))
        _daemon_ns._log_event(
            app, "exec",
            f"post-migrate env rebuild started: {dest}",
            source="workspaces", actor="system",
            payload={"dest": str(dest)},
        )
        ok, setup_out = await cebridge.setup(dest)
        if not ok:
            await _daemon_ns._broadcast(app, protocol.notice(
                f"Moved «{label}»: environment setup failed — graph "
                f"may show nodes without edges until you re-run setup. "
                f"Detail: {setup_out[-300:]}",
                kind="error",
            ))
            _daemon_ns._log_event(
                app, "exec",
                f"post-migrate setup failed: {dest}",
                source="workspaces", actor="system",
                payload={"dest": str(dest), "detail": setup_out[-500:]},
            )
            return
        # ensure_env=False: we just ran setup; don't double-invoke.
        data = await cebridge.build(dest, ensure_env=False)
        if data is None:
            await _daemon_ns._broadcast(app, protocol.notice(
                f"Moved «{label}»: env ready but graph rebuild failed "
                f"(no wiki/?). Try Rescan when the workspace is active.",
                kind="error",
            ))
            return
        _daemon_ns._put_graph_cache(app, str(dest.resolve()), data)
        n_edges = len(data.get("edges") or [])
        n_nodes = len(data.get("nodes") or data.get("pages") or {})
        await _daemon_ns._broadcast(app, protocol.files_changed())
        await _daemon_ns._broadcast(app, protocol.notice(
            f"Moved «{label}»: graph ready — {n_nodes} nodes, "
            f"{n_edges} edges.",
            kind="chat",
        ))
        _daemon_ns._log_event(
            app, "curation",
            f"post-migrate graph rebuild ok: {dest} "
            f"(nodes={n_nodes}, edges={n_edges})",
            source="workspaces", actor="system",
            payload={
                "dest": str(dest),
                "nodes": n_nodes,
                "edges": n_edges,
            },
        )
    except Exception:  # noqa: BLE001
        log.exception("post-migrate env rebuild failed for %s", dest)
        try:
            await _daemon_ns._broadcast(app, protocol.notice(
                f"Moved «{label}»: background env/graph rebuild crashed "
                f"— see daemon log. Run CE setup.sh in the workspace, "
                f"then Rescan.",
                kind="error",
            ))
        except Exception:  # noqa: BLE001
            pass

async def handle_workspaces_migrate(request: web.Request) -> web.Response:
    """Move a registered, non-active workspace into the workspaces
    home (folder + registry + machine-local state). Body: {path}.

    After a successful copy, schedules a background CE setup + graph
    rebuild so the excluded `.venv` is recreated and edges work."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    raw = str(body.get("path") or "").strip()
    if not raw:
        return web.json_response({"error": "path required"}, status=400)
    active = str(request.app["workspace"])
    if raw == active:
        return web.json_response(
            {"error": "that workspace is active — switch away first"},
            status=400,
        )
    home = app_settings.workspaces_home_path()
    res = await asyncio.to_thread(
        workspaces.migrate_into_home, Path(raw), home,
    )
    if isinstance(res, str):
        return web.json_response({"error": res}, status=400)
    _daemon_ns._log_event(
        request.app, "exec",
        f"workspace copied into home (source retained): {res['old']} → {res['new']}",
        source="workspaces", actor="user", payload=res,
    )
    # The registry repointed to the new path — tell every client so the
    # switcher shows the new location live (add/switch do this via
    # _activate; migrate doesn't touch the active workspace so we
    # broadcast the fresh hello directly).
    await _daemon_ns._broadcast(request.app, _daemon_ns._hello_payload(request.app))
    # Files have landed; regenerate .venv + graph off the request path
    # (setup downloads kuzu etc. and can take minutes).
    dest = Path(res["new"])
    asyncio.create_task(_post_migrate_env_rebuild(request.app, dest))
    res = {**res, "env_rebuild": "started"}
    body_out = await asyncio.to_thread(_workspaces_home_body, active)
    body_out["migrated"] = res
    return web.json_response(body_out)

async def handle_workspaces_migrate_cleanup(request: web.Request) -> web.Response:
    """PHASE 2 of a move: remove the source folder left behind by
    `/api/workspaces/migrate` after the user confirms. Body:
    {old, new}."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    old = str(body.get("old") or "").strip()
    new = str(body.get("new") or "").strip()
    if not old or not new:
        return web.json_response({"error": "old + new required"}, status=400)
    active = str(request.app["workspace"])
    if old == active:
        return web.json_response(
            {"error": "that workspace is active — switch away first"},
            status=400,
        )
    res = await asyncio.to_thread(
        workspaces.cleanup_migrated_source, Path(old), Path(new),
    )
    if isinstance(res, str):
        return web.json_response({"error": res}, status=400)
    _daemon_ns._log_event(
        request.app, "exec",
        f"removed old workspace copy after move: {old}",
        source="workspaces", actor="user", payload=res,
    )
    await _daemon_ns._broadcast(request.app, _daemon_ns._hello_payload(request.app))
    body_out = await asyncio.to_thread(_workspaces_home_body, active)
    body_out["cleaned"] = res
    return web.json_response(body_out)

async def handle_workspaces_unregister(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    path = Path(str(body.get("path", "")).strip()).expanduser()
    workspaces.unregister(path)
    return web.json_response({
        "ok": True,
        "workspaces": {
            **workspaces.load(),
            "archived": workspaces.load_archived(),
        },
    })

async def handle_workspaces_archive(request: web.Request) -> web.Response:
    """Move a workspace from active list → archive. Settings under
    .workbench/ stay on disk so a later /restore re-instates the
    workspace exactly as it was."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    path = Path(str(body.get("path", "")).strip()).expanduser()
    return web.json_response({
        "ok": True,
        "workspaces": workspaces.archive(path),
    })

async def handle_workspaces_restore(request: web.Request) -> web.Response:
    """Move a workspace from archive → active list."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    path = Path(str(body.get("path", "")).strip()).expanduser()
    return web.json_response({
        "ok": True,
        "workspaces": workspaces.restore(path),
    })

async def handle_workspaces_delete(request: web.Request) -> web.Response:
    """Hard-delete: remove from registry + archive AND remove the
    `.workbench/` settings directory under the workspace. The user's
    own content (wiki/, vault/, figures/, etc.) is NEVER touched —
    only switchbay's internal state."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    path = Path(str(body.get("path", "")).strip()).expanduser()
    return web.json_response({
        "ok": True,
        "workspaces": workspaces.delete(path),
    })

async def handle_page_post(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    rel = str(body.get("path", ""))
    content = str(body.get("content", ""))
    if len(content.encode("utf-8")) > _daemon_ns.MAX_FILE_BYTES:
        return web.json_response({"error": "content too large"}, status=413)
    target = _daemon_ns._resolve_wiki_md(workspace, rel)
    if target is None:
        return web.json_response({"error": "invalid path"}, status=400)

    def _write() -> tuple[bool, int, int]:
        existed = target.is_file()
        prev = target.stat().st_size if existed else 0
        target.parent.mkdir(parents=True, exist_ok=True)
        atomicio.write_text_atomic(target, content)
        return existed, prev, target.stat().st_size

    existed, prev_size, new_size = await asyncio.to_thread(_write)
    norm_rel = rel if rel.startswith("wiki/") else f"wiki/{rel}"
    file_state.record_internal_write(workspace, norm_rel, owner="editor")
    _daemon_ns._log_event(
        request.app, "file_edit_internal",
        f"{'edited' if existed else 'created'} {rel} ({new_size} bytes)",
        source="editor", actor="user",
        payload={
            "path": rel,
            "created": not existed,
            "size_before": prev_size,
            "size_after": new_size,
        },
    )
    await _daemon_ns._broadcast(request.app, protocol.files_changed())

    # Rebuild data.json so subsequent /api/graph/data reflects the edit.
    data = await cebridge.build(workspace)
    if data is None:
        return web.json_response({"ok": True, "rebuilt": False})
    request.app["graph_data"] = data
    _daemon_ns._log_event(
        request.app, "curation",
        f"rebuilt graph after {rel} edit (pages={len(data.get('pages') or {})})",
        source="cebridge", actor="system",
        payload={"trigger": "page_save", "path": rel},
    )
    return web.json_response({"ok": True, "rebuilt": True})
