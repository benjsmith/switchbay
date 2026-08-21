#!/usr/bin/env python3
"""Turn a CI enterprise payload into a bake folder IT can import.

IT admins do not run this. The company bake machine does, then signs,
then Intune/Jamf imports the output. Endpoints never run uv/pnpm.

Usage (from repo root, after unzipping the GitHub release asset):

    python scripts/bake_enterprise.py \\
      --payload dist/switchbay-enterprise-win11-x64 \\
      --copilot-host github.example.com \\
      --out dist/bake
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "enterprise" / "packaging"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def stamp_baked(
    payload: Path,
    *,
    copilot_host: str | None = None,
    sso_slug: str | None = None,
    allow_hf: bool | None = None,
    skills_npx: bool | None = None,
) -> dict:
    """Write policy into payload/admin.baked.json. Returns the dict."""
    path = payload / "admin.baked.json"
    if path.is_file():
        data = _load_json(path)
    else:
        data = _load_json(ROOT / "config" / "admin.enterprise.json")
    data["profile"] = "enterprise"
    data["allow_profile_override"] = False
    copilot = dict(data.get("copilot") or {})
    if copilot_host:
        copilot["host"] = copilot_host.strip()
    if sso_slug is not None:
        copilot["sso_slug"] = sso_slug.strip()
    copilot["lock_host"] = True
    data["copilot"] = copilot
    feats = dict(data.get("features") or {})
    if allow_hf is not None:
        feats["hf_model_download"] = bool(allow_hf)
    if skills_npx is not None:
        feats["install_skills_npx"] = bool(skills_npx)
    data["features"] = feats
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def unpack_if_needed(payload: Path, work: Path) -> Path:
    """Return a directory tree. Zip/tar are extracted into work/payload."""
    if payload.is_dir():
        return payload
    dest = work / "payload"
    dest.mkdir(parents=True, exist_ok=True)
    name = payload.name.lower()
    if name.endswith(".zip"):
        with zipfile.ZipFile(payload) as zf:
            zf.extractall(dest)
    elif name.endswith(".tar.gz") or name.endswith(".tgz"):
        with tarfile.open(payload, "r:gz") as tf:
            tf.extractall(dest)
    else:
        raise SystemExit(f"payload must be a directory, .zip, or .tar.gz: {payload}")
    kids = [p for p in dest.iterdir() if p.is_dir()]
    if len(kids) == 1 and (kids[0] / "src").is_dir():
        return kids[0]
    if (dest / "src").is_dir():
        return dest
    raise SystemExit(f"unpacked tree has no src/: {dest}")


def find_cpython(payload: Path) -> Path | None:
    py = payload / "python"
    if not py.is_dir():
        return None
    for child in sorted(py.iterdir()):
        if child.is_dir() and child.name.startswith("cpython-"):
            return child
    return None


def write_ico(png: Path, ico: Path) -> bool:
    if not png.is_file():
        return False
    try:
        from PIL import Image
    except ImportError:
        return False
    img = Image.open(png).convert("RGBA")
    ico.parent.mkdir(parents=True, exist_ok=True)
    img.save(
        ico, format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (256, 256)],
    )
    return True


def _write_windows_wrappers(layout: Path, prefix: Path | None) -> None:
    py = "bin\\switchbay.exe"
    if not (layout / "bin" / "switchbay.exe").is_file() and prefix is not None:
        rel = prefix.relative_to(layout)
        py = str(rel / "python.exe").replace("/", "\\")
    cmd = (
        "@echo off\r\n"
        "setlocal\r\n"
        "set \"SWITCHBAY_INSTALL_ROOT=%~dp0\"\r\n"
        "set \"SWITCHBAY_PROFILE=enterprise\"\r\n"
        "set \"PYTHONPATH=%SWITCHBAY_INSTALL_ROOT%src\"\r\n"
        "if exist \"%SWITCHBAY_INSTALL_ROOT%vendor\\curiosity-engine\\\" (\r\n"
        "  set \"SWITCHBAY_CE_ROOT=%SWITCHBAY_INSTALL_ROOT%vendor\\curiosity-engine\"\r\n"
        ")\r\n"
        "if not defined SWITCHBAY_WORKSPACE "
        "set \"SWITCHBAY_WORKSPACE=%USERPROFILE%\\SwitchBay\\workspace\"\r\n"
        "if not exist \"%SWITCHBAY_WORKSPACE%\" mkdir \"%SWITCHBAY_WORKSPACE%\"\r\n"
        "cd /d \"%SWITCHBAY_INSTALL_ROOT%\"\r\n"
        f"\"%SWITCHBAY_INSTALL_ROOT%{py}\" -m switchbay serve "
        "--workspace \"%SWITCHBAY_WORKSPACE%\" %*\r\n"
    )
    (layout / "serve-task.cmd").write_text(cmd, encoding="utf-8")


def layout_windows(payload: Path, layout: Path) -> dict[str, str]:
    """Copy payload into an install tree with bin\\ next to src\\."""
    if layout.exists():
        shutil.rmtree(layout)
    shutil.copytree(
        payload, layout,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        dirs_exist_ok=False,
    )
    prefix = find_cpython(layout)
    bindir = layout / "bin"
    bindir.mkdir(exist_ok=True)
    notes: dict[str, str] = {"host": "python.exe fallback"}
    if prefix is not None:
        for name in ("python313.dll", "python313.zip", "python.exe"):
            src = prefix / name
            if src.is_file():
                shutil.copy2(src, bindir / name)
        lib = prefix / "Lib"
        if lib.is_dir() and not (bindir / "Lib").exists():
            shutil.copytree(
                lib, bindir / "Lib",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        pth = PACK / "windows" / "python313._pth"
        if pth.is_file():
            shutil.copy2(pth, bindir / "python313._pth")
    win_pack = layout / "enterprise" / "packaging" / "windows"
    win_pack.mkdir(parents=True, exist_ok=True)
    for name in ("register-user-task.ps1", "SwitchBay.xml.template"):
        shutil.copy2(PACK / "windows" / name, win_pack / name)
    png = layout / "frontend" / "dist" / "icon-512.png"
    if not png.is_file():
        png = layout / "frontend" / "dist" / "icon-192.png"
    write_ico(png, layout / "frontend" / "dist" / "icon.ico")

    compiled = _try_compile_windows_host(layout, prefix)
    if compiled:
        notes["host"] = "bin\\switchbay.exe"
    _write_windows_wrappers(layout, prefix)
    return notes


def _try_compile_windows_host(layout: Path, prefix: Path | None) -> bool:
    cl = shutil.which("cl")
    if cl is None:
        return False
    bindir = layout / "bin"
    libdir = str(prefix) if prefix is not None else str(bindir)
    env = os.environ.copy()
    def _cl(src: Path, out: Path, extra: list[str]) -> bool:
        cmd = [cl, "/nologo", "/O2", f"/Fe:{out}", str(src), *extra]
        try:
            subprocess.run(cmd, check=True, cwd=libdir, env=env,
                           capture_output=True, text=True)
            return out.is_file()
        except (OSError, subprocess.CalledProcessError):
            return False
    host_c = PACK / "windows" / "switchbay-host.c"
    gui_c = PACK / "windows" / "switchbay-gui.c"
    ok_host = _cl(host_c, bindir / "switchbay.exe", ["python313.lib", "user32.lib"])
    ok_gui = _cl(gui_c, bindir / "SwitchBay.exe", ["shell32.lib", "wininet.lib"])
    return ok_host and ok_gui


def write_macos_wrappers(layout: Path) -> None:
    sh = """#!/bin/sh
set -eu
ROOT="/Library/Application Support/SwitchBay"
export SWITCHBAY_INSTALL_ROOT="$ROOT"
export SWITCHBAY_PROFILE=enterprise
export PYTHONPATH="$ROOT/src"
export PYTHONUNBUFFERED=1
export SWITCHBAY_SERVICE=1
if [ -d "$ROOT/vendor/curiosity-engine" ]; then
  export SWITCHBAY_CE_ROOT="$ROOT/vendor/curiosity-engine"
fi
WS="${SWITCHBAY_WORKSPACE:-$HOME/SwitchBay/workspace}"
mkdir -p "$WS"
PY=$(echo "$ROOT"/python/cpython-*/bin/python3)
if [ ! -x "$PY" ]; then
  PY=$(echo "$ROOT"/python/cpython-*/bin/python)
fi
cd "$ROOT"
exec "$PY" -m switchbay serve --workspace "$WS"
"""
    p = layout / "serve-user.sh"
    p.write_text(sh, encoding="utf-8")
    p.chmod(p.stat().st_mode | 0o111)


def write_launchagent_plist(dest: Path) -> None:
    dest.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.switchbay.daemon</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Library/Application Support/SwitchBay/serve-user.sh</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>~/Library/Logs/switchbay-daemon.log</string>
  <key>StandardErrorPath</key><string>~/Library/Logs/switchbay-daemon.log</string>
</dict>
</plist>
""",
        encoding="utf-8",
    )


def bake_macos_pkg(payload: Path, out: Path) -> Path:
    write_macos_wrappers(payload)
    staging = out / "pkgroot"
    if staging.exists():
        shutil.rmtree(staging)
    install = staging / "Library" / "Application Support" / "SwitchBay"
    install.parent.mkdir(parents=True)
    shutil.copytree(
        payload, install,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    write_macos_wrappers(install)
    agents = staging / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    write_launchagent_plist(agents / "com.switchbay.daemon.plist")
    stub_src = PACK / "macos" / "switchbay-stub.c"
    app_mac = (
        staging / "Applications" / "Switch Bay.app" / "Contents" / "MacOS"
    )
    app_mac.mkdir(parents=True)
    subprocess.run(
        ["cc", "-O2", "-o", str(app_mac / "SwitchBay"), str(stub_src)],
        check=True,
    )
    (app_mac.parent / "Info.plist").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key><string>com.switchbay.app</string>
  <key>CFBundleName</key><string>Switch Bay</string>
  <key>CFBundleExecutable</key><string>SwitchBay</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
</dict>
</plist>
""",
        encoding="utf-8",
    )
    ver = "0.9.16"
    init = payload / "src" / "switchbay" / "__init__.py"
    if init.is_file():
        for line in init.read_text(encoding="utf-8").splitlines():
            if line.startswith("__version__"):
                ver = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    pkg = out / f"SwitchBay-{ver}-unsigned.pkg"
    subprocess.run(
        [
            "pkgbuild", "--root", str(staging),
            "--identifier", "com.switchbay.pkg",
            "--version", ver,
            "--install-location", "/",
            str(pkg),
        ],
        check=True,
    )
    return pkg


def overlay_example(*, copilot_host: str, allow_hf: bool) -> dict:
    return {
        "profile": "enterprise",
        "copilot": {"host": copilot_host, "lock_host": True},
        "features": {"hf_model_download": allow_hf},
    }


def write_next(out: Path, *, kind: str, extra: dict[str, str]) -> None:
    lines = [
        "Switch Bay bake output — remaining HUMAN steps",
        "",
        "1. Sign (company cert; CI cannot do this).",
    ]
    if kind == "windows":
        lines += [
            "   Sign layout\\bin\\switchbay.exe, SwitchBay.exe, python313.dll",
            "   with the company Authenticode pipeline.",
            "   (If bake fell back to python.exe, install VS Build Tools and",
            "   re-run bake so switchbay.exe exists; EDR prefers that host.)",
            "",
            "2. Intune → Apps → Windows → Add → Windows app (Win32).",
            "   Install:   powershell.exe -ExecutionPolicy Bypass -File install.ps1",
            "   Uninstall: powershell.exe -ExecutionPolicy Bypass -File uninstall.ps1",
            "   Detection: detection.ps1",
            "   Install behavior: System. Assignment: user group. Restart: no.",
            "",
            "3. Copy admin.overlay.example.json to "
            "%ProgramData%\\SwitchBay\\admin.json via Intune (separate",
            "   Device configuration / script) if this fleet's Copilot host",
            "   differs from baked. Overlay cannot turn ON a baked-off flag.",
            "",
            "4. SentinelOne: import enterprise/packaging/sentinelone/"
            "SwitchBay-exclusions.json after switchbay.exe is signed.",
            "",
            f"Host used: {extra.get('host', '?')}",
        ]
    else:
        lines += [
            "   Developer ID-sign the .app and dylibs, productsign the pkg,",
            "   notarize, staple — company pipeline.",
            "",
            "2. Jamf / MDM: deploy the notarized pkg. LaunchAgent is",
            "   /Library/LaunchAgents/com.switchbay.daemon.plist (runs as the",
            "   logged-in user). Safari stub is /Applications/Switch Bay.app.",
            "",
            "3. Overlay (optional): /Library/Application Support/SwitchBay/admin.json",
            "   — cannot turn ON a baked-off flag.",
            "",
            f"Unsigned pkg: {extra.get('pkg', '?')}",
        ]
    (out / "NEXT.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--payload", required=True, type=Path,
                   help="Unzipped CI tree, or the .zip / .tar.gz itself")
    p.add_argument("--out", type=Path, default=Path("dist/bake"))
    p.add_argument("--copilot-host", default="github.com",
                   help="github.com or your GitHub Enterprise host")
    p.add_argument("--sso-slug", default="",
                   help="EMU enterprise slug (optional)")
    p.add_argument("--allow-hf", action="store_true",
                   help="Bake Hugging Face downloads ON (overlay cannot enable later)")
    p.add_argument("--no-skills-npx", action="store_true",
                   help="Bake npx/uvx skills add OFF")
    p.add_argument("--vendor-ce", type=Path, default=None,
                   help="Copy this curiosity-engine skill dir to layout/vendor/")
    args = p.parse_args(argv)

    out = args.out if args.out.is_absolute() else ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    payload_in = args.payload if args.payload.is_absolute() else Path.cwd() / args.payload
    payload = unpack_if_needed(payload_in, out / "_unpack")
    stamp_baked(
        payload,
        copilot_host=args.copilot_host,
        sso_slug=args.sso_slug or None,
        allow_hf=True if args.allow_hf else None,
        skills_npx=False if args.no_skills_npx else None,
    )
    if args.vendor_ce:
        dest = payload / "vendor" / "curiosity-engine"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(args.vendor_ce, dest)

    kind = "windows" if sys.platform == "win32" else "macos"
    extra: dict[str, str] = {}
    if kind == "windows":
        layout = out / "layout"
        extra.update(layout_windows(payload, layout))
        for name in ("install.ps1", "uninstall.ps1"):
            shutil.copy2(PACK / "windows" / name, out / name)
        shutil.copy2(PACK / "intune" / "detection.ps1", out / "detection.ps1")
    else:
        if platform.machine().lower() not in ("arm64", "aarch64"):
            print("warning: this kit is darwin-arm64; Intel Macs are not a SKU",
                  file=sys.stderr)
        pkg = bake_macos_pkg(payload, out)
        extra["pkg"] = str(pkg)

    (out / "admin.overlay.example.json").write_text(
        json.dumps(overlay_example(
            copilot_host=args.copilot_host,
            allow_hf=bool(args.allow_hf),
        ), indent=2) + "\n",
        encoding="utf-8",
    )
    write_next(out, kind=kind, extra=extra)
    print(f"baked {out}")
    print(f"next:  {out / 'NEXT.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
