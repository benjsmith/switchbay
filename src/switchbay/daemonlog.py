"""Daemon process logging: quiet poll access lines + a size-bounded file.

launchd/systemd/the Windows task must not hold an fd on the daemon log.
Those supervisors open StandardOut/Error once and never rotate; a
``RotatingFileHandler`` rename then leaves the supervisor writing to the
old inode forever. Python owns ``switchbay-daemon.log``; supervisor
stdio goes to ``/dev/null``.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

from aiohttp.web_log import AccessLogger
from aiohttp.web_request import BaseRequest
from aiohttp.web_response import StreamResponse

# Rotate at 100 MiB; keep one previous file. Worst-case disk is ~200 MiB.
LOG_MAX_BYTES = 100 * 1024 * 1024
LOG_BACKUP_COUNT = 1

# Frontend pollers hit these every 1–2s for the life of every open
# window. Successful responses are not diagnostic; failures still log.
QUIET_ACCESS_PATHS = frozenset({"/api/health", "/api/runs/active"})

_LOG_FORMAT = "%(asctime)s %(name)s %(message)s"


def log_path() -> Path:
    """Platform-conventional daemon log path.

    ``SWITCHBAY_DAEMON_LOG`` overrides (tests, sandboxed deploys).
    """
    override = os.environ.get("SWITCHBAY_DAEMON_LOG")
    if override:
        return Path(override).expanduser()
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Logs" / "switchbay-daemon.log"
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(home / "AppData" / "Local")
        return Path(base) / "switchbay" / "logs" / "daemon.log"
    xdg = os.environ.get("XDG_STATE_HOME") or str(home / ".local" / "state")
    return Path(xdg) / "switchbay" / "daemon.log"


def should_log_access(path: str, status: int) -> bool:
    """False for successful (or redirect) hits on the heartbeat pollers."""
    if path in QUIET_ACCESS_PATHS and 200 <= status < 400:
        return False
    return True


class QuietAccessLogger(AccessLogger):
    """aiohttp access logger that drops 2xx/3xx heartbeat poller hits."""

    def log(self, request: BaseRequest, response: StreamResponse, time: float) -> None:
        if not should_log_access(request.path, int(response.status)):
            return
        super().log(request, response, time)


class _StreamToLogger:
    """Line-buffered stdout/stderr → logging, so ``print`` and tracebacks
    land in the rotating file when the supervisor pointed stdio at
    ``/dev/null``."""

    def __init__(self, logger: logging.Logger, level: int) -> None:
        self._logger = logger
        self._level = level
        self._buf = ""
        self._in_write = False

    def write(self, msg: str) -> int:
        if isinstance(msg, bytes):
            msg = msg.decode("utf-8", "replace")
        elif not isinstance(msg, str):
            msg = str(msg)
        n = len(msg)
        if not msg:
            return 0
        if self._in_write:
            return n
        self._in_write = True
        try:
            self._buf += msg
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                if line:
                    self._logger.log(self._level, line)
        finally:
            self._in_write = False
        return n

    def flush(self) -> None:
        if self._in_write or not self._buf:
            return
        self._in_write = True
        try:
            self._logger.log(self._level, self._buf)
            self._buf = ""
        finally:
            self._in_write = False

    def isatty(self) -> bool:
        return False


def _drop_oversized(path: Path) -> None:
    """Unlink a log left behind by launchd (unbounded, mostly poller noise).

    ``RotatingFileHandler`` would rename it to ``.1`` and keep ~300 MB of
    haystack on disk until the next rollover. Dropping it is the bound.
    """
    try:
        if path.is_file() and path.stat().st_size > LOG_MAX_BYTES:
            path.unlink()
    except OSError:
        pass


def configure(*, console: bool | None = None) -> Path:
    """Install the rotating file handler on the root logger.

    ``console`` defaults to "stderr is a TTY" so a foreground
    ``make dev-daemon`` still prints, while the launchd job (stdio →
    ``/dev/null``) only writes the file. Non-TTY stdio is redirected
    into the log so ``print`` is not lost.
    """
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _drop_oversized(path)

    fmt = logging.Formatter(_LOG_FORMAT)
    file_h = logging.handlers.RotatingFileHandler(
        path,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_h.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass
    root.addHandler(file_h)

    if console is None:
        try:
            console = bool(sys.stderr.isatty())
        except Exception:
            console = False
    if console:
        stream_h = logging.StreamHandler(sys.stderr)
        stream_h.setFormatter(fmt)
        root.addHandler(stream_h)
    else:
        sys.stdout = _StreamToLogger(logging.getLogger("switchbay.stdout"), logging.INFO)  # type: ignore[assignment]
        sys.stderr = _StreamToLogger(logging.getLogger("switchbay.stderr"), logging.ERROR)  # type: ignore[assignment]

    return path
