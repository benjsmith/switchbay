#!/usr/bin/env python3
"""Stage a platform-specific enterprise payload for packaging teams.

Does not run uv/pnpm itself — CI (or a builder) must already have
`uv sync` and `pnpm --dir frontend run build`. Copies:

  * ``src/``, ``frontend/dist/``, lockfiles, license, policy templates
  * the uv-managed CPython standalone into ``python/``
  * venv ``site-packages`` merged into that interpreter (no .venv trampoline)

The resulting tree is relocatable as a unit. Endpoints start it with
``SWITCHBAY_PROFILE=enterprise`` and never invoke uv/pnpm/setup.sh.

Usage (from repo root, after sync + frontend build):

    python scripts/stage_enterprise_payload.py --out dist/enterprise
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import sys
from pathlib import Path

SKIP_DIR_NAMES = {
    ".git", ".github", "node_modules", "__pycache__", ".pytest_cache",
    "test-results", "playwright-report", "bench", "samples",
}


def _copy_tree(src: Path, dst: Path) -> None:
    if not src.is_dir():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for child in src.iterdir():
        if child.name in SKIP_DIR_NAMES or child.name.startswith("."):
            continue
        target = dst / child.name
        if child.is_dir():
            _copy_tree(child, target)
        else:
            shutil.copy2(child, target)


def _merge_tree(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for child in src.iterdir():
        if child.name in ("__pycache__",) or child.suffix == ".pyc":
            continue
        target = dst / child.name
        if child.is_dir():
            _merge_tree(child, target)
        else:
            shutil.copy2(child, target)


def _venv_home(venv: Path) -> Path | None:
    cfg = venv / "pyvenv.cfg"
    if not cfg.is_file():
        return None
    try:
        lines = cfg.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        if line.lower().startswith("home"):
            _, _, rest = line.partition("=")
            raw = rest.strip()
            return Path(raw) if raw else None
    return None


def standalone_prefix(home: Path) -> Path | None:
    """uv python-build-standalone prefix (directory named ``cpython-*``)."""
    try:
        cur = home.resolve() if home.exists() else home
    except OSError:
        cur = home
    for p in [cur, *list(cur.parents)]:
        if p.name.startswith("cpython-"):
            return p
    return None


def venv_site_packages(venv: Path) -> Path | None:
    win = venv / "Lib" / "site-packages"
    if win.is_dir():
        return win
    lib = venv / "lib"
    if not lib.is_dir():
        return None
    try:
        children = list(lib.iterdir())
    except OSError:
        return None
    for child in children:
        sp = child / "site-packages"
        if sp.is_dir():
            return sp
    return None


def standalone_site_packages(prefix: Path) -> Path | None:
    win = prefix / "Lib" / "site-packages"
    if win.is_dir() or (prefix / "python.exe").is_file() or (prefix / "python.bat").is_file():
        return win
    lib = prefix / "lib"
    if not lib.is_dir():
        return None
    try:
        children = list(lib.iterdir())
    except OSError:
        return None
    for child in children:
        if child.name.startswith("python") and child.is_dir():
            return child / "site-packages"
    return None


def interpreter_path(prefix: Path) -> Path | None:
    for cand in (
        prefix / "python.exe",
        prefix / "bin" / "python3",
        prefix / "bin" / "python",
        prefix / "Scripts" / "python.exe",
    ):
        if cand.is_file() or cand.is_symlink():
            return cand
    return None


def _copy_standalone_and_site(repo: Path, out: Path) -> Path | None:
    """Copy uv CPython + venv site-packages into ``out/python/<name>``.

    Returns the interpreter path inside the payload, or None if the
    builder venv is not an uv standalone (caller may fall back).
    """
    venv = repo / ".venv"
    home = _venv_home(venv)
    if home is None:
        return None
    prefix = standalone_prefix(home)
    if prefix is None or not prefix.is_dir():
        return None
    dest = out / "python" / prefix.name
    shutil.copytree(
        prefix, dest,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        symlinks=False,
        dirs_exist_ok=True,
    )
    src_sp = venv_site_packages(venv)
    dst_sp = standalone_site_packages(dest)
    if src_sp is None or dst_sp is None:
        print("warning: could not merge site-packages into standalone python", file=sys.stderr)
        return interpreter_path(dest)
    _merge_tree(src_sp, dst_sp)
    return interpreter_path(dest)


def _write_launchers(out: Path) -> None:
    posix = """#!/bin/sh
# Packaging-team smoke launcher. Endpoints should use the MSI/PKG.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
export PYTHONPATH="$ROOT/src"
export SWITCHBAY_PROFILE="${SWITCHBAY_PROFILE:-enterprise}"
export SWITCHBAY_SERVICE="${SWITCHBAY_SERVICE:-1}"
PY=$(echo "$ROOT"/python/cpython-*/bin/python3)
if [ ! -x "$PY" ]; then
  PY=$(echo "$ROOT"/python/cpython-*/bin/python)
fi
WS="${SWITCHBAY_WORKSPACE:-$HOME/SwitchBay/workspace}"
mkdir -p "$WS"
exec "$PY" -m switchbay serve --workspace "$WS" "$@"
"""
    win = (
        "@echo off\r\n"
        "setlocal EnableExtensions\r\n"
        "set \"ROOT=%~dp0\"\r\n"
        "set \"PYTHONPATH=%ROOT%src\"\r\n"
        "if not defined SWITCHBAY_PROFILE set SWITCHBAY_PROFILE=enterprise\r\n"
        "set SWITCHBAY_SERVICE=1\r\n"
        "set \"PY=\"\r\n"
        "for /d %%D in (\"%ROOT%python\\cpython-*\") do set \"PY=%%D\\python.exe\"\r\n"
        "if not defined PY (\r\n"
        "  echo python standalone missing in python\\cpython-*\r\n"
        "  exit /b 1\r\n"
        ")\r\n"
        "if not defined SWITCHBAY_WORKSPACE set \"SWITCHBAY_WORKSPACE=%USERPROFILE%\\SwitchBay\\workspace\"\r\n"
        "if not exist \"%SWITCHBAY_WORKSPACE%\" mkdir \"%SWITCHBAY_WORKSPACE%\"\r\n"
        "\"%PY%\" -m switchbay serve --workspace \"%SWITCHBAY_WORKSPACE%\" %*\r\n"
    )
    sh = out / "serve.sh"
    sh.write_text(posix, encoding="utf-8")
    try:
        sh.chmod(sh.stat().st_mode | 0o111)
    except OSError:
        pass
    (out / "serve.cmd").write_text(win, encoding="utf-8")


def stage(repo: Path, out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    shutil.copy2(repo / "pyproject.toml", out / "pyproject.toml")
    shutil.copy2(repo / "uv.lock", out / "uv.lock")
    shutil.copy2(repo / "LICENSE", out / "LICENSE")
    shutil.copy2(repo / "README.md", out / "README.md")
    _copy_tree(repo / "src", out / "src")
    frontend_dist = repo / "frontend" / "dist"
    if not (frontend_dist / "index.html").is_file():
        raise SystemExit("frontend/dist missing — run pnpm --dir frontend run build")
    _copy_tree(frontend_dist, out / "frontend" / "dist")
    venv = repo / ".venv"
    if not venv.is_dir():
        raise SystemExit(".venv missing — run uv sync")
    interp = _copy_standalone_and_site(repo, out)
    if interp is None:
        # Builder used a non-uv interpreter. Copy the venv as a last
        # resort — paths inside it may need rebaking on the packager's OS.
        print(
            "warning: uv standalone python not found; copying .venv as-is",
            file=sys.stderr,
        )
        shutil.copytree(
            venv, out / ".venv",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            symlinks=False,
        )
    cfg = out / "config"
    cfg.mkdir()
    shutil.copy2(repo / "config" / "admin.enterprise.json", cfg / "admin.enterprise.json")
    (out / "SWITCHBAY_PROFILE").write_text("enterprise\n", encoding="utf-8")
    docs = out / "docs"
    docs.mkdir()
    for name in ("enterprise.md", "enterprise-windows-design.md", "providers.md"):
        src = repo / "docs" / name
        if src.is_file():
            shutil.copy2(src, docs / name)
    pack = repo / "enterprise" / "packaging"
    if pack.is_dir():
        _copy_tree(pack, out / "enterprise" / "packaging")
    _write_launchers(out)

    plat = sys.platform
    machine = platform.machine().lower()
    interp_note = str(interp) if interp is not None else "(none — using .venv fallback)"
    (out / "PAYLOAD.txt").write_text(
        "\n".join([
            "Switch Bay enterprise payload",
            f"platform={plat} machine={machine}",
            f"interpreter={interp_note}",
            "",
            "This tree is frozen. Do not run uv, pnpm, npx, or setup.sh",
            "on endpoints. Wrap it with MSI/PKG; stamp SWITCHBAY_PROFILE=enterprise",
            "in the service environment.",
            "",
            "Layout:",
            "  python/cpython-*/     relocatable CPython + site-packages",
            "  src/                  Switch Bay",
            "  frontend/dist/        built PWA",
            "  config/admin.enterprise.json",
            "",
            "Admin policy template: config/admin.enterprise.json",
            "To allow Hugging Face downloads, set features.hf_model_download true.",
            "Copilot host: set copilot.host (github.com or your GHE URL) at bake.",
            "Windows overlay: %ProgramData%\\SwitchBay\\admin.json",
            "macOS overlay: /Library/Application Support/SwitchBay/admin.json",
            "Default workspace: %USERPROFILE%\\SwitchBay\\workspace  (or ~/SwitchBay/workspace)",
            "",
            "Smoke (packaging builder, not the employee PC):",
            "  POSIX:   ./serve.sh",
            "  Windows: serve.cmd",
            "  Then open http://127.0.0.1:8765 in Edge (Windows) or Safari (macOS).",
            "",
        ]) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="dist/enterprise-payload")
    args = p.parse_args()
    repo = Path(__file__).resolve().parents[1]
    out = Path(args.out)
    if not out.is_absolute():
        out = repo / out
    stage(repo, out)
    print(f"staged {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
