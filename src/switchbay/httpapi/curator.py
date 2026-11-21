"""Curator profile read, write, and draft routes.

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

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

async def handle_curator_profile_get(request: web.Request) -> web.Response:
    """The active workspace's curator profile (D6): the full text of
    `.curator/profile.md` for the Settings text box, plus the
    injection cap so the UI can show how much of it curate prompts
    will actually see."""
    workspace: Path = request.app["workspace"]

    def _read() -> str:
        try:
            return (workspace / ".curator" / "profile.md").read_text(
                encoding="utf-8",
            )
        except OSError:
            return ""

    text = await asyncio.to_thread(_read)
    return web.json_response({
        "profile": text,
        "cap": _daemon_ns._CURATOR_PROFILE_CAP_TOKENS,
        "cap_unit": "tokens",
        "workspace_name": workspace.name,
    })

async def handle_curator_profile_post(request: web.Request) -> web.Response:
    """Persist the curator profile to `<workspace>/.curator/profile.md`.
    Stored in full (the file-on-disk contract roams with the
    workspace); only the injection is capped."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    workspace: Path = request.app["workspace"]
    text = str(body.get("profile") or "")

    def _write() -> None:
        d = workspace / ".curator"
        d.mkdir(parents=True, exist_ok=True)
        (d / "profile.md").write_text(text, encoding="utf-8")

    await asyncio.to_thread(_write)
    _daemon_ns._log_event(
        request.app, "file_edit_internal", "curator profile updated",
        source="settings", actor="user",
        payload={"path": ".curator/profile.md", "chars": len(text)},
    )
    return web.json_response({
        "ok": True,
        "profile": text,
        "cap": _daemon_ns._CURATOR_PROFILE_CAP_TOKENS,
        "cap_unit": "tokens",
        "workspace_name": workspace.name,
    })

async def handle_curator_profile_draft(request: web.Request) -> web.Response:
    """"Draft it for me" (D6 refinement): dispatch a background agent
    that surveys the workspace — registry, wiki buckets, a few pages —
    and writes (or refines) `.curator/profile.md`. Mirrors the
    ingest-agent pattern: returns the run_id immediately; the Settings
    panel polls GET /api/curator-profile until the file changes."""
    prompt = (
        "Draft (or refine) this workspace's curator profile at "
        "`.curator/profile.md`.\n\n"
        "The profile steers every curation pass with the DOMAIN "
        "JUDGMENT the generic curiosity-engine skill cannot derive. "
        "It is injected verbatim into curate prompts, capped at "
        f"~{_daemon_ns._CURATOR_PROFILE_CAP_TOKENS} tokens (≈"
        f"{_daemon_ns._CURATOR_PROFILE_CAP_TOKENS * _daemon_ns._CHARS_PER_TOKEN_EST} "
        "characters). Stay comfortably UNDER the cap — a tight "
        "profile of hard rulings beats an exhaustive one; if you're "
        "near the limit, cut the weakest rulings rather than "
        "compressing the wording.\n\n"
        "1. Survey first: read `.curator/projects.json` (registered "
        "projects), list the wiki/ buckets (entities/, concepts/, "
        "facts/, analyses/ page names), and read 2-3 representative "
        "pages. Infer what this wiki cares about and the implicit "
        "rulings already visible — e.g. which kinds of things got "
        "entity pages and which recurring names never did.\n"
        "2. If `.curator/profile.md` already has content, PRESERVE "
        "the user's existing rulings and refine around them; "
        "otherwise write fresh.\n"
        "3. Structure:\n"
        "   · Line 1: one crisp sentence saying what the workspace "
        "is about — it doubles as the routing description a small "
        "model uses to judge message relevance, so name the domains "
        "plainly.\n"
        "   · Entity rulings WITH the why (what always gets a page; "
        "what never does — e.g. 'ticket IDs like PROJ-1234 always "
        "link to their project definition page').\n"
        "   · Concept / fact standards (what a fact must carry to be "
        "worth keeping).\n"
        "   · Scope edges (adjacent material that IS in scope and "
        "where to route it).\n"
        "   · Noise (what looks like content here but should be "
        "skipped).\n"
        "4. Rulings, not vibes: no 'keep quality high', and no file "
        "naming / frontmatter mechanics — the skill owns those. "
        "Every line should be a rule the curator can act on, ideally "
        "with its reason so it generalizes.\n"
        "5. Write the result to `.curator/profile.md` with Write, "
        "then stop. Reply with a one-paragraph summary of the "
        "rulings you chose."
    )
    run_id = f"run-{uuid.uuid4().hex[:8]}"

    async def _runner() -> None:
        try:
            await _daemon_ns._dispatch_chat(
                request.app, ws=None, text=prompt,
                input_excerpt="draft curator profile",
                run_id=run_id,
            )
        except Exception:  # noqa: BLE001
            log.exception("curator-profile draft run %s crashed", run_id)

    task = asyncio.create_task(_runner())
    task.add_done_callback(_daemon_ns._make_dispatch_error_surface(request.app, run_id))
    return web.json_response({"ok": True, "run_id": run_id})
