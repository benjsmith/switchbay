"""Shared executable / PATH resolution for launchd-starved environments.

Never sources shell profiles. Discovers user-managed node/pnpm via
explicit env (``NVM_BIN``, ``NVM_DIR``, ``PNPM_HOME``, Volta/asdf/fnm/mise)
and well-known default install locations. An explicitly selected binary
always wins if it is a real executable.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from pathlib import Path

# Homebrew / MacPorts / user-local — always considered, never required.
_SYSTEM_BIN_DIRS = (
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/opt/local/bin",
)

_EXPLICIT_NODE_ENV = ("SWITCHBAY_NODE", "NODE_BINARY", "NODE")
_EXPLICIT_PNPM_ENV = ("SWITCHBAY_PNPM", "PNPM_BINARY")


def home_dir(
    *,
    home: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    if home is not None:
        return Path(home).expanduser()
    env = environ if environ is not None else os.environ
    raw = (env.get("HOME") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home()


def _windows_pathext() -> tuple[str, ...]:
    """PATHEXT suffixes in search order. Windows-only helper."""
    raw = os.environ.get("PATHEXT") or ".COM;.EXE;.BAT;.CMD"
    out: list[str] = []
    seen: set[str] = set()
    for ext in raw.split(os.pathsep):
        item = ext.strip().lower()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return tuple(out)


def is_executable(path: Path | str) -> bool:
    """True when ``path`` is a file the process can execute.

    Follows a symlink to the target. Directories, missing paths, and
    non-executable files are rejected. Windows has no POSIX execute
    bit — the suffix must be listed in ``PATHEXT``.
    """
    try:
        p = Path(path)
        if not p.is_file():
            return False
        if os.name == "nt" and p.suffix.lower() not in _windows_pathext():
            return False
        return os.access(p, os.X_OK)
    except OSError:
        return False


def _existing_dir(path: Path | str) -> str | None:
    try:
        p = Path(path)
        if p.is_dir():
            return str(p)
    except OSError:
        return None
    return None


def _first_nonempty_line(path: Path) -> str | None:
    """First non-empty, non-comment line, or None. Empty files are None."""
    try:
        if not path.is_file():
            return None
        for line in path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if text and not text.startswith("#"):
                return text
    except OSError:
        return None
    return None


def _strip_node_v(name: str) -> str:
    raw = name.strip()
    if raw.startswith("v") and len(raw) > 1 and raw[1].isdigit():
        return raw[1:]
    return raw


def _version_sort_key(name: str) -> tuple[int, ...]:
    parts: list[int] = []
    for bit in _strip_node_v(name).split("."):
        try:
            parts.append(int(bit))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _nvm_lookup_version_bin(versions: Path, wanted: str) -> str | None:
    """Exact version directory, else highest installed major/partial match."""
    wanted = _strip_node_v(wanted)
    if not wanted:
        return None
    for cand in (versions / f"v{wanted}" / "bin", versions / wanted / "bin"):
        d = _existing_dir(cand)
        if d:
            return d
    if not versions.is_dir():
        return None
    matches: list[str] = []
    prefix = f"v{wanted}"
    try:
        for child in versions.iterdir():
            name = child.name
            if name == prefix or name.startswith(prefix + "."):
                if (child / "bin").is_dir():
                    matches.append(name)
    except OSError:
        return None
    if not matches:
        return None
    matches.sort(key=_version_sort_key)
    return str(versions / matches[-1] / "bin")


def _nvm_resolve_name(nvm_dir: Path, name: str, seen: set[str] | None = None) -> str | None:
    """Resolve an nvm alias or version (including ``lts/*`` chains)."""
    raw = (name or "").strip()
    if not raw:
        return None
    seen = seen if seen is not None else set()
    key = raw.lower()
    if key in seen:
        return None
    seen.add(key)
    for alias_file in (
        nvm_dir / "alias" / raw,
        nvm_dir / "alias" / "lts" / raw,
    ):
        line = _first_nonempty_line(alias_file)
        if line:
            return _nvm_resolve_name(nvm_dir, line, seen)
    return _nvm_lookup_version_bin(nvm_dir / "versions" / "node", raw)


def _nvm_bin_dirs(
    *,
    home: Path,
    environ: Mapping[str, str],
) -> list[str]:
    """nvm bin directories without sourcing nvm.sh.

    Prefer ``NVM_BIN`` (already the active version). Else resolve
    ``NVM_DIR`` (default ``~/.nvm``) via ``alias/default``, including
    major versions (``22``), partials (``22.11``), ``lts/*``, and
    alias chains. Empty alias files are ignored.
    """
    out: list[str] = []
    nvm_bin = (environ.get("NVM_BIN") or "").strip()
    if nvm_bin:
        d = _existing_dir(Path(nvm_bin).expanduser())
        if d:
            out.append(d)
    nvm_dir_raw = (environ.get("NVM_DIR") or "").strip()
    nvm_dir = Path(nvm_dir_raw).expanduser() if nvm_dir_raw else (home / ".nvm")
    wanted = _first_nonempty_line(nvm_dir / "alias" / "default")
    if wanted:
        d = _nvm_resolve_name(nvm_dir, wanted)
        if d:
            out.append(d)
    current = nvm_dir / "current" / "bin"
    d = _existing_dir(current)
    if d:
        out.append(d)
    return out


def _version_manager_dirs(
    *,
    home: Path,
    environ: Mapping[str, str],
) -> list[str]:
    out: list[str] = []

    volta_home = (environ.get("VOLTA_HOME") or "").strip()
    volta = Path(volta_home).expanduser() if volta_home else (home / ".volta")
    d = _existing_dir(volta / "bin")
    if d:
        out.append(d)

    fnm_multi = (environ.get("FNM_MULTISHELL_PATH") or "").strip()
    if fnm_multi:
        d = _existing_dir(Path(fnm_multi).expanduser())
        if d:
            out.append(d)
    fnm_dir_raw = (environ.get("FNM_DIR") or "").strip()
    fnm_roots = []
    if fnm_dir_raw:
        fnm_roots.append(Path(fnm_dir_raw).expanduser())
    fnm_roots.extend((
        home / ".local" / "share" / "fnm",
        home / ".fnm",
    ))
    for root in fnm_roots:
        for rel in ("aliases/default/bin", "current/bin"):
            d = _existing_dir(root / rel)
            if d:
                out.append(d)

    asdf_data = (environ.get("ASDF_DATA_DIR") or "").strip()
    asdf_dir_raw = (environ.get("ASDF_DIR") or "").strip()
    asdf_roots = []
    if asdf_data:
        asdf_roots.append(Path(asdf_data).expanduser())
    if asdf_dir_raw:
        asdf_roots.append(Path(asdf_dir_raw).expanduser())
    asdf_roots.append(home / ".asdf")
    for root in asdf_roots:
        d = _existing_dir(root / "shims")
        if d:
            out.append(d)

    mise_data = (environ.get("MISE_DATA_DIR") or "").strip()
    mise_roots = []
    if mise_data:
        mise_roots.append(Path(mise_data).expanduser())
    mise_roots.extend((
        home / ".local" / "share" / "mise",
        home / ".mise",
    ))
    for root in mise_roots:
        d = _existing_dir(root / "shims")
        if d:
            out.append(d)

    pnpm_home = (environ.get("PNPM_HOME") or "").strip()
    if pnpm_home:
        d = _existing_dir(Path(pnpm_home).expanduser())
        if d:
            out.append(d)
    else:
        d = _existing_dir(home / "Library" / "pnpm")
        if d:
            out.append(d)
        d = _existing_dir(home / ".local" / "share" / "pnpm")
        if d:
            out.append(d)

    return out


def extra_path_dirs(
    *,
    home: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
    extra_dirs: tuple[str, ...] | list[str] = (),
) -> list[str]:
    """Candidate PATH prefixes that currently exist as directories.

    Order: caller extras, explicit version-manager env, well-known
    Homebrew/local bins, ``~/.local/bin`` / ``~/bin``. Missing dirs
    are omitted. Does not source shell profiles.
    """
    env = environ if environ is not None else os.environ
    h = home_dir(home=home, environ=env)
    seen: set[str] = set()
    out: list[str] = []

    def add(raw: str | Path | None) -> None:
        if not raw:
            return
        d = _existing_dir(Path(str(raw)).expanduser())
        if d and d not in seen:
            seen.add(d)
            out.append(d)

    for d in extra_dirs:
        add(d)
    add(env.get("NVM_BIN"))
    for d in _nvm_bin_dirs(home=h, environ=env):
        add(d)
    for d in _version_manager_dirs(home=h, environ=env):
        add(d)
    for d in _SYSTEM_BIN_DIRS:
        add(d)
    add(h / ".local" / "bin")
    add(h / "bin")
    return out


def enrich_env(
    env: dict[str, str] | None = None,
    *,
    extra_dirs: tuple[str, ...] | list[str] = (),
    prepend: tuple[str, ...] | list[str] = (),
    home: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return a copy of ``env`` with discovered bins appended after PATH.

    ``prepend`` wins (explicit selected runtimes). Existing PATH entries
    beat fallback discoveries (nvm / Homebrew / version managers) so a
    selected PATH runtime is not overridden. Missing dirs are omitted.
    """
    base = dict(env if env is not None else (environ if environ is not None else os.environ))
    discovered = extra_path_dirs(
        home=home, environ=base, extra_dirs=tuple(extra_dirs),
    )
    existing = [p for p in base.get("PATH", "").split(os.pathsep) if p]
    seen: set[str] = set()
    prefix: list[str] = []

    def add(raw: str) -> None:
        if not raw or raw in seen:
            return
        seen.add(raw)
        prefix.append(raw)

    for d in prepend:
        if d:
            add(str(Path(d).expanduser()))
    for d in existing:
        add(d)
    for d in discovered:
        add(d)
    if prefix:
        base["PATH"] = os.pathsep.join(prefix)
    return base


def apply_to_environ(env: dict[str, str] | None = None) -> dict[str, str]:
    """In-place enrich of ``os.environ`` (or ``env``). Returns the mapping."""
    target = env if env is not None else os.environ
    enriched = enrich_env(dict(target))
    target["PATH"] = enriched.get("PATH", target.get("PATH", ""))
    return target


def resolve_executable(
    name: str,
    env: Mapping[str, str] | None = None,
    *,
    extra_dirs: tuple[str, ...] | list[str] = (),
    explicit: str | Path | None = None,
    home: Path | str | None = None,
) -> str | None:
    """Resolve ``name`` to an executable path, or None.

    Precedence: ``explicit`` (if it is a real executable), then
    existing PATH, then discovered fallbacks (nvm/volta/homebrew) so a
    launchd-minimal PATH still finds user-managed runtimes without
    overriding a selected PATH binary.
    """
    if explicit:
        p = Path(str(explicit)).expanduser()
        if is_executable(p):
            return str(p.resolve()) if p.exists() else str(p)
    enriched = enrich_env(
        dict(env if env is not None else os.environ),
        extra_dirs=tuple(extra_dirs),
        home=home,
    )
    path = enriched.get("PATH") or os.defpath
    found = shutil.which(name, path=path)
    if found and is_executable(found):
        return found
    for d in extra_path_dirs(
        home=home,
        environ=enriched,
        extra_dirs=tuple(extra_dirs),
    ):
        # Search this directory only. shutil.which(path=d) prepends cwd
        # on Windows, so enumerate PATHEXT suffixes here instead.
        cand = Path(d) / name
        if is_executable(cand):
            return str(cand)
        if os.name == "nt" and not Path(name).suffix:
            for ext in _windows_pathext():
                cand_ext = Path(d) / f"{name}{ext}"
                if is_executable(cand_ext):
                    return str(cand_ext)
    return None


def _explicit_from_env(keys: tuple[str, ...], environ: Mapping[str, str]) -> str | None:
    for k in keys:
        raw = (environ.get(k) or "").strip()
        if raw:
            return raw
    return None


def resolve_node(
    env: Mapping[str, str] | None = None,
    *,
    extra_dirs: tuple[str, ...] | list[str] = (),
    explicit: str | Path | None = None,
    home: Path | str | None = None,
) -> str | None:
    environ = env if env is not None else os.environ
    chosen = explicit or _explicit_from_env(_EXPLICIT_NODE_ENV, environ)
    return resolve_executable(
        "node", environ, extra_dirs=extra_dirs, explicit=chosen, home=home,
    )


def resolve_pnpm(
    env: Mapping[str, str] | None = None,
    *,
    extra_dirs: tuple[str, ...] | list[str] = (),
    explicit: str | Path | None = None,
    home: Path | str | None = None,
) -> str | None:
    environ = env if env is not None else os.environ
    chosen = explicit or _explicit_from_env(_EXPLICIT_PNPM_ENV, environ)
    return resolve_executable(
        "pnpm", environ, extra_dirs=extra_dirs, explicit=chosen, home=home,
    )


def spawn_env(
    env: Mapping[str, str] | None = None,
    *,
    extra_dirs: tuple[str, ...] | list[str] = (),
    prepend: tuple[str, ...] | list[str] = (),
    home: Path | str | None = None,
) -> dict[str, str]:
    """Environment dict suitable for ``subprocess`` / asyncio spawn.

    After resolving Node, that binary's directory is prepended so
    ``#!/usr/bin/env node`` shebangs (pnpm/npx) use the same runtime.
    Re-enrichment does not let Homebrew/system fallbacks override it.
    """
    base = dict(env if env is not None else os.environ)
    extra = tuple(extra_dirs)
    pre = [str(Path(d).expanduser()) for d in prepend if d]
    chosen = _explicit_from_env(_EXPLICIT_NODE_ENV, base)
    node = resolve_node(base, extra_dirs=extra, explicit=chosen, home=home)
    if node:
        bindir = str(Path(node).parent)
        if bindir not in pre:
            pre.insert(0, bindir)
    return enrich_env(
        base,
        extra_dirs=extra,
        prepend=tuple(pre),
        home=home,
    )


# Narrow OS-service allowlist. Secrets, full shell PATH, and profile
# dumps stay out of launchd/systemd/scheduled-task env.
_SERVICE_RUNTIME_KEYS = (
    "NVM_BIN",
    "NVM_DIR",
    "PNPM_HOME",
    "SWITCHBAY_NODE",
    "SWITCHBAY_PNPM",
    "NODE_BINARY",
    "PNPM_BINARY",
    "VOLTA_HOME",
    "ASDF_DATA_DIR",
    "ASDF_DIR",
    "FNM_DIR",
    "FNM_MULTISHELL_PATH",
    "MISE_DATA_DIR",
)

_SERVICE_BOOTSTRAP_PATH = ("/usr/bin", "/bin", "/usr/sbin", "/sbin")


def service_runtime_exports(
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | str | None = None,
) -> dict[str, str]:
    """Allowlisted runtime dirs for an OS-service supervisor.

    Copies configured NVM/pnpm/explicit binary locations and puts the
    resolved selected bin directories on a *minimal* PATH (bootstrap +
    those dirs). Does not source shells or copy secret env.
    """
    env = dict(environ if environ is not None else os.environ)
    h = home_dir(home=home, environ=env)
    out: dict[str, str] = {}
    for key in _SERVICE_RUNTIME_KEYS:
        raw = (env.get(key) or "").strip()
        if raw:
            out[key] = raw

    bins: list[str] = []
    seen: set[str] = set()

    def add_dir(raw: str | Path | None) -> None:
        if not raw:
            return
        d = _existing_dir(Path(str(raw)).expanduser())
        if d and d not in seen:
            seen.add(d)
            bins.append(d)

    add_dir(out.get("NVM_BIN"))
    add_dir(out.get("PNPM_HOME"))
    node = resolve_node(env, home=h)
    if node:
        add_dir(Path(node).parent)
    pnpm = resolve_pnpm(env, home=h)
    if pnpm:
        add_dir(Path(pnpm).parent)
    add_dir(h / ".local" / "bin")

    path_parts: list[str] = []
    path_seen: set[str] = set()
    for p in _SERVICE_BOOTSTRAP_PATH:
        if p not in path_seen:
            path_seen.add(p)
            path_parts.append(p)
    for d in bins:
        if d not in path_seen:
            path_seen.add(d)
            path_parts.append(d)
    out["PATH"] = os.pathsep.join(path_parts)
    return out
