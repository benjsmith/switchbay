"""Analysis documents and the LLM slug helper route.

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
import re
from aiohttp import web
from switchbay import analyses
from switchbay import llmgateway
from switchbay import protocol
from switchbay import sketches

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

async def handle_analyses_list(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    # Walks wiki/ + analyses/ reading every file's frontmatter — off-thread.
    listed = await asyncio.to_thread(analyses.list_analyses, workspace)
    return web.json_response({"analyses": listed})

async def handle_analysis_get(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    p = request.query.get("path", "").strip() or request.query.get("slug", "").strip()
    if not p:
        return web.json_response({"error": "path or slug required"}, status=400)
    a = analyses.load_analysis(workspace, p)
    if a is None:
        return web.json_response({"error": "not an analysis page"}, status=404)
    return web.json_response({"analysis": a})

async def handle_analysis_by_slide(request: web.Request) -> web.Response:
    """Find a leftover analysis/deck wiki page whose `slides[]`
    contains a given sketch id. Sketch tab no longer enters deck
    mode; this remains for wiki/legacy lookup only."""
    workspace: Path = request.app["workspace"]
    sid = request.query.get("sketch_id", "").strip()
    if not sid:
        return web.json_response({"error": "sketch_id required"}, status=400)
    for meta in analyses.list_analyses(workspace):
        slides = meta.get("slides") or []
        if sid in slides:
            full = analyses.load_analysis(workspace, meta["path"])
            if full is not None:
                return web.json_response({"analysis": full})
    return web.json_response({"analysis": None})

async def handle_analysis_delete(request: web.Request) -> web.Response:
    """Tear a leftover analysis/deck wiki page down: cancel any
    tagged run, delete member sketches, then delete the page.
    Sketch tab no longer exposes this; kept for API/legacy use."""
    workspace: Path = request.app["workspace"]
    path = request.query.get("path", "").strip()
    if not path:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            body = {}
        path = str(body.get("path") or "").strip()
    if not path:
        return web.json_response({"error": "path required"}, status=400)

    a = analyses.load_analysis(workspace, path)
    if a is None:
        return web.json_response(
            {"error": f"analysis not found: {path}"}, status=404,
        )

    # 1. Cancel any populate run targeting this analysis. Match on
    #    the analysis_path tag we attach in handle_analysis_populate;
    #    fall back to the input_excerpt prefix for older runs.
    runs: dict[str, dict[str, Any]] = request.app.setdefault("runs", {})
    cancelled: list[str] = []
    for rid, rec in list(runs.items()):
        same = (
            rec.get("analysis_path") == a["path"]
            or str(rec.get("input_excerpt") or "").startswith(f"populate {a['path']}")
        )
        if not same:
            continue
        task = rec.get("task")
        if task is not None and not task.done():
            task.cancel()
        cancelled.append(rid)

    # 2. Delete every member sketch + its PNG export.
    deleted_sketches: list[str] = []
    for sid in a.get("slides") or []:
        try:
            if sketches.delete_sketch(workspace, str(sid)):
                deleted_sketches.append(str(sid))
        except ValueError:
            continue

    # 3. Delete the analysis page itself. resolve_doc_path tolerates
    #    flat-wiki + wiki/analyses/ + bare-slug input.
    page = analyses.resolve_doc_path(workspace, a["path"])
    if page is not None and page.is_file():
        try:
            page.unlink()
        except OSError as e:
            log.warning("failed to remove analysis page %s: %s", page, e)

    # 4. Tell every WS client the wiki shape changed and schedule a
    #    graph rebuild so the deck disappears from sidebar/graph.
    await _daemon_ns._broadcast(request.app, protocol.files_changed())
    try:
        asyncio.create_task(_daemon_ns._rebuild_graph_async(request.app))
    except Exception:  # noqa: BLE001
        log.exception("graph rebuild scheduling failed (deck delete)")

    return web.json_response({
        "ok": True,
        "deleted_sketches": deleted_sketches,
        "cancelled_runs": cancelled,
        "page_removed": (page is not None and not page.is_file()),
    })

async def handle_analysis_set_slides(request: web.Request) -> web.Response:
    """Replace the slides list on an analysis-or-deck. The Sketch
    tab calls this from its Delete handler to drop a slide id from
    the analysis frontmatter before deleting the underlying sketch
    — otherwise deck mode keeps the missing id and the user sees
    a half-broken deck that visually reads as "all slides gone."""
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    path = str(body.get("path") or "").strip()
    if not path:
        return web.json_response({"error": "path required"}, status=400)
    slides = body.get("slides")
    if not isinstance(slides, list):
        return web.json_response(
            {"error": "slides must be a list"}, status=400,
        )
    updated = analyses.set_slides(workspace, path, [str(s) for s in slides])
    if updated is None:
        return web.json_response({"error": f"analysis not found: {path}"}, status=404)
    # The body rewrite changed the rendered figures; schedule a
    # background graph rebuild so the sidebar/graph reflect it.
    try:
        asyncio.create_task(_daemon_ns._rebuild_graph_async(request.app))
    except Exception:  # noqa: BLE001
        log.exception("graph rebuild scheduling failed (set_slides)")
    return web.json_response({"analysis": updated})

async def handle_analysis_set_note(request: web.Request) -> web.Response:
    """Set/clear a single slide's presenter note. The Sketch tab's
    deck-mode notes textarea autosaves here. Body:
    `{path, sketch_id, note}` — a blank note clears it. Only touches
    frontmatter (no figure change → no graph rebuild)."""
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    path = str(body.get("path") or "").strip()
    sketch_id = str(body.get("sketch_id") or "").strip()
    if not path or not sketch_id:
        return web.json_response(
            {"error": "path and sketch_id required"}, status=400,
        )
    note = str(body.get("note") or "")
    # Off-thread: the analysis .md lives under wiki/ which may be on a
    # cloud-sync service (an evicted write would block the loop).
    updated = await asyncio.to_thread(
        analyses.set_note, workspace, path, sketch_id, note,
    )
    if updated is None:
        return web.json_response({"error": f"analysis not found: {path}"}, status=404)
    return web.json_response({"analysis": updated})

async def handle_analysis_append(request: web.Request) -> web.Response:
    """Append a sketch id to an analysis's slides list. Used by the
    Sketch tab's Add Sketch button when an analysis is active."""
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    slug = str(body.get("slug") or "").strip()
    sketch_id = str(body.get("sketch_id") or "").strip()
    if not slug or not sketch_id:
        return web.json_response({"error": "slug and sketch_id required"}, status=400)
    a = analyses.append_slide(workspace, slug, sketch_id)
    if a is None:
        return web.json_response({"error": "analysis not found"}, status=404)
    return web.json_response({"analysis": a})

async def handle_analysis_compose(request: web.Request) -> web.Response:
    """Create a fresh analysis from existing slides — the "remix"
    path. Body: {title, slides: [...], sources?: [...], body?}. The
    same sketch can be referenced by many analyses (different stories
    over the same library)."""
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    title = str(body.get("title") or "").strip()
    slides = body.get("slides")
    if not isinstance(slides, list) or not all(isinstance(s, str) for s in slides):
        return web.json_response({"error": "slides must be a list of sketch ids"}, status=400)
    sources = body.get("sources") if isinstance(body.get("sources"), list) else []
    narrative = body.get("body") if isinstance(body.get("body"), str) else None
    a = analyses.save_analysis(
        workspace, title=title, slides=slides,
        sources=list(sources), body=narrative,
    )
    return web.json_response({"analysis": a})

async def handle_llm_slug(request: web.Request) -> web.Response:
    """Compact a long sketch / analysis title into a 3-4 word slug
    suitable for a filename. Used by the Sketch tab when creating a
    new sketch with a long title — keeps the filename readable. Falls
    back to a deterministic word-truncating slug when no provider is
    configured / available, so behaviour is well-defined offline."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    title = str(body.get("title") or "").strip()
    if not title:
        return web.json_response({"slug": ""})
    # Cheap path: short titles don't need the model.
    words = re.findall(r"[A-Za-z0-9]+", title)
    if len(words) <= 4:
        return web.json_response({"slug": "-".join(w.lower() for w in words)})

    pid = _daemon_ns._resolve_default_provider()
    try:
        provider = llmgateway.get(pid)
    except llmgateway.ProviderError:
        provider = None
    if provider is None or not provider.has_key():
        # Deterministic fallback: take the first 4 word-tokens.
        return web.json_response({"slug": "-".join(w.lower() for w in words[:4])})

    workspace: Path = request.app["workspace"]
    req = llmgateway.ChatRequest(
        messages=[{"role": "user", "content": (
            f"Compact this title into a 3-4 word lowercase hyphen-separated slug "
            f"suitable for a filename. Return ONLY the slug, no other text, no quotes.\n\n"
            f"Title: {title}"
        )}],
        model=_daemon_ns._effective_model(pid) or provider.PROVIDER.get("default_model"),
        max_tokens=32,
        reasoning_effort=_daemon_ns._effort_for(
            pid, _daemon_ns._effective_model(pid), "background"),
        workspace=str(workspace),
    )
    accumulated = ""
    try:
        async for ev in provider.chat_stream(req):
            if isinstance(ev, llmgateway.TextChunk):
                accumulated += ev.text
            if isinstance(ev, llmgateway.DoneChunk):
                break
    except Exception:  # noqa: BLE001
        log.exception("slug compaction failed; using deterministic fallback")
        return web.json_response({"slug": "-".join(w.lower() for w in words[:4])})
    raw = accumulated.strip().splitlines()[0] if accumulated.strip() else ""
    cleaned = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    if not cleaned:
        cleaned = "-".join(w.lower() for w in words[:4])
    return web.json_response({"slug": cleaned})
