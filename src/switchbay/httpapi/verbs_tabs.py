"""Verb catalogue, shell detection, and extra tab routes.

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
from aiohttp import web
from switchbay import commands
from switchbay import conversations
from switchbay import tabstore
from switchbay import verbs

from switchbay.httpapi._ns import _daemon_ns

async def handle_verbs(request: web.Request) -> web.Response:
    """List registered verbs + user-defined commands for the rail's
    slash-autocomplete menu. Each entry is `{name, aliases,
    description}` (+ `scope` for user commands). The frontend
    re-fetches on thread changes (covers workspace switches too) and
    filters by typed prefix."""
    items = []
    for v in verbs.all_verbs():
        items.append({
            "name": v.name,
            "aliases": list(v.aliases),
            "description": v.description,
        })
    # Built-in slash handlers not in the verb registry.
    items.append({
        "name": "micro-edits",
        "aliases": ["microedits"],
        "description": (
            "Micro-edit ladder rung (trivial/normal/hard) for small "
            "Sheet/Sketch/Table/Plot changes · /micro-edits status"
        ),
    })
    items.append({
        "name": "quit",
        "aliases": ["shutdown", "exit"],
        "description": (
            "Stop Switch Bay (all workspaces; ends running agents) · "
            "confirm with /quit confirm"
        ),
    })
    items.append({
        "name": "start",
        "aliases": ["restart"],
        "description": (
            "Restart the Switch Bay daemon (runs `make restart`) · "
            "the app reconnects automatically"
        ),
    })
    builtin_names = {i["name"] for i in items}
    user_cmds = await asyncio.to_thread(
        commands.list_commands, request.app["workspace"],
    )
    for c in user_cmds:
        if c["name"] in builtin_names:
            continue  # built-ins win at dispatch; don't advertise a dupe
        items.append({
            "name": c["name"],
            "aliases": [],
            "description": c["description"] or f"user command ({c['scope']})",
            "scope": c["scope"],
        })
    return web.json_response({"verbs": items})

def _detect_shellish(text: str) -> bool:
    """High-confidence "this looks like a shell command" heuristic for
    the rail's interpretation chip. Conservative by design: false
    positives send prose to a shell (bad); false negatives just mean
    the user types `!` like before. Sync (PATH stats) — call off-loop."""
    import re as _re
    import shutil as _shutil

    t = text.strip()
    if not t or "\n" in t or len(t) > 300:
        return False
    if t[0] in "/!":
        return False  # explicit prefixes already routed
    tok = t.split()[0]
    # Lowercase unix-ish token only — "Git log" reads as prose.
    if not _re.fullmatch(r"[a-z0-9_.~/-]+", tok):
        return False
    # On-PATH words that are also ordinary chat. `yes` prints y
    # forever in a new shell thread; `what` is /usr/bin/what on macOS
    # (SCCS banner) and is how people start a wiki question.
    if tok in {
        "yes", "no", "y", "n", "ok", "okay", "true", "false",
        "please", "thanks", "thank",
        "what", "who", "where", "when", "why", "how", "which",
        "whom", "whose",
        "hi", "hello", "hey",
    }:
        return False
    builtins = {"cd", "export", "source", "pwd", "env", "alias", "unset", "set"}
    if tok not in builtins and _shutil.which(tok) is None:
        return False
    words = t.split()
    # A lone on-PATH word ("date", "ls") or a short invocation is
    # confidently shell. Longer input needs shell-shaped evidence —
    # flags, paths, pipes, redirects, assignments — because plenty of
    # English sentences start with an on-PATH word ("man pages are…",
    # "test whether the daemon…").
    if len(words) <= 3:
        return True
    shell_shaped = (
        any(c in t for c in "|&;<>$=")
        or any(w.startswith("-") for w in words[1:])
        or any("/" in w for w in words[1:])
    )
    return shell_shaped

async def handle_tab_scope(request: web.Request) -> web.Response:
    """Scope a user tab to a thread (`thread_id`) or back to
    workspace-wide (`thread_id: null`). Scoped tabs render only while
    their thread is focused — the filter is client-side, so switching
    threads shows/hides them instantly. Broadcasts a fresh hello so
    every client's mode picks up the change."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    tab_id = str(body.get("tab_id") or "").strip()
    if not tab_id:
        return web.json_response({"error": "tab_id required"}, status=400)
    raw_tid = body.get("thread_id")
    thread_id = str(raw_tid).strip() if raw_tid else None
    workspace: Path = request.app["workspace"]
    if thread_id:
        kind = await asyncio.to_thread(
            conversations.thread_kind, workspace, thread_id,
        )
        if kind is None:
            return web.json_response(
                {"error": "no such thread in this workspace"}, status=404,
            )
    ok = await asyncio.to_thread(
        tabstore.set_thread_scope, workspace, tab_id, thread_id,
    )
    if not ok:
        return web.json_response(
            {"error": "tab not found, or not a user tab (only user tabs "
                      "can be thread-scoped)"},
            status=400,
        )
    await _daemon_ns._broadcast(request.app, _daemon_ns._hello_payload(request.app))
    return web.json_response({"ok": True, "tab_id": tab_id, "thread_id": thread_id})

async def handle_tab_terminal_add(request: web.Request) -> web.Response:
    """Pop a pty thread out of the rail into a center tab (user tab,
    kind "terminal", payload.thread_id). Each terminal tab exists by
    deliberate choice — there is no standing Terminal tab; the first
    pop-out this session is what creates one. Idempotent per thread.
    Body: {thread_id}."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    thread_id = str(body.get("thread_id") or "").strip()
    if not thread_id:
        return web.json_response({"error": "thread_id required"}, status=400)
    workspace: Path = request.app["workspace"]
    kind = await asyncio.to_thread(
        conversations.thread_kind, workspace, thread_id,
    )
    if kind is None:
        return web.json_response({"error": "no such thread"}, status=404)
    if kind != "interactive-pty":
        return web.json_response(
            {"error": "not a shell thread — only terminals pop out"},
            status=400,
        )
    title = await asyncio.to_thread(
        conversations.thread_title, workspace, thread_id,
    )
    tab = await asyncio.to_thread(
        tabstore.add_terminal_tab, workspace, thread_id, title,
    )
    if tab is None:
        return web.json_response(
            {"error": "mode.json unreadable — fix or delete it"}, status=500,
        )
    await _daemon_ns._broadcast(request.app, _daemon_ns._hello_payload(request.app))
    return web.json_response({"ok": True, "tab": tab})

async def handle_tab_terminal_remove(request: web.Request) -> web.Response:
    """Return a popped-out terminal to the rail: remove its tab. The
    thread + session are untouched — only the surface moves. Body:
    {tab_id}."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    tab_id = str(body.get("tab_id") or "").strip()
    if not tab_id:
        return web.json_response({"error": "tab_id required"}, status=400)
    workspace: Path = request.app["workspace"]
    removed = await asyncio.to_thread(
        tabstore.remove_terminal_tabs, workspace, tab_id=tab_id,
    )
    if not removed:
        return web.json_response({"error": "no such terminal tab"}, status=404)
    await _daemon_ns._broadcast(request.app, _daemon_ns._hello_payload(request.app))
    return web.json_response({"ok": True, "removed": removed})

async def handle_tab_vault_doc_add(request: web.Request) -> web.Response:
    """Open (or focus) a dedicated user markdown tab for a vault
    extracted source. Idempotent by payload.path. Body: {path, name?}.
    CE wiki-view / the graph modal call this instead of handing the
    file to the OS default app."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    raw = str(body.get("path") or body.get("name") or "").strip()
    path = tabstore.normalize_vault_source_path(raw)
    if not path:
        return web.json_response(
            {"error": "vault markdown path required"}, status=400,
        )
    title = str(body.get("name") or "").strip() or Path(path).name
    workspace: Path = request.app["workspace"]
    tab = await asyncio.to_thread(
        tabstore.add_vault_doc_tab, workspace, path, title,
    )
    if tab is None:
        return web.json_response(
            {"error": "mode.json unreadable — fix or delete it"}, status=500,
        )
    await _daemon_ns._broadcast(request.app, _daemon_ns._hello_payload(request.app))
    return web.json_response({"ok": True, "tab": tab})

async def handle_tab_vault_doc_remove(request: web.Request) -> web.Response:
    """Close a dedicated vault-source Editor tab. Body: {tab_id}.
    Only removes user markdown tabs created by /api/tabs/vault-doc —
    the core Editor is untouched."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    tab_id = str(body.get("tab_id") or "").strip()
    if not tab_id:
        return web.json_response({"error": "tab_id required"}, status=400)
    workspace: Path = request.app["workspace"]
    removed = await asyncio.to_thread(
        tabstore.remove_vault_doc_tab, workspace, tab_id,
    )
    if not removed:
        return web.json_response(
            {"error": "no such vault-source tab"}, status=404,
        )
    await _daemon_ns._broadcast(request.app, _daemon_ns._hello_payload(request.app))
    return web.json_response({"ok": True, "removed": tab_id})

async def handle_shell_detect(request: web.Request) -> web.Response:
    """Router support for the rail's interpretation chip: does this
    input look like a shell command? (PATH lookups off-loop.)"""
    text = request.query.get("text", "")
    shellish = await asyncio.to_thread(_detect_shellish, text)
    return web.json_response({"shell": shellish})

async def handle_rail_events(request: web.Request) -> web.Response:
    """Hydrate the rail UI from the on-disk event log.

    GET /api/rail/events?before_id=&limit=    — page of events older
    than `before_id` (ascending order). Without `before_id`, returns
    the most recent `limit` events in the active thread.

    The frontend uses this both on page load (initial seed) and on
    scroll-to-top (load older). `thread_id` is omitted from the API —
    the active thread is inferred from the daemon's state, so the UI
    doesn't need to track ids."""
    workspace: Path = request.app["workspace"]
    try:
        limit = int(request.query.get("limit", "50"))
    except ValueError:
        limit = 50
    limit = max(1, min(200, limit))
    raw_before = request.query.get("before_id")
    before_id: int | None
    if raw_before:
        try:
            before_id = int(raw_before)
        except ValueError:
            return web.json_response({"error": "before_id must be int"}, status=400)
    else:
        before_id = None
    # `run_id` filter — used by the Agent Dashboard's transcript
    # expander. Bypasses thread-id resolution since a run is the
    # unit here, not a thread.
    run_id = request.query.get("run_id", "").strip() or None
    if run_id is not None:
        # The Agent Dashboard is cross-workspace: a run's transcript must
        # be read from that run's OWN workspace DB, not the focused one.
        # Resolve via the capped run→ws map (survives the run finishing);
        # fall back to the focused workspace for runs we don't know about.
        run_ws = _daemon_ns._run_workspace(request.app, run_id) or workspace
        # sqlite query + JSON payload parse — off-thread so rail
        # scrollback hydration never blocks the loop.
        events = await asyncio.to_thread(
            conversations.list_events,
            run_ws, before_id=before_id, limit=limit, run_id=run_id,
        )
        return web.json_response({"events": events, "run_id": run_id})
    # Workspace-spanning history: previously the rail hydrated only
    # the active thread (~ <50 events), so the scrollback button hit
    # "no older history" almost immediately even though the
    # workspace's DB had hundreds of events across dozens of prior
    # threads. Pass thread_id=None so list_events paginates across
    # every thread in this workspace's DB, ordered by event id. A
    # `thread_id=<id>` query param still pins to one thread if the
    # caller wants the old behaviour.
    pinned_thread = request.query.get("thread_id", "").strip() or None
    events = await asyncio.to_thread(
        conversations.list_events,
        workspace, pinned_thread, before_id=before_id, limit=limit,
        any_thread=pinned_thread is None,
    )
    active_thread = request.app.get("thread_id")
    if not active_thread:
        active_thread = await asyncio.to_thread(
            conversations.active_thread_id, workspace,
        )
    return web.json_response({"events": events, "thread_id": active_thread})

async def handle_llm_reset(request: web.Request) -> web.Response:
    """Drop any in-flight provider resume handles AND start a fresh
    local thread. Next rail turn opens a new thread row in
    `<workspace>/.workbench/state/conversations.db` — older turns stay
    searchable via the recall_rail tool."""
    # Drop only the FOREGROUND thread's provider handle (sessions are
    # keyed by thread_id) so backgrounded cross-workspace runs keep
    # theirs. Resetting thread_id opens a fresh thread next turn.
    cur = request.app.get("thread_id")
    if cur:
        (request.app.get("llm_sessions") or {}).pop(cur, None)
    request.app["thread_id"] = None
    request.app["thread_kind"] = None
    return web.json_response({"ok": True})
