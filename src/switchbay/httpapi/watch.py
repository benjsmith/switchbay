"""Watch-folder ingest and bulk scan routes.

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
import uuid
from aiohttp import web
from switchbay import admin_policy
from switchbay import capture
from switchbay import file_state
from switchbay import protocol
from switchbay import watchfolders
from switchbay import workspaces

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

async def _dispatch_watch_ingest(
    app: web.Application, cand: watchfolders.Candidate, *, workspace: Path,
) -> None:
    """Hydrate (if needed), stage, and CE-ingest one watched file.

    ``workspace`` is the one captured at scan time. Do not re-read
    ``app["workspace"]`` — a UI switch before this task runs must not
    ingest into a different vault that happens to watch the same folder.

    Deterministic supported extraction runs here — no model dispatch.
    Marked seen only after accepted extracted content is handed off.
    """
    inflight: set[str] = app.setdefault("watch_inflight", set())
    key = cand.logical
    if key in inflight:
        return
    inflight.add(key)
    try:
        result = await asyncio.to_thread(watchfolders.handoff, workspace, cand)
        payload = {
            "path": cand.path,
            "logical": cand.logical,
            "status": result.status,
            "vault_path": result.vault_rel,
            "extracted": result.extracted,
            "error": result.error,
        }
        if result.status == "success":
            _daemon_ns._log_event(
                app, "exec", f"watch-folder ingest: {cand.logical}",
                source="watchfolders", actor="system", payload=payload,
            )
            _daemon_ns._broadcast_files_changed_soon(app)
        else:
            log.info(
                "watch-folder %s %s: %s",
                result.status, cand.logical, result.error or "",
            )
    except Exception:  # noqa: BLE001
        log.exception("watch-folder ingest failed: %s", cand.logical)
        try:
            await asyncio.to_thread(
                watchfolders.record_pending,
                workspace, cand.logical,
                state="error",
                error="internal watch-ingest error",
                retryable=True,
            )
        except Exception:  # noqa: BLE001
            log.exception("watch-folder pending record failed")
    finally:
        inflight.discard(key)

async def _watch_folders_loop(app: web.Application) -> None:
    """Background: poll the active workspace's watch folders and
    auto-ingest new files (capped per beat). Sleep-first; hydration
    and staging run off-loop with timeouts so the heartbeat stays
    responsive. Every failure contained."""
    while True:
        try:
            await asyncio.sleep(_daemon_ns._WATCH_FOLDERS_INTERVAL)
            if not admin_policy.feature_enabled("watch_folders"):
                continue
            ws: Path = app["workspace"]
            inflight: set[str] = app.setdefault("watch_inflight", set())
            inflight_snap = set(inflight)
            picked, backlog = await asyncio.to_thread(
                watchfolders.scan_candidates, ws, inflight=inflight_snap,
            )
            if Path(app["workspace"]) != ws:
                continue
            tasks = [
                asyncio.create_task(
                    _dispatch_watch_ingest(app, cand, workspace=ws),
                )
                for cand in picked
            ]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            if backlog:
                log.info(
                    "watch folders: %d more new files queued for later "
                    "beats (cap %d/beat)", backlog, watchfolders.MAX_PER_BEAT,
                )
        except asyncio.CancelledError:
            return
        except Exception:  # noqa: BLE001
            log.exception("watch-folders iteration failed")

async def handle_watch_folders_get(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    status = await asyncio.to_thread(watchfolders.api_status, workspace)
    status["interval_s"] = int(_daemon_ns._WATCH_FOLDERS_INTERVAL)
    return web.json_response(status)

async def handle_watch_folders_add(request: web.Request) -> web.Response:
    """Register a watch folder. Body {path} — or {pick: true} to open
    the OS folder picker. Existing contents are BASELINED (only files
    arriving after this point auto-ingest)."""
    blocked = _daemon_ns._policy_block("watch_folders")
    if blocked:
        return blocked
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    workspace: Path = request.app["workspace"]
    raw = str(body.get("path") or "").strip()
    if not raw and body.get("pick"):
        picked = await workspaces.pick_folder()
        if not picked:
            return web.json_response({"ok": False, "cancelled": True})
        raw = picked
    if not raw:
        return web.json_response({"error": "path required"}, status=400)
    res = await asyncio.to_thread(watchfolders.add_folder, workspace, raw)
    if isinstance(res, str):
        return web.json_response({"error": res}, status=400)
    _daemon_ns._log_event(
        request.app, "exec", f"watch folder added: {res['path']}",
        source="watchfolders", actor="user", payload=res,
    )
    status = await asyncio.to_thread(watchfolders.api_status, workspace)
    return web.json_response({"ok": True, "folder": res, **status})

async def handle_watch_folders_remove(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    workspace: Path = request.app["workspace"]
    raw = str(body.get("path") or "").strip()
    ok = await asyncio.to_thread(watchfolders.remove_folder, workspace, raw)
    if not ok:
        return web.json_response({"error": "not a watched folder"}, status=404)
    status = await asyncio.to_thread(watchfolders.api_status, workspace)
    return web.json_response({"ok": True, **status})

async def handle_watch_folders_toggle(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    workspace: Path = request.app["workspace"]
    raw = str(body.get("path") or "").strip()
    enabled = bool(body.get("enabled"))
    ok = await asyncio.to_thread(
        watchfolders.set_enabled, workspace, raw, enabled,
    )
    if not ok:
        return web.json_response({"error": "not a watched folder"}, status=404)
    status = await asyncio.to_thread(watchfolders.api_status, workspace)
    return web.json_response({"ok": True, **status})

def _bulk_listing(root: Path) -> tuple[str, int, int]:
    """Compact, model-readable summary of a directory tree for the
    bulk-ingest architecture scan: per-directory file counts, extension
    histograms, and a few sample names — metadata only, no contents.
    Returns (listing_text, total_files, total_bytes)."""
    per_dir: dict[str, dict[str, Any]] = {}
    total_files = 0
    total_bytes = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        rel = os.path.relpath(dirpath, root)
        rec = per_dir.setdefault(rel, {"n": 0, "bytes": 0, "exts": {}, "samples": []})
        for name in filenames:
            if name.startswith("."):
                continue
            total_files += 1
            rec["n"] += 1
            try:
                sz = os.stat(os.path.join(dirpath, name)).st_size
            except OSError:
                sz = 0
            total_bytes += sz
            rec["bytes"] += sz
            ext = Path(name).suffix.lower() or "(none)"
            rec["exts"][ext] = rec["exts"].get(ext, 0) + 1
            if len(rec["samples"]) < 8:
                rec["samples"].append(name)
            if total_files >= 5000:
                break
        if total_files >= 5000:
            break
    lines: list[str] = []
    for rel in sorted(per_dir):
        rec = per_dir[rel]
        if rec["n"] == 0:
            continue
        exts = ", ".join(
            f"{k}×{v}" for k, v in
            sorted(rec["exts"].items(), key=lambda kv: -kv[1])[:6]
        )
        lines.append(
            f"{rel + '/' if rel != '.' else './'}  — {rec['n']} files "
            f"({rec['bytes'] // 1024} KB; {exts})\n"
            f"    e.g. {', '.join(rec['samples'])}"
        )
        if len("\n".join(lines)) > 6000:
            lines.append("… (listing truncated)")
            break
    return "\n".join(lines), total_files, total_bytes

async def handle_ingest_bulk_scan(request: web.Request) -> web.Response:
    """Bulk-ingest ARCHITECTURE STEP (charter, 2026-07-04): the user
    points switchbay at a big outside folder; before anything is
    ingested, a background agent reads the tree's METADATA (names,
    counts, types — never contents) and either blesses a single
    workspace or proposes 2-3 candidate architectures, each with the
    principle behind it. Nothing is ingested by this endpoint — the
    proposal names the concrete next moves and the user stays in
    control of the (per-file agent-run) cost. Body: {path} or
    {pick: true}."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    raw = str(body.get("path") or "").strip()
    if not raw and body.get("pick"):
        picked = await workspaces.pick_folder()
        if not picked:
            return web.json_response({"ok": False, "cancelled": True})
        raw = picked
    if not raw:
        return web.json_response({"error": "path required"}, status=400)
    d = Path(os.path.expanduser(raw))
    if not d.is_absolute() or not d.is_dir():
        return web.json_response({"error": "not a directory"}, status=400)
    listing, total_files, total_bytes = await asyncio.to_thread(_bulk_listing, d)
    if total_files == 0:
        return web.json_response({"error": "folder has no visible files"}, status=400)
    workspace: Path = request.app["workspace"]
    prompt = (
        f"The user wants to adopt switchbay for their existing files and "
        f"pointed it at `{d}` — {total_files} files, "
        f"{total_bytes // (1024 * 1024)} MB (metadata below; you have NOT "
        f"read any contents, and you must NOT ingest anything in this "
        f"run).\n\n"
        f"Your job is the ARCHITECTURE STEP: decide how this material "
        f"should divide into workspaces so it fits the user's mental "
        f"model.\n\n"
        f"1. Read the tree summary and infer what kinds of material live "
        f"where.\n"
        f"2. If it reads as ONE coherent workspace (this one: "
        f"`{workspace.name}`), say so plainly and skip to step 4.\n"
        f"3. Otherwise propose 2-3 CANDIDATE ARCHITECTURES. For each: "
        f"the PRINCIPLE (by life-domain, by project, by time…), the "
        f"workspaces it creates, and which folders map to which. Give "
        f"your recommendation and why. Keep it scannable.\n"
        f"4. Concrete next steps (be explicit these are the user's "
        f"moves, with rough cost — every ingested file is one background "
        f"agent run):\n"
        f"   · drag a subfolder onto the Browser column to ingest it "
        f"into THIS workspace (good up to ~100 files at a time);\n"
        f"   · Settings → Watch folders to auto-ingest whatever arrives "
        f"there from now on;\n"
        f"   · for a multi-workspace architecture: create the other "
        f"workspaces from the top-bar switcher, then repeat the above "
        f"per workspace.\n\n"
        f"TREE SUMMARY:\n{listing}"
    )
    run_id = f"run-{uuid.uuid4().hex[:8]}"

    async def _runner() -> None:
        try:
            await _daemon_ns._dispatch_chat(
                request.app, ws=None, text=prompt,
                input_excerpt=f"architecture scan: {d.name}",
                run_id=run_id,
            )
        except Exception:  # noqa: BLE001
            log.exception("bulk-scan run %s crashed", run_id)

    task = asyncio.create_task(_runner())
    task.add_done_callback(_daemon_ns._make_dispatch_error_surface(request.app, run_id))
    _daemon_ns._log_event(
        request.app, "exec", f"bulk-ingest architecture scan: {d}",
        source="ingest", actor="user",
        payload={"path": str(d), "files": total_files, "run_id": run_id},
    )
    return web.json_response({
        "ok": True, "run_id": run_id, "files": total_files,
    })

async def handle_decisions_pending(request: web.Request) -> web.Response:
    """Proposed-but-undecided charter amendments for the active
    workspace — the frontend re-offers their review cards after a
    reload (permission cards are ephemeral; these are disk-backed)."""
    ws: Path = request.app["workspace"]
    entries = await asyncio.to_thread(capture.list_decisions, ws)
    return web.json_response({
        "decisions": [e for e in entries if e.get("status") == "proposed"],
        "pending_drafts": sum(
            1 for e in entries if e.get("status") == "pending"
        ),
    })

async def handle_decision_decide(request: web.Request) -> web.Response:
    """One-click verdict on a drafted charter amendment. Accept writes
    the proposed page IN PLACE (the only path that touches the wiki);
    dismiss leaves the captured note where it is and closes the card."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    dec_id = str(body.get("id") or "").strip()
    decision = str(body.get("decision") or "").strip()
    if not dec_id or decision not in ("accept", "dismiss"):
        return web.json_response(
            {"error": "need id + decision: accept|dismiss"}, status=400,
        )
    ws: Path = request.app["workspace"]
    entries = await asyncio.to_thread(capture.list_decisions, ws)
    entry = next((e for e in entries if e.get("id") == dec_id), None)
    if entry is None:
        return web.json_response({"error": "unknown decision id"}, status=404)
    if entry.get("status") != "proposed":
        return web.json_response(
            {"error": f"decision is {entry.get('status')}, not proposed"},
            status=409,
        )
    if decision == "dismiss":
        await asyncio.to_thread(
            capture.update_decision, ws, dec_id, status="dismissed",
        )
        await _daemon_ns._broadcast(
            request.app, protocol.decision_review_resolved(dec_id, "dismiss"),
        )
        return web.json_response({"ok": True, "status": "dismissed"})
    rel = str(entry.get("charter_path") or "")
    proposal = str(entry.get("proposal") or "")
    if not rel or not proposal:
        return web.json_response(
            {"error": "proposal missing — will re-draft next beat"},
            status=409,
        )
    await asyncio.to_thread(capture.write_charter, ws, rel, proposal)
    await asyncio.to_thread(
        file_state.record_internal_write, ws, rel, owner="heartbeat",
    )
    await asyncio.to_thread(
        capture.update_decision, ws, dec_id, status="promoted",
    )
    _daemon_ns._log_event(
        request.app, "capture", f"charter amended: {rel} (decision {dec_id})",
        source="rail", actor="user",
        payload={"id": dec_id, "charter_path": rel},
    )
    await _daemon_ns._broadcast(
        request.app, protocol.decision_review_resolved(dec_id, "accept"),
    )
    await _daemon_ns._broadcast(request.app, protocol.files_changed())
    # Charter pages are wiki content — refresh the graph off-request.
    asyncio.create_task(_daemon_ns._rebuild_graph_async(request.app))
    return web.json_response(
        {"ok": True, "status": "promoted", "charter_path": rel},
    )
