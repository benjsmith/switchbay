"""Tool, rule, palette, sketch, and duckdb starter routes.

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
from switchbay import agent_rules
from switchbay import command_palettes
from switchbay import duckdb_starters
from switchbay import fileops
from switchbay import localllm
from switchbay import sketches
from switchbay import terminals
from switchbay import tools
from switchbay.agents import rail_default

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

async def handle_runs_stop_all(request: web.Request) -> web.Response:
    """Cancel every active run. Backs the top-bar 'stop all running
    tasks' affordance: closing the window normally leaves runs going
    (the daemon is always-on), so this is the explicit 'terminate the
    work too' choice. The daemon itself stays up. Idempotent."""
    runs: dict[str, dict[str, Any]] = request.app.get("runs") or {}
    cancelled = 0
    from switchbay import kernel as sbk
    for rec in list(runs.values()):
        rec["user_cancel"] = True
        ws_raw = rec.get("workspace")
        rid = str(rec.get("run_id") or "")
        if ws_raw and rid:
            try:
                sbk.quiet_run(Path(ws_raw), rid)
            except Exception:  # noqa: BLE001
                log.exception("desk quiet on stop-all failed")
        task = rec.get("task")
        if task is not None and not task.done():
            try:
                task.cancel()
                cancelled += 1
            except Exception:  # noqa: BLE001
                pass
        sid = rec.get("pty_session")
        if sid:
            s = (request.app.get("terminals") or {}).get(sid)
            if s is not None:
                terminals.kill(s)
                cancelled += 1
    return web.json_response({"ok": True, "cancelled": cancelled})

async def handle_tools_list(request: web.Request) -> web.Response:
    """List every registered tool — what the agent can call. The Agent
    Dashboard tab reads this to show the live tool registry."""
    out = []
    for name, t in sorted(tools.REGISTRY.items()):
        out.append({
            "name": name,
            "description": t.description,
            "input_schema": t.input_schema,
        })
    return web.json_response({"tools": out})

async def handle_agent_rules_list(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    return web.json_response({"rules": agent_rules.load(workspace)})

async def handle_agent_rules_delete(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    rid = request.query.get("id", "").strip()
    if not rid:
        return web.json_response({"error": "id required"}, status=400)
    removed = agent_rules.remove(workspace, rid)
    return web.json_response({"ok": removed})

async def _local_rung_for_request() -> Any:
    cfg = await asyncio.to_thread(localllm.load_config)
    return rail_default.resolve_local_rung(
        localllm.ram_gb(),
        model_hint=rail_default.model_hint_from_cfg(cfg),
    )

async def handle_command_palettes_list(request: web.Request) -> web.Response:
    """Shipped + user-command palettes for the Agent Dashboard editor."""
    workspace: Path = request.app["workspace"]
    rung = await _local_rung_for_request()
    payload = await asyncio.to_thread(
        command_palettes.describe_all, workspace, rung,
    )
    return web.json_response(payload)

async def handle_command_palettes_put(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    name = str(body.get("command") or body.get("name") or "").strip()
    raw = body.get("tools")
    if not name:
        return web.json_response({"error": "command required"}, status=400)
    if not isinstance(raw, list):
        return web.json_response({"error": "tools must be a list"}, status=400)
    try:
        saved = await asyncio.to_thread(
            command_palettes.set_override, workspace, name, raw,
        )
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    rung = await _local_rung_for_request()
    payload = await asyncio.to_thread(
        command_palettes.describe_all, workspace, rung,
    )
    payload["saved"] = saved
    return web.json_response(payload)

async def handle_command_palettes_delete(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    name = (request.query.get("command") or request.query.get("name") or "").strip()
    if not name:
        return web.json_response({"error": "command required"}, status=400)
    removed = await asyncio.to_thread(
        command_palettes.clear_override, workspace, name,
    )
    rung = await _local_rung_for_request()
    payload = await asyncio.to_thread(
        command_palettes.describe_all, workspace, rung,
    )
    payload["ok"] = removed
    return web.json_response(payload)

async def handle_sketches_list(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    return web.json_response({"sketches": sketches.list_sketches(workspace)})

async def handle_sketch_get(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    sid = request.query.get("id", "").strip()
    if not sid:
        return web.json_response({"error": "id required"}, status=400)
    try:
        s = sketches.get_sketch(workspace, sid)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    if s is None:
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response({"sketch": s})

async def handle_sketch_post(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    name = str(body.get("name") or "").strip()
    kind = str(body.get("kind") or "").strip()
    data = body.get("data")
    sid = body.get("id")
    png_b64 = body.get("png_b64")
    if data is None:
        return web.json_response({"error": "data required"}, status=400)
    try:
        record = sketches.save_sketch(
            workspace, name=name, kind=kind, data=data,
            sketch_id=sid if isinstance(sid, str) and sid else None,
            png_b64=png_b64 if isinstance(png_b64, str) else None,
        )
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({"sketch": record})

async def handle_sketch_delete(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    sid = request.query.get("id", "").strip()
    if not sid:
        return web.json_response({"error": "id required"}, status=400)
    try:
        ok = sketches.delete_sketch(workspace, sid)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({"ok": ok})

async def handle_duckdb_starters_get(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    # read_text on .workbench/state/duckdb-starters.json — tiny, but
    # under iCloud-synced ~/Documents it can be evicted (dataless) and
    # block for tens of seconds while iCloud re-downloads, wedging the
    # loop (watchdog caught exactly this on the Table tab). Off-thread.
    starters = await asyncio.to_thread(duckdb_starters.load, workspace)
    return web.json_response({"starters": starters})

async def handle_duckdb_starters_post(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    items = body.get("starters")
    if not isinstance(items, list):
        return web.json_response({"error": "starters must be an array"}, status=400)
    # Off-thread: same iCloud-eviction wedge risk as the GET path.
    await asyncio.to_thread(duckdb_starters.save, workspace, items)
    _daemon_ns._log_event(
        request.app, "starter_change",
        f"saved {len(items)} DuckDB starter pill{'s' if len(items) != 1 else ''}",
        source="duckdb", actor="user",
        payload={"count": len(items)},
    )
    return web.json_response({"ok": True, "starters": duckdb_starters.load(workspace)})

async def handle_fs_inventory(request: web.Request) -> web.Response:
    """Bulk file stat — used by the DuckDB tab to seed its `files` table.

    Returns [{path, size, mtime, ext}] for every visible file in the
    workspace (same visibility rules as /api/tree). Single response so
    the tab doesn't N+1 against /api/fs/stat.
    """
    workspace: Path = request.app["workspace"]
    # Full tree walk + stat() per file — off-thread so the DuckDB
    # tab's seed request doesn't wedge the loop on a big workspace.
    inv = await asyncio.to_thread(fileops.inventory, workspace)
    return web.json_response({"files": inv})

async def handle_fs_raw(request: web.Request) -> web.StreamResponse:
    """Stream raw file contents (any byte content). Used by DuckDB-WASM
    to read CSV / parquet / JSON files in the workspace via
    `read_csv_auto('http://.../api/fs/raw?path=...')` etc.

    Same path-resolution rules as /api/file (no escape, no NUL); no
    extension restriction (DuckDB needs CSV/parquet/etc.).

    Vault extracts: when `vault/*.extracted.md` is missing on disk but
    present in vault/vault.db FTS, return the indexed body as text/markdown
    so Editor / CE "Open full vault source" still works on wiki-only tips.
    """
    workspace: Path = request.app["workspace"]
    rel = request.query.get("path", "")
    target = _daemon_ns._safe_resolve(workspace, rel)
    if target is None or not target.is_file():
        body = await asyncio.to_thread(fileops.vault_db_read_body, workspace, rel)
        if body is not None:
            return web.Response(
                text=body,
                content_type="text/markdown",
                charset="utf-8",
                headers={"X-Switchbay-Vault-Source": "vault.db"},
            )
        if fileops.vault_extracted_basename(rel):
            return web.json_response({
                "error": (
                    f"vault source missing on disk and not in vault.db: {rel}. "
                    "Restore vault/*.extracted.md (or a populated vault.db) "
                    "from the hybrid vault / tip archive."
                ),
            }, status=404)
        return web.json_response({"error": "not found"}, status=404)
    return web.FileResponse(target)
