"""Watch-folders (D5, Phase 8 stage 4): auto-ingest NEW files that
appear in user-chosen external directories.

Model:
  * Config (`.workbench/watch-folders.json`, roams with the
    workspace): `[{path, enabled, added_at}]` — absolute directories.
  * Seen-index (machine-local, `statedir.workspace_state_dir()/
    watch-seen.json`, regenerable): file path → {mtime, size} at the
    moment we processed it. Machine-local because the same synced
    workspace on another machine watches that machine's folders.
  * On ADD the folder is BASELINED — everything already inside is
    marked seen without ingesting (auto-ingest means "new files from
    now on", not "swallow this folder's history"; a whole-corpus
    import is the bulk-ingest architecture step's job).
  * Each daemon beat picks up to `MAX_PER_BEAT` unseen files per
    workspace (every new file = one background ingest agent = one
    LLM run — the cap keeps a big folder-dump from dispatching an
    agent stampede; the backlog drains on subsequent beats).

Pure logic + fs here; the daemon owns the loop, the vault staging,
and the agent dispatch.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from . import statedir
from . import atomicio

log = logging.getLogger(__name__)

CONFIG_FILE = "watch-folders.json"
SEEN_FILE = "watch-seen.json"

# Per-beat dispatch cap — see module docstring.
MAX_PER_BEAT = 5
# Files larger than the upload-ingest cap are skipped (same limit).
MAX_FILE_BYTES = 50 * 1024 * 1024
# In-flight / junk suffixes that must never auto-ingest.
_SKIP_SUFFIXES = {".tmp", ".part", ".crdownload", ".download", ".swp", ".lock"}


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
    seen = _load_seen(workspace)
    for fp, st in _walk_files(d):
        seen[fp] = {"mtime": st.st_mtime, "size": st.st_size}
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
                seen = _load_seen(workspace)
                d = Path(f["path"])
                if d.is_dir():
                    for fp, st in _walk_files(d):
                        seen[fp] = {"mtime": st.st_mtime, "size": st.st_size}
                    _save_seen(workspace, seen)
            return True
    return False


# ── Seen-index (machine-local) ─────────────────────────────────────


def _seen_path(workspace: Path) -> Path:
    return statedir.workspace_state_dir(workspace) / SEEN_FILE


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
    p.write_text(json.dumps(seen), encoding="utf-8")


# ── Scanning ───────────────────────────────────────────────────────


def _walk_files(root: Path):
    """Yield (abs_path_str, stat) for every visible file under root.
    Hidden dirs/files pruned; stat errors skipped."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name.startswith("."):
                continue
            full = os.path.join(dirpath, name)
            try:
                st = os.stat(full)
            except OSError:
                continue
            yield full, st


def _ingestable(path: str, size: int) -> bool:
    if size == 0 or size > MAX_FILE_BYTES:
        return False
    return Path(path).suffix.lower() not in _SKIP_SUFFIXES


def scan_new(workspace: Path) -> tuple[list[str], int]:
    """One beat: mark-and-return up to MAX_PER_BEAT unseen files
    across the enabled watch folders. Returns (paths_to_ingest,
    backlog_count). Every unseen file is recorded as seen the moment
    it's picked (or skipped as junk) so a crash never double-
    dispatches; the backlog count is what remains for later beats."""
    folders = [f for f in list_folders(workspace) if f["enabled"]]
    if not folders:
        return [], 0
    seen = _load_seen(workspace)
    dirty = False
    fresh: list[tuple[str, os.stat_result]] = []
    for f in folders:
        d = Path(f["path"])
        if not d.is_dir():
            continue  # unplugged volume / deleted dir — silently idle
        for fp, st in _walk_files(d):
            if fp in seen:
                continue
            # Settling guard: a file modified in the last 5s may
            # still be mid-copy — leave it for the next beat.
            if time.time() - st.st_mtime < 5:
                continue
            if not _ingestable(fp, st.st_size):
                seen[fp] = {"mtime": st.st_mtime, "size": st.st_size}
                dirty = True
                continue
            fresh.append((fp, st))
    fresh.sort(key=lambda t: t[1].st_mtime)  # oldest first — FIFO drain
    picked = fresh[:MAX_PER_BEAT]
    for fp, st in picked:
        seen[fp] = {"mtime": st.st_mtime, "size": st.st_size}
        dirty = True
    if dirty:
        _save_seen(workspace, seen)
    return [fp for fp, _ in picked], max(0, len(fresh) - len(picked))
