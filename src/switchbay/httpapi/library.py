"""Library search and report-package routes.

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
from switchbay import library
from switchbay import protocol
from switchbay import report_html
from switchbay import report_packages
from switchbay import tabstore

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

# ── Library (reports · slideshows · worksheets) ─────────────────────


async def handle_library_list(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    data = await asyncio.to_thread(library.list_all, workspace)
    return web.json_response(data)

async def handle_library_search(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    q = str(request.rel_url.query.get("q") or "").strip()
    try:
        limit = int(request.rel_url.query.get("limit") or 40)
    except ValueError:
        limit = 40
    hits = await asyncio.to_thread(library.search, workspace, q, limit=limit)
    return web.json_response({"q": q, "hits": hits})

async def handle_report_packages_list(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    items = await asyncio.to_thread(report_packages.list_packages, workspace)
    return web.json_response({"reports": items})

async def handle_report_package_file(request: web.Request) -> web.StreamResponse:
    workspace: Path = request.app["workspace"]
    slug = request.match_info.get("slug", "").strip()
    rel = request.match_info.get("path", "").strip() or "index.html"
    path = await asyncio.to_thread(
        report_packages.resolve_file, workspace, slug, rel,
    )
    if path is None:
        # try default entry
        path = await asyncio.to_thread(report_packages.entry_path, workspace, slug)
    if path is None or not path.is_file():
        return web.json_response({"error": "not found"}, status=404)
    if path.suffix.lower() in {".html", ".htm"}:
        text = await asyncio.to_thread(path.read_text, encoding="utf-8")
        # aiohttp forbids charset= in content_type when `text=` is used.
        return web.Response(
            text=report_html.linkify_report_html(text),
            content_type="text/html",
            headers={"X-Content-Type-Options": "nosniff"},
        )
    return web.FileResponse(path=path)

async def handle_report_packages_close(request: web.Request) -> web.Response:
    """Close the durable Report-doc tab (Library package viewer).

    Same contract as Reviews / Slideshow ✕: drop the transient tab from
    mode.json, broadcast hello, focus Graph so the pane does not keep an
    empty shell.
    """
    workspace: Path = request.app["workspace"]
    removed = await asyncio.to_thread(tabstore.remove_report_doc_tab, workspace)
    if removed:
        await _daemon_ns._broadcast(request.app, _daemon_ns._hello_payload(request.app))
        await _daemon_ns._broadcast(request.app, protocol.nav("graph", {}, "Graph"))
    return web.json_response({"ok": True, "removed": removed})

async def handle_report_package_open(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}
    slug = str((body or {}).get("slug") or "").strip()
    if not report_packages.is_valid_slug(slug):
        return web.json_response({"error": "invalid slug"}, status=400)
    entry = await asyncio.to_thread(report_packages.entry_path, workspace, slug)
    if entry is None:
        return web.json_response({"error": f"no report {slug!r}"}, status=404)
    title = slug
    try:
        meta_p = report_packages.package_dir(workspace, slug) / "report.json"
        if meta_p.is_file():
            meta = json.loads(meta_p.read_text(encoding="utf-8"))
            if isinstance(meta, dict) and meta.get("title"):
                title = str(meta["title"])
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    await _open_report_doc_tab(request.app, workspace, slug, title)
    return web.json_response({
        "ok": True, "slug": slug, "title": title,
        "url": f"/api/report-packages/{slug}/",
    })

async def handle_report_package_promote(request: web.Request) -> web.Response:
    """Promote ephemeral statedir report → durable reports/<slug>/."""
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}
    rid = str((body or {}).get("report_id") or "").strip()
    slug = str((body or {}).get("slug") or "").strip() or None
    if not rid:
        return web.json_response({"error": "report_id required"}, status=400)
    try:
        result = await asyncio.to_thread(
            report_packages.import_from_ephemeral, workspace, rid, slug=slug,
        )
    except FileNotFoundError as e:
        return web.json_response({"error": str(e)}, status=404)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response(result)

async def _open_report_doc_tab(
    app: web.Application, workspace: Path, slug: str, title: str,
) -> None:
    try:
        await asyncio.to_thread(tabstore.add_report_doc_tab, workspace)
        await _daemon_ns._broadcast(app, _daemon_ns._hello_payload(app))
        await _daemon_ns._broadcast(app, protocol.custom({
            "type": "open_report_doc",
            "slug": slug,
            "title": title,
        }))
    except Exception:  # noqa: BLE001
        log.exception("open_report_doc_tab failed for %s", slug)
