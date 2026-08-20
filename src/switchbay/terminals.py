"""PTY-backed interactive terminal sessions for the rail.

The Agent Dashboard's transcript view is great for watching the
agent's structured tool calls, but it can't show an interactive
shell — `bash setup.sh` or `npx skills update -g` need a real TTY
where the user can answer Y/n prompts, see colour output, and
arrow-key through completions. This module backs those with a
proper PTY:

  · spawn() forks `bash -l` (or any caller-supplied argv) under a
    `pty.openpty()` master/slave pair, child's stdin/stdout/stderr
    point at the slave fd.
  · An asyncio reader on the master fd ships every chunk of output
    over the WebSocket to the rail's terminal panel.
  · Input from xterm.js arrives via WS, gets `os.write()`-ed to
    the master fd.
  · Resize events from the terminal's fit-addon trigger an
    `ioctl(TIOCSWINSZ)` so curses-aware programs (vim, less, …)
    redraw at the right size.

Sessions are tracked in `app["terminals"]` keyed by id; the rail
panel asks for the snapshot via the WS protocol's terminal
messages.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import select
import signal
import struct
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

log = logging.getLogger("switchbay.terminals")


def pty_available() -> bool:
    """Interactive PTY rail (fork + unix pty). False on Windows v1."""
    return sys.platform != "win32"


# Per-line cap on what we ship back to the client in one chunk.
# Most chunks are small; this prevents a runaway producer from
# eating the WS frame buffer.
_READ_CHUNK = 16 * 1024


@dataclass
class TerminalSession:
    id: str
    pid: int
    master_fd: int
    name: str
    cwd: str
    argv: list[str]
    rows: int = 24
    cols: int = 80
    # Replay buffer — bounded so a long session doesn't grow without
    # limit. The rail panel's xterm renderer asks for the last N
    # bytes on (re)connect so the user doesn't see a blank canvas.
    buffer: bytearray = field(default_factory=bytearray)
    # When the PTY last produced output — feeds the dormancy heuristic
    # (`is_idle`), so a shell sitting at its prompt doesn't count as a
    # "running" task in the dashboard / thread bar.
    last_output_at: float = field(default_factory=time.time)
    exited: bool = False
    exit_code: int | None = None
    reader_task: asyncio.Task | None = None
    # Callback fired with `(session, chunk_bytes)` on every read.
    # Daemon installs this so it can broadcast over WS without
    # `terminals.py` knowing about aiohttp.
    on_output: Callable[["TerminalSession", bytes], Awaitable[None]] | None = None
    on_exit: Callable[["TerminalSession", int | None], Awaitable[None]] | None = None


# Replay buffer cap — 256 KiB per session. Past this, oldest bytes
# fall off the front. Enough to redraw a typical terminal after
# reconnect; small enough that 10 idle sessions stay under 3 MiB.
_BUFFER_CAP = 256 * 1024


def _trim_buffer(session: TerminalSession) -> None:
    if len(session.buffer) > _BUFFER_CAP:
        # Keep the trailing chunk; drop the head.
        del session.buffer[: len(session.buffer) - _BUFFER_CAP]


def spawn(
    *,
    cwd: Path,
    argv: list[str] | None = None,
    name: str | None = None,
    rows: int = 24,
    cols: int = 80,
    extra_env: dict[str, str] | None = None,
) -> TerminalSession:
    """Fork a child process attached to a fresh PTY. Returns the
    session record; caller installs `on_output` / `on_exit`
    callbacks and then starts the asyncio reader via
    `start_reader(session)`.

    `argv` defaults to the user's login shell (`$SHELL -l`) so the
    user's own rc file is sourced — starship prompt, aliases, PATH
    extensions etc. all show up in the docked terminal exactly like
    they would in iTerm / Ghostty. Falls back to `["bash", "-l"]`
    when $SHELL isn't set (rare; e.g. launched from a barebones
    LaunchAgent). `cwd` is required so the shell starts in the
    active workspace.
    """
    if not pty_available():
        raise RuntimeError("interactive PTY is not available on this platform")
    import pty  # noqa: PLC0415 — POSIX-only; lazy so Windows can import this module

    if argv is None:
        login_shell = os.environ.get("SHELL", "").strip() or "/bin/bash"
        argv = [login_shell, "-l"]
    else:
        argv = list(argv)
    master_fd, slave_fd = pty.openpty()
    # Set initial winsize on the slave before fork so the child
    # sees the right TERM dimensions from the start.
    _set_winsize(master_fd, rows, cols)
    env = os.environ.copy()
    env.setdefault("TERM", "xterm-256color")
    env.setdefault("COLORTERM", "truecolor")
    # Marker for the user's rc: switchbay terminals are often much
    # narrower than a full terminal app (the rail is ~45 cols), so a
    # prompt config can key off this to render a compacted prompt
    # (e.g. p10k: fewer segments when SWITCHBAY_TERM is set).
    env.setdefault("SWITCHBAY_TERM", "1")
    # Strip the venv markers we use elsewhere when spawning foreign
    # uv projects — same env-leak gotcha that bit cebridge.py.
    for k in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "PYTHONPATH"):
        env.pop(k, None)
    if extra_env:
        env.update(extra_env)

    # Readiness pipe: the parent MUST NOT signal this child until it
    # has detached from our signal machinery below. Signalling earlier
    # is a daemon-killer: web.run_app registers SIGTERM/SIGINT with
    # the asyncio loop via a C-level handler that writes into a
    # self-pipe (signal.set_wakeup_fd), and the fork inherits both —
    # a SIGTERM landing in the fork→detach window writes into the
    # SHARED pipe and the PARENT's loop processes it as its own,
    # gracefully shutting the whole daemon down (found live: a
    # dashboard cancel 2 ms after spawn). The child writes one byte
    # once detached; spawn() blocks (bounded, ~1-3 ms typical) on it,
    # so by the time any caller can know this session exists, it is
    # safe to kill. Pipe fds are CLOEXEC (PEP 446) → nothing leaks
    # into the shell.
    ready_r, ready_w = os.pipe()
    pid = os.fork()
    if pid == 0:
        # Child — FIRST detach from the parent's signal machinery
        # (see above), then make the slave fd our controlling tty
        # and exec.
        try:
            signal.set_wakeup_fd(-1)
        except (ValueError, OSError):
            pass
        for _sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            try:
                signal.signal(_sig, signal.SIG_DFL)
            except (OSError, ValueError):
                pass
        try:
            os.setsid()
        except OSError:
            pass
        try:
            os.write(ready_w, b"x")
            os.close(ready_w)
        except OSError:
            pass
        os.dup2(slave_fd, 0)
        os.dup2(slave_fd, 1)
        os.dup2(slave_fd, 2)
        if slave_fd > 2:
            os.close(slave_fd)
        os.close(master_fd)
        try:
            os.chdir(str(cwd))
        except OSError:
            pass
        try:
            os.execvpe(argv[0], argv, env)
        except OSError as e:
            os._exit(127 if e.errno == 2 else 126)
    # Parent — wait (bounded) for the child's detach confirmation
    # before anyone can address this session. 250 ms cap: if the child
    # is somehow that slow, we proceed anyway (the kill() session-
    # leader guard is the second line of defence).
    os.close(ready_w)
    try:
        select.select([ready_r], [], [], 0.25)
    except (OSError, ValueError):
        pass
    finally:
        try:
            os.close(ready_r)
        except OSError:
            pass
    os.close(slave_fd)
    sid = uuid.uuid4().hex[:10]
    session = TerminalSession(
        id=sid,
        pid=pid,
        master_fd=master_fd,
        name=name or argv[0],
        cwd=str(cwd),
        argv=argv,
        rows=rows,
        cols=cols,
    )
    log.info(
        "terminal spawned: id=%s pid=%d argv=%r cwd=%s",
        sid, pid, argv, cwd,
    )
    return session


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    if not pty_available():
        return
    import fcntl  # noqa: PLC0415
    import termios  # noqa: PLC0415
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except OSError:
        pass


def resize(session: TerminalSession, rows: int, cols: int) -> None:
    session.rows = rows
    session.cols = cols
    _set_winsize(session.master_fd, rows, cols)


def write_input(session: TerminalSession, data: bytes) -> None:
    """Forward keystrokes from the client to the PTY."""
    if session.exited:
        return
    try:
        os.write(session.master_fd, data)
    except OSError as e:
        log.warning("terminal %s: write failed: %s", session.id, e)


def is_idle(session: TerminalSession, *, quiet_after: float = 8.0) -> bool:
    """True when the session is dormant — an open shell sitting at its
    prompt, or a TUI (claude, vim, a REPL) waiting for user input.

    Primary signal: output recency. A working foreground program
    (claude thinking, a build printing) keeps talking; a prompt / TUI
    waiting for input goes silent — so `quiet_after` seconds of
    silence means dormant. Any output (including the echo of typed
    keys) flips the session straight back to running.

    Refinement where the platform allows it: a SILENT foreground
    child (e.g. `sleep 900`, a quiet long build) still counts as
    working when the master fd reports a foreground process group
    other than the shell's. That works on Linux; on macOS
    tcgetpgrp(master) returns 0 from outside the session (and
    reopening the slave gives ENOTTY), so there silence alone
    decides — a rare quiet-but-working command reads idle until its
    next byte of output, which is the cheap side of the error.
    """
    if session.exited:
        return True
    if time.time() - session.last_output_at < quiet_after:
        return False
    try:
        fg = os.tcgetpgrp(session.master_fd)
        if fg > 0 and fg != os.getpgid(session.pid):
            return False  # silent foreground child — still working
    except OSError:
        pass  # fd/process gone mid-check — fall through to idle
    return True


def _signal_session(session: TerminalSession, sig: int) -> None:
    """Deliver one signal to the session with the session-leader guard
    (same rule as `reap_pidfile`): only `killpg` when
    `getpgid(pid) == pid`. Right after `spawn()` there's a window
    where the forked child hasn't executed its `os.setsid()` yet — its
    pgid is still the DAEMON's, and an unguarded killpg would signal
    the daemon's own process group (found live: a dashboard cancel
    5 ms after a respawn took the whole daemon down). In that window
    we signal the pid directly; the child dies before or during exec
    and the PTY reader sees EOF as usual."""
    try:
        pgid = os.getpgid(session.pid)
    except (ProcessLookupError, PermissionError):
        return
    try:
        if pgid == session.pid:
            os.killpg(pgid, sig)
        else:
            os.kill(session.pid, sig)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(session.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass


def kill(session: TerminalSession, *, escalate_after: float = 2.0) -> None:
    """Close the session: SIGHUP + SIGTERM now, SIGKILL if it's still
    alive after `escalate_after` seconds.

    SIGHUP first because it's the "terminal went away" signal —
    INTERACTIVE shells (bash, zsh) deliberately IGNORE SIGTERM, which
    is why the old TERM-only kill silently did nothing against a shell
    at its prompt (found live: the rail ✕ kill button). SIGTERM still
    goes out for well-behaved non-shell programs, and the delayed
    SIGKILL is the backstop for anything that ignores both. The
    escalation is scheduled on the running loop when there is one
    (all daemon paths); without a loop it's fire-and-forget signals."""
    if session.exited:
        return
    _signal_session(session, signal.SIGHUP)
    _signal_session(session, signal.SIGTERM)

    def _force() -> None:
        if not session.exited:
            _signal_session(session, signal.SIGKILL)

    try:
        asyncio.get_running_loop().call_later(escalate_after, _force)
    except RuntimeError:
        pass  # no loop (tests / teardown) — HUP+TERM will have to do


# ── Orphan-reap pidfile ──────────────────────────────────────────────
# Terminal shells are spawned under `os.setsid()` (their own session,
# so pgid == pid). If the daemon is SIGKILL'd (e.g. after a wedge that
# ignored SIGTERM), those shells outlive it as orphans. We record the
# live shell PIDs to a pidfile so the next daemon can reap them on
# startup. The path is supplied by the caller (daemon → statedir) to
# keep this module decoupled from where state lives.


def write_pidfile(path: Path, sessions: dict[str, "TerminalSession"]) -> None:
    """Snapshot the live (non-exited) terminal PIDs to `path`. Called
    after every spawn / exit so the file tracks reality. Best-effort."""
    try:
        pids = [s.pid for s in sessions.values() if not s.exited]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(pids), encoding="utf-8")
    except OSError as e:
        log.warning("terminal pidfile write failed: %s", e)


def reap_pidfile(path: Path) -> int:
    """Kill any still-alive shells recorded by a previous daemon, then
    clear the file. Returns the number reaped.

    Safety against PID reuse: we only signal a recorded PID if it is
    still a *session leader* (`getpgid(pid) == pid`) — which our
    setsid'd shells are, and an unrelated process that happened to
    reuse the PID almost never is. We `killpg` so the whole shell
    session (and its children) goes down."""
    try:
        recorded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    reaped = 0
    for pid in recorded if isinstance(recorded, list) else []:
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            continue
        try:
            if os.getpgid(pid) != pid:
                continue  # not a session leader → not one of our shells
            os.killpg(pid, signal.SIGTERM)
            reaped += 1
        except (ProcessLookupError, PermissionError, OSError):
            continue
    try:
        path.unlink()
    except OSError:
        pass
    if reaped:
        log.info("reaped %d orphaned terminal shell(s) from a prior daemon", reaped)
    return reaped


async def _reap(session: TerminalSession) -> int | None:
    """Best-effort waitpid — runs after the reader loop sees EOF
    on the master fd."""
    try:
        _, status = await asyncio.get_event_loop().run_in_executor(
            None, os.waitpid, session.pid, 0,
        )
    except (ChildProcessError, OSError):
        return None
    if os.WIFEXITED(status):
        return os.WEXITSTATUS(status)
    if os.WIFSIGNALED(status):
        return -os.WTERMSIG(status)
    return None


def start_reader(session: TerminalSession) -> asyncio.Task:
    """Kick the async reader loop that ships PTY output to the
    client via `session.on_output`. Closing the master fd or the
    child exiting both end the loop; the on_exit callback fires
    with the exit code (best-effort)."""

    loop = asyncio.get_event_loop()
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    def _on_readable() -> None:
        try:
            data = os.read(session.master_fd, _READ_CHUNK)
        except OSError:
            data = b""
        if not data:
            loop.remove_reader(session.master_fd)
            queue.put_nowait(None)
            return
        queue.put_nowait(data)

    try:
        loop.add_reader(session.master_fd, _on_readable)
    except (ValueError, PermissionError) as e:
        log.warning("terminal %s: add_reader failed: %s", session.id, e)

    async def _pump() -> None:
        try:
            while True:
                chunk = await queue.get()
                if chunk is None:
                    break
                session.buffer.extend(chunk)
                _trim_buffer(session)
                session.last_output_at = time.time()
                if session.on_output is not None:
                    try:
                        await session.on_output(session, chunk)
                    except Exception:  # noqa: BLE001
                        log.exception("terminal %s: on_output crashed", session.id)
        finally:
            session.exited = True
            session.exit_code = await _reap(session)
            try:
                os.close(session.master_fd)
            except OSError:
                pass
            if session.on_exit is not None:
                try:
                    await session.on_exit(session, session.exit_code)
                except Exception:  # noqa: BLE001
                    log.exception("terminal %s: on_exit crashed", session.id)
            log.info("terminal %s exited (code=%s)", session.id, session.exit_code)

    task = loop.create_task(_pump())
    session.reader_task = task
    return task


def snapshot(session: TerminalSession) -> dict[str, Any]:
    """Compact metadata for the WS protocol's term.list message."""
    return {
        "id": session.id,
        "name": session.name,
        "cwd": session.cwd,
        "argv": session.argv,
        "rows": session.rows,
        "cols": session.cols,
        "pid": session.pid,
        "exited": session.exited,
        "exit_code": session.exit_code,
    }
