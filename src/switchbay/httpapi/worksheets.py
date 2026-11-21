"""Worksheet snapshots and slideshow-from-markdown.

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
from aiohttp import web
from switchbay import protocol
from switchbay import slideshow_from_md
from switchbay import tabstore
from switchbay import worksheets_store

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

async def handle_worksheets_list(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    items = await asyncio.to_thread(worksheets_store.list_packages, workspace)
    return web.json_response({"worksheets": items})

async def handle_worksheet_get(request: web.Request) -> web.Response:
    """Load a named worksheet snapshot. Query: ?slug="""
    workspace: Path = request.app["workspace"]
    slug = str(request.rel_url.query.get("slug") or "").strip()
    if not worksheets_store.is_valid_slug(slug):
        return web.json_response({"error": "invalid slug"}, status=400)
    snap = await asyncio.to_thread(worksheets_store.load_snapshot, workspace, slug)
    if snap is None:
        return web.json_response({"error": "not found"}, status=404)
    title = slug
    try:
        meta = worksheets_store.package_dir(workspace, slug) / "meta.json"
        if meta.is_file():
            m = json.loads(meta.read_text(encoding="utf-8"))
            if isinstance(m, dict) and m.get("title"):
                title = str(m["title"])
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return web.json_response({
        "slug": slug, "title": title, "snapshot": snap,
    })

async def handle_worksheet_save(request: web.Request) -> web.Response:
    """Save snapshot as named worksheet. Body: {slug, title?, snapshot}."""
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    slug = str((body or {}).get("slug") or "").strip()
    if not slug:
        title_for_slug = str((body or {}).get("title") or "worksheet")
        slug = worksheets_store.slugify(title_for_slug)
    if not worksheets_store.is_valid_slug(slug):
        return web.json_response({"error": "invalid slug"}, status=400)
    snap = (body or {}).get("snapshot")
    if not isinstance(snap, dict):
        return web.json_response({"error": "snapshot must be an object"}, status=400)
    title = str((body or {}).get("title") or slug).strip()
    summary = str((body or {}).get("summary") or "")
    result = await asyncio.to_thread(
        worksheets_store.save_snapshot,
        workspace, slug, snap, title=title, summary=summary,
    )
    await _daemon_ns._broadcast(request.app, protocol.files_changed())
    return web.json_response(result)

async def handle_worksheet_open(request: web.Request) -> web.Response:
    """Open named worksheet in Sheet tab (client loads snapshot)."""
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}
    slug = str((body or {}).get("slug") or "").strip()
    if not worksheets_store.is_valid_slug(slug):
        return web.json_response({"error": "invalid slug"}, status=400)
    snap = await asyncio.to_thread(worksheets_store.load_snapshot, workspace, slug)
    if snap is None:
        return web.json_response({"error": "not found"}, status=404)
    title = slug
    try:
        meta = worksheets_store.package_dir(workspace, slug) / "meta.json"
        if meta.is_file():
            m = json.loads(meta.read_text(encoding="utf-8"))
            if isinstance(m, dict) and m.get("title"):
                title = str(m["title"])
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    await _daemon_ns._broadcast(request.app, protocol.custom({
        "type": "open_worksheet",
        "slug": slug,
        "title": title,
        "snapshot": snap,
    }))
    await _daemon_ns._broadcast(request.app, protocol.nav("univer", {}, "Sheet"))
    return web.json_response({"ok": True, "slug": slug, "title": title})

async def handle_slideshow_from_md(request: web.Request) -> web.Response:
    """Build an HTML slideshow from author markdown.

    Body::
      {
        "path": "notes/my-deck.md",   # workspace-relative (or absolute under ws)
        "markdown": "…",              # alt: raw MD (no path)
        "slug": "optional-slug",
        "title": "optional override",
        "wiki_topics": ["transformer"],
        "generate_media": true,       # image prompts + TTS (default true)
        "generate_images": null,      # override image gen only
        "generate_voice": null,       # override TTS only
        "open": true                  # open Slideshow tab when done
      }

    Long-running (image/TTS network) — runs in a worker thread.
    """
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}
    body = body or {}
    md_path = str(body.get("path") or body.get("md_path") or "").strip() or None
    markdown = body.get("markdown")
    if markdown is not None:
        markdown = str(markdown)
    if not md_path and not markdown:
        return web.json_response(
            {"error": "path or markdown required"}, status=400,
        )
    slug = str(body.get("slug") or "").strip() or None
    title = str(body.get("title") or "").strip() or None
    wiki_topics = body.get("wiki_topics")
    if wiki_topics is not None and not isinstance(wiki_topics, list):
        wiki_topics = [str(wiki_topics)]
    generate_media = body.get("generate_media")
    if generate_media is None:
        generate_media = True
    generate_images = body.get("generate_images")
    generate_voice = body.get("generate_voice")
    open_tab = bool(body.get("open", True))

    def _run() -> dict:
        return slideshow_from_md.build_from_markdown(
            workspace,
            md_path,
            markdown=markdown,
            slug=slug,
            title=title,
            wiki_topics=wiki_topics,
            generate_media=bool(generate_media),
            generate_images=None if generate_images is None else bool(generate_images),
            generate_voice=None if generate_voice is None else bool(generate_voice),
        )

    try:
        result = await asyncio.to_thread(_run)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    except FileNotFoundError as e:
        return web.json_response({"error": str(e)}, status=404)
    except Exception as e:  # noqa: BLE001
        log.exception("slideshow_from_md failed")
        return web.json_response({"error": str(e)}, status=500)

    if open_tab and result.get("ok"):
        await _open_html_deck_tab(
            request.app, workspace,
            str(result["slug"]), str(result.get("title") or result["slug"]),
        )
    return web.json_response(result)

async def _open_html_deck_tab(
    app: web.Application, workspace: Path, slug: str, title: str,
) -> None:
    try:
        await asyncio.to_thread(tabstore.add_html_deck_tab, workspace)
        await _daemon_ns._broadcast(app, _daemon_ns._hello_payload(app))
        await _daemon_ns._broadcast(app, protocol.custom({
            "type": "open_html_deck",
            "slug": slug,
            "title": title,
        }))
    except Exception:  # noqa: BLE001
        log.exception("open_html_deck_tab failed for %s", slug)
