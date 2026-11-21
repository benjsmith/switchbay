"""OWID import and the intro/walkthrough routes.

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
from switchbay import owid
from switchbay import proposals
from switchbay import protocol
from switchbay import tabstore

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

async def handle_owid_search(request: web.Request) -> web.Response:
    """Browse the OWID starter catalog (client filters further)."""
    q = request.query.get("q", "")
    return web.json_response({"charts": await asyncio.to_thread(owid.search, q)})

async def handle_owid_import(request: web.Request) -> web.Response:
    """Import an OWID chart (bare slug or grapher URL) into the workspace:
    save its CSV under data/owid/ and author a starter Vega-Lite plot.
    On success, refresh files + jump to the Plot tab."""
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    slug = str(body.get("slug") or body.get("url") or "").strip()
    if not slug:
        return web.json_response({"error": "slug or url required"}, status=400)
    res = await asyncio.to_thread(owid.import_chart, workspace, slug)
    if not res.get("ok"):
        return web.json_response({"error": res.get("error", "import failed")}, status=400)
    await _daemon_ns._broadcast(request.app, protocol.files_changed())
    # Jump to the Plot tab AND select the new plot so it highlights +
    # scrolls into view (the nav handler applies payload.selection).
    sel = ({"kind": "plot", "id": res["plot_id"]} if res.get("plot_id") else None)
    await _daemon_ns._broadcast(request.app, protocol.nav(
        "vega", {"selection": sel}, f"OWID · {res.get('title')}"))
    return web.json_response(res)

def _intro_deck_path() -> Path:
    """The bundled intro-and-benchmark deck, resolved relative to the
    package root (src/switchbay/daemon.py → repo → docs/)."""
    return Path(_daemon_ns.__file__).resolve().parents[2] / "docs" / "intro_and_bench.html"

def _intro_marker_path() -> Path:
    """Global first-install marker — its presence means the Intro tab
    has already been seeded once, so we don't re-add it after the user
    closes it. App-global (not per-workspace): first *install*, not
    first workspace."""
    from switchbay.workspaces import config_dir

    return config_dir() / "intro-shown"

def _walkthrough_marker_path() -> Path:
    """Global first-install marker for the interactive product tour.
    Written when the user finishes or dismisses the walkthrough so
    auto-start only fires once; `/walkthrough` re-runs anytime."""
    from switchbay.workspaces import config_dir

    return config_dir() / "walkthrough-shown"

async def handle_walkthrough_status(request: web.Request) -> web.Response:
    """Whether the first-run walkthrough has already been completed."""
    done = await asyncio.to_thread(_walkthrough_marker_path().is_file)
    return web.json_response({"done": done})

async def handle_walkthrough_done(request: web.Request) -> web.Response:
    """Mark the first-run walkthrough complete (finish or dismiss)."""
    path = _walkthrough_marker_path()

    def _touch() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    await asyncio.to_thread(_touch)
    return web.json_response({"ok": True, "done": True})

async def handle_intro_get(request: web.Request) -> web.Response:
    """Serve the bundled Intro deck. First-party + self-contained
    (inline scripts, base64 images) — rendered in the Intro tab's
    sandboxed iframe, and directly viewable fullscreen via the tab's ⤢
    link. 404 if the deck file is missing (e.g. an install without
    docs/)."""
    path = _intro_deck_path()
    try:
        html = await asyncio.to_thread(path.read_text, encoding="utf-8")
    except OSError:
        return web.json_response({"error": "intro deck not found"}, status=404)
    return web.Response(
        text=html, content_type="text/html",
        headers={"X-Content-Type-Options": "nosniff"},
    )

async def handle_intro_close(request: web.Request) -> web.Response:
    """Close the Intro tab (its own ✕). Removes it from mode.json,
    tells clients the tab set changed, and moves focus to the Graph so
    the pane doesn't blank. The first-install marker stays set — reopen
    with `/intro`."""
    workspace: Path = request.app["workspace"]
    removed = await asyncio.to_thread(tabstore.remove_intro_tab, workspace)
    if removed:
        await _daemon_ns._broadcast(request.app, _daemon_ns._hello_payload(request.app))
        await _daemon_ns._broadcast(request.app, protocol.nav("graph", {}, "Graph"))
    return web.json_response({"ok": True, "removed": removed})

async def handle_reviews_close(request: web.Request) -> web.Response:
    """Close the Reviews tab. Remaining proposed pages stay on disk
    (close/ignore = keep) and are marked accepted. Focus Graph so the
    pane doesn't blank."""
    workspace: Path = request.app["workspace"]
    kept = await asyncio.to_thread(proposals.accept_all_proposed, workspace)
    for e in kept:
        rel = str(e.get("path") or "")
        if rel.startswith("wiki/") or rel == proposals.CHARTER_REL:
            try:
                await _daemon_ns._after_wiki_write(request.app, workspace, rel)
            except Exception:  # noqa: BLE001
                log.exception("reviews-close wiki write follow-up failed")
        await _daemon_ns._broadcast(request.app, protocol.custom({
            "type": "page_proposal_resolved", "id": e.get("id"),
            "decision": "accept",
        }))
    removed = await asyncio.to_thread(tabstore.remove_report_tab, workspace)
    if removed:
        await _daemon_ns._broadcast(request.app, _daemon_ns._hello_payload(request.app))
        await _daemon_ns._broadcast(request.app, protocol.nav("graph", {}, "Graph"))
    return web.json_response({
        "ok": True, "removed": removed, "accepted": len(kept),
    })

async def _open_intro_tab(
    app: web.Application, workspace: Path, *, pin_first: bool = False,
) -> None:
    """Ensure the Intro tab exists, refresh the client tab set (hello),
    then focus it. Fail-soft."""
    try:
        await asyncio.to_thread(
            tabstore.add_intro_tab, workspace, pin_first=pin_first)
        await _daemon_ns._broadcast(app, _daemon_ns._hello_payload(app))
        await _daemon_ns._broadcast(app, protocol.custom({"type": "open_intro"}))
    except Exception:  # noqa: BLE001
        log.exception("open_intro_tab failed")
