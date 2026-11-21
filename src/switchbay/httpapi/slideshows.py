"""HTML slideshow open, close, file, and PDF routes.

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
import os
from aiohttp import web
from switchbay import html_decks
from switchbay import protocol
from switchbay import tabstore

from switchbay.httpapi._ns import _daemon_ns

# ── Workspace HTML decks (`decks/<slug>/`) ──────────────────────────


async def handle_decks_list(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    decks = await asyncio.to_thread(html_decks.list_decks, workspace)
    return web.json_response({"decks": decks})

async def handle_deck_file(request: web.Request) -> web.StreamResponse:
    """Serve decks/<slug>/… for the HtmlDeck iframe (relative media)."""
    workspace: Path = request.app["workspace"]
    slug = request.match_info.get("slug", "").strip()
    rel = request.match_info.get("path", "").strip()
    if not rel:
        rel = "index.html"
    path = await asyncio.to_thread(html_decks.resolve_file, workspace, slug, rel)
    if path is None:
        return web.json_response({"error": "not found"}, status=404)
    return web.FileResponse(path=path)

async def handle_deck_open(request: web.Request) -> web.Response:
    """Open a deck in the HtmlDeck tab. Body: {slug}."""
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}
    slug = str((body or {}).get("slug") or request.rel_url.query.get("slug") or "").strip()
    if not html_decks.is_valid_slug(slug):
        return web.json_response({"error": "invalid slug"}, status=400)
    entry = await asyncio.to_thread(html_decks.entry_html, workspace, slug)
    if entry is None:
        return web.json_response({"error": f"no deck {slug!r}"}, status=404)
    title = slug
    try:
        meta_path = html_decks.deck_dir(workspace, slug) / "deck.json"
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(meta, dict) and meta.get("title"):
                title = str(meta["title"])
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    await _daemon_ns._open_html_deck_tab(request.app, workspace, slug, title)
    return web.json_response({
        "ok": True, "slug": slug, "title": title,
        "url": f"/api/slideshows/{slug}/index.html",
    })

async def handle_slideshow_close(request: web.Request) -> web.Response:
    """Close the Slideshow tab (its own ✕). Removes it from mode.json,
    broadcasts the new tab set, and focuses Graph so the pane doesn't
    blank. Reopen with `/slideshow <slug>` or a slideshow wikilink."""
    workspace: Path = request.app["workspace"]
    removed = await asyncio.to_thread(tabstore.remove_html_deck_tab, workspace)
    if removed:
        await _daemon_ns._broadcast(request.app, _daemon_ns._hello_payload(request.app))
        await _daemon_ns._broadcast(request.app, protocol.nav("graph", {}, "Graph"))
    return web.json_response({"ok": True, "removed": removed})

def _pdf_render_error(detail: str) -> tuple[str, int]:
    """Classify renderer failure: missing runtime vs browser vs spawn."""
    blob = (detail or "").lower()
    if "cannot find package" in blob or "cannot find module" in blob:
        return (
            "PDF renderer cannot resolve Playwright. "
            "Install frontend deps with `pnpm --dir frontend install --frozen-lockfile`.",
            503,
        )
    if "executable doesn't exist" in blob or "browserType.launch" in blob:
        return (
            "Playwright Chromium is not installed. "
            "Run `pnpm --dir frontend exec playwright install chromium`.",
            503,
        )
    if "enoent" in blob or "no such file" in blob:
        return ("PDF renderer failed to spawn Node or Playwright.", 503)
    return ("PDF rendering failed", 500)

async def handle_slideshow_pdf(request: web.Request) -> web.Response:
    """Render every HTML slide to one 16:9 PDF page under vault/exports."""
    from switchbay import runtime
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}
    slug = str((body or {}).get("slug") or "").strip()
    if not html_decks.is_valid_slug(slug):
        return web.json_response({"error": "invalid slideshow slug"}, status=400)
    if await asyncio.to_thread(html_decks.entry_html, workspace, slug) is None:
        return web.json_response({"error": "slideshow not found"}, status=404)
    spawn_env = runtime.spawn_env()
    node = runtime.resolve_node(spawn_env)
    renderer = (
        Path(_daemon_ns.__file__).resolve().parents[2]
        / "frontend" / "scripts" / "render-slideshow-pdf.mjs"
    )
    if not node:
        return web.json_response({
            "error": "Node.js is not installed or not executable",
            "detail": "PDF export needs a Node runtime on PATH (nvm, Homebrew, or Volta).",
        }, status=503)
    if not renderer.is_file():
        return web.json_response(
            {"error": "PDF renderer is not installed"}, status=503,
        )
    exports = workspace / "vault" / "exports"
    await asyncio.to_thread(exports.mkdir, parents=True, exist_ok=True)
    destination = exports / f"{slug}.pdf"
    temporary = exports / f".{slug}.rendering.pdf"
    port = int(request.app.get("daemon_port") or 8765)
    url = f"http://127.0.0.1:{port}/api/slideshows/{slug}/index.html"
    proc: asyncio.subprocess.Process | None = None
    try:
        try:
            proc = await asyncio.create_subprocess_exec(
                node,
                str(renderer),
                url,
                str(temporary),
                cwd=str(renderer.parent.parent),
                env=spawn_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as e:
            return web.json_response({
                "error": "PDF renderer failed to spawn",
                "detail": str(e),
            }, status=503)
        output, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode != 0 or not temporary.is_file():
            detail = output.decode(errors="replace")[-1600:]
            msg, status = _pdf_render_error(detail)
            return web.json_response({
                "error": msg,
                "detail": detail or "Install the Playwright Chromium browser.",
            }, status=status)
        await asyncio.to_thread(os.replace, temporary, destination)
    except asyncio.TimeoutError:
        if proc is not None:
            proc.kill()
            try:
                await proc.communicate()
            except Exception:  # noqa: BLE001
                pass
        return web.json_response({"error": "PDF rendering timed out"}, status=504)
    finally:
        if temporary.is_file():
            await asyncio.to_thread(temporary.unlink)
    await _daemon_ns._broadcast(request.app, protocol.files_changed())
    return web.json_response({
        "ok": True,
        "path": destination.relative_to(workspace).as_posix(),
        "bytes": destination.stat().st_size,
    })
