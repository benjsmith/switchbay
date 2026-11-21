"""Pack install, file serving, and registry routes.

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
import uuid
from aiohttp import web
from switchbay import ingest_run_drain
from switchbay import pack_run_drain
from switchbay import packstore
from switchbay import protocol
from switchbay import sketches
from switchbay import skillkit
from switchbay import slide_layouts

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

async def handle_packs_list(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    return web.json_response({"packs": packstore.list_packs(workspace)})

async def handle_file_routes(request: web.Request) -> web.Response:
    """Aggregate `file_routes` from every installed pack into a
    single per-extension lookup table. The file browser uses this
    to drive click + context-menu behaviour without hard-coding
    file-type knowledge in the frontend.

    Shape: `{ routes: [{ext, action, label, endpoint, tab_kind, …,
                        pack, scope}, …] }`
    """
    workspace: Path = request.app["workspace"]
    return web.json_response({
        "routes": packstore.file_routes_for(workspace),
    })

async def handle_packs_install(request: web.Request) -> web.Response:
    """Install a pack from a git URL or local path. Body shape:
        {"source": "https://github.com/foo/bar" | "/abs/path",
         "scope": "workspace" | "user"}
    URL-shape inputs go through `git clone --depth 1`; absolute paths
    are deep-copied. Both validate the manifest before the install
    becomes permanent."""
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    source = str(body.get("source") or "").strip()
    scope = str(body.get("scope") or "workspace").strip()
    if not source:
        return web.json_response({"error": "source is required"}, status=400)
    if scope not in ("workspace", "user"):
        return web.json_response({"error": "invalid scope"}, status=400)
    looks_like_url = (
        source.startswith(("http://", "https://", "git@", "ssh://", "git+"))
        or source.endswith(".git")
    )
    try:
        if looks_like_url:
            rec = await packstore.install_from_git(
                source, workspace=workspace, scope=scope,
            )
        else:
            rec = packstore.install_from_path(
                Path(source), workspace=workspace, scope=scope,
            )
            # install_from_path is synchronous (no clone), so the
            # remote-skill fetch has to run separately. install_from_git
            # already triggers it inline.
            try:
                fetch_report = await packstore.fetch_remote_skills(
                    Path(rec["path"]),
                )
                if not fetch_report.get("ok"):
                    log.warning(
                        "pack %s: skill fetch partial: %s",
                        rec.get("name"), fetch_report,
                    )
            except Exception:  # noqa: BLE001
                log.exception(
                    "pack %s: skill fetch crashed", rec.get("name"),
                )
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({"pack": rec})

async def handle_figure_file(request: web.Request) -> web.StreamResponse:
    """Serve a PNG (or any binary) referenced from rendered wiki HTML.

    The URL `/figures/<rel>` is overloaded across two conventions
    because CE and switchbay both emit `figures/...` image refs:

      · `<workspace>/figures/<id>.png` — switchbay sketch exports
        (Excalidraw/drawio PNGs from the Sketch tab). Flat layout
        because the figure id is the sketch id.
      · `<workspace>/wiki/figures/<rel>` — CE-extracted images
        (PDF page rasters, paste-board images, `_assets/...` mirrors).
        Lives under wiki/ because CE treats figures as wiki content
        and rewrites `<img>` paths relative to the wiki tree.

    Look-up order: sketches first (own writes), wiki/ second (CE
    fallback). Path-traversal blocked by resolving + checking
    containment under the chosen root.
    """
    workspace: Path = request.app["workspace"]
    rel = request.match_info.get("path", "").strip()
    if not rel:
        return web.json_response({"error": "path required"}, status=400)
    roots = [
        # CE-native asset home (2026-07-05 convention migration) —
        # sketch exports write here now; `/figures/<id>.png` URLs
        # from older pages resolve here too.
        (workspace / "wiki" / "figures" / "_assets").resolve(),
        # Legacy workspace-root exports (pre-migration workspaces,
        # collision leftovers).
        (workspace / "figures").resolve(),
        # CE full wiki-relative refs (`_assets/...` and figure pages).
        (workspace / "wiki" / "figures").resolve(),
    ]
    candidate: Path | None = None
    sketch_root = roots[0]
    for root in roots:
        if not root.is_dir():
            continue
        c = (root / rel).resolve()
        if not _daemon_ns._within(root, c):
            continue
        if c.is_file():
            candidate = c
            break
    if candidate is not None:
        return web.FileResponse(path=candidate)
    # On-demand server-side raster: if rel is `<sketch-id>.png` and
    # the underlying sketch JSON exists, render via Pillow and cache
    # to disk so the analysis-doc image refs resolve even for slides
    # whose canonical Excalidraw export hasn't run client-side yet.
    sketch_target = (sketch_root / rel).resolve()
    if rel.endswith(".png") and _daemon_ns._within(sketch_root, sketch_target):
        stem = sketch_target.stem
        if stem:
            try:
                rec = sketches.get_sketch(workspace, stem)
            except ValueError:
                rec = None
            if (
                rec
                and rec.get("kind") == "excalidraw"
                and isinstance(rec.get("data"), dict)
            ):
                try:
                    # Pillow rasterization + write are CPU/IO heavy —
                    # off the event loop so a slide render can't wedge it.
                    def _raster() -> None:
                        png_bytes = slide_layouts.rasterize_scene_png(rec["data"])
                        sketch_root.mkdir(parents=True, exist_ok=True)
                        sketch_target.write_bytes(png_bytes)

                    await asyncio.to_thread(_raster)
                    return web.FileResponse(path=sketch_target)
                except Exception:  # noqa: BLE001
                    log.exception(
                        "on-demand raster failed for sketch %s", stem,
                    )
    return web.json_response({"error": "file not found"}, status=404)

async def handle_pack_file(request: web.Request) -> web.StreamResponse:
    """Serve a file from inside an installed pack — the runtime
    extension hook for pack-supplied tab modules. Path traversal is
    blocked by resolving the candidate path and confirming it stays
    inside the pack's directory.

    URL: GET /api/packs/<name>/files/<path...>
    Pack name is matched via the existing list_packs registry so a
    user can drop a pack in either scope and the loader finds it.
    """
    workspace: Path = request.app["workspace"]
    name = request.match_info.get("name", "").strip()
    rel = request.match_info.get("path", "").strip()
    if not name or not rel:
        return web.json_response({"error": "name + path required"}, status=400)
    rec = packstore.get_pack(workspace, name)
    if rec is None:
        return web.json_response({"error": "pack not found"}, status=404)
    pack_dir = Path(str(rec.get("path") or "")).resolve()
    if not pack_dir.is_dir():
        return web.json_response({"error": "pack dir missing"}, status=404)
    candidate = (pack_dir / rel).resolve()
    if not _daemon_ns._within(pack_dir, candidate):
        return web.json_response({"error": "path outside pack"}, status=400)
    if not candidate.is_file():
        return web.json_response({"error": "file not found"}, status=404)
    # Best-effort content-type — JS / CSS / JSON / images. aiohttp's
    # FileResponse handles streaming + range headers natively.
    return web.FileResponse(path=candidate)

async def handle_pack_action(request: web.Request) -> web.Response:
    """Run a pack's file-route action on a workspace file by dispatching
    a background agent with the pack's `<pack>-<action>` skill loaded.
    Generic over packs: a pack declaring a `file_routes` entry for an
    extension POSTs here (`/api/packs/<pack>/action/<action>` with
    `{path}`). Returns `{run_id}` immediately — the work runs as a
    background agent; watch it in the Agents tab. The wiki page / figures
    it writes appear when it finishes."""
    workspace: Path = request.app["workspace"]
    pack = request.match_info.get("pack", "").strip()
    action = request.match_info.get("action", "").strip()
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    rel = str(body.get("path") or "").strip()
    if not pack or not action or not rel:
        return web.json_response({"error": "pack, action, path required"}, status=400)
    candidate = (workspace / rel).resolve()
    if not _daemon_ns._within(workspace, candidate):
        return web.json_response({"error": "path outside workspace"}, status=400)
    if not candidate.is_file():
        return web.json_response({"error": "file not found"}, status=404)
    rec = packstore.get_pack(workspace, pack)
    if rec is None:
        return web.json_response({"error": f"pack not found: {pack}"}, status=404)
    if not rec.get("enabled"):
        return web.json_response(
            {"error": f"pack '{pack}' is not active — activate it in Settings → Packs"},
            status=409,
        )
    skill = f"{pack}-{action}"
    if skillkit.get_skill(workspace, skill) is None:
        return web.json_response({"error": f"pack skill not found: {skill}"}, status=404)
    prompt = (
        f"Load the `{skill}` skill with load_skill(\"{skill}\") and follow it "
        f"exactly to handle the file `{rel}` in this workspace. The `{pack}` "
        f"pack is active. Route every output to the workspace per the skill — "
        f"`wiki/` pages, `figures/` PNGs, `data/` tables — and finish with a "
        f"one-line summary naming what you wrote."
    )
    run_id = f"run-{uuid.uuid4().hex[:8]}"

    async def _runner() -> None:
        try:
            await _daemon_ns._dispatch_chat(
                request.app, ws=None, text=prompt,
                input_excerpt=f"{pack}:{action} {candidate.name}", run_id=run_id,
            )
        except Exception:  # noqa: BLE001
            log.exception("pack-action run %s crashed", run_id)

    task = asyncio.create_task(_runner())
    task.add_done_callback(_daemon_ns._make_dispatch_error_surface(request.app, run_id))

    async def _tag_run() -> None:
        await asyncio.sleep(0)
        runs = request.app.get("runs") or {}
        r = runs.get(run_id)
        if r is not None:
            r["kind"] = f"pack:{pack}:{action}"
            r["vault_path"] = rel
    asyncio.create_task(_tag_run())
    return web.json_response({"run_id": run_id, "pack": pack, "action": action})

async def handle_packs_drain(request: web.Request) -> web.Response:
    """Drain CE-queued ``.workbench/pack-runs/*.json`` into rail LLM seats.

    CE's proxied filebrowser only writes ``status: queued`` files; this
    endpoint (and the background poll loop) seats ``_dispatch_chat`` the
    same way ``handle_pack_action`` does. Returns
    ``{drained, skipped, errors, …}``.
    """
    summary = await pack_run_drain.drain_once(request.app)
    return web.json_response(summary)

async def handle_ingest_drain(request: web.Request) -> web.Response:
    """Drain CE-queued ``.workbench/ingest-runs/*.json``.

    Prefer deterministic ``local_ingest``; escalate to rail LLM only when
    run metadata opts in (see ``docs/architecture.md``). Returns
    ``{drained, skipped, errors, …}``.
    """
    summary = await ingest_run_drain.drain_once(request.app)
    return web.json_response(summary)

async def handle_packs_uninstall(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    name = request.query.get("name", "").strip()
    scope = request.query.get("scope", "workspace").strip()
    if not name:
        return web.json_response({"error": "name required"}, status=400)
    if scope not in ("workspace", "user"):
        return web.json_response({"error": "invalid scope"}, status=400)
    try:
        ok = packstore.uninstall_pack(name, workspace=workspace, scope=scope)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({"ok": ok})

async def handle_packs_toggle(request: web.Request) -> web.Response:
    """Soft enable/disable a pack without deleting it from disk.
    Body: `{name, scope, enabled}`. System-scope packs reject the
    call — there's no off switch for bundled packs."""
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    name = str(body.get("name") or "").strip()
    scope = str(body.get("scope") or "").strip()
    enabled = bool(body.get("enabled"))
    if not name:
        return web.json_response({"error": "name required"}, status=400)
    if scope not in ("workspace", "user", "system"):
        return web.json_response({"error": "invalid scope"}, status=400)
    try:
        packstore.set_enabled(workspace, scope, name, enabled)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    # Tell connected clients the tab/route table just shifted so
    # the file browser + tab strip refresh their caches.
    await _daemon_ns._broadcast(request.app, protocol.files_changed())
    return web.json_response({
        "ok": True,
        "pack": next(
            (p for p in packstore.list_packs(workspace)
             if p.get("name") == name and p.get("scope") == scope),
            None,
        ),
    })
