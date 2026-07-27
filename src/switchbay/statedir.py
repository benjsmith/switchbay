"""Machine-local state directory — keep transient/regenerable state off
cloud-sync services (iCloud Drive, OneDrive Files-On-Demand, Dropbox
Smart Sync, Google Drive File Stream).

Why this module exists
----------------------
A workspace is the user's documents, and users legitimately put those
under a cloud-synced folder so they roam between machines. But those
services keep files as *dehydrated placeholders*: the `stat` metadata is
local and cheap, while reading the *content* triggers a synchronous
hydration from the cloud that can block for tens of seconds. Two failure
modes followed from putting our runtime state inside that synced tree:

  1. a sync read on the asyncio event loop froze the whole daemon, and
  2. even offloaded, the user waited tens of seconds for first access.

The fix (charter amendment, 2026-06-05): split workspace state in two.

  * **Durable, user-facing, roams across machines** — wiki docs,
    ``figures/``, sketch sources, plots, analyses, and the small config
    JSON (``mode.json``, ``tabs-state``, ``agent_rules``, permissions,
    ``sheet``, duckdb starters). These STAY in ``<workspace>/.workbench``
    so they sync; they tolerate stale-while-revalidate + the dataless
    probe below.
  * **Machine-local, regenerable / hot** — fan-out ``runs/``, staged
    ``uploads/``, the curation cache, and (opt-in) the rail-history
    ``conversations.db``. These move HERE, to an OS-conventional
    app-state root that is never synced.

Cross-platform by design
-------------------------
This is the layer the future native mac/win/linux ports share. One
common abstraction (``state_root``) with thin per-OS branches that follow
each platform's convention — the same place well-behaved apps (VS Code's
workspaceStorage, JetBrains, etc.) keep per-workspace databases:

  * macOS    ``~/Library/Application Support/switchbay``
  * Windows  ``%LOCALAPPDATA%\\switchbay``
  * Linux    ``$XDG_STATE_HOME/switchbay`` (default ``~/.local/state``)

``SWITCHBAY_STATE_DIR`` overrides the root (tests, sandboxed deploys).
"""

from __future__ import annotations

import hashlib
import os
import stat as _stat
import sys
from pathlib import Path

# ── State root (per-OS, thin branches) ──────────────────────────────


def state_root() -> Path:
    """OS-conventional, non-synced app-state root for switchbay.

    Honours ``SWITCHBAY_STATE_DIR`` first (absolute path), then falls
    back to the platform convention."""
    override = os.environ.get("SWITCHBAY_STATE_DIR")
    if override:
        return Path(override).expanduser()
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "switchbay"
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(home / "AppData" / "Local")
        return Path(base) / "switchbay"
    # Linux / other POSIX — XDG state dir (regenerable machine-local
    # state, distinct from XDG_CONFIG_HOME which holds user prefs).
    base = os.environ.get("XDG_STATE_HOME") or str(home / ".local" / "state")
    return Path(base) / "switchbay"


def workspace_state_dir(workspace: Path) -> Path:
    """Per-workspace machine-local state dir.

    Keyed by a stable hash of the absolute workspace path so two
    workspaces that happen to share a basename never collide, with the
    basename kept as a human-readable prefix for anyone spelunking the
    state root. Does NOT create the directory — callers `mkdir` the
    specific leaf they need (keeps this pure for path math)."""
    resolved = _resolve(workspace)
    digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:12]
    slug = _slug(resolved.name) or "workspace"
    return state_root() / "workspaces" / f"{slug}-{digest}"


def _resolve(workspace: Path) -> Path:
    try:
        return Path(workspace).expanduser().resolve()
    except OSError:
        return Path(workspace).expanduser()


def _slug(name: str) -> str:
    keep = [c if (c.isalnum() or c in "-_") else "-" for c in name]
    return "".join(keep).strip("-").lower()[:40]


# ── Path helpers — the relocated state ───────────────────────────────


def runs_dir(workspace: Path, parent_run_id: str | None = None) -> Path:
    """Fan-out worker output. Transient; never roams."""
    base = workspace_state_dir(workspace) / "runs"
    return base / parent_run_id if parent_run_id else base


def uploads_dir(workspace: Path) -> Path:
    """Staged-upload dedup cache. Transient; never roams."""
    return workspace_state_dir(workspace) / "uploads"


def terminal_pidfile() -> Path:
    """Daemon-global record of live terminal-shell PIDs, used to reap
    orphans left by a SIGKILL'd daemon on the next startup. Machine-
    local (a runtime artifact); never synced."""
    return state_root() / "terminal-pids.json"


def curation_cache(workspace: Path, name: str) -> Path:
    """Derived curation-history cache. Regenerable; never roams."""
    return workspace_state_dir(workspace) / name


def _synced_conversations_db(workspace: Path) -> Path:
    """The roam-by-default home: inside the (possibly synced) workspace."""
    return workspace / ".workbench" / "state" / "conversations.db"


def _local_conversations_db(workspace: Path) -> Path:
    """The opt-in machine-local home, off any sync service."""
    return workspace_state_dir(workspace) / "state" / "conversations.db"


def conversations_db(workspace: Path, *, local: bool) -> Path:
    """Resolve the rail-history DB path.

    ``local`` reflects the user's ``rail_history_local`` setting:
      * ``False`` (default) — DB lives in the workspace and roams across
        machines via whatever sync service backs the workspace folder.
      * ``True`` — DB lives in the machine-local state root: fast and
        sync-safe, but does not roam.

    Pure: it only computes the path. Use ``migrate_conversations_db`` to
    actually move an existing DB when the setting flips."""
    return _local_conversations_db(workspace) if local else _synced_conversations_db(workspace)


# sqlite spreads across up to three files in WAL mode.
_SQLITE_SIDECARS = ("", "-wal", "-shm", "-journal")


def migrate_conversations_db(workspace: Path, *, local: bool) -> bool:
    """Move an existing conversations.db (+ sqlite sidecars) to the
    location implied by ``local`` if it currently lives at the other
    one. Idempotent and best-effort — returns True if anything moved.

    Called at workspace activation and right after the setting toggles,
    so resolution itself stays a pure function."""
    dest_base = conversations_db(workspace, local=local)
    src_base = conversations_db(workspace, local=not local)
    if not src_base.exists():
        return False
    if dest_base.exists():
        # Both present (e.g. a stale copy at the other location) — keep
        # the destination authoritative, don't clobber it.
        return False
    dest_base.parent.mkdir(parents=True, exist_ok=True)
    moved = False
    for suffix in _SQLITE_SIDECARS:
        src = src_base.with_name(src_base.name + suffix)
        if src.exists():
            src.replace(dest_base.with_name(dest_base.name + suffix))
            moved = True
    return moved


# ── Cloud-sync placeholder detection (for honest "syncing" UI) ───────


def is_dataless(path: Path) -> bool:
    """True if ``path`` is a cloud-sync *placeholder* whose content is
    not local — reading it would trigger a slow hydration from the
    cloud. Cheap: inspects flags/attributes only, never the content.

    Cross-platform, thin per-OS branch (mirrors ``state_root``):
      * macOS   — ``st_flags`` carries ``SF_DATALESS`` (0x40000000) on
        iCloud-evicted files.
      * Windows — file attributes carry one of ``OFFLINE`` /
        ``RECALL_ON_OPEN`` / ``RECALL_ON_DATA_ACCESS`` for OneDrive,
        Dropbox, and Google Drive placeholders.
      * else    — no known placeholder mechanism; always False.

    Fail-soft: any error answers False (treat as a normal local file)."""
    try:
        if sys.platform == "darwin":
            SF_DATALESS = 0x40000000
            flags = os.stat(path).st_flags  # type: ignore[attr-defined]
            return bool(flags & SF_DATALESS)
        if sys.platform == "win32":
            import ctypes

            FILE_ATTRIBUTE_OFFLINE = 0x00001000
            FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x00040000
            FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000
            mask = (
                FILE_ATTRIBUTE_OFFLINE
                | FILE_ATTRIBUTE_RECALL_ON_OPEN
                | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
            )
            attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
            if attrs == 0xFFFFFFFF:  # INVALID_FILE_ATTRIBUTES
                return False
            return bool(attrs & mask)
    except (OSError, AttributeError, ValueError):
        return False
    return False


# Known cloud-sync roots, used only to phrase the "syncing" message and
# (optionally) warn when a workspace is added under one. Detection of an
# actual eviction is `is_dataless`; this is just for friendlier copy.
def sync_service_hint(path: Path) -> str | None:
    """Best-effort name of the sync service backing ``path`` (for UI
    copy like "Downloading from iCloud…"), or None if unknown."""
    s = str(path)
    if "Mobile Documents" in s or "/Library/CloudStorage/iCloud" in s:
        return "iCloud"
    low = s.lower()
    if "onedrive" in low:
        return "OneDrive"
    if "dropbox" in low:
        return "Dropbox"
    if "google drive" in low or "googledrive" in low or "/my drive" in low:
        return "Google Drive"
    # macOS "Desktop & Documents Folders" iCloud sync lives at the
    # plain ~/Documents and ~/Desktop — NOT under "Mobile Documents" —
    # so the path looks local. It's the most common eviction source we
    # hit; treat those roots as iCloud on darwin. (Callers only reach
    # here for a path we already know is dataless, so this can't
    # mislabel a genuinely-local file.)
    if sys.platform == "darwin":
        try:
            resolved = Path(path).expanduser().resolve()
            home = Path.home().resolve()
            for sub in ("Documents", "Desktop"):
                if resolved == home / sub or (home / sub) in resolved.parents:
                    return "iCloud"
        except OSError:
            return None
    return None
