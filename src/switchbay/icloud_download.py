"""macOS iCloud Drive download-on-demand for a single watched file.

Uses the public Foundation API ``NSFileManager.startDownloadingUbiquitousItemAtURL:error:``
via a bundled JXA helper (``/usr/bin/osascript -l JavaScript``). The file path is
passed as an argv element — never interpolated into JavaScript or a shell command.

This starts a download for one item and then polls until the bytes are local.
It does not evict, pin, change "Keep Downloaded", or recursively sync a tree.
Only iCloud on darwin is implemented; other cloud placeholders stay retryable
pending without claiming support.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import statedir

log = logging.getLogger(__name__)

HELPER = Path(__file__).resolve().parent / "helpers" / "icloud_download.js"
OSASCRIPT = "/usr/bin/osascript"
# Overall bound for probe + start + poll (not 8s each).
HYDRATE_WAIT = 8.0
_POLL = 0.25

# Legacy iCloud stub: ".Presentation.pptx.icloud"
_ICLOUD_STUB_SUFFIX = ".icloud"


@dataclass
class HydrateResult:
    ok: bool
    ready: bool
    path: str
    error: str | None = None
    retryable: bool = True
    ubiquitous: bool = False
    started: bool = False
    detail: str | None = None


def supported() -> bool:
    """True when this process can invoke the public macOS download API."""
    return (
        sys.platform == "darwin"
        and Path(OSASCRIPT).is_file()
        and HELPER.is_file()
    )


def is_icloud_stub(path: Path | str) -> bool:
    name = Path(path).name
    return name.startswith(".") and name.endswith(_ICLOUD_STUB_SUFFIX) and len(name) > 8


def logical_path(path: Path | str) -> Path:
    """Map a legacy ``.name.ext.icloud`` stub to the visible filename."""
    p = Path(path)
    if is_icloud_stub(p):
        return p.with_name(p.name[1 : -len(_ICLOUD_STUB_SUFFIX)])
    return p


def _is_ready(path: Path) -> bool:
    try:
        if is_icloud_stub(path):
            return False
        if not path.is_file():
            return False
        if statedir.is_dataless(path):
            return False
        return path.stat().st_size > 0
    except OSError:
        return False


def ready_path(path: Path) -> Path | None:
    """Return a locally readable path for ``path``, or None if still a placeholder."""
    logical = logical_path(path)
    for cand in (logical, path):
        try:
            if _is_ready(cand):
                return cand
        except OSError:
            continue
    return None


def run_helper(action: str, path: Path, *, timeout: float = 15.0) -> dict[str, Any]:
    """Run the JXA helper. ``path`` is argv-only (no string interpolation)."""
    if action not in {"probe", "status", "start"}:
        return {"ok": False, "error": f"unknown action {action!r}"}
    if not supported():
        return {"ok": False, "error": "icloud download helper unavailable", "unsupported": True}
    try:
        proc = subprocess.run(
            [OSASCRIPT, "-l", "JavaScript", str(HELPER), action, str(path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"osascript timed out after {int(timeout)}s", "retryable": True}
    except OSError as e:
        return {"ok": False, "error": f"osascript failed: {e}", "retryable": True}
    stdout = (proc.stdout or "").strip()
    parsed: Any = None
    if stdout:
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError:
            # JXA may print logs; take the last JSON object.
            start, end = stdout.rfind("{"), stdout.rfind("}")
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(stdout[start : end + 1])
                except json.JSONDecodeError:
                    parsed = None
    if isinstance(parsed, dict):
        if proc.returncode and "error" not in parsed:
            parsed["error"] = (proc.stderr or "").strip() or f"osascript exited {proc.returncode}"
        return parsed
    err = (proc.stderr or stdout or f"osascript exited {proc.returncode}")[-400:]
    return {"ok": False, "error": err, "retryable": True}


def hydrate_file(path: Path, *, timeout: float = HYDRATE_WAIT) -> HydrateResult:
    """Ensure ``path`` is local. Starts an iCloud download when needed; bounded wait."""
    path = Path(path)
    existing = ready_path(path)
    if existing is not None:
        return HydrateResult(ok=True, ready=True, path=str(existing), retryable=False)

    hint = statedir.sync_service_hint(path)
    stub = is_icloud_stub(path)
    dataless = False
    try:
        dataless = path.exists() and statedir.is_dataless(path)
    except OSError:
        dataless = False

    if hint and hint != "iCloud" and not stub:
        return HydrateResult(
            ok=False,
            ready=False,
            path=str(path),
            error=f"{hint} placeholder; download-on-demand is iCloud-only",
            retryable=True,
            detail=hint,
        )

    if sys.platform != "darwin":
        return HydrateResult(
            ok=False,
            ready=False,
            path=str(path),
            error="cloud placeholder; download-on-demand is macOS iCloud only",
            retryable=True,
        )

    if not supported():
        return HydrateResult(
            ok=False,
            ready=False,
            path=str(path),
            error="osascript/JXA helper unavailable",
            retryable=True,
        )

    deadline = time.monotonic() + max(0.2, timeout)

    def _remain() -> float:
        return max(0.05, deadline - time.monotonic())

    probe = run_helper("probe", path, timeout=min(_remain(), 2.0))
    ubiquitous = bool(probe.get("ubiquitous"))
    if not ubiquitous and not stub and not dataless:
        # Local non-iCloud file that is empty or missing — not ours to download.
        try:
            size = path.stat().st_size if path.is_file() else 0
        except OSError as e:
            return HydrateResult(
                ok=False, ready=False, path=str(path),
                error=f"access denied: {e}", retryable=True,
            )
        if size == 0:
            return HydrateResult(
                ok=False, ready=False, path=str(path),
                error="placeholder size 0", retryable=True, detail="size0",
            )
        if not path.exists():
            return HydrateResult(
                ok=False, ready=False, path=str(path),
                error="source disappeared", retryable=True, detail="missing",
            )
        return HydrateResult(ok=True, ready=True, path=str(path), retryable=False)

    if time.monotonic() >= deadline:
        return HydrateResult(
            ok=False, ready=False, path=str(path),
            error="iCloud download did not finish in time",
            retryable=True, ubiquitous=ubiquitous, detail="timeout",
        )
    start = run_helper("start", path, timeout=min(_remain(), 2.0))
    started = bool(start.get("started") or start.get("ok"))
    while time.monotonic() < deadline:
        got = ready_path(path)
        if got is not None:
            return HydrateResult(
                ok=True, ready=True, path=str(got),
                ubiquitous=ubiquitous, started=started, retryable=False,
            )
        time.sleep(_POLL)

    got = ready_path(path)
    if got is not None:
        return HydrateResult(
            ok=True, ready=True, path=str(got),
            ubiquitous=ubiquitous, started=started, retryable=False,
        )
    err = start.get("error") if isinstance(start, dict) else None
    return HydrateResult(
        ok=False,
        ready=False,
        path=str(path),
        error=str(err or "iCloud download did not finish in time"),
        retryable=True,
        ubiquitous=ubiquitous,
        started=started,
        detail="timeout",
    )


def helper_argv(action: str, path: Path) -> list[str]:
    """Argv used to invoke the helper (tests assert no shell interpolation)."""
    return [OSASCRIPT, "-l", "JavaScript", str(HELPER), action, str(path)]
