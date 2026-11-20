"""Pinned local browser for Switch Bay agents.

Microsoft's Playwright CLI (``@playwright/cli@0.1.23``, released
31 Oct 2026) plus the skill it ships. The CLI depends on Playwright
``1.65.0-alpha-2026-10-30``, which downloads its own browser builds:

  chromium 1252, firefox 1569, webkit 2386, ffmpeg 1013

Switch Bay's UI tests pin ``@playwright/test`` 1.64.1, whose browsers
are chromium 1248, firefox 1555, webkit 2370, and the same ffmpeg
1013. Playwright stores each revision in its own cache directory, so
the agent browsers and the test browsers sit side by side. ffmpeg
1013 is one shared build.

Install is on by default. ``service install --no-browser`` skips it.
Enterprise ``browser_use`` skips it and, at runtime, hides the skill
and the ``playwright_cli`` tool. A user can turn the same switch off
in Settings; that does not uninstall the files.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

CLI_VERSION = "0.1.23"
CLI_SPEC = f"@playwright/cli@{CLI_VERSION}"
# playwright dependency of that exact CLI release. Not a float.
CLI_PLAYWRIGHT = "1.65.0-alpha-2026-10-30"
# Browser revisions CLI_PLAYWRIGHT installs (browsers.json installByDefault).
CLI_BROWSER_REVISIONS = {
    "chromium": "1252",
    "chromium-headless-shell": "1252",
    "firefox": "1569",
    "webkit": "2386",
    "ffmpeg": "1013",
}
# @playwright/test 1.64.1 / playwright-core 1.64.1. Different revisions,
# same cache root, except ffmpeg which is the same build.
E2E_BROWSER_REVISIONS = {
    "chromium": "1248",
    "chromium-headless-shell": "1248",
    "firefox": "1555",
    "webkit": "2370",
    "ffmpeg": "1013",
}

SKILL_NAME = "playwright-cli"
TOOL_NAME = "playwright_cli"
SESSION = "switchbay"

NODE_MIN_MAJOR = 20
NPM_TIMEOUT_S = 300
SKILL_TIMEOUT_S = 120
BROWSER_TIMEOUT_S = 600
CALL_TIMEOUT_S = 120
MAX_ARGS = 64
MAX_ARG_CHARS = 4000
MAX_STDOUT_CHARS = 24000
MAX_STDERR_CHARS = 8000

_CLI_BASENAMES = frozenset({
    "playwright-cli",
    "playwright-cli.cmd",
    "playwright-cli.exe",
})
_NPX_BASENAMES = frozenset({
    "npx", "npx.cmd", "npx.exe",
    "npm", "npm.cmd", "npm.exe",
})

Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass
class InstallResult:
    status: str  # installed | skipped | failed
    reason: str = ""
    commands: list[list[str]] = field(default_factory=list)


def _home() -> Path:
    return Path.home()


def install_prefix() -> Path:
    return _home() / ".local" / "share" / "switchbay" / "playwright-cli"


def _cli_filename() -> str:
    return "playwright-cli.cmd" if os.name == "nt" else "playwright-cli"


def cli_path(prefix: Path | None = None) -> Path:
    root = prefix if prefix is not None else install_prefix()
    return root / "node_modules" / ".bin" / _cli_filename()


def bin_link() -> Path:
    return _home() / ".local" / "bin" / _cli_filename()


def cli_binary() -> str | None:
    """Absolute path of the pinned CLI, or None when it is not installed."""
    for cand in (cli_path(), bin_link()):
        try:
            if cand.is_file():
                return str(cand)
        except OSError:
            continue
    return None


def installed_version(prefix: Path | None = None) -> str | None:
    pkg = (prefix if prefix is not None else install_prefix()) / "node_modules" / "@playwright" / "cli" / "package.json"
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    ver = data.get("version") if isinstance(data, dict) else None
    return str(ver) if isinstance(ver, str) and ver else None


def browser_use_enabled() -> bool:
    """Admin flag and the Settings toggle. Both have to be on."""
    if block_reason() is not None:
        return False
    return True


def block_reason() -> str | None:
    """Why agents must not see the skill or the tool, or None."""
    from . import admin_policy, llm_config
    if not admin_policy.feature_enabled("browser_use"):
        return admin_policy.feature_error("browser_use")
    if not llm_config.get_browser_use():
        return "local browser is off in Settings"
    return None


def is_browser_skill(name: str, path: str = "") -> bool:
    if (name or "").strip() == SKILL_NAME:
        return True
    if path:
        try:
            return Path(path).parent.name == SKILL_NAME
        except OSError:
            return False
    return False


def shell_block_reason(argv: list[str]) -> str | None:
    """Refuse a shell argv that would drive a browser outside the pin.

    ``npx`` / ``npm`` of ``@playwright/cli`` is always refused so a
    chat turn cannot fetch a newer release than ``CLI_VERSION``.
    The pinned binary is refused only when browser use is off.
    """
    if not argv:
        return None
    base = Path(str(argv[0])).name.lower()
    if base in _NPX_BASENAMES and any("@playwright/cli" in str(a) for a in argv[1:]):
        return (
            f"Switch Bay installs {CLI_SPEC}. "
            "Use the playwright_cli tool."
        )
    if base in _CLI_BASENAMES:
        return block_reason()
    return None


def shell_block_reason_from_command(command: str) -> str | None:
    text = (command or "").strip()
    if not text:
        return None
    try:
        argv = shlex.split(text, posix=(os.name != "nt"))
    except ValueError:
        return None
    return shell_block_reason(argv)


def skip_reason(*, skip: bool) -> str | None:
    """Why install should not run. User Settings do not skip install."""
    if skip:
        return "installer flag --no-browser"
    from . import admin_policy
    if not admin_policy.feature_enabled("browser_use"):
        return "admin policy browser_use=false"
    return None


def _node_major(node: str, runner: Runner) -> int | None:
    try:
        proc = runner(
            [node, "-p", "process.versions.node.split('.')[0]"],
            cwd=str(_home()),
            env=os.environ.copy(),
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    raw = (proc.stdout or "").strip()
    if raw.isdigit():
        return int(raw)
    return None


def can_install_system_deps() -> bool:
    """Linux system libraries need root. Never prompt for a password."""
    if not sys.platform.startswith("linux"):
        return False
    try:
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            return True
    except OSError:
        return False
    sudo = shutil.which("sudo")
    if not sudo:
        return False
    try:
        proc = subprocess.run(
            [sudo, "-n", "true"],
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _default_runner(
    argv: list[str],
    *,
    cwd: str,
    env: Mapping[str, str],
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        env=dict(env),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _link_cli(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        if dest.is_symlink() and dest.resolve() == src.resolve():
            return
    except OSError:
        pass
    try:
        if dest.is_symlink() or dest.exists():
            dest.unlink()
    except OSError:
        pass
    try:
        dest.symlink_to(src)
        return
    except OSError:
        pass
    if os.name == "nt":
        dest.write_text(f'@echo off\r\n"{src}" %*\r\n', encoding="utf-8")
        return
    dest.write_text(
        "#!/bin/sh\n"
        f"exec {shlex.quote(str(src))} \"$@\"\n",
        encoding="utf-8",
    )
    dest.chmod(0o755)


def _cli_env() -> dict[str, str]:
    from . import runtime
    env = runtime.spawn_env()
    if not env.get("HOME"):
        env["HOME"] = str(_home())
    # The CLI shells out to `npm view … @latest` and prints an upgrade
    # notice. Keep the pin; do not advertise a newer release.
    env["NO_UPDATE_NOTIFIER"] = "1"
    for key in list(env):
        upper = key.upper()
        if (
            upper.endswith("_API_KEY")
            or upper.endswith("_TOKEN")
            or "SECRET" in upper
            or upper in {"GITHUB_TOKEN", "GH_TOKEN", "NPM_TOKEN"}
        ):
            env.pop(key, None)
    return env


def install(
    *,
    skip: bool = False,
    runner: Runner | None = None,
    with_deps: bool | None = None,
    node_major: int | None = None,
    npm_bin: str | None = None,
    node_bin: str | None = None,
) -> InstallResult:
    """Install the pinned CLI, its global agent skill, and its browsers.

    Non-fatal for the rest of service install: callers print ``status``
    and keep going. Network and npm run only when the skip reason is
    empty and Node is new enough.
    """
    reason = skip_reason(skip=skip)
    if reason:
        print(f"  playwright-cli: SKIPPED ({reason})")
        return InstallResult("skipped", reason)

    run = runner or _default_runner
    from . import runtime
    node = node_bin or runtime.resolve_node()
    major = node_major
    if major is None:
        if not node:
            msg = "Node.js 20 or newer is required (node was not found)"
            print(f"  playwright-cli: FAILED ({msg})")
            return InstallResult("failed", msg)
        major = _node_major(node, run)
    if major is None or major < NODE_MIN_MAJOR:
        found = f" (found {major})" if major is not None else ""
        msg = f"Node.js {NODE_MIN_MAJOR} or newer is required{found}"
        print(f"  playwright-cli: FAILED ({msg})")
        return InstallResult("failed", msg)

    npm = npm_bin or runtime.resolve_executable("npm")
    if not npm:
        msg = "npm was not found (it ships with Node.js)"
        print(f"  playwright-cli: FAILED ({msg})")
        return InstallResult("failed", msg)

    if with_deps is None:
        with_deps = can_install_system_deps()

    prefix = install_prefix()
    prefix.mkdir(parents=True, exist_ok=True)
    env = _cli_env()
    commands: list[list[str]] = []
    cwd = str(prefix)

    if installed_version(prefix) != CLI_VERSION:
        npm_cmd = [
            npm, "install",
            "--prefix", str(prefix),
            "--no-fund", "--no-audit", "--loglevel=error",
            CLI_SPEC,
        ]
        commands.append(npm_cmd)
        try:
            proc = run(npm_cmd, cwd=cwd, env=env, timeout=NPM_TIMEOUT_S)
        except (OSError, subprocess.TimeoutExpired) as e:
            msg = f"npm install failed ({e})"
            print(f"  playwright-cli: FAILED ({msg})")
            return InstallResult("failed", msg, commands)
        if proc.returncode != 0:
            detail = ((proc.stderr or proc.stdout) or "").strip()[:300]
            msg = f"npm install exited {proc.returncode}" + (f": {detail}" if detail else "")
            print(f"  playwright-cli: FAILED ({msg})")
            return InstallResult("failed", msg, commands)
        got = installed_version(prefix)
        if got != CLI_VERSION:
            msg = f"installed {got or 'nothing'}, expected {CLI_SPEC}"
            print(f"  playwright-cli: FAILED ({msg})")
            return InstallResult("failed", msg, commands)

    binary = cli_path(prefix)
    if not binary.is_file():
        msg = f"missing {binary}"
        print(f"  playwright-cli: FAILED ({msg})")
        return InstallResult("failed", msg, commands)
    _link_cli(binary, bin_link())

    skill_cmd = [str(binary), "install", "--skills=agents", "-g"]
    browser_cmd = [str(binary), "install-browser"]
    if with_deps:
        browser_cmd.append("--with-deps")
    for cmd, timeout in (
        (skill_cmd, SKILL_TIMEOUT_S),
        (browser_cmd, BROWSER_TIMEOUT_S),
    ):
        commands.append(cmd)
        try:
            proc = run(cmd, cwd=cwd, env=env, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            msg = f"{Path(cmd[0]).name} {' '.join(cmd[1:])} failed ({e})"
            print(f"  playwright-cli: FAILED ({msg})")
            return InstallResult("failed", msg, commands)
        if proc.returncode != 0:
            detail = ((proc.stderr or proc.stdout) or "").strip()[:300]
            msg = (
                f"{' '.join(cmd[1:])} exited {proc.returncode}"
                + (f": {detail}" if detail else "")
            )
            print(f"  playwright-cli: FAILED ({msg})")
            return InstallResult("failed", msg, commands)

    print(
        f"  playwright-cli {CLI_VERSION} installed "
        f"(playwright {CLI_PLAYWRIGHT}; "
        f"chromium {CLI_BROWSER_REVISIONS['chromium']}). "
        f"UI tests keep Playwright 1.64.1 "
        f"(chromium {E2E_BROWSER_REVISIONS['chromium']}) "
        "beside it in the browser cache."
    )
    if sys.platform.startswith("linux") and not with_deps:
        print(
            "  Linux system libraries were not installed. "
            "If Chromium does not start, run: "
            "playwright-cli install-browser --with-deps"
        )
    return InstallResult("installed", "", commands)


def _with_session(argv: list[str]) -> list[str]:
    for arg in argv:
        if arg in ("-s", "--session") or arg.startswith(("-s=", "--session=")):
            return list(argv)
    return [f"-s={SESSION}", *argv]


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n…[clipped]"


def run(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Run the pinned CLI. ``argv`` is the arguments after the binary."""
    denied = block_reason()
    if denied:
        return {"ok": False, "error": denied}
    raw = payload.get("argv")
    if isinstance(raw, str):
        try:
            argv = shlex.split(raw, posix=(os.name != "nt"))
        except ValueError as e:
            return {"ok": False, "error": f"bad argv: {e}"}
    elif isinstance(raw, list):
        if not all(isinstance(a, str) for a in raw):
            return {"ok": False, "error": "argv must be a list of strings"}
        argv = [str(a) for a in raw]
    else:
        return {"ok": False, "error": "argv is required"}
    if argv and Path(argv[0]).name.lower() in _CLI_BASENAMES:
        argv = argv[1:]
    if not argv:
        return {"ok": False, "error": "argv is required"}
    if len(argv) > MAX_ARGS or any(len(a) > MAX_ARG_CHARS for a in argv):
        return {"ok": False, "error": "argv is too large"}
    binary = cli_binary()
    if not binary:
        return {
            "ok": False,
            "error": (
                f"{CLI_SPEC} is not installed. "
                "Re-run the Switch Bay install without --no-browser."
            ),
        }
    full = [binary, *_with_session(argv)]
    try:
        proc = subprocess.run(
            full,
            cwd=str(workspace),
            env=_cli_env(),
            capture_output=True,
            text=True,
            timeout=CALL_TIMEOUT_S,
            start_new_session=(os.name != "nt"),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"playwright-cli timed out after {CALL_TIMEOUT_S}s"}
    except OSError as e:
        return {"ok": False, "error": str(e)}
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout": _clip(proc.stdout or "", MAX_STDOUT_CHARS),
        "stderr": _clip(proc.stderr or "", MAX_STDERR_CHARS),
        "session": SESSION,
    }


def status_view() -> dict[str, Any]:
    from . import admin_policy, llm_config
    binary = cli_binary()
    return {
        "admin_allowed": admin_policy.feature_enabled("browser_use"),
        "user_enabled": llm_config.get_browser_use(),
        "enabled": browser_use_enabled(),
        "installed": binary is not None,
        "binary": binary,
        "version": CLI_VERSION,
        "playwright": CLI_PLAYWRIGHT,
    }
