"""Workspace tree listing and file read/write.

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
from switchbay import admin_policy
from switchbay import atomicio
from switchbay import file_state
from switchbay import fileops
from switchbay import modestore
from switchbay import packstore
from switchbay import protocol
from switchbay import statedir
from switchbay import tabstore

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

def _walk_tree(workspace: Path) -> list[str]:
    # Prune hidden + skip dirs IN PLACE during the walk so we never
    # descend into them. The old `rglob("*")` visited every file under
    # .git / .venv / .curator / node_modules and discarded them after
    # the fact — on a CE workspace that's 150k+ files (a 45k-file .venv
    # + a 100k-file .curator), ~14s of stat() churn on iCloud storage
    # for ~2k files of real content. os.walk lets us skip those subtrees
    # entirely.
    out: list[str] = []
    ws = str(workspace)
    for root, dirnames, filenames in os.walk(workspace):
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".") and d not in _daemon_ns.SKIP_DIRS
        ]
        for fn in filenames:
            if fn.startswith("."):
                continue
            out.append(os.path.relpath(os.path.join(root, fn), ws))
    out.sort()
    return out

def _pick_default_file(workspace: Path) -> str | None:
    for rel in _daemon_ns.DEFAULT_FILE_CANDIDATES:
        if (workspace / rel).is_file():
            return rel
    return None

async def handle_admin_policy(request: web.Request) -> web.Response:
    """GET /api/admin-policy — resolved machine policy (read-only)."""
    return web.json_response({"ok": True, **admin_policy.public_view()})

async def handle_health(request: web.Request) -> web.Response:
    """Cheap liveness + identity for the open PWA/dev client.

    The frontend polls this on loopback and reloads itself when
    `boot_id` (daemon process) or `frontend_mtime` (built dist)
    changes — so a `make refresh` restarts the daemon without forcing
    the user to quit/reopen the dock PWA. Intentionally tiny and
    non-blocking (no workspace walks, no sqlite)."""
    dist: Path | None = request.app.get("frontend_dist")
    frontend_mtime = 0
    if isinstance(dist, Path):
        index = dist / "index.html"
        try:
            if index.is_file():
                frontend_mtime = int(index.stat().st_mtime)
        except OSError:
            frontend_mtime = 0
    return web.json_response({
        "ok": True,
        "boot_id": request.app.get("boot_id") or "",
        "pid": os.getpid(),
        "started_at": request.app.get("started_at") or 0,
        "frontend_mtime": frontend_mtime,
        "workspace": str(request.app.get("workspace") or ""),
        # True when we're the installed always-on service (vs a
        # foreground serve). Settings → Restart works on both.
        "service_managed": request.app.get("service_managed", False),
        # Absolute repo root — the offline/stopped screens cache this to
        # build `make -C "<repo>" restart`.
        "repo_root": request.app.get("repo_root", ""),
        "policy": {
            "profile": admin_policy.profile(),
            "source": admin_policy.load().get("source"),
        },
    })

async def handle_tree(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    # _walk_tree rglob's the whole workspace — off-thread so a large
    # tree doesn't wedge the event loop (see plan.md async hygiene).
    files = await asyncio.to_thread(_walk_tree, workspace)
    return web.json_response({"files": files})

async def handle_file(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    rel = request.query.get("path", "")
    if not rel:
        return web.json_response({"error": "missing path"}, status=400)
    target = _daemon_ns._safe_resolve(workspace, rel)
    if target is None or not target.is_file():
        # Vault extracts: fall back to FTS body in vault/vault.db when the
        # on-disk *.extracted.md is absent (wiki-only tip checkouts).
        body = await asyncio.to_thread(fileops.vault_db_read_body, workspace, rel)
        if body is not None:
            if len(body.encode("utf-8")) > _daemon_ns.MAX_FILE_BYTES:
                return web.json_response({"error": "file too large"}, status=413)
            return web.json_response({
                "path": rel, "text": body, "source": "vault.db",
            })
        if fileops.vault_extracted_basename(rel):
            return web.json_response({
                "error": (
                    f"vault source missing on disk and not in vault.db: {rel}. "
                    "Restore vault/*.extracted.md (or a populated vault.db) "
                    "from the hybrid vault / tip archive."
                ),
            }, status=404)
        return web.json_response({"error": "not found"}, status=404)
    # Cloud-sync placeholder: the bytes aren't local yet, so reading
    # them would block for tens of seconds while the sync service
    # hydrates. Don't make the user stare at a silent spinner — kick
    # the download off-thread and tell the frontend it's syncing so it
    # can show an honest "Downloading from <service>…" state and retry.
    if statedir.is_dataless(target):
        async def _pull() -> None:
            try:
                await asyncio.to_thread(target.read_bytes)
            except Exception:  # noqa: BLE001
                log.exception("hydration read failed for %s", target)
        asyncio.create_task(_pull())
        return web.json_response(
            {"path": rel, "syncing": True,
             "service": statedir.sync_service_hint(workspace)},
            status=202,
        )
    if target.stat().st_size > _daemon_ns.MAX_FILE_BYTES:
        return web.json_response({"error": "file too large"}, status=413)
    try:
        text = await asyncio.to_thread(target.read_text, encoding="utf-8")
    except UnicodeDecodeError:
        return web.json_response({"error": "binary file"}, status=415)
    _daemon_ns._check_external_edit(request.app, rel)
    return web.json_response({"path": rel, "text": text})

async def handle_file_save(request: web.Request) -> web.Response:
    """Save arbitrary text content to an in-workspace path. Used by
    the Editor tab's code-file mode (#24) — /api/page is wiki/*.md
    only and refuses to touch non-wiki paths. This one tolerates any
    in-workspace text file (Python source, JSON config, …), still
    blocking path-traversal via _safe_resolve."""
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    rel = str(body.get("path", "")).strip()
    content = str(body.get("content", ""))
    if not rel:
        return web.json_response({"error": "missing path"}, status=400)
    if len(content.encode("utf-8")) > _daemon_ns.MAX_FILE_BYTES:
        return web.json_response({"error": "content too large"}, status=413)
    target = _daemon_ns._safe_resolve(workspace, rel)
    if target is None:
        return web.json_response({"error": "path outside workspace"}, status=400)
    def _write() -> tuple[bool, int, int]:
        existed = target.is_file()
        prev = target.stat().st_size if existed else 0
        target.parent.mkdir(parents=True, exist_ok=True)
        # Atomic: a crash mid-save must not truncate the user's source
        # file to empty (see atomicio).
        atomicio.write_text_atomic(target, content)
        return existed, prev, target.stat().st_size

    existed, prev_size, new_size = await asyncio.to_thread(_write)
    file_state.record_internal_write(workspace, rel, owner="editor")
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
    return web.json_response({
        "ok": True, "path": rel, "size": new_size, "created": not existed,
    })

async def handle_mode(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    # _compose_mode reads mode.json + scans pack scopes (iterdir +
    # per-pack JSON) — off-thread so tab-nav refreshes never block.
    mode = await asyncio.to_thread(_compose_mode, workspace)
    return web.json_response(mode)

def _compose_mode(workspace: Path) -> dict[str, Any]:
    """Merge core tabs (from mode.json) with pack-contributed tabs
    so the frontend sees one unified Mode. Pack tabs land AFTER
    core tabs; user-supplied edits to mode.json (e.g. extra
    custom tabs) keep their relative order at the end.

    `source` is tagged so the tab strip can render dividers
    between groups. Core tabs without an explicit `source` get
    `core`; the user-extended ones get `user` by convention if
    they don't already carry a source field."""
    mode = modestore.load(workspace)
    raw_tabs = list(mode.get("tabs") or [])
    tabs: list[dict[str, Any]] = []
    for t in raw_tabs:
        if not isinstance(t, dict):
            continue
        src = tabstore.classify_source(t)
        t["source"] = src
        # User-source tabs honour soft-disable via tabs-state.json.
        # Core + pack tabs ignore that file (pack toggling lives in
        # the packstore enable bit; core tabs aren't optional).
        if src == "user":
            tid = str(t.get("id") or "")
            if tid and not tabstore.is_enabled(workspace, tid):
                continue
        tabs.append(t)
    # Self-heal: when DEFAULT_MODE grows a new core tab (e.g. Slides
    # added in Stage 2), splice it into the composed list at its
    # canonical position from DEFAULT_MODE so existing mode.json
    # files don't need a manual migration to see the new tab. Skip
    # if the user has explicitly disabled it via tabs-state.
    default_tabs = [
        t for t in modestore.DEFAULT_MODE.get("tabs", [])
        if isinstance(t, dict) and t.get("id")
    ]
    pinned_ids = {str(t.get("id")) for t in tabs if isinstance(t, dict)}
    for i, dt in enumerate(default_tabs):
        tid = str(dt.get("id"))
        if tid in pinned_ids:
            continue
        if not tabstore.is_enabled(workspace, tid):
            continue
        # Insert just after the previous default-tab that's actually
        # present (so the new tab lands in its DEFAULT_MODE
        # neighbourhood). Falls back to append if no anchor exists.
        anchor: int | None = None
        for prev in reversed(default_tabs[:i]):
            prev_id = str(prev.get("id"))
            for j, existing in enumerate(tabs):
                if str(existing.get("id")) == prev_id:
                    anchor = j + 1
                    break
            if anchor is not None:
                break
        injected = {**dt, "source": dt.get("source") or "core"}
        if anchor is None:
            tabs.append(injected)
        else:
            tabs.insert(anchor, injected)
        pinned_ids.add(tid)
    pack_tabs = packstore.pack_tabs_for(workspace)
    # Skip pack tabs already pinned in mode.json (the user may
    # have manually re-ordered them — keep their position).
    for pt in pack_tabs:
        if pt.get("id") not in pinned_ids:
            tabs.append(pt)
    return {**mode, "tabs": tabs}
