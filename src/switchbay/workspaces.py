"""Cross-session registry of known workspaces.

Persisted to `$XDG_CONFIG_HOME/switchbay/workspaces.json` (default
`~/.config/switchbay/workspaces.json`). The daemon's
`app["workspace"]` is mutable at runtime; switching workspaces in the
top-bar dropdown rewrites this file and broadcasts a fresh `hello` to
all connected clients.

Shape:
    {
      "paths": ["/abs/path/a", "/abs/path/b"],
      "active": "/abs/path/a"   # may be null if registry is empty
    }
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any
from . import atomicio

log = logging.getLogger(__name__)


def config_dir() -> Path:
    override = os.environ.get("XDG_CONFIG_HOME")
    if override:
        return Path(override) / "switchbay"
    if sys.platform == "win32":
        dest = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        dest = dest / "switchbay" / "config"
        _migrate_xdg_config_once(dest)
        return dest
    base = str(Path.home() / ".config")
    return Path(base) / "switchbay"


def _migrate_xdg_config_once(dest: Path) -> None:
    marker = dest / ".migrated-from-xdg"
    if marker.is_file() or any(dest.glob("*")):
        return
    src = Path.home() / ".config" / "switchbay"
    if not src.is_dir():
        return
    try:
        dest.mkdir(parents=True, exist_ok=True)
        for child in src.iterdir():
            target = dest / child.name
            if child.is_file() and not target.exists():
                shutil.copy2(child, target)
        marker.write_text("1\n", encoding="utf-8")
    except OSError:
        pass


def _path() -> Path:
    return config_dir() / "workspaces.json"


# ── Home-directory sandbox (cross-platform) ──────────────────────────
# Hardcoded safety net: workspaces are restricted to paths inside the
# current user's home (`~`). On macOS that's /Users/<u>, on Linux
# /home/<u>, on Windows C:\Users\<u>. The risk: cebridge, fileops, and
# cebridge.setup() all run subprocesses with cwd=workspace and write
# to it. A bad workspace value (`/etc`, `/`, `/Volumes/SystemDisk`,
# etc.) would let the daemon's file-ops endpoints touch system files.
# We refuse anywhere outside the user's home.

def is_within_home(path: Path) -> bool:
    try:
        target = Path(path).expanduser().resolve()
        home = Path.home().resolve()
        target.relative_to(home)
        return True
    except (ValueError, OSError):
        return False


def home_label() -> str:
    """Human-readable home root, for error messages."""
    return str(Path.home())


def load() -> dict[str, Any]:
    p = _path()
    if not p.is_file():
        return {"paths": [], "active": None}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"paths": [], "active": None}
    if not isinstance(data, dict):
        return {"paths": [], "active": None}
    raw_paths = data.get("paths") or []
    active = data.get("active")
    if not isinstance(raw_paths, list):
        raw_paths = []
    # Defense in depth: silently drop registry entries that aren't
    # inside $HOME — protects against an older binary having added
    # something dangerous (e.g. /etc) before the guard existed, or
    # against a hand-edited workspaces.json.
    safe_paths: list[str] = []
    for entry in raw_paths:
        s = str(entry)
        if is_within_home(Path(s)):
            safe_paths.append(s)
    safe_active = str(active) if active else None
    # Permit `active` to be a path that's NOT in `paths` — the daemon
    # may be serving an unregistered workspace (the CLI-supplied
    # cwd) the user hasn't explicitly added to the dropdown. Only
    # require that it lives inside $HOME for safety.
    if safe_active and not is_within_home(Path(safe_active)):
        safe_active = safe_paths[0] if safe_paths else None
    cleaned = {"paths": safe_paths, "active": safe_active}
    # Persist the cleaned form so stale bad entries are gone for good.
    if cleaned != {"paths": [str(x) for x in raw_paths], "active": str(active) if active else None}:
        try:
            save(cleaned)
        except OSError:
            pass
    return cleaned


def save(data: dict[str, Any]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(p, data)


def resolve_path(
    path_str: str | None,
    *,
    default: Path | None = None,
    must_exist: bool = True,
) -> Path:
    """Resolve a workspace path from HTTP/tool input.

    Expands ``~``, requires the path under ``$HOME``, and optionally
    that it is an existing directory. Raises ``OutsideHomeError`` or
    ``ValueError`` on bad input.
    """
    raw = (path_str or "").strip()
    if not raw:
        if default is None:
            raise ValueError("workspace path required")
        return Path(default).expanduser().resolve()
    target = Path(raw).expanduser().resolve()
    if not is_within_home(target):
        raise OutsideHomeError(
            f"workspaces must live inside {home_label()}; refusing {target}"
        )
    if must_exist and not target.is_dir():
        raise ValueError(f"workspace is not a directory: {target}")
    return target


class OutsideHomeError(ValueError):
    pass


def register(path: Path, set_active: bool = True) -> dict[str, Any]:
    """Add path to registry (no-op if already present); optionally make active.

    Raises `OutsideHomeError` if `path` resolves outside the user's home.
    """
    if not is_within_home(path):
        raise OutsideHomeError(
            f"workspaces must live inside {home_label()}; refusing {path}"
        )
    data = load()
    s = str(path.resolve())
    if s not in data["paths"]:
        data["paths"].append(s)
    if set_active:
        data["active"] = s
    save(data)
    return data


# Regenerable dirs NEVER copied on a workspace move — a seeded uv
# cache + venv can be 100k+ files (and, on iCloud, the very files that
# get evicted, so they copy as 0 bytes). They rebuild on first `uv
# run` in the new location. Matched by basename at any depth (so
# `.curator/uv-cache` and a nested `.venv` both hit).
_MIGRATE_EXCLUDE_DIRS = frozenset({
    ".venv", "__pycache__", "node_modules", "uv-cache", ".uv-cache",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
})

# Cap on how many not-downloaded files we bother counting before we
# refuse — one is enough to refuse; the count just phrases the message.
_DATALESS_SCAN_CAP = 200


def _walk_pruned(root: Path):
    """os.walk that skips `_MIGRATE_EXCLUDE_DIRS` in place, so the heavy
    regenerable caches are never visited by the dataless scan or the
    verify pass (mirrors what copytree's ignore does)."""
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _MIGRATE_EXCLUDE_DIRS]
        yield dirpath, dirs, files


def _scan_dataless(root: Path, cap: int = _DATALESS_SCAN_CAP) -> int:
    """Count iCloud/cloud placeholder (not-downloaded) files under the
    KEPT tree (excludes pruned), stopping at `cap`. Cheap: `is_dataless`
    inspects flags only, never hydrates."""
    from . import statedir

    n = 0
    for dirpath, _dirs, files in _walk_pruned(root):
        for f in files:
            if statedir.is_dataless(Path(dirpath) / f):
                n += 1
                if n >= cap:
                    return n
    return n


def _verify_no_hollow(src: Path, dest: Path) -> str | None:
    """After a copy, confirm no KEPT file lost its bytes (a dataless
    source file can copy as 0 bytes without erroring). Returns a human
    error describing the first mismatch, or None when every kept source
    file has a same-size counterpart in dest. Excluded dirs + symlinks
    skipped."""
    for dirpath, _dirs, files in _walk_pruned(src):
        rel = os.path.relpath(dirpath, src)
        for f in files:
            sp = Path(dirpath) / f
            if sp.is_symlink():
                continue
            try:
                ssize = sp.stat().st_size
            except OSError:
                continue
            dp = dest / rel / f if rel != "." else dest / f
            try:
                dsize = dp.stat().st_size
            except OSError:
                return f"missing in copy: {os.path.join(rel, f)}"
            # A non-empty source that copied to 0 bytes = hollow (the
            # iCloud-dataless failure mode).
            if ssize > 0 and dsize == 0:
                return f"hollow copy (0 bytes): {os.path.join(rel, f)}"
    return None


def migrate_into_home(path: Path, home: Path) -> str | dict[str, Any]:
    """PHASE 1 of a two-step move of a registered, NON-ACTIVE workspace
    into the workspaces home (stage-5 ruling: fixed home, default
    `~/Workspaces`, Settings-configurable): COPY the durable content,
    verify it, move the machine-local state dir, and repoint the
    registry — but **leave the source folder on disk** for the user to
    remove via `cleanup_migrated_source` once they're satisfied.

    Returns on success:
      {"old", "new", "kept", "excluded", "cleanup_pending": True}
    or a human-readable error string. The ACTIVE workspace is always
    refused — never move the daemon's live cwd (the session-1 wedge).

    **iCloud safety (this whole function was rewritten after a data-loss
    incident):** a source on an iCloud "Documents" path crosses a device
    boundary, so the old `shutil.move` fell back to copytree+rmtree —
    copytree copied *dataless* (not-downloaded) files as 0 bytes, then
    rmtree deleted the good originals. Three defenses now: (1) SKIP the
    regenerable caches (`.venv`, `.curator/uv-cache`, … — usually the
    bulk of the tree and the evicted files); (2) REFUSE up front if any
    KEPT file isn't downloaded; (3) copy → verify-no-hollow → and never
    auto-delete: the source is removed only by an explicit second step."""
    from . import statedir  # deferred: statedir is import-cycle-free

    src = Path(path).expanduser()
    try:
        src = src.resolve()
    except OSError:
        pass
    data = load()
    s = str(src)
    if s not in data["paths"]:
        return "not a registered workspace"
    if data.get("active") == s:
        return "that workspace is active — switch to another one first"
    if not src.is_dir():
        return "workspace folder is missing on disk"
    home_p = Path(home).expanduser()
    if not is_within_home(home_p):
        return f"workspaces home must live inside {home_label()}"
    try:
        home_p = home_p.resolve()
    except OSError:
        pass
    if s == str(home_p) or s.startswith(str(home_p) + os.sep):
        return "already inside the workspaces home"
    dest = home_p / src.name
    if dest.exists():
        return f"target already exists: {dest}"

    # (1) Refuse if any KEPT file isn't downloaded from iCloud — copying
    # it now would silently zero it out. (Excluded caches don't count.)
    dataless = _scan_dataless(src)
    if dataless:
        approx = f"{dataless}+" if dataless >= _DATALESS_SCAN_CAP else str(dataless)
        service = statedir.sync_service_hint(src) or "the cloud"
        return (
            f"{approx} files in this workspace aren't downloaded from "
            f"{service} yet — moving now would lose their contents. "
            f"Download them first (in Finder: right-click the folder → "
            f"Download Now, or run `brctl download {shlex.quote(str(src))}`), "
            f"then retry the move."
        )

    old_state = statedir.workspace_state_dir(src)
    home_p.mkdir(parents=True, exist_ok=True)

    # (2) Copy the KEPT tree → verify no file went hollow. NEVER
    # shutil.move (its cross-device fallback rmtrees the source).
    ignore = shutil.ignore_patterns(*_MIGRATE_EXCLUDE_DIRS)
    try:
        shutil.copytree(src, dest, symlinks=True, ignore=ignore)
    except (OSError, shutil.Error) as e:
        shutil.rmtree(dest, ignore_errors=True)
        return f"copy failed, source untouched: {e}"
    hollow = _verify_no_hollow(src, dest)
    if hollow:
        shutil.rmtree(dest, ignore_errors=True)
        return (
            f"copy verification failed — {hollow}. Source left untouched; "
            f"nothing was deleted. (Likely an iCloud file evicted mid-copy — "
            f"download the folder fully, then retry.)"
        )

    # (3) Copy is whole. Repoint the registry + move the machine-local
    # state dir. The SOURCE folder stays on disk until the user confirms
    # (cleanup_migrated_source). Nothing of theirs is deleted here.
    data["paths"] = [str(dest) if p == s else p for p in data["paths"]]
    save(data)
    try:
        new_state = statedir.workspace_state_dir(dest)
        if old_state.is_dir() and not new_state.exists():
            new_state.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old_state), str(new_state))
    except OSError:
        # Regenerable caches — worst case the opt-in local history
        # stays under the old key; surface in the log, don't fail.
        log.warning("machine-local state move failed for %s", dest)

    kept = sum(len(f) for _d, _s, f in _walk_pruned(dest))
    return {
        "old": s,
        "new": str(dest),
        "kept": kept,
        "excluded": sorted(_MIGRATE_EXCLUDE_DIRS),
        "cleanup_pending": True,
    }


def cleanup_migrated_source(old: Path, new: Path) -> str | dict[str, Any]:
    """PHASE 2: remove the source folder left behind by
    `migrate_into_home`, once the user confirms. Refuses unless the NEW
    location is a registered, on-disk workspace (so we never delete a
    source whose copy didn't take), and unless `old` is no longer
    registered (the repoint happened) and is not the active workspace.

    Returns {"removed": <old>} or a human-readable error string."""
    old_p = Path(old).expanduser()
    new_p = Path(new).expanduser()
    try:
        old_p = old_p.resolve()
    except OSError:
        pass
    try:
        new_p = new_p.resolve()
    except OSError:
        pass
    data = load()
    so, sn = str(old_p), str(new_p)
    if sn not in data["paths"]:
        return "the new location isn't registered — refusing to delete the old copy"
    if not new_p.is_dir():
        return "the new copy is missing on disk — refusing to delete the old copy"
    if so in data["paths"]:
        return "the old path is still registered — not safe to delete"
    if data.get("active") == so:
        return "that workspace is active — switch away first"
    if not old_p.is_dir():
        return {"removed": so, "note": "already gone"}
    shutil.rmtree(old_p)
    return {"removed": so}


def set_active_only(path: Path) -> dict[str, Any]:
    """Validate the CLI-supplied cwd lives inside $HOME, but DON'T
    touch the registry's `active` field — that's reserved for the
    user's explicit picks via the workspace switcher. The daemon
    keeps its own `app["workspace"]` for the path it actually
    serves; the registry stays a record of user intent only.

    Returns the (unchanged) registry dict."""
    if not is_within_home(path):
        raise OutsideHomeError(
            f"workspaces must live inside {home_label()}; refusing {path}"
        )
    return load()


async def pick_folder() -> str | None:
    """Open the OS-native folder picker. Returns the chosen path, or None
    if the user cancelled / no picker is available.

    macOS:   osascript ‘choose folder’
    Linux:   zenity → kdialog → xdg-mime fallback
    Windows: PowerShell FolderBrowserDialog
    """
    import asyncio
    import logging
    import shutil
    import sys

    log = logging.getLogger("switchbay.workspaces")

    if sys.platform == "darwin":
        # `choose folder` opens a sheet that defaults to BEHIND the
        # frontmost app — when switchbay is driven from a browser the
        # dialog appears behind the browser window and looks like the
        # Browse button does nothing. The fix is to run `choose folder`
        # *inside* the `tell application "System Events"` block after
        # activating it, so the dialog is OWNED by a now-frontmost app
        # and comes to the front. The previous version activated
        # System Events but ran the picker in osascript's default
        # (non-frontmost) context, so it still opened behind. Verified
        # on macOS 26 / Darwin 25.
        script = (
            'tell application "System Events"\n'
            "  activate\n"
            "  set chosenFolder to choose folder with prompt "
            '"Pick a switchbay workspace"\n'
            "  return POSIX path of chosenFolder\n"
            "end tell"
        )
        argv = ["osascript", "-e", script]
    elif sys.platform == "win32":
        argv = [
            "powershell", "-NoProfile", "-Command",
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$f = New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$f.Description = 'Pick a switchbay workspace'; "
            "if ($f.ShowDialog() -eq 'OK') { Write-Output $f.SelectedPath }",
        ]
    elif shutil.which("zenity"):
        argv = ["zenity", "--file-selection", "--directory",
                "--title=Pick a switchbay workspace"]
    elif shutil.which("kdialog"):
        argv = ["kdialog", "--getexistingdirectory", str(Path.home())]
    else:
        return None

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
    except FileNotFoundError:
        log.warning("folder picker binary not found: %s", argv[0])
        return None
    if proc.returncode != 0:
        # Stay quiet on a real cancel (-128 on macOS, rc=1 on
        # zenity/kdialog) but surface genuine failures — previously
        # stderr was discarded, so a permission/automation error read
        # to the user as "the Browse button does nothing".
        err = stderr.decode(errors="replace").strip()
        cancelled = (
            "-128" in err
            or "User canceled" in err
            or (not err and proc.returncode == 1)
        )
        if not cancelled:
            log.warning(
                "folder picker failed (rc=%s): %s",
                proc.returncode, err or "<no stderr>",
            )
        return None
    chosen = stdout.decode(errors="replace").strip()
    return chosen or None


def unregister(path: Path) -> dict[str, Any]:
    """Remove from registry. Files on disk are untouched."""
    data = load()
    s = str(path.resolve())
    data["paths"] = [p for p in data["paths"] if p != s]
    if data["active"] == s:
        data["active"] = data["paths"][0] if data["paths"] else None
    save(data)
    return data


# ── Archive ─────────────────────────────────────────────────────────


def _archive_path() -> Path:
    return config_dir() / "archived-workspaces.json"


def load_archived() -> list[dict[str, Any]]:
    """List of archived workspace records: each is `{path, archived_at}`.
    Used by the dropdown's "Archived" section so the user can restore
    a workspace they previously took off the active list."""
    p = _archive_path()
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        s = str(entry.get("path") or "")
        if not s:
            continue
        out.append({
            "path": s,
            "archived_at": entry.get("archived_at"),
        })
    return out


def _save_archived(records: list[dict[str, Any]]) -> None:
    p = _archive_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(p, records)


def archive(path: Path) -> dict[str, Any]:
    """Move a workspace from the active registry into the archive.
    The on-disk `.workbench/` settings are preserved as-is — restore
    just re-adds the path to the active list. Returns the updated
    {paths, active, archived} envelope."""
    import time as _time
    s = str(path.resolve())
    data = unregister(path)  # drops from paths + reassigns active
    archived = load_archived()
    if not any(a["path"] == s for a in archived):
        archived.insert(0, {"path": s, "archived_at": _time.time()})
        _save_archived(archived)
    return {**data, "archived": archived}


def restore(path: Path) -> dict[str, Any]:
    """Move a workspace back from archive into the active registry.
    Doesn't switch active to it — that's an explicit user action via
    the dropdown afterwards."""
    s = str(path.resolve())
    archived = [a for a in load_archived() if a["path"] != s]
    _save_archived(archived)
    data = load()
    if s not in data["paths"]:
        data["paths"].append(s)
        save(data)
    return {**data, "archived": archived}


def delete(path: Path, *, purge_settings: bool = True) -> dict[str, Any]:
    """Remove from registry + archive AND optionally delete
    switchbay-internal settings under `<workspace>/.workbench/`.
    The user's content (wiki/, vault/, figures/, etc.) is NEVER
    touched — only the workbench directory created by switchbay.
    Returns the updated envelope."""
    s = str(path.resolve())
    data = unregister(path)
    archived = [a for a in load_archived() if a["path"] != s]
    _save_archived(archived)
    if purge_settings:
        wb = path / ".workbench"
        if wb.is_dir():
            try:
                import shutil as _shutil
                _shutil.rmtree(wb)
            except OSError:
                # Non-fatal — registry cleanup already happened.
                pass
    return {**data, "archived": archived}
