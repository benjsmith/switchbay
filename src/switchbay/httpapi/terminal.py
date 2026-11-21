"""Interactive PTY spawn and terminal websocket commands.

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
import logging
import time
from aiohttp import web
from switchbay import admin_policy
from switchbay import conversations
from switchbay import protocol
from switchbay import statedir
from switchbay import terminals
from switchbay import workspaces

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

async def _attach_term_callbacks(
    app: web.Application, session: "terminals.TerminalSession",
) -> None:
    """Install the on_output / on_exit broadcasters every PTY session
    gets — output streams to the rail's xterm surface via `term.output`,
    exit closes the thread's AG-UI run + unmaps it for respawn."""
    import base64
    sessions = app.setdefault("terminals", {})

    async def _on_output(s: "terminals.TerminalSession", chunk: bytes) -> None:
        await _daemon_ns._broadcast(app, {
            "type": "term.output",
            "id": s.id,
            "data": base64.b64encode(chunk).decode("ascii"),
        })

    async def _on_exit(s: "terminals.TerminalSession", code: int | None) -> None:
        await _daemon_ns._broadcast(app, {
            "type": "term.exit",
            "id": s.id,
            "exit_code": code,
        })
        sessions.pop(s.id, None)
        _sync_term_pidfile(app)
        # Thread-scoped PTY bookkeeping: close the AG-UI run so the
        # dashboard's row ends, and unmap the thread so a later focus
        # respawns a fresh shell into the same (durable) thread.
        meta = (app.get("pty_meta") or {}).pop(s.id, None)
        if meta:
            tid = meta["thread_id"]
            (app.get("runs") or {}).pop(meta["run_id"], None)
            tp: dict[str, str] = app.get("thread_pty") or {}
            if tp.get(tid) == s.id:
                tp.pop(tid, None)
            await _daemon_ns._broadcast(app, protocol.run_finished(
                tid, meta["run_id"], None, None, f"exit:{code}",
            ))
            _daemon_ns._append_event(app,
                Path(meta["workspace"]), tid, "exec",
                f"shell exited (code={code})",
                source="pty", actor="pty",
            )

    session.on_output = _on_output
    session.on_exit = _on_exit
    # Record the live shell PIDs so the next daemon can reap this one
    # if we're SIGKILL'd before its on_exit fires.
    _sync_term_pidfile(app)

def _sync_term_pidfile(app: web.Application) -> None:
    """Persist the live terminal PIDs to the orphan-reap pidfile.
    Best-effort; called after every spawn + exit."""
    try:
        terminals.write_pidfile(statedir.terminal_pidfile(), app.get("terminals") or {})
    except Exception:  # noqa: BLE001
        log.exception("terminal pidfile sync failed")

def _compact_prompt_env(cols: int | None) -> dict[str, str]:
    """Env overrides that swap prompt frameworks to a compact layout
    for narrow spawns. Root cause (2026-07-05): starship renders its
    full segment line (~85 cols) regardless of terminal width — it
    truncates segments, never the line — so any sidebar-width shell
    wraps no matter how perfectly the PTY size is synced. Redirecting
    STARSHIP_CONFIG for <80-col spawns is non-invasive: the user's
    own config is untouched, non-starship users are unaffected, and
    wide (tab) spawns keep the full prompt."""
    if cols is None or cols >= 80:
        return {}
    try:
        p = workspaces.config_dir() / "starship-compact.toml"
        first = ""
        if p.is_file():
            first = p.read_text(encoding="utf-8").split("\n", 1)[0]
        # (Re)generate on missing file OR a version-line mismatch —
        # user edits survive iff they changed the first line.
        if first != _daemon_ns._COMPACT_PROMPT_VERSION and (
            not first or first.startswith("# switchbay")
        ):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(_daemon_ns._COMPACT_PROMPT_TOML, encoding="utf-8")
        return {"STARSHIP_CONFIG": str(p)}
    except OSError:
        return {}

async def _spawn_pty_for_thread(
    app: web.Application,
    thread_id: str,
    *,
    argv: list[str] | None = None,
    name: str | None = None,
    rows: int | None = None,
    cols: int | None = None,
    cwd: Path | None = None,
) -> "terminals.TerminalSession":
    """Spawn a PTY session as THE live attachment of an
    `interactive-pty` thread: registers the session, maps
    thread↔session, opens an AG-UI run (provider `pty`) so the
    dashboard's cross-thread view stays uniform, and drops a rail
    breadcrumb into the thread. Raises on spawn failure — callers
    surface the error on their own channel.

    `rows`/`cols` should be the client's FITTED xterm size whenever
    the caller knows it (term.attach carries it). Spawning at the
    real size matters: the shell's very first prompt paint is
    formatted for the spawn width, so an 80-col default in a ~45-col
    rail wraps the powerline prompt onto a second line before any
    resize can reach the shell. Callers that spawn before any client
    surface exists (`!cmd`) fall back to the last size any client
    reported (`term_size_hint`), then 80×24."""
    if not admin_policy.feature_enabled("interactive_terminal"):
        raise RuntimeError(admin_policy.feature_error("interactive_terminal"))
    if not terminals.pty_available():
        raise RuntimeError("interactive terminals are not available on this platform")
    workspace: Path = app["workspace"]
    # `cwd` override lets a shell start in a directory other than the
    # active workspace (e.g. "watch in shell" points it at an external
    # source's dir). Defaults to the workspace.
    spawn_cwd = cwd or workspace
    sessions: dict[str, terminals.TerminalSession] = app.setdefault("terminals", {})
    hint = app.get("term_size_hint") or (24, 80)
    spawn_cols = cols or hint[1]
    session = terminals.spawn(
        cwd=spawn_cwd, argv=argv, name=name,
        rows=rows or hint[0], cols=spawn_cols,
        extra_env=_compact_prompt_env(spawn_cols),
    )
    sessions[session.id] = session
    run_id = f"pty-{session.id}"
    app.setdefault("thread_pty", {})[thread_id] = session.id
    app.setdefault("pty_meta", {})[session.id] = {
        "thread_id": thread_id,
        "run_id": run_id,
        "workspace": str(workspace),
    }
    # Dashboard row: a live shell is a run like any other. `task` is
    # None (no asyncio task to cancel) — handle_run_cancel /stop-all
    # kill via `pty_session` instead.
    runs: dict[str, dict[str, Any]] = app.setdefault("runs", {})
    runs[run_id] = {
        "run_id": run_id,
        "provider": "pty",
        "model": session.argv[0],
        "input_excerpt": session.name,
        "started_at": time.time(),
        "last_chunk_at": time.time(),
        "tool_count": 0,
        "status": "running",
        "task": None,
        "pty_session": session.id,
        "thread_id": thread_id,
        "workspace": str(workspace),
        "workspace_name": workspace.name,
    }
    _daemon_ns._remember_run_workspace(app, run_id, workspace)
    _daemon_ns._remember_run_thread(app, run_id, thread_id)
    await _attach_term_callbacks(app, session)
    terminals.start_reader(session)
    await _daemon_ns._broadcast(app, protocol.run_started(
        thread_id, run_id, "pty", session.argv[0], str(workspace),
    ))
    _daemon_ns._append_event(app,
        workspace, thread_id, "exec",
        f"shell started: {' '.join(session.argv)}",
        source="pty", actor="pty",
    )
    return session

async def _dispatch_shell_command(
    app: web.Application, ws: web.WebSocketResponse, body: str,
    *,
    argv: list[str] | None = None,
    name: str | None = None,
) -> None:
    """`!<cmd>` / `!py <expr>`: create a fresh `interactive-pty`
    THREAD, spawn its shell, focus it (all clients' rails swap to the
    xterm surface via `thread_focused`), and write `<body>\n` into
    the PTY. The shell then behaves like any terminal — the user can
    interact further (Ctrl-C, follow-up commands, history, …) rather
    than getting a one-shot capture. The thread outlives the shell:
    re-focusing it after exit respawns via `term.attach`."""
    workspace: Path = app["workspace"]
    if not name:
        # Keep a readable chunk of the ACTUAL command in the title —
        # not just its leading binary — so the switcher / ThreadBar can
        # tell shell threads apart (e.g. `! bash …/update.sh --yes`
        # instead of a bare `! bash`). Collapse whitespace; ellipsize
        # when long. The full command is always in the scrollback once
        # it executes.
        flat = " ".join(body.split())
        name = f"! {flat}" if flat else "!"
        if len(name) > 48:
            name = name[:47].rstrip() + "…"
    thread_id = await asyncio.to_thread(
        conversations.new_thread, workspace, name, "interactive-pty",
    )
    app["thread_id"] = thread_id
    app["thread_kind"] = "interactive-pty"
    try:
        session = await _daemon_ns._spawn_pty_for_thread(
            app, thread_id, argv=argv, name=name,
        )
    except Exception as e:  # noqa: BLE001
        log.exception("!cmd spawn failed")
        await ws.send_json({"type": "term.error", "message": str(e)})
        return
    await _daemon_ns._broadcast(app, protocol.thread_focused(
        thread_id, "interactive-pty", workspace=str(app["workspace"]),
    ))
    # Give the shell a beat to source ~/.bashrc / .zshrc, then write
    # the command + newline. A small sleep here keeps the prompt
    # from interleaving with our injected line in the displayed
    # scrollback. Tests against bash -l show ~30 ms is usually
    # enough; 80 ms gives macOS its breathing room without feeling
    # laggy.
    await asyncio.sleep(0.08)
    terminals.write_input(session, body.encode("utf-8") + b"\n")

async def _handle_term_attach(
    app: web.Application, ws: web.WebSocketResponse, data: dict[str, Any],
) -> None:
    """A client focused an `interactive-pty` thread and wants its
    xterm surface wired up. Reuses the thread's live session when one
    exists (reply carries the replay buffer so scrollback survives
    switches/reconnects); respawns a fresh shell into the thread when
    the old one exited — pty threads are durable, sessions aren't."""
    import base64
    thread_id = str(data.get("thread_id") or "").strip()
    if not thread_id:
        await ws.send_json({"type": "term.error", "message": "thread_id required"})
        return
    workspace: Path = app["workspace"]
    kind = await asyncio.to_thread(conversations.thread_kind, workspace, thread_id)
    if kind != "interactive-pty":
        await ws.send_json({
            "type": "term.error",
            "message": "not a shell thread" if kind else "no such thread",
        })
        return
    # The client's fitted xterm size rides along so a fresh spawn's
    # FIRST prompt paint is already the right width (see
    # _spawn_pty_for_thread). Also remembered as the app-wide hint
    # for spawns that happen before any surface exists (`!cmd`).
    try:
        rows = int(data.get("rows") or 0) or None
        cols = int(data.get("cols") or 0) or None
    except (TypeError, ValueError):
        rows = cols = None
    # Only RAIL surfaces feed the pre-surface spawn hint — `!cmd`
    # spawns target the rail, and a wide pop-out TAB attach would
    # otherwise poison the hint with ~200-col widths.
    if rows and cols and str(data.get("surface") or "rail") == "rail":
        app["term_size_hint"] = (rows, cols)
    sessions: dict[str, terminals.TerminalSession] = app.setdefault("terminals", {})
    sid = (app.get("thread_pty") or {}).get(thread_id)
    session = sessions.get(sid) if sid else None
    if session is None or session.exited:
        try:
            session = await _daemon_ns._spawn_pty_for_thread(
                app, thread_id, rows=rows, cols=cols,
            )
        except Exception as e:  # noqa: BLE001
            log.exception("term.attach respawn failed")
            await ws.send_json({"type": "term.error", "message": str(e)})
            return
    elif rows and cols and (session.rows, session.cols) != (rows, cols):
        # Live session, different surface size (e.g. sidebar ↔ tab
        # move): resize now so the SIGWINCH redraw happens before the
        # client paints the replay on top.
        terminals.resize(session, rows, cols)
        # The replay bytes are formatted for the OLD width — a stale
        # prompt paint wraps/clips after the reflow and zsh's WINCH
        # redraw can't fix lines it doesn't own. For a dormant session
        # (shell at its prompt, TUI awaiting input) a ^L right after
        # the SIGWINCH makes the foreground repaint cleanly at the new
        # width (zsh: clear + fresh prompt; TUIs: redraw). Working
        # sessions are left alone.
        if terminals.is_idle(session, quiet_after=2.0):
            terminals.write_input(session, b"\x0c")
    await ws.send_json({
        "type": "term.opened",
        "session": terminals.snapshot(session),
        "thread_id": thread_id,
        "replay": base64.b64encode(bytes(session.buffer)).decode("ascii"),
    })

async def _handle_term_input(app: web.Application, data: dict[str, Any]) -> None:
    sessions: dict[str, terminals.TerminalSession] = app.get("terminals") or {}
    s = sessions.get(str(data.get("id") or ""))
    if s is None:
        return
    raw = data.get("data") or ""
    if isinstance(raw, str):
        # Client always sends base64 of utf-8 bytes so multi-byte
        # input (paste, emoji, etc.) round-trips correctly.
        import base64
        try:
            payload = base64.b64decode(raw)
        except Exception:  # noqa: BLE001
            payload = raw.encode("utf-8", errors="replace")
    else:
        payload = b""
    terminals.write_input(s, payload)

async def _handle_term_resize(app: web.Application, data: dict[str, Any]) -> None:
    sessions: dict[str, terminals.TerminalSession] = app.get("terminals") or {}
    s = sessions.get(str(data.get("id") or ""))
    if s is None:
        return
    rows = int(data.get("rows") or s.rows)
    cols = int(data.get("cols") or s.cols)
    changed = (s.rows, s.cols) != (rows, cols)
    terminals.resize(s, rows, cols)
    # A REAL size change on a dormant session gets a ^L so the
    # foreground repaints at the new width. This is what finally
    # covers the wrapped-powerbar case the spawn-size hint can't
    # reach: the client's first fit runs before the Nerd Font
    # finishes loading, so the spawn width is a few columns off and
    # the very first prompt paint wraps; when the fonts.ready refit
    # corrects the size, this nudge redraws the prompt cleanly.
    # Debounced so drag-resizing doesn't spam clears; working
    # sessions are never touched.
    if changed and terminals.is_idle(s, quiet_after=2.0):
        now = time.time()
        if now - getattr(s, "_last_nudge", 0.0) > 1.5:
            s._last_nudge = now  # type: ignore[attr-defined]
            terminals.write_input(s, b"\x0c")

async def _handle_term_kill(app: web.Application, data: dict[str, Any]) -> None:
    sessions: dict[str, terminals.TerminalSession] = app.get("terminals") or {}
    s = sessions.get(str(data.get("id") or ""))
    if s is not None:
        terminals.kill(s)
