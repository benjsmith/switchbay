"""Watch-folders: auto-ingest NEW files from user-chosen directories.

Model:
  * Config (``.workbench/watch-folders.json``, roams with the
    workspace): ``[{path, enabled, added_at}]`` — absolute directories.
  * Seen-index (machine-local, ``statedir.workspace_state_dir()/
    watch-seen.json``): marked only after a file is staged and CE ingest
    hands off accepted extracted content. Crash/download/staging failure
    must not permanently lose the file.
  * Pending-index (same state dir, ``watch-pending.json``): retryable
    hydration/staging/ingest failures, including iCloud placeholders
    and size-0 files. Surfaced on the watch-folders API.
  * On ADD the folder is BASELINED — everything already inside is
    marked seen without ingesting (new files from now on only).
  * Each daemon beat picks up to ``MAX_PER_BEAT`` due files. Ready
    local files and due cloud/retry items each get a bounded share of
    the cap so neither side starves. iCloud download-on-demand is
    per-file, macOS only.

Deterministic CE extraction (``ce_ingest`` / ``local_ingest.py``) runs
before any model dispatch and writes vault ``.extracted.md``. Wiki
pages are a later Curate pass — watch ingest does not create wiki
pages. Other extensions are skipped (marked seen, not claimed ingested).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import stat as _stat
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from . import atomicio
from . import icloud_download
from . import ingest_prep
from . import statedir

log = logging.getLogger(__name__)

CONFIG_FILE = "watch-folders.json"
SEEN_FILE = "watch-seen.json"
PENDING_FILE = "watch-pending.json"

# Per-beat dispatch cap — see module docstring.
MAX_PER_BEAT = 5
# Files larger than the upload-ingest cap are skipped (same limit).
MAX_FILE_BYTES = 50 * 1024 * 1024
# In-flight / junk suffixes that must never auto-ingest.
_SKIP_SUFFIXES = {".tmp", ".part", ".crdownload", ".download", ".swp", ".lock"}
# Copy-settle: a file modified this recently may still be mid-write.
SETTLE_SECONDS = 5.0
HYDRATE_WAIT = icloud_download.HYDRATE_WAIT
STAGE_TIMEOUT = 30.0
INGEST_TIMEOUT = 90.0
MAX_BACKOFF = 300.0
_BACKOFF_EXP_CAP = 8  # 15 * 2**8 = 3840, then clipped to MAX_BACKOFF
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_INDEX_LOCK = threading.RLock()
WATCH_STAGE_REL = "vault/.watch-ingest"

# Copy worker: paths arrive as argv. Refuses symlinks, enforces size cap
# during the copy, and aborts if the source identity (size / mtime_ns /
# inode / device) changes. Opens with O_NOFOLLOW when available so a
# final-component symlink swap cannot replace the lstat'd file.
_COPY_WORKER = r"""
import os, stat, sys
src, dst, max_b_s, exp_size_s, exp_mtime_ns_s, exp_ino_s, exp_dev_s, exp_mtime_s = sys.argv[1:9]
max_b = int(max_b_s)
exp_size = int(exp_size_s)
exp_mtime_ns = int(exp_mtime_ns_s)
exp_ino = int(exp_ino_s)
exp_dev = int(exp_dev_s)
exp_mtime = float(exp_mtime_s)

def refuse_symlink(st):
    if stat.S_ISLNK(st.st_mode):
        sys.stderr.write("symlink refused\n")
        sys.exit(2)

def identity_ok(st):
    if st.st_size != exp_size:
        return False
    if exp_ino != 0 and (st.st_ino != exp_ino or st.st_dev != exp_dev):
        return False
    if st.st_mtime_ns == exp_mtime_ns:
        return True
    # Float-only callers (no inode snapshot) still reject any mtime change,
    # including sub-second, without a 1s tolerance.
    if exp_ino == 0 and st.st_mtime == exp_mtime:
        return True
    return False

st = os.lstat(src)
refuse_symlink(st)
if st.st_size != exp_size:
    sys.stderr.write("source size changed\n")
    sys.exit(3)
if not identity_ok(st):
    sys.stderr.write("source changed mid-copy\n")
    sys.exit(4)
if st.st_size <= 0 or st.st_size > max_b:
    sys.stderr.write("size cap\n")
    sys.exit(5)
flags = os.O_RDONLY
if hasattr(os, "O_BINARY"):
    flags |= os.O_BINARY
if hasattr(os, "O_CLOEXEC"):
    flags |= os.O_CLOEXEC
if hasattr(os, "O_NOFOLLOW"):
    flags |= os.O_NOFOLLOW
try:
    fd = os.open(src, flags)
except OSError as e:
    sys.stderr.write("source open failed: %s\n" % e)
    sys.exit(2)
written = 0
try:
    stf = os.fstat(fd)
    if stf.st_ino != st.st_ino or stf.st_dev != st.st_dev:
        sys.stderr.write("source changed mid-copy\n")
        sys.exit(4)
    if not identity_ok(stf):
        sys.stderr.write("source changed mid-copy\n")
        sys.exit(4)
    parent = os.path.dirname(dst)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(dst, "wb") as out:
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > max_b:
                sys.stderr.write("size cap during copy\n")
                sys.exit(5)
            out.write(chunk)
            st2 = os.fstat(fd)
            if not identity_ok(st2):
                sys.stderr.write("source changed mid-copy\n")
                sys.exit(4)
        out.flush()
        os.fsync(out.fileno())
finally:
    os.close(fd)
if written != exp_size:
    sys.stderr.write("partial copy\n")
    sys.exit(6)
"""


class IndexSyncError(Exception):
    """CE/index provenance update failed after a successful extract rewrite."""


# ── Config ─────────────────────────────────────────────────────────


def _config_path(workspace: Path) -> Path:
    return workspace / ".workbench" / CONFIG_FILE


def list_folders(workspace: Path) -> list[dict[str, Any]]:
    p = _config_path(workspace)
    if not p.is_file():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    out = []
    for f in raw:
        if isinstance(f, dict) and f.get("path"):
            out.append({
                "path": str(f["path"]),
                "enabled": bool(f.get("enabled", True)),
                "added_at": float(f.get("added_at") or 0),
            })
    return out


def _save_folders(workspace: Path, folders: list[dict[str, Any]]) -> None:
    p = _config_path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(p, folders)


def add_folder(workspace: Path, raw: str) -> dict[str, Any] | str:
    """Register a directory and baseline its current contents as
    seen. Returns the folder record, or an error string."""
    d = Path(os.path.expanduser(raw.strip()))
    if not d.is_absolute():
        return "path must be absolute (or ~-relative)"
    try:
        d = d.resolve()
    except OSError:
        pass
    if not d.is_dir():
        return "not a directory"
    from . import workspaces
    if not workspaces.is_within_home(d):
        return f"watch folders must stay under {workspaces.home_label()}"
    ws_real = str(workspace.resolve())
    if str(d) == ws_real or str(d).startswith(ws_real + os.sep):
        return "that's inside the workspace — it's already browsable and ingestable"
    folders = list_folders(workspace)
    if any(f["path"] == str(d) for f in folders):
        return "already watched"
    rec = {"path": str(d), "enabled": True, "added_at": time.time()}
    folders.append(rec)
    _save_folders(workspace, folders)
    # Baseline: mark everything currently present as seen.
    with _INDEX_LOCK:
        seen = _load_seen(workspace)
        for cand in _iter_folder_files(d):
            seen[cand.logical] = {"mtime": cand.mtime, "size": cand.size}
        _save_seen(workspace, seen)
    return rec


def remove_folder(workspace: Path, raw: str) -> bool:
    folders = list_folders(workspace)
    kept = [f for f in folders if f["path"] != raw]
    if len(kept) == len(folders):
        return False
    _save_folders(workspace, kept)
    return True


def set_enabled(workspace: Path, raw: str, enabled: bool) -> bool:
    folders = list_folders(workspace)
    for f in folders:
        if f["path"] == raw:
            f["enabled"] = bool(enabled)
            _save_folders(workspace, folders)
            if enabled:
                # Re-baseline on re-enable: files that arrived while
                # the folder was paused are deliberately NOT ingested
                # (pausing means "stop watching", not "queue up").
                d = Path(f["path"])
                with _INDEX_LOCK:
                    seen = _load_seen(workspace)
                    if d.is_dir():
                        for cand in _iter_folder_files(d):
                            seen[cand.logical] = {
                                "mtime": cand.mtime, "size": cand.size,
                            }
                        _save_seen(workspace, seen)
            return True
    return False


def folder_authorized(workspace: Path, folder_path: str) -> bool:
    """True when ``folder_path`` is still an enabled watch folder."""
    for f in list_folders(workspace):
        if f["path"] == folder_path and f["enabled"]:
            return True
    return False


def handoff_allowed(workspace: Path, folder_path: str) -> str | None:
    """None if ingest may proceed; otherwise a skip reason."""
    from . import admin_policy
    if not admin_policy.feature_enabled("watch_folders"):
        return "watch folders disabled by admin policy"
    if not folder_authorized(workspace, folder_path):
        return "watch folder paused or removed"
    return None


# ── Seen / pending (machine-local) ─────────────────────────────────


def _seen_path(workspace: Path) -> Path:
    return statedir.workspace_state_dir(workspace) / SEEN_FILE


def _pending_path(workspace: Path) -> Path:
    return statedir.workspace_state_dir(workspace) / PENDING_FILE


def _load_seen(workspace: Path) -> dict[str, dict[str, float]]:
    p = _seen_path(workspace)
    if not p.is_file():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _save_seen(workspace: Path, seen: dict[str, dict[str, float]]) -> None:
    p = _seen_path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(p, seen)


def _load_pending(workspace: Path) -> dict[str, dict[str, Any]]:
    p = _pending_path(workspace)
    if not p.is_file():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _save_pending(workspace: Path, pending: dict[str, dict[str, Any]]) -> None:
    p = _pending_path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(p, pending)


def list_pending(workspace: Path) -> list[dict[str, Any]]:
    pending = _load_pending(workspace)
    out: list[dict[str, Any]] = []
    for path, rec in pending.items():
        if not isinstance(rec, dict):
            continue
        out.append({
            "path": path,
            "state": str(rec.get("state") or "pending"),
            "error": rec.get("error"),
            "retryable": bool(rec.get("retryable", True)),
            "attempts": int(rec.get("attempts") or 0),
            "next_attempt": float(rec.get("next_attempt") or 0),
            "updated_at": float(rec.get("updated_at") or 0),
        })
    out.sort(key=lambda r: r.get("updated_at") or 0, reverse=True)
    return out


def mark_seen(workspace: Path, logical: str, *, mtime: float, size: int) -> None:
    with _INDEX_LOCK:
        seen = _load_seen(workspace)
        seen[logical] = {"mtime": mtime, "size": float(size)}
        _save_seen(workspace, seen)
        pending = _load_pending(workspace)
        if logical in pending:
            pending.pop(logical, None)
            _save_pending(workspace, pending)


def clear_pending(workspace: Path, logical: str) -> None:
    with _INDEX_LOCK:
        pending = _load_pending(workspace)
        if logical in pending:
            pending.pop(logical, None)
            _save_pending(workspace, pending)


def _backoff(attempts: int) -> float:
    exp = min(max(0, int(attempts) - 1), _BACKOFF_EXP_CAP)
    return min(MAX_BACKOFF, 15.0 * (2 ** exp))


def record_pending(
    workspace: Path,
    logical: str,
    *,
    state: str,
    error: str | None,
    retryable: bool = True,
) -> dict[str, Any]:
    with _INDEX_LOCK:
        pending = _load_pending(workspace)
        prev = pending.get(logical) if isinstance(pending.get(logical), dict) else {}
        attempts = int(prev.get("attempts") or 0) + 1
        rec = {
            "state": state,
            "error": error,
            "retryable": retryable,
            "attempts": attempts,
            "next_attempt": time.time() + (
                _backoff(attempts) if retryable else MAX_BACKOFF
            ),
            "updated_at": time.time(),
        }
        pending[logical] = rec
        _save_pending(workspace, pending)
        return rec


# ── Scanning ───────────────────────────────────────────────────────


def _within(root: Path, candidate: Path) -> bool:
    try:
        root = root.resolve()
        candidate = candidate.resolve()
    except (OSError, ValueError):
        return False
    return candidate == root or root in candidate.parents


def _path_in_scope(folder: Path, full: str) -> Path | None:
    """Resolve ``full``; None if it escapes the watch folder or $HOME."""
    try:
        real = Path(full).resolve()
        folder_real = folder.resolve()
    except (OSError, ValueError):
        return None
    if not _within(folder_real, real):
        return None
    from . import workspaces
    if not workspaces.is_within_home(real):
        return None
    return real


def authorized_real_path(folder: str, path: Path) -> Path | None:
    """Re-check ``path`` against the approved folder and $HOME.

    Follows a symlink only after confirming the resolved target stays
    inside the watch folder and the user's home. Escaping swaps after
    scan are rejected.
    """
    try:
        folder_real = Path(folder).resolve()
        p = Path(path)
        os.lstat(p)
        real = p.resolve()
    except (OSError, ValueError):
        return None
    if not _within(folder_real, real):
        return None
    from . import workspaces
    if not workspaces.is_within_home(real):
        return None
    try:
        if not real.is_file():
            return None
    except OSError:
        return None
    return real


@dataclass
class Candidate:
    path: str
    logical: str
    folder: str
    size: int
    mtime: float
    hydrate: str = ""  # "", "dataless", "icloud_stub", "size0"
    ext: str = ""


def _logical_and_ext(name: str) -> tuple[str, str]:
    if icloud_download.is_icloud_stub(name):
        visible = name[1:-len(".icloud")]
        return visible, Path(visible).suffix.lower()
    return name, Path(name).suffix.lower()


def _iter_folder_files(root: Path) -> Iterable[Candidate]:
    """Yield candidates under ``root`` (icloud stubs included)."""
    try:
        root_real = root.resolve()
    except OSError:
        return
    for dirpath, dirnames, filenames in os.walk(root_real, followlinks=False):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            stub = icloud_download.is_icloud_stub(name)
            if name.startswith(".") and not stub:
                continue
            full = os.path.join(dirpath, name)
            scoped = _path_in_scope(root_real, full)
            if scoped is None:
                continue
            visible, ext = _logical_and_ext(name)
            logical = str(scoped.with_name(visible)) if stub else str(scoped)
            try:
                st = os.lstat(full) if stub else os.stat(full)
            except OSError:
                continue
            if not stub and os.path.islink(full):
                # lstat was not used; os.stat followed. Scope already
                # checked the real path. Skip if the link itself is the
                # only name and the target escaped (handled above).
                pass
            hydrate = ""
            size = int(getattr(st, "st_size", 0) or 0)
            if stub:
                hydrate = "icloud_stub"
            elif statedir.is_dataless(scoped):
                hydrate = "dataless"
            elif size == 0:
                hydrate = "size0"
            yield Candidate(
                path=str(scoped if not stub else Path(full)),
                logical=logical,
                folder=str(root_real),
                size=size,
                mtime=float(getattr(st, "st_mtime", 0) or 0),
                hydrate=hydrate,
                ext=ext,
            )


def _ingestable_ext(ext: str) -> bool:
    if ext in _SKIP_SUFFIXES:
        return False
    return ext in ingest_prep.CE_DEFAULT_EXTS


def scan_candidates(
    workspace: Path,
    *,
    inflight: set[str] | None = None,
    now: float | None = None,
) -> tuple[list[Candidate], int]:
    """One beat: return up to MAX_PER_BEAT due files without marking seen.

    Ready local files and due retries each get a bounded share of the
    cap when both exist, so cloud hydration cannot starve locals and
    locals cannot starve due retries.
    """
    folders = [f for f in list_folders(workspace) if f["enabled"]]
    if not folders:
        return [], 0
    inflight = inflight or set()
    now = time.time() if now is None else now
    ready: list[Candidate] = []
    due_pending: list[Candidate] = []
    waiting = 0
    with _INDEX_LOCK:
        seen = _load_seen(workspace)
        pending = _load_pending(workspace)
        dirty_seen = False
        for f in folders:
            d = Path(f["path"])
            if not d.is_dir():
                continue
            for cand in _iter_folder_files(d):
                if cand.logical in seen or cand.logical in inflight:
                    continue
                if cand.ext in _SKIP_SUFFIXES:
                    seen[cand.logical] = {"mtime": cand.mtime, "size": cand.size}
                    dirty_seen = True
                    continue
                if cand.size > MAX_FILE_BYTES:
                    seen[cand.logical] = {"mtime": cand.mtime, "size": cand.size}
                    dirty_seen = True
                    continue
                if not _ingestable_ext(cand.ext):
                    seen[cand.logical] = {"mtime": cand.mtime, "size": cand.size}
                    dirty_seen = True
                    continue
                if (
                    not cand.hydrate
                    and now - cand.mtime < SETTLE_SECONDS
                ):
                    waiting += 1
                    continue
                rec = pending.get(cand.logical)
                if isinstance(rec, dict):
                    nxt = float(rec.get("next_attempt") or 0)
                    if nxt > now:
                        waiting += 1
                        continue
                    due_pending.append(cand)
                    continue
                if cand.hydrate:
                    due_pending.append(cand)
                else:
                    ready.append(cand)
        if dirty_seen:
            _save_seen(workspace, seen)
    ready.sort(key=lambda c: c.mtime)
    due_pending.sort(key=lambda c: c.mtime)
    picked = _fair_pick(ready, due_pending, MAX_PER_BEAT)
    leftover_ready = max(0, len(ready) - sum(1 for c in picked if c in ready))
    leftover_pending = max(
        0, len(due_pending) - sum(1 for c in picked if c in due_pending),
    )
    backlog = leftover_ready + leftover_pending + waiting
    return picked, backlog


def _fair_pick(
    ready: list[Candidate], due: list[Candidate], cap: int,
) -> list[Candidate]:
    """Give both ready locals and due retries bounded progress."""
    if cap <= 0:
        return []
    if not ready:
        return due[:cap]
    if not due:
        return ready[:cap]
    due_take = min(len(due), max(1, cap // 2))
    ready_take = min(len(ready), cap - due_take)
    picked = ready[:ready_take] + due[:due_take]
    extra = cap - len(picked)
    if extra > 0:
        picked.extend(ready[ready_take:ready_take + extra])
        extra = cap - len(picked)
    if extra > 0:
        picked.extend(due[due_take:due_take + extra])
    return picked


def scan_new(workspace: Path) -> tuple[list[str], int]:
    """Compat wrapper: paths due this beat (not yet marked seen)."""
    picked, backlog = scan_candidates(workspace)
    return [c.path for c in picked], backlog


# ── Staging + handoff ──────────────────────────────────────────────


@dataclass
class HandoffResult:
    status: str  # success | pending | skipped | error
    retryable: bool = True
    error: str | None = None
    vault_rel: str | None = None
    extracted: str | None = None
    logical: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def _safe_filename(name: str) -> str:
    return _SAFE_NAME.sub("_", name) or "file.bin"


def _copy_bounded(
    src: Path,
    dest: Path,
    *,
    timeout: float,
    expected_size: int,
    expected_mtime: float,
    max_bytes: int = MAX_FILE_BYTES,
    expected_mtime_ns: int | None = None,
    expected_ino: int | None = None,
    expected_dev: int | None = None,
) -> None:
    """Copy ``src`` → ``dest`` via a killable child; refuse blank/partial."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.part")
    try:
        if tmp.exists():
            tmp.unlink()
    except OSError:
        pass
    if expected_mtime_ns is None:
        expected_mtime_ns = int(round(float(expected_mtime) * 1_000_000_000))
    try:
        proc = subprocess.run(
            [
                sys.executable, "-c", _COPY_WORKER,
                str(src), str(tmp),
                str(int(max_bytes)), str(int(expected_size)),
                str(int(expected_mtime_ns)),
                str(int(expected_ino or 0)),
                str(int(expected_dev or 0)),
                f"{float(expected_mtime):.17g}",
            ],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise TimeoutError(f"copy timed out after {int(timeout)}s") from None
    if proc.returncode != 0:
        try:
            tmp.unlink()
        except OSError:
            pass
        err = (proc.stderr or proc.stdout or b"").decode("utf-8", errors="replace")[-300:]
        raise OSError(err or f"copy exited {proc.returncode}")
    try:
        dst_size = tmp.stat().st_size
    except OSError as e:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise OSError(f"copy stat failed: {e}") from e
    if dst_size == 0 or dst_size != expected_size:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise OSError("blank or partial copy refused")
    os.replace(tmp, dest)


def stage_file(workspace: Path, src: Path, *, timeout: float = STAGE_TIMEOUT) -> tuple[str, int]:
    """Copy ``src`` into a unique ``vault/.watch-ingest/<attempt>/`` path.

    Always creates a new dest so a failed retry cannot recycle (and
    later delete) a pre-existing vault original. Returns (rel, size).
    """
    ws = workspace.resolve()
    src = Path(src)
    try:
        st = os.lstat(src)
    except OSError as e:
        raise OSError(f"source stat failed: {e}") from e
    if _stat.S_ISLNK(st.st_mode):
        raise OSError("symlink refused")
    safe_name = _safe_filename(src.name)
    attempt_dir = ws / "vault" / ".watch-ingest" / f"{os.getpid()}-{time.time_ns()}"
    dest = attempt_dir / safe_name
    _copy_bounded(
        src, dest, timeout=timeout,
        expected_size=int(st.st_size), expected_mtime=float(st.st_mtime),
        expected_mtime_ns=int(st.st_mtime_ns),
        expected_ino=int(st.st_ino), expected_dev=int(st.st_dev),
    )
    size = dest.stat().st_size
    if size == 0:
        try:
            dest.unlink()
        except OSError:
            pass
        raise OSError("blank copy refused")
    return str(dest.relative_to(ws)), size


def _default_ingest(workspace: Path, rel: str, timeout: float) -> dict[str, Any]:
    from . import ce_tools
    return ce_tools._ce_ingest(workspace, {"path": rel, "timeout": timeout})


def _cleanup_stage(workspace: Path, rel: str | None) -> None:
    """Delete only this attempt's ``vault/.watch-ingest/`` file."""
    if not rel:
        return
    try:
        path = (workspace / rel).resolve()
        root = (workspace.resolve() / "vault" / ".watch-ingest").resolve()
    except OSError:
        return
    if not _within(root, path):
        return
    try:
        if path.is_file():
            path.unlink()
        parent = path.parent
        while parent != root and _within(root, parent):
            if not parent.is_dir() or any(parent.iterdir()):
                break
            parent.rmdir()
            parent = parent.parent
    except OSError:
        pass


def _stamp_watch_source(workspace: Path, extracted: str, original: str) -> None:
    """Record the authorized original path on the extract we just wrote.

    Does not re-read the original file. CE ``source_path`` otherwise
    points at the staged vault copy.
    """
    if not extracted or not original:
        return
    cand = Path(extracted)
    if not cand.is_absolute():
        cand = workspace / extracted
    try:
        cand = cand.resolve()
        ws = workspace.resolve()
    except OSError:
        return
    if not _within(ws, cand) or not cand.name.endswith(".extracted.md"):
        return
    if not cand.is_file():
        return
    try:
        text = cand.read_text(encoding="utf-8")
    except OSError:
        return
    if not text.startswith("---"):
        return
    end = text.find("\n---", 3)
    if end < 0:
        return
    fm = text[3:end]
    lines = fm.splitlines()
    out_lines: list[str] = []
    seen_source = False
    seen_from = False
    for ln in lines:
        if ln.startswith("source_path:"):
            out_lines.append(f"source_path: {original}")
            seen_source = True
        elif ln.startswith("extracted_from:"):
            out_lines.append(f"extracted_from: {original}")
            seen_from = True
        else:
            out_lines.append(ln)
    if not seen_source:
        out_lines.append(f"source_path: {original}")
    if not seen_from:
        out_lines.append(f"extracted_from: {original}")
    new = "---" + "\n".join(out_lines) + text[end:]
    atomicio.write_text_atomic(cand, new)
    _sync_index_after_provenance_rewrite(workspace, cand, original)


def extract_index_paths(workspace: Path, extracted: Path) -> list[str]:
    """Exact vault-relative and absolute paths for one extract. No globs."""
    out: list[str] = []

    def add(raw: str) -> None:
        if raw and raw not in out:
            out.append(raw)

    add(str(extracted))
    add(extracted.as_posix())
    try:
        resolved = extracted.resolve()
    except OSError:
        resolved = extracted
    add(str(resolved))
    add(resolved.as_posix())
    try:
        rel = resolved.relative_to((workspace / "vault").resolve())
        add(str(rel))
        add(rel.as_posix())
    except (ValueError, OSError):
        pass
    return out


def _sync_index_after_provenance_rewrite(
    workspace: Path, extracted: Path, original: str,
) -> None:
    """Reindex the rewritten extract, then set ``source_path`` exactly.

    Prefers curiosity-engine ``vault_index.py`` so body/hash use CE
    normalisation. Index failures raise ``IndexSyncError`` so the
    caller can keep the extract and surface a retryable error.
    """
    from . import ce_tools, cebridge

    paths = extract_index_paths(workspace, extracted)
    script = cebridge.ce_root() / "scripts" / "vault_index.py"
    if script.is_file():
        try:
            vault_rel = extracted.resolve().relative_to(
                (workspace / "vault").resolve()
            )
            ce_path = (Path("vault") / vault_rel).as_posix()
        except (ValueError, OSError):
            ce_path = extracted.as_posix()
        title = extracted.name
        if title.endswith(".extracted.md"):
            title = title[: -len(".extracted.md")]
        out = ce_tools._ce_vault_index(
            workspace, {"path": ce_path, "title": title},
        )
        if not isinstance(out, dict) or out.get("error") or out.get("status") == "error":
            raise IndexSyncError(
                str((out or {}).get("error") or (out or {}).get("status") or "vault_index failed")
            )
        indexed = str(out.get("path") or "")
        if indexed:
            paths = [indexed, *[p for p in paths if p != indexed]]
        _set_index_source_path_exact(workspace, paths, original)
        _assert_index_hash_matches(workspace, paths, extracted, original)
        return
    db = workspace / "vault" / "vault.db"
    if not db.is_file():
        return
    _refresh_index_row_exact(workspace, extracted, original, paths)
    _assert_index_hash_matches(workspace, paths, extracted, original)


def _set_index_source_path_exact(
    workspace: Path, paths: list[str], original: str,
) -> None:
    db = workspace / "vault" / "vault.db"
    if not db.is_file() or not paths:
        return
    with sqlite3.connect(str(db)) as conn:
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            )
        }
        if "sources" not in tables:
            return
        cols = [r[1] for r in conn.execute("PRAGMA table_info(sources)").fetchall()]
        if cols and "source_path" not in cols:
            return
        for path in paths:
            conn.execute(
                "UPDATE sources SET source_path = ? WHERE path = ?",
                (original, path),
            )
        conn.commit()


def _refresh_index_row_exact(
    workspace: Path, extracted: Path, original: str, paths: list[str],
) -> None:
    """CE-absent fallback: rewrite hash/body/source_path for exact paths only."""
    db = workspace / "vault" / "vault.db"
    text = extracted.read_text(encoding="utf-8")
    digest = hashlib.sha256(extracted.read_bytes()).hexdigest()
    with sqlite3.connect(str(db)) as conn:
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            )
        }
        for path in paths:
            if "sources" in tables:
                conn.execute(
                    "UPDATE sources SET source_path = ?, body = ? WHERE path = ?",
                    (original, text, path),
                )
            if "source_meta" in tables:
                conn.execute(
                    "UPDATE source_meta SET sha256 = ? WHERE path = ?",
                    (digest, path),
                )
        conn.commit()


def _assert_index_hash_matches(
    workspace: Path, paths: list[str], extracted: Path, original: str,
) -> None:
    db = workspace / "vault" / "vault.db"
    if not db.is_file():
        raise IndexSyncError("vault.db missing after index sync")
    digest = hashlib.sha256(extracted.read_bytes()).hexdigest()
    with sqlite3.connect(str(db)) as conn:
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            )
        }
        if "source_meta" not in tables:
            raise IndexSyncError("source_meta missing after index sync")
        row = None
        matched_path = None
        for path in paths:
            row = conn.execute(
                "SELECT sha256 FROM source_meta WHERE path = ?", (path,),
            ).fetchone()
            if row:
                matched_path = path
                break
        if not row:
            raise IndexSyncError("indexed extract path not found after vault_index")
        if row[0] != digest:
            raise IndexSyncError("indexed hash still stale after vault_index")
        body_row = conn.execute(
            "SELECT body, source_path FROM sources WHERE path = ?",
            (matched_path,),
        ).fetchone()
        if not body_row:
            raise IndexSyncError("indexed extract row missing after vault_index")
        body, source_path = body_row[0] or "", body_row[1] or ""
        if original not in body or source_path != original:
            raise IndexSyncError("indexed body missing rewritten provenance")


def handoff(
    workspace: Path,
    cand: Candidate,
    *,
    hydrate: Callable[..., icloud_download.HydrateResult] | None = None,
    ingest: Callable[..., dict[str, Any]] | None = None,
    now: float | None = None,
) -> HandoffResult:
    """Hydrate (if needed), stage atomically, CE-ingest. Mark seen only on success."""
    del now
    hydrate = hydrate or icloud_download.hydrate_file
    ingest = ingest or _default_ingest
    logical = cand.logical
    deny = handoff_allowed(workspace, cand.folder)
    if deny:
        return HandoffResult(
            status="skipped", retryable=False, error=deny, logical=logical,
        )

    src = Path(cand.path)
    if cand.hydrate:
        try:
            result = hydrate(src, timeout=HYDRATE_WAIT)
        except Exception as e:  # noqa: BLE001
            record_pending(
                workspace, logical, state="hydrating",
                error=f"hydrate failed: {e}", retryable=True,
            )
            return HandoffResult(
                status="pending", error=f"hydrate failed: {e}",
                retryable=True, logical=logical,
            )
        if not result.ready:
            record_pending(
                workspace, logical, state="hydrating",
                error=result.error or "waiting for local bytes",
                retryable=result.retryable,
            )
            return HandoffResult(
                status="pending",
                error=result.error or "waiting for local bytes",
                retryable=result.retryable, logical=logical,
            )
        src = Path(result.path)

    deny = handoff_allowed(workspace, cand.folder)
    if deny:
        return HandoffResult(
            status="skipped", retryable=False, error=deny, logical=logical,
        )

    real = authorized_real_path(cand.folder, src)
    if real is None:
        record_pending(
            workspace, logical, state="error",
            error="source escaped approved folder or home",
            retryable=True,
        )
        return HandoffResult(
            status="error", error="source escaped approved folder or home",
            retryable=True, logical=logical,
        )
    src = real

    try:
        if statedir.is_dataless(src) or icloud_download.is_icloud_stub(src):
            record_pending(
                workspace, logical, state="hydrating",
                error="still a cloud placeholder", retryable=True,
            )
            return HandoffResult(
                status="pending", error="still a cloud placeholder",
                retryable=True, logical=logical,
            )
        st = os.lstat(src)
    except OSError as e:
        record_pending(
            workspace, logical, state="error",
            error=f"source disappeared or access denied: {e}",
            retryable=True,
        )
        return HandoffResult(
            status="pending",
            error=f"source disappeared or access denied: {e}",
            retryable=True, logical=logical,
        )
    if _stat.S_ISLNK(st.st_mode):
        record_pending(
            workspace, logical, state="error",
            error="source escaped approved folder or home",
            retryable=True,
        )
        return HandoffResult(
            status="error", error="source escaped approved folder or home",
            retryable=True, logical=logical,
        )
    if st.st_size == 0:
        record_pending(
            workspace, logical, state="hydrating",
            error="placeholder size 0", retryable=True,
        )
        return HandoffResult(
            status="pending", error="placeholder size 0",
            retryable=True, logical=logical,
        )
    if st.st_size > MAX_FILE_BYTES:
        record_pending(
            workspace, logical, state="error",
            error="file too large", retryable=False,
        )
        mark_seen(workspace, logical, mtime=st.st_mtime, size=st.st_size)
        return HandoffResult(
            status="skipped", error="file too large",
            retryable=False, logical=logical,
        )

    # Re-check immediately before opening the source for copy.
    real = authorized_real_path(cand.folder, src)
    if real is None:
        record_pending(
            workspace, logical, state="error",
            error="source escaped approved folder or home",
            retryable=True,
        )
        return HandoffResult(
            status="error", error="source escaped approved folder or home",
            retryable=True, logical=logical,
        )

    rel: str | None = None
    try:
        rel, size = stage_file(workspace, real, timeout=STAGE_TIMEOUT)
    except Exception as e:  # noqa: BLE001
        record_pending(
            workspace, logical, state="error",
            error=f"staging failed: {e}", retryable=True,
        )
        return HandoffResult(
            status="pending", error=f"staging failed: {e}",
            retryable=True, logical=logical,
        )

    deny = handoff_allowed(workspace, cand.folder)
    if deny:
        _cleanup_stage(workspace, rel)
        return HandoffResult(
            status="skipped", retryable=False, error=deny, logical=logical,
        )

    try:
        out = ingest(workspace, rel, INGEST_TIMEOUT)
    except Exception as e:  # noqa: BLE001
        _cleanup_stage(workspace, rel)
        record_pending(
            workspace, logical, state="error",
            error=f"ingest failed: {e}", retryable=True,
        )
        return HandoffResult(
            status="error", error=f"ingest failed: {e}",
            retryable=True, logical=logical, vault_rel=rel,
        )

    from . import ce_tools
    if not ce_tools.ingest_is_success(out):
        _cleanup_stage(workspace, rel)
        err = str(
            (out or {}).get("error")
            or (out or {}).get("reject_reason")
            or "extraction failed"
        )
        record_pending(
            workspace, logical, state="error", error=err, retryable=True,
        )
        return HandoffResult(
            status="error", error=err, retryable=True,
            logical=logical, vault_rel=rel, extra={"ingest": out},
        )

    extracted = None
    rows = out.get("results") if isinstance(out, dict) else None
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and row.get("extracted"):
                extracted = str(row["extracted"])
                break
    if isinstance(out, dict) and not extracted:
        extracted = str(out.get("extracted") or "") or None
    if extracted:
        try:
            _stamp_watch_source(workspace, extracted, logical)
        except (IndexSyncError, OSError) as e:
            kept_rel = _cleanup_stage_if_separate_kept(workspace, rel, out)
            if kept_rel:
                rel = kept_rel
            err = f"index provenance failed: {e}"
            record_pending(
                workspace, logical, state="error", error=err, retryable=True,
            )
            return HandoffResult(
                status="error", error=err, retryable=True,
                logical=logical, vault_rel=rel, extracted=extracted,
                extra={"ingest": out},
            )
        if isinstance(out, dict) and isinstance(out.get("results"), list):
            for row in out["results"]:
                if isinstance(row, dict) and row.get("extracted"):
                    row["source_path"] = logical
                    row["extracted_from"] = logical

    mark_seen(workspace, logical, mtime=st.st_mtime, size=size)
    kept_rel = _cleanup_stage_if_separate_kept(workspace, rel, out)
    if kept_rel:
        rel = kept_rel
    return HandoffResult(
        status="success", retryable=False, logical=logical,
        vault_rel=rel, extracted=extracted,
        extra={"ingest": out, "bytes": size, "original": logical},
    )


def _durable_kept_path(
    workspace: Path, out: dict[str, Any] | None,
) -> Path | None:
    """CE-kept original, if it is a real file distinct from source_in_place."""
    if not isinstance(out, dict):
        return None
    items: list[Any] = [out]
    rows = out.get("results")
    if isinstance(rows, list):
        items.extend(rows)
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("source_in_place") is True:
            return None
        kept = item.get("kept")
        if not kept:
            continue
        p = Path(str(kept))
        if not p.is_absolute():
            p = workspace / p
        try:
            p = p.resolve()
        except OSError:
            continue
        if p.is_file():
            return p
    return None


def _cleanup_stage_if_separate_kept(
    workspace: Path, rel: str | None, out: dict[str, Any] | None,
) -> str | None:
    """Drop this attempt's staging copy only when CE kept another original.

    Returns the workspace-relative kept path so callers can point
    ``vault_rel`` at a file that still exists.
    """
    kept = _durable_kept_path(workspace, out)
    if not kept or not rel:
        return None
    try:
        staged = (workspace / rel).resolve()
        kept_rel = str(kept.relative_to(workspace.resolve()))
    except (OSError, ValueError):
        return None
    if kept == staged:
        return None
    stage_root = (workspace.resolve() / "vault" / ".watch-ingest").resolve()
    if _within(stage_root, kept):
        return None
    _cleanup_stage(workspace, rel)
    return kept_rel


def api_status(workspace: Path) -> dict[str, Any]:
    return {
        "folders": list_folders(workspace),
        "pending": list_pending(workspace),
        "cap_per_beat": MAX_PER_BEAT,
        "icloud_download": icloud_download.supported(),
    }
