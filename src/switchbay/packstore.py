"""Extension pack registry — "yard packs".

A pack is a small directory with a `pack.json` manifest declaring
skills, custom tab kinds, and an optional default mode.json template.
Distributed as GitHub repos (or any local path the user wants to drop
in).

Storage layout:

  <workspace>/.workbench/packs/<pack-name>/   — workspace-installed
  ~/.config/switchbay/packs/<pack-name>/     — user-global

Both locations are scanned at list time. Workspace packs win on
name collision (so a project can override a global default).

GitHub installs land via `git clone --depth 1 <url> <target>` —
no special tooling, no auth glue (the user's git config handles
private repos via SSH). Local-path installs are symlink-or-copy:
a path argument copies the tree into the chosen scope so the
canonical pack directory is always self-contained.

What lands in this commit (MVP):

  · Manifest read / validate.
  · list_packs / get_pack — pack registry.
  · install_pack / uninstall_pack — git or local path.

What's stubbed (the runtime extension hooks need other modules
that don't exist yet):

  · Skill resolution — needs the `skillkit` module (step O is
    folded into the Agent Dashboard tab; skill loading itself
    is unbuilt).
  · Tab-kind registration — needs a frontend tab-kind registry
    extension point + dynamic JS module loading via Vite.
    Today's TabStrip dispatches by hard-coded `kind === ...`
    branches; opening that up is a separate refactor.

(`agent_presets` was a declared-but-never-applied field; cut for
v1.0. A manifest may still carry the key — it's ignored, not an
error.)

Manifests with these fields will validate; the daemon just
records them and returns them in the list. Wiring them to do
anything is the next round of work for step S.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import workspaces
from . import atomicio

log = logging.getLogger("switchbay.packstore")

PACK_FILE = "pack.json"

# Slug used for both directory names and de-dup keys. Keep the
# alphabet narrow so a malicious manifest can't wedge a path with
# `../` or absolute roots.
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


# ── Storage locations ──────────────────────────────────────────────


def _workspace_dir(workspace: Path) -> Path:
    return workspace / ".workbench" / "packs"


def _user_global_dir() -> Path:
    return Path.home() / ".config" / "switchbay" / "packs"


def _system_dir() -> Path:
    """Read-only bundled packs that ship with switchbay. Resolves
    to `<switchbay-source>/packs/` so a checkout-then-uv-run setup
    finds the bundled libreoffice / etc. packs without any install
    step. Install flows refuse to write here; uninstall ignores it.
    """
    # `__file__` is .../src/switchbay/packstore.py — repo root is
    # two levels up. The bundled `packs/` dir sits at the repo top.
    return Path(__file__).resolve().parent.parent.parent / "packs"


def _scope_dir(workspace: Path, scope: str) -> Path:
    if scope == "workspace":
        return _workspace_dir(workspace)
    if scope == "user":
        return _user_global_dir()
    if scope == "system":
        return _system_dir()
    raise ValueError(
        f"invalid scope {scope!r}; expected 'workspace', 'user', or 'system'"
    )


# ── Enabled-state persistence ──────────────────────────────────────
# Soft-disable lets the user keep a pack on disk but stop its
# tabs / file routes / skills from registering at runtime. State
# lives next to the scope dirs:
#
#   <workspace>/.workbench/packs-state.json    workspace overrides
#   ~/.config/switchbay/packs-state.json      user-global default
#
# Workspace state takes precedence. The system scope is always
# enabled — there's no "disable the bundled libreoffice pack" UX;
# uninstall a custom pack to drop it instead.

_STATE_FILE = "packs-state.json"


def _workspace_state_path(workspace: Path) -> Path:
    return workspace / ".workbench" / _STATE_FILE


def _user_state_path() -> Path:
    return Path.home() / ".config" / "switchbay" / _STATE_FILE


def _load_state(p: Path) -> dict[str, Any]:
    if not p.is_file():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _save_state(p: Path, state: dict[str, Any]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(p, state)


def _is_enabled(workspace: Path, scope: str, name: str) -> bool:
    """A pack is enabled unless an explicit `false` is set for it
    in the matching state file.

    System packs are enabled-by-default *unless* their manifest
    declares `requires_extra` — those need an explicit pip-install
    + toggle-on by the user, so the safe default is OFF. The state
    file used is the user-global one (~/.config/switchbay/), since
    a system pack isn't workspace-specific."""
    if scope == "system":
        u = _load_state(_user_state_path())
        if name in u:
            return bool(u[name])
        # Bundled pack that declares requires_extra → default OFF
        # (caller has to confirm the pip install + activate). Plain
        # bundled packs default ON.
        sys_dir = _system_dir() / name
        m = _read_manifest(sys_dir) if sys_dir.is_dir() else None
        if m and m.requires_extra:
            return False
        return True
    if scope == "workspace":
        ws = _load_state(_workspace_state_path(workspace))
        if name in ws:
            return bool(ws[name])
        return True
    if scope == "user":
        u = _load_state(_user_state_path())
        if name in u:
            return bool(u[name])
        return True
    return True


def set_enabled(
    workspace: Path, scope: str, name: str, enabled: bool,
) -> None:
    """Persist an enable/disable decision. System-scope packs that
    declare `requires_extra` ARE toggleable (the user has to opt in
    + accept the pip install); plain bundled packs without extras
    stay always-enabled."""
    if not _NAME_RE.match(name):
        raise ValueError(f"invalid pack name: {name!r}")
    if scope == "system":
        sys_dir = _system_dir() / name
        m = _read_manifest(sys_dir) if sys_dir.is_dir() else None
        if not m or not m.requires_extra:
            raise ValueError(
                "system-scope packs without requires_extra are always enabled",
            )
        p = _user_state_path()
    elif scope == "workspace":
        p = _workspace_state_path(workspace)
    elif scope == "user":
        p = _user_state_path()
    else:
        raise ValueError(f"invalid scope {scope!r}")
    state = _load_state(p)
    state[name] = bool(enabled)
    _save_state(p, state)


# ── Manifest ───────────────────────────────────────────────────────


@dataclass
class Manifest:
    name: str
    version: str
    description: str = ""
    skills: list[str] = field(default_factory=list)
    tabs: list[dict[str, Any]] = field(default_factory=list)
    # NOTE: `agent_presets` was a declared-but-never-applied surface —
    # cut for v1.0. A manifest may still carry the key; it's ignored
    # (fail-soft), not an error.
    mode_template: str | None = None
    # File-extension → action table. Each entry:
    #   { ext: ".pptx",
    #     action: "<unique-action-id>",
    #     label: "Open as image deck",
    #     description: "Renders slides to PNGs via LibreOffice",
    #     endpoint: "/api/bio/run",       # optional — POST {path}
    #     tab_kind: "vega",               # optional — switch on success
    #     selection_kind: "csv",          # optional — selection.kind to set
    #     primary: true,                  # the default click-handler
    #     requires_binary: "soffice" }    # optional dependency check
    # The daemon surfaces these via /api/file-routes; the file
    # browser uses them to decide what to do on click / right-click.
    file_routes: list[dict[str, Any]] = field(default_factory=list)
    # Python packages this pack needs available before its skills /
    # routes can do real work. Surfaces in Settings as a confirm-
    # install dialog when the user toggles a pack from inactive
    # → active. Empty list = no extra deps; the pack is pure
    # configuration (tab declarations, routes, agent presets).
    requires_extra: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "skills": self.skills,
            "tabs": self.tabs,
            "mode_template": self.mode_template,
            "file_routes": self.file_routes,
            "requires_extra": self.requires_extra,
        }


def _parse_manifest(raw: dict[str, Any]) -> Manifest:
    name = str(raw.get("name") or "").strip()
    if not _NAME_RE.match(name):
        raise ValueError(
            f"manifest `name` must match {_NAME_RE.pattern!r}; got {name!r}"
        )
    version = str(raw.get("version") or "").strip() or "0.0.0"
    description = str(raw.get("description") or "")
    skills_raw = raw.get("skills") or []
    skills = [str(s) for s in skills_raw if isinstance(s, str)]
    tabs_raw = raw.get("tabs") or []
    tabs = [t for t in tabs_raw if isinstance(t, dict)]
    # `agent_presets` (if present) is intentionally ignored — cut for v1.0.
    mode_template = raw.get("mode_template")
    if mode_template is not None and not isinstance(mode_template, str):
        mode_template = None
    routes_raw = raw.get("file_routes") or []
    file_routes: list[dict[str, Any]] = []
    for r in routes_raw:
        if not isinstance(r, dict):
            continue
        ext = str(r.get("ext") or "").strip().lower()
        action = str(r.get("action") or "").strip()
        if not ext or not action:
            continue
        # Normalise: leading dot, lower-case.
        if not ext.startswith("."):
            ext = "." + ext
        entry: dict[str, Any] = {"ext": ext, "action": action}
        for k in ("label", "description", "endpoint", "tab_kind",
                  "selection_kind", "requires_binary"):
            v = r.get(k)
            if isinstance(v, str) and v:
                entry[k] = v
        if r.get("primary") is True:
            entry["primary"] = True
        file_routes.append(entry)
    extra_raw = raw.get("requires_extra") or []
    requires_extra = [str(e) for e in extra_raw if isinstance(e, str)]
    return Manifest(
        name=name, version=version, description=description,
        skills=skills, tabs=tabs,
        mode_template=mode_template, file_routes=file_routes,
        requires_extra=requires_extra,
    )


def _read_manifest(pack_dir: Path) -> Manifest | None:
    pf = pack_dir / PACK_FILE
    if not pf.is_file():
        return None
    try:
        raw = json.loads(pf.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("pack %s: bad pack.json", pack_dir.name)
        return None
    if not isinstance(raw, dict):
        return None
    try:
        return _parse_manifest(raw)
    except ValueError as e:
        log.warning("pack %s: %s", pack_dir.name, e)
        return None


# ── Public API ─────────────────────────────────────────────────────


def list_packs(workspace: Path) -> list[dict[str, Any]]:
    """Every pack visible to this workspace — system, user, and
    workspace scopes merged. Precedence (lowest → highest):
    system → user → workspace. Higher scope wins on name collision
    so a workspace pack can override a bundled one (e.g. a project
    forks the LibreOffice pack with custom routes)."""
    out: dict[str, dict[str, Any]] = {}
    for scope, scope_dir in (
        ("system",    _system_dir()),
        ("user",      _user_global_dir()),
        ("workspace", _workspace_dir(workspace)),
    ):
        if not scope_dir.is_dir():
            continue
        for d in sorted(scope_dir.iterdir()):
            if not d.is_dir():
                continue
            m = _read_manifest(d)
            if m is None:
                continue
            entry = m.to_dict()
            entry["scope"] = scope
            entry["path"] = str(d)
            entry["enabled"] = _is_enabled(workspace, scope, m.name)
            out[m.name] = entry  # higher-scope iteration overwrites
    return list(out.values())


def pack_tabs_for(workspace: Path) -> list[dict[str, Any]]:
    """Flatten every pack's `tabs[]` array into TabSpec records the
    daemon can merge into mode.json. Each manifest entry should be:

        { kind: "<tab-kind-id>",         # required
          title: "Slides",               # required
          id: "pack:libreoffice:slides", # optional, derived if missing
          payload: { ... } }             # optional pass-through

    The output is annotated with `source: "pack"` and `pack:
    <pack-name>` so the frontend knows where to group it.
    """
    out: list[dict[str, Any]] = []
    for pack in list_packs(workspace):
        if not pack.get("enabled", True):
            continue
        pack_name = pack.get("name") or "?"
        for i, raw in enumerate(pack.get("tabs") or []):
            if not isinstance(raw, dict):
                continue
            kind = str(raw.get("kind") or "").strip()
            title = str(raw.get("title") or "").strip()
            if not kind or not title:
                continue
            spec: dict[str, Any] = {
                "id": str(raw.get("id") or f"pack:{pack_name}:{i}"),
                "title": title,
                "kind": kind,
                "source": "pack",
                "pack": pack_name,
            }
            payload = raw.get("payload")
            if isinstance(payload, dict):
                spec["payload"] = payload
            out.append(spec)
    return out


def file_routes_for(workspace: Path) -> list[dict[str, Any]]:
    """Flatten every pack's `file_routes` into a single list,
    annotated with the source pack. The file browser uses this to
    build a per-extension action map."""
    routes: list[dict[str, Any]] = []
    for pack in list_packs(workspace):
        if not pack.get("enabled", True):
            continue
        for r in pack.get("file_routes") or []:
            if not isinstance(r, dict):
                continue
            routes.append({
                **r,
                "pack": pack.get("name"),
                "scope": pack.get("scope"),
            })
    return routes


def get_pack(workspace: Path, name: str) -> dict[str, Any] | None:
    if not _NAME_RE.match(name):
        return None
    # Workspace first (override semantics), then user-global, then the
    # bundled system scope — packs shipped in switchbay itself live
    # there, so omitting it made get_pack (and /api/packs/<name>/action)
    # report "pack not found" for active bundled packs.
    for scope_dir, scope_name in (
        (_workspace_dir(workspace), "workspace"),
        (_user_global_dir(), "user"),
        (_system_dir(), "system"),
    ):
        d = scope_dir / name
        if d.is_dir():
            m = _read_manifest(d)
            if m is None:
                continue
            entry = m.to_dict()
            entry["scope"] = scope_name
            entry["path"] = str(d)
            entry["enabled"] = _is_enabled(workspace, scope_name, name)
            return entry
    return None


def _check_writable_scope(scope: str) -> None:
    if scope == "system":
        raise ValueError(
            "the `system` scope is bundled-read-only — install via "
            "`user` or `workspace` scope instead",
        )


async def install_from_git(
    url: str, *, workspace: Path, scope: str = "workspace",
) -> dict[str, Any]:
    """Install via `git clone --depth 1`. Target dir name is the
    repo's basename minus `.git` — pack.json's `name` field is then
    the canonical id and must match the directory.

    The clone runs as a subprocess so the daemon's event loop stays
    responsive. Inherits the user's git config for auth (SSH keys,
    credential helper, etc.); we don't carry credentials of our own.
    """
    _check_writable_scope(scope)
    if not url or not isinstance(url, str):
        raise ValueError("url is required")
    target_name = _slug_from_url(url)
    if not _NAME_RE.match(target_name):
        raise ValueError(f"can't derive a safe pack name from {url!r}")
    dest_root = _scope_dir(workspace, scope)
    dest_root.mkdir(parents=True, exist_ok=True)
    target = dest_root / target_name
    if target.exists():
        raise ValueError(f"pack {target_name!r} already installed in {scope}")
    log.info("git clone %s → %s", url, target)
    proc = await asyncio.create_subprocess_exec(
        "git", "clone", "--depth", "1", url, str(target),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        # Strip any ambient env that might point git at our own venv
        # (mirror the env-leak gotcha already in cebridge / claude_code).
        env={k: v for k, v in os.environ.items()
             if k not in {"VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "PYTHONPATH"}},
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        # Best-effort cleanup so a partial clone doesn't wedge the
        # next install attempt.
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        raise ValueError(
            f"git clone failed (rc={proc.returncode}): "
            f"{stderr.decode('utf-8', 'replace').strip()[:400]}"
        )
    m = _read_manifest(target)
    if m is None:
        shutil.rmtree(target, ignore_errors=True)
        raise ValueError(
            f"cloned repo at {url!r} has no valid {PACK_FILE} — "
            "not a switchbay pack"
        )
    if m.name != target_name:
        # Manifest declares a different name than the repo directory.
        # Rename the directory to match the manifest so subsequent
        # lookups by name find it. Skip when target already exists.
        renamed = dest_root / m.name
        if renamed.exists():
            shutil.rmtree(target, ignore_errors=True)
            raise ValueError(
                f"manifest name {m.name!r} collides with existing pack"
            )
        target.rename(renamed)
        target = renamed
    # Pull down any remote-declared skills before returning — fits
    # within the install round-trip so the freshly-installed pack is
    # immediately usable. Failures get logged but don't fail the
    # install; the user can re-fetch by uninstalling + reinstalling.
    try:
        report = await fetch_remote_skills(target)
        if not report.get("ok"):
            log.warning("pack %s: skill fetch partial: %s", m.name, report)
    except Exception:  # noqa: BLE001
        log.exception("pack %s: skill fetch crashed", m.name)
    rec = m.to_dict()
    rec["scope"] = scope
    rec["path"] = str(target)
    return rec


def install_from_path(
    src: Path, *, workspace: Path, scope: str = "workspace",
) -> dict[str, Any]:
    """Copy a local directory into the chosen scope. Useful for
    developing a pack alongside switchbay before publishing.
    Manifest must validate; missing pack.json bails with an error."""
    _check_writable_scope(scope)
    src = Path(src).expanduser().resolve()
    if not src.is_dir():
        raise ValueError(f"not a directory: {src}")
    m = _read_manifest(src)
    if m is None:
        raise ValueError(f"{src} has no valid {PACK_FILE}")
    dest_root = _scope_dir(workspace, scope)
    dest_root.mkdir(parents=True, exist_ok=True)
    target = dest_root / m.name
    if target.exists():
        raise ValueError(f"pack {m.name!r} already installed in {scope}")
    # Deep-copy so the canonical pack dir is self-contained and the
    # user can move / delete the original.
    shutil.copytree(src, target)
    rec = m.to_dict()
    rec["scope"] = scope
    rec["path"] = str(target)
    return rec


def uninstall_pack(name: str, *, workspace: Path, scope: str) -> bool:
    _check_writable_scope(scope)
    if not _NAME_RE.match(name):
        raise ValueError(f"invalid pack name: {name!r}")
    target = _scope_dir(workspace, scope) / name
    if not target.exists():
        return False
    # Defensive: confirm the target is inside the expected scope dir
    # (block path-traversal even though _NAME_RE rejects `..`).
    expected = _scope_dir(workspace, scope).resolve()
    if expected not in target.resolve().parents:
        raise ValueError("refusing to delete outside the pack scope dir")
    shutil.rmtree(target)
    return True


# ── Remote skill fetch ─────────────────────────────────────────────


# Subdir inside each pack that materialises remote-fetched skills.
# Mirrors the on-disk shape of bundled `skills/` so skillkit's
# discovery walk handles both with one code path.
FETCHED_SKILLS_DIR = ".fetched-skills"

# Skill refs in `pack.json`'s `skills` list can take three shapes:
#   · "<bare-name>"        — bundled, found by glob in <pack>/skills/
#   · "github:owner/repo"  — git clone via https from GitHub
#   · "git+https://…"      — git clone from any reachable HTTPS URL
# Anything else is ignored with a log warning.
_GH_RE = re.compile(r"^github:([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+?)(?:\.git)?$")
_GIT_RE = re.compile(r"^git\+(https?://\S+|git@\S+)$")


def _safe_id_for_ref(ref: str) -> str | None:
    """Stable directory name for a remote skill ref. Returns None
    for bundled refs (no fetch needed) and for refs we don't know
    how to handle."""
    m = _GH_RE.match(ref)
    if m:
        return f"github__{m.group(1)}__{m.group(2)}".lower()
    m = _GIT_RE.match(ref)
    if m:
        url = m.group(1)
        slug = re.sub(r"[^a-z0-9._-]+", "-", url.lower()).strip("-")
        return f"git__{slug}"[:80]
    return None


def _url_for_ref(ref: str) -> str | None:
    m = _GH_RE.match(ref)
    if m:
        return f"https://github.com/{m.group(1)}/{m.group(2)}.git"
    m = _GIT_RE.match(ref)
    if m:
        return m.group(1)
    return None


async def fetch_remote_skills(pack_dir: Path) -> dict[str, Any]:
    """Walk the pack manifest's `skills` list and `git clone` any
    remote refs into `<pack>/.fetched-skills/<safe-id>/`. Idempotent:
    a ref whose target dir already exists is skipped (re-fetch via
    uninstall + reinstall the pack). Returns a structured report so
    callers can surface failures.

    Bundled skills (bare names) are left alone — the existing
    `<pack>/skills/` walk in skillkit handles those."""
    m = _read_manifest(pack_dir)
    if m is None:
        return {"ok": False, "reason": "no-manifest"}
    fetched: list[str] = []
    skipped: list[str] = []
    failed: list[dict[str, str]] = []
    base = pack_dir / FETCHED_SKILLS_DIR
    for ref in m.skills:
        safe_id = _safe_id_for_ref(ref)
        if safe_id is None:
            # Bundled or unknown — no work for the fetch path.
            skipped.append(ref)
            continue
        target = base / safe_id
        if target.is_dir():
            skipped.append(ref)
            continue
        url = _url_for_ref(ref)
        if url is None:
            failed.append({"ref": ref, "reason": "no-url-resolved"})
            continue
        base.mkdir(parents=True, exist_ok=True)
        log.info("pack %s: cloning skill %s from %s", m.name, ref, url)
        proc = await asyncio.create_subprocess_exec(
            "git", "clone", "--depth", "1", url, str(target),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={k: v for k, v in os.environ.items()
                 if k not in {"VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "PYTHONPATH"}},
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            failed.append({
                "ref": ref,
                "reason": "clone-failed",
                "detail": stderr.decode("utf-8", "replace").strip()[:400],
            })
            continue
        fetched.append(ref)
    return {
        "ok": not failed,
        "pack": m.name,
        "fetched": fetched,
        "skipped": skipped,
        "failed": failed,
    }


# ── Helpers ────────────────────────────────────────────────────────


def _slug_from_url(url: str) -> str:
    """Derive a directory name from a git URL. Tries to match the
    `name` the pack will declare in its manifest, but the install
    flow renames the directory if there's a mismatch."""
    s = url.rstrip("/")
    if s.endswith(".git"):
        s = s[: -len(".git")]
    s = s.rsplit("/", 1)[-1]
    s = s.rsplit(":", 1)[-1]
    s = re.sub(r"[^a-z0-9._-]+", "-", s.lower()).strip("-")
    return s or "pack"


# Sanity check at import — if the user's home isn't writable for
# any reason, surface it as a log warning rather than a runtime
# error during install.
def _sanity_warn() -> None:
    home = Path.home()
    if not workspaces.is_within_home(home):
        log.warning("home dir not writable — user-global packs disabled")


_sanity_warn()
