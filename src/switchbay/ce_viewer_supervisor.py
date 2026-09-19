"""Keep the CE HTML viewer alive for Switchbay proxied Graph embeds.

When ``proxied_skill_embeds`` is on, Graph loads CE through ``/embed/ce/*``.
That requires a long-lived CE ``viewer.sh serve`` on loopback. This module
starts it, health-checks it, and restarts it if it dies. Optional wiki
mtime polling triggers ``viewer.sh build`` so the served bundle tracks
wiki edits (reload still needed in the Phase 4a HTML panel).
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

from . import app_settings, cebridge, embed_proxy

log = logging.getLogger("switchbay.ce_viewer_supervisor")

_PID_NAME = "ce-viewer.pid"
_LOG_NAME = "ce-viewer.log"
_HEALTH_PATH = "/"
_POLL_SEC = 8.0
_WIKI_POLL_SEC = 15.0


def _state_dir() -> Path:
    d = Path.home() / ".local" / "state" / "switchbay"
    d.mkdir(parents=True, exist_ok=True)
    return d


def pid_path() -> Path:
    return _state_dir() / _PID_NAME


def log_path() -> Path:
    return _state_dir() / _LOG_NAME


def upstream_base() -> str:
    return embed_proxy.ce_upstream()


def upstream_port() -> int:
    u = urlparse(upstream_base())
    if u.port:
        return int(u.port)
    return 443 if u.scheme == "https" else 80


def health_url() -> str:
    return upstream_base().rstrip("/") + _HEALTH_PATH


def is_healthy(*, timeout: float = 2.0) -> bool:
    try:
        with urlopen(health_url(), timeout=timeout) as resp:  # noqa: S310 — loopback only
            return 200 <= int(getattr(resp, "status", 200)) < 500
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
    # Match embed proxy prefix so asset URLs work under /embed/ce/.
    return (os.environ.get("CE_PUBLIC_BASE") or "/embed/ce").rstrip("/") or "/embed/ce"


def start(workspace: Path) -> dict[str, Any]:
    """Start CE viewer.sh serve if not healthy. Idempotent."""
    workspace = Path(workspace).expanduser().resolve()
    if is_healthy():
        return {
            "ok": True,
            "already_running": True,
            "healthy": True,
            "url": upstream_base(),
            "port": upstream_port(),
            "pid": _read_pid(),
        }

    if not cebridge.has_wiki(workspace):
        return {
            "ok": False,
            "error": f"no wiki/ under workspace {workspace}",
            "hint": "Open a CE wiki workspace or run curiosity-engine setup.",
        }

    script = cebridge.ce_root() / "scripts" / "viewer.sh"
    if not script.is_file():
        return {
            "ok": False,
            "error": f"viewer.sh not found under {cebridge.ce_root()}",
            "hint": "Install CE skill or set SWITCHBAY_CE_ROOT.",
        }

    port = upstream_port()
    # Drop stale pid if process is gone.
    old = _read_pid()
    if old and not _pid_alive(old):
        try:
            pid_path().unlink(missing_ok=True)
        except OSError:
            pass

    env = os.environ.copy()
    env["CE_PUBLIC_BASE"] = _public_base()
    # Prefer the same CE root Switchbay already resolved.
    env.setdefault("SWITCHBAY_CE_ROOT", str(cebridge.ce_root()))

    logf = log_path().open("a", encoding="utf-8")
    try:
        proc = subprocess.Popen(  # noqa: S603
            ["bash", str(script), "serve", str(port)],
            cwd=str(workspace),
            env=env,
            stdout=logf,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as e:
        logf.close()
        return {"ok": False, "error": f"failed to spawn viewer: {e}"}

    try:
        pid_path().write_text(str(proc.pid) + "\n", encoding="utf-8")
    except OSError as e:
        log.warning("could not write ce-viewer pid: %s", e)

    # Wait briefly for bind.
    deadline = time.time() + 12.0
    while time.time() < deadline:
        if is_healthy():
            return {
                "ok": True,
                "already_running": False,
                "healthy": True,
                "url": upstream_base(),
                "port": port,
                "pid": proc.pid,
                "workspace": str(workspace),
                "log": str(log_path()),
            }
        if proc.poll() is not None:
            return {
                "ok": False,
                "error": f"viewer exited early code={proc.returncode}",
                "log": str(log_path()),
            }
        time.sleep(0.4)

    return {
        "ok": False,
        "error": "viewer started but health check timed out",
        "pid": proc.pid,
        "log": str(log_path()),
        "url": upstream_base(),
    }


def stop() -> dict[str, Any]:
    pid = _read_pid()
    if not pid:
        return {"ok": True, "stopped": False, "note": "no pid file"}
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as e:
        pid_path().unlink(missing_ok=True)
        return {"ok": True, "stopped": False, "note": f"pid gone: {e}"}
    deadline = time.time() + 5.0
    while time.time() < deadline and _pid_alive(pid):
        time.sleep(0.2)
    if _pid_alive(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    pid_path().unlink(missing_ok=True)
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
        "ce_root": str(cebridge.ce_root()),
        "workspace": str(workspace) if workspace else None,
        "proxied_skill_embeds": app_settings.get_proxied_skill_embeds(),
        "log": str(log_path()),
    }


def rebuild_bundle(workspace: Path) -> dict[str, Any]:
    """Run viewer.sh build so the served bundle picks up wiki edits."""
    workspace = Path(workspace).expanduser().resolve()
    if not cebridge.has_wiki(workspace):
        return {"ok": False, "error": "no wiki/"}
    script = cebridge.ce_root() / "scripts" / "viewer.sh"
    if not script.is_file():
        return {"ok": False, "error": f"viewer.sh missing under {cebridge.ce_root()}"}
    env = os.environ.copy()
    env["CE_PUBLIC_BASE"] = _public_base()
    try:
        proc = subprocess.run(  # noqa: S603
            ["bash", str(script), "build"],
            cwd=str(workspace),
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "error": str(e)}
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-800:]
        return {"ok": False, "error": f"build exit {proc.returncode}", "detail": tail}
    return {"ok": True, "rebuilt": True}


def _wiki_mtime(workspace: Path) -> float:
    wiki = Path(workspace) / "wiki"
    if not wiki.is_dir():
        return 0.0
    newest = 0.0
    try:
        for p in wiki.rglob("*"):
            if p.is_file():
                try:
                    newest = max(newest, p.stat().st_mtime)
                except OSError:
                    continue
    except OSError:
        return newest
    return newest


async def run_supervisor(app: Any) -> None:
    """Background task: keep CE up while proxied embeds are enabled."""
    last_wiki_mtime = 0.0
    last_rebuild = 0.0
    while True:
        try:
            if not app_settings.get_proxied_skill_embeds():
                await asyncio.sleep(_POLL_SEC)
                continue
            ws = Path(app["workspace"])
            if not is_healthy():
                log.info("CE viewer unhealthy — starting for %s", ws)
                out = await asyncio.to_thread(start, ws)
                if not out.get("ok"):
                    log.warning("CE viewer start failed: %s", out.get("error"))
            else:
                # Rebuild static bundle when wiki changes (Phase 4a panel
                # still needs a browser reload; keep-alive is the hard part).
                mtime = await asyncio.to_thread(_wiki_mtime, ws)
                now = time.time()
                if (
                    mtime > last_wiki_mtime
                    and last_wiki_mtime > 0.0
                    and (now - last_rebuild) > _WIKI_POLL_SEC
                ):
                    last_rebuild = now
                    reb = await asyncio.to_thread(rebuild_bundle, ws)
                    log.info("CE viewer rebuild after wiki change: %s", reb)
                if last_wiki_mtime == 0.0:
                    last_wiki_mtime = mtime
                elif mtime > last_wiki_mtime:
                    last_wiki_mtime = mtime
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("CE viewer supervisor loop error")
        await asyncio.sleep(_POLL_SEC)
