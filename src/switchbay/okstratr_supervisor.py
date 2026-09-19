"""Keep okstratr desk kernel alive for Switchbay (core skill).

Mirrors ``ce_viewer_supervisor``: start on loopback (default
``http://127.0.0.1:8767``, override ``SWITCHBAY_OKSTRATR_UPSTREAM``),
health-check ``/health``, restart on death. Pid/log under
``~/.local/state/switchbay/``.

Spawn: ``okstratr serve --host/--port`` on PATH (or
``SWITCHBAY_OKSTRATR_BIN`` / ``python -m okstratr serve``). Uses the
long-lived ``serve`` entry (same as okstratr ``lifecycle._spawn_serve``),
not ``start`` which exits after detaching.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

from . import embed_proxy

log = logging.getLogger("switchbay.okstratr_supervisor")

_PID_NAME = "okstratr.pid"
_LOG_NAME = "okstratr.log"
_HEALTH_PATH = "/health"
_POLL_SEC = 5.0

# Contract C1 state machine (shared with core_skills.status).
_STATE: dict[str, Any] = {
    "state": "stopped",  # starting|healthy|unhealthy|stopped
    "detail": "",
}


def _state_dir() -> Path:
    d = Path.home() / ".local" / "state" / "switchbay"
    d.mkdir(parents=True, exist_ok=True)
    return d


def pid_path() -> Path:
    return _state_dir() / _PID_NAME


def log_path() -> Path:
    return _state_dir() / _LOG_NAME


def upstream_base() -> str:
    return embed_proxy.okstratr_upstream()


def upstream_port() -> int:
    u = urlparse(upstream_base())
    if u.port:
        return int(u.port)
    return 443 if u.scheme == "https" else 80


def upstream_host() -> str:
    u = urlparse(upstream_base())
    return u.hostname or "127.0.0.1"


def health_url() -> str:
    return upstream_base().rstrip("/") + _HEALTH_PATH


def is_healthy(*, timeout: float = 2.0) -> bool:
    try:
        with urlopen(health_url(), timeout=timeout) as resp:  # noqa: S310 — loopback
            if not (200 <= int(getattr(resp, "status", 200)) < 500):
                return False
            # okstratr /health returns {"ok": true}; tolerate plain 200 too.
            raw = resp.read().decode("utf-8", errors="replace")
            if not raw.strip():
                return True
            import json

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                return True
            if isinstance(data, dict) and "ok" in data:
                return bool(data.get("ok"))
            return True
    except (URLError, OSError, TimeoutError, ValueError):
        return False


def _read_pid() -> int | None:
    p = pid_path()
    if not p.is_file():
        return None
    try:
        raw = p.read_text(encoding="utf-8").strip()
        return int(raw) if raw else None
    except (OSError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _public_base() -> str:
    return (
        os.environ.get("OKSTRATR_PUBLIC_BASE") or "/embed/okstratr"
    ).rstrip("/") or "/embed/okstratr"


def resolve_okstratr_argv() -> list[str]:
    """Return argv prefix to invoke okstratr CLI (no subcommand yet)."""
    override = (os.environ.get("SWITCHBAY_OKSTRATR_BIN") or "").strip()
    if override:
        return [override]
    exe = shutil.which("okstratr")
    if exe:
        return [exe]
    return [sys.executable or "python3", "-m", "okstratr"]


def _set_state(state: str, detail: str = "") -> None:
    _STATE["state"] = state
    _STATE["detail"] = detail


def contract_slice() -> dict[str, Any]:
    """C1 status slice for okstratr."""
    healthy = is_healthy()
    pid = _read_pid()
    if healthy:
        state = "healthy"
        detail = _STATE.get("detail") or "up"
    elif _STATE.get("state") == "starting":
        state = "starting"
        detail = _STATE.get("detail") or "starting"
    elif pid and _pid_alive(pid):
        state = "unhealthy"
        detail = _STATE.get("detail") or "process up but /health failing"
    elif _STATE.get("state") == "unhealthy":
        state = "unhealthy"
        detail = _STATE.get("detail") or "unhealthy"
    else:
        state = "stopped"
        detail = _STATE.get("detail") or "stopped"
    return {
        "state": state,
        "url": upstream_base(),
        "detail": detail,
    }


def start(workspace: Path | None = None) -> dict[str, Any]:
    """Start okstratr serve if not healthy. Idempotent."""
    if is_healthy():
        _set_state("healthy", "already running")
        return {
            "ok": True,
            "already_running": True,
            "healthy": True,
            "url": upstream_base(),
            "port": upstream_port(),
            "pid": _read_pid(),
        }

    _set_state("starting", "spawning okstratr serve")
    old = _read_pid()
    if old and not _pid_alive(old):
        try:
            pid_path().unlink(missing_ok=True)
        except OSError:
            pass

    host = upstream_host()
    port = upstream_port()
    # Use `serve` (long-lived HTTP), not `start` (launcher that exits after
    # detaching). Same command lifecycle._spawn_serve uses.
    argv = resolve_okstratr_argv() + [
        "serve",
        "--host",
        host,
        "--port",
        str(port),
    ]

    env = os.environ.copy()
    env["OKSTRATR_PUBLIC_BASE"] = _public_base()
    # Prefer embed public base so hosted observer URLs match /embed/okstratr.
    if workspace is not None:
        env.setdefault("OKSTRATR_WORKSPACE", str(Path(workspace).expanduser()))

    logf = log_path().open("a", encoding="utf-8")
    try:
        proc = subprocess.Popen(  # noqa: S603
            argv,
            cwd=str(Path(workspace).expanduser()) if workspace else None,
            env=env,
            stdout=logf,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as e:
        logf.close()
        _set_state("unhealthy", f"failed to spawn: {e}")
        return {"ok": False, "error": f"failed to spawn okstratr: {e}", "argv": argv}

    try:
        pid_path().write_text(str(proc.pid) + "\n", encoding="utf-8")
    except OSError as e:
        log.warning("could not write okstratr pid: %s", e)

    deadline = time.time() + 15.0
    while time.time() < deadline:
        if is_healthy():
            _set_state("healthy", "started")
            return {
                "ok": True,
                "already_running": False,
                "healthy": True,
                "url": upstream_base(),
                "port": port,
                "pid": proc.pid,
                "argv": argv,
                "log": str(log_path()),
            }
        if proc.poll() is not None:
            _set_state("unhealthy", f"serve exited code={proc.returncode}")
            return {
                "ok": False,
                "error": f"okstratr serve exited early code={proc.returncode}",
                "log": str(log_path()),
                "argv": argv,
            }
        time.sleep(0.4)

    if is_healthy():
        _set_state("healthy", "started (late health)")
        return {
            "ok": True,
            "already_running": False,
            "healthy": True,
            "url": upstream_base(),
            "port": port,
            "pid": proc.pid,
            "argv": argv,
            "log": str(log_path()),
        }

    _set_state("unhealthy", "health check timed out")
    return {
        "ok": False,
        "error": "okstratr started but health check timed out",
        "pid": proc.pid,
        "log": str(log_path()),
        "url": upstream_base(),
        "argv": argv,
    }


def stop() -> dict[str, Any]:
    """Stop the serve process we spawned (best-effort)."""
    pid = _read_pid()
    if not pid:
        _set_state("stopped", "no pid file")
        return {"ok": True, "stopped": False, "note": "no pid file"}
    if not _pid_alive(pid):
        try:
            pid_path().unlink(missing_ok=True)
        except OSError:
            pass
        _set_state("stopped", "pid gone")
        return {"ok": True, "stopped": False, "note": "pid gone", "pid": pid}
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as e:
        try:
            pid_path().unlink(missing_ok=True)
        except OSError:
            pass
        _set_state("stopped", f"pid gone: {e}")
        return {"ok": True, "stopped": False, "note": f"pid gone: {e}", "pid": pid}
    deadline = time.time() + 5.0
    while time.time() < deadline and _pid_alive(pid):
        time.sleep(0.2)
    if _pid_alive(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    try:
        pid_path().unlink(missing_ok=True)
    except OSError:
        pass
    _set_state("stopped", "stopped")
    return {"ok": True, "stopped": True, "pid": pid}


def status(workspace: Path | None = None) -> dict[str, Any]:
    pid = _read_pid()
    return {
        "ok": True,
        "healthy": is_healthy(),
        "url": upstream_base(),
        "port": upstream_port(),
        "pid": pid,
        "pid_alive": _pid_alive(pid) if pid else False,
        "public_base": _public_base(),
        "argv_prefix": resolve_okstratr_argv(),
        "workspace": str(workspace) if workspace else None,
        "log": str(log_path()),
        "contract": contract_slice(),
    }


async def run_supervisor(app: Any) -> None:
    """Background task: always keep okstratr up (core experience)."""
    while True:
        try:
            if not is_healthy():
                ws = Path(app["workspace"])
                log.info("okstratr unhealthy — starting for %s", ws)
                _set_state("starting", "supervisor restart")
                out = await asyncio.to_thread(start, ws)
                if not out.get("ok"):
                    _set_state("unhealthy", str(out.get("error") or "start failed"))
                    log.warning("okstratr start failed: %s", out.get("error"))
                else:
                    _set_state("healthy", "supervisor")
            else:
                _set_state("healthy", "supervisor")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("okstratr supervisor loop error")
            _set_state("unhealthy", "supervisor loop error")
        await asyncio.sleep(_POLL_SEC)
