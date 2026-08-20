"""Install switchbay's daemon as an always-on per-user OS service so
the installed PWA's dock/Start icon "just works" (starts on login,
restarts on crash). One common surface — `install / uninstall / start /
stop / restart / status` — with a thin per-OS implementation:

  * macOS    → launchd user agent (~/Library/LaunchAgents/<label>.plist)
  * Linux    → systemd --user unit (~/.config/systemd/user/<name>.service)
  * Windows  → Scheduled Task (ONLOGON) running a generated launcher

Design mirrors the rest of switchbay: the daemon is the *same* Python
process everywhere; only the supervisor wiring differs. All three invoke
the repo's venv interpreter directly (`<repo>/.venv/bin/python` —
`Scripts\\python.exe` on Windows) with `PYTHONPATH=<repo>/src`, not
`uv run` (which re-resolves/locks and behaved erratically under launchd).

macOS is the tested path; the Linux + Windows implementations are
correct-by-construction but exercise on their own platform before
trusting them.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

LABEL = "com.switchbay.daemon"   # macOS launchd label / Linux unit stem base
UNIT = "switchbay"               # systemd unit name + Windows task name

# First-party skills auto-installed at `service install` into
# ~/.agents/skills (which skillkit discovers; Claude Code may also
# symlink into ~/.claude/skills). Distinct from third-party
# packs, which stay opt-in. Installed via the `skills` CLI over npx.
BUNDLED_SKILLS = ("benjsmith/curiosity-engine", "benjsmith/curiosity-merge")


def _ensure_uv() -> None:
    """Make sure `uv` is available — switchbay installs pack extras with
    `uv pip install` (uv-created venvs have no pip). Best-effort: if uv
    isn't found, run the official installer; warn (don't fail) if that
    can't run."""
    from . import admin_policy
    if not admin_policy.feature_enabled("uv_python_install"):
        return
    if shutil.which("uv"):
        return
    for c in (Path.home() / ".local" / "bin" / "uv", Path("/opt/homebrew/bin/uv")):
        if c.is_file():
            return
    print("  uv not found — installing it (https://astral.sh/uv)…")
    try:
        subprocess.run(
            "curl -LsSf https://astral.sh/uv/install.sh | sh",
            shell=True, check=True, timeout=180,
        )
        print("  uv installed (~/.local/bin). You may need to reopen your shell.")
    except (subprocess.SubprocessError, OSError) as e:
        print(f"  uv auto-install failed ({e}). Install manually: "
              "https://docs.astral.sh/uv/getting-started/installation/")


def _install_bundled_skills() -> None:
    """Install our first-party skills into ~/.claude/skills via
    `npx skills add <ref>`. Best-effort + non-fatal: warns (doesn't
    fail the service install) if npx/network is unavailable."""
    from . import admin_policy
    if not admin_policy.feature_enabled("install_skills_npx"):
        print("  bundled skills: SKIPPED (admin policy install_skills_npx=false)")
        return
    npx = shutil.which("npx")
    if not npx:
        print("  bundled skills: SKIPPED (npx not found). Install Node, then:")
        for ref in BUNDLED_SKILLS:
            print(f"      npx skills add {ref}")
        return
    for ref in BUNDLED_SKILLS:
        try:
            r = subprocess.run(
                # -g = install USER-GLOBAL (~/.agents/skills + a
                # ~/.claude/skills symlink) regardless of cwd. Without it
                # the CLI installs into the nearest project's
                # .agents/skills (would pollute the workspace/repo).
                # -y after `add` is the skills CLI's non-interactive
                # flag — omit it and a headless install hangs on a
                # confirmation prompt (the new-Mac CE failure).
                [npx, "-y", "skills", "add", "-g", "-y", ref],
                capture_output=True, text=True, timeout=180,
            )
            if r.returncode == 0:
                print(f"  bundled skill installed: {ref}")
            else:
                print(f"  bundled skill {ref}: rc={r.returncode} "
                      f"{(r.stderr or r.stdout).strip()[:160]}")
        except (subprocess.TimeoutExpired, OSError) as e:
            print(f"  bundled skill {ref}: failed ({e})")


def _repo_root() -> Path:
    # src/switchbay/service.py → repo root is parents[2].
    return Path(__file__).resolve().parents[2]


def _venv_python(repo: Path) -> Path:
    if sys.platform == "win32":
        return repo / ".venv" / "Scripts" / "python.exe"
    return repo / ".venv" / "bin" / "python"


def _stamped_profile(repo: Path) -> str | None:
    """Profile baked into the service environment.

    Honour ``SWITCHBAY_PROFILE`` in the installer environment, else a
    ``SWITCHBAY_PROFILE`` file at the payload/repo root (enterprise
    payloads write this). Open/default omits the var so git checkouts
    stay on ``DEFAULT_PROFILE``.
    """
    raw = (os.environ.get("SWITCHBAY_PROFILE") or "").strip().lower()
    if raw in ("open", "enterprise"):
        return raw
    marker = repo / "SWITCHBAY_PROFILE"
    try:
        if marker.is_file():
            lines = marker.read_text(encoding="utf-8").strip().splitlines()
            val = (lines[0] if lines else "").strip().lower()
            if val in ("open", "enterprise"):
                return val
    except OSError:
        pass
    return None


def _xml_text(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _service_environment(repo: Path) -> dict[str, str]:
    env = {
        "PYTHONPATH": str(repo / "src"),
        "PYTHONUNBUFFERED": "1",
        "SWITCHBAY_SERVICE": "1",
    }
    profile = _stamped_profile(repo)
    if profile:
        env["SWITCHBAY_PROFILE"] = profile
    return env


def _pid_path() -> Path:
    from . import statedir
    return statedir.daemon_pid_path()


def write_daemon_pid() -> None:
    p = _pid_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(os.getpid()), encoding="utf-8")


def clear_daemon_pid() -> None:
    try:
        _pid_path().unlink()
    except OSError:
        pass


def read_daemon_pid() -> int | None:
    try:
        raw = _pid_path().read_text(encoding="utf-8").strip()
        pid = int(raw)
    except (OSError, ValueError):
        return None
    return pid if pid > 0 else None


def stop_daemon_pid() -> None:
    """Stop the serve process recorded in the PID file.

    Windows uses ``taskkill /PID /T`` so children (llama-server) die
    too. Never ``/IM python.exe``.
    """
    pid = read_daemon_pid()
    if pid is None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
        )
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    clear_daemon_pid()


def _require_built_frontend(repo: Path) -> None:
    if not (repo / "frontend" / "dist" / "index.html").is_file():
        raise SystemExit(
            "frontend not built — run `make build-frontend` "
            "(or `pnpm --dir frontend run build`) first."
        )


# ── macOS (launchd) ──────────────────────────────────────────────────


def _mac_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _mac_domain() -> str:
    return f"gui/{os.getuid()}"


def _mac_write_plist(repo: Path) -> Path:
    py = _venv_python(repo)
    if not py.exists():
        raise SystemExit(f"venv python not found at {py} — run `make sync` first.")
    log = Path.home() / "Library" / "Logs" / "switchbay-daemon.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    p = _mac_plist_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    env = _service_environment(repo)
    env["PATH"] = f"/usr/bin:/bin:/usr/sbin:/sbin:{Path.home() / '.local' / 'bin'}"
    env_xml = "\n".join(
        f"    <key>{_xml_text(k)}</key><string>{_xml_text(v)}</string>"
        for k, v in env.items()
    )
    p.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{_xml_text(str(py))}</string>
    <string>-m</string><string>switchbay</string>
    <string>serve</string><string>--workspace</string><string>{_xml_text(str(repo))}</string>
  </array>
  <key>WorkingDirectory</key><string>{_xml_text(str(repo))}</string>
  <key>EnvironmentVariables</key>
  <dict>
{env_xml}
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>StandardOutPath</key><string>{_xml_text(str(log))}</string>
  <key>StandardErrorPath</key><string>{_xml_text(str(log))}</string>
  <key>ProcessType</key><string>Interactive</string>
</dict>
</plist>
""",
        encoding="utf-8",
    )
    return p


def _mac(action: str, repo: Path) -> int:
    dom, label = _mac_domain(), LABEL
    if action == "install":
        _require_built_frontend(repo)
        _mac_write_plist(repo)
        # Bootout any existing agent and WAIT for it to actually leave the
        # domain — bootstrap fails (exit 5) if the label is still loaded,
        # and bootout is asynchronous.
        subprocess.run(["launchctl", "bootout", f"{dom}/{label}"], capture_output=True)
        for _ in range(40):
            still = subprocess.run(
                ["launchctl", "print", f"{dom}/{label}"], capture_output=True
            )
            if still.returncode != 0:  # not found → fully booted out
                break
            time.sleep(0.25)
        subprocess.run(["launchctl", "bootstrap", dom, str(_mac_plist_path())], check=True)
        subprocess.run(["launchctl", "kickstart", "-k", f"{dom}/{label}"], capture_output=True)
        print("installed + started. Open http://127.0.0.1:8765 and use your "
              "browser's Install / Add to Dock for the app icon.")
    elif action == "uninstall":
        subprocess.run(["launchctl", "bootout", f"{dom}/{label}"], capture_output=True)
        _mac_plist_path().unlink(missing_ok=True)
        print("uninstalled.")
    elif action == "stop":
        # SIGTERM → clean exit 0 → KeepAlive(SuccessfulExit:false) won't restart.
        subprocess.run(["launchctl", "kill", "TERM", f"{dom}/{label}"], capture_output=True)
        print("stopped (restarts on next login, or `service start`).")
    elif action == "start":
        # kickstart fails (exit 113) if the agent isn't loaded — e.g.
        # after a manual bootout or a never-install. Bootstrap first
        # when print says the label is missing.
        loaded = subprocess.run(
            ["launchctl", "print", f"{dom}/{label}"], capture_output=True,
        )
        if loaded.returncode != 0:
            plist = _mac_plist_path()
            if not plist.is_file():
                raise SystemExit(
                    f"launchd agent not installed ({plist} missing) — "
                    "run `make install-service` first."
                )
            subprocess.run(
                ["launchctl", "bootstrap", dom, str(plist)], check=True,
            )
        subprocess.run(
            ["launchctl", "kickstart", "-k", f"{dom}/{label}"], check=True,
        )
        print("started.")
    elif action == "restart":
        # Same resilience as start: kickstart -k alone fails when the
        # label isn't in the domain (common when a one-shot nohup
        # daemon was used during a prior session and the agent was
        # never re-bootstrapped). Bootstrap if needed, then kill-start.
        loaded = subprocess.run(
            ["launchctl", "print", f"{dom}/{label}"], capture_output=True,
        )
        if loaded.returncode != 0:
            plist = _mac_plist_path()
            if not plist.is_file():
                raise SystemExit(
                    f"launchd agent not installed ({plist} missing) — "
                    "run `make install-service` first."
                )
            subprocess.run(
                ["launchctl", "bootstrap", dom, str(plist)], check=True,
            )
        r = subprocess.run(
            ["launchctl", "kickstart", "-k", f"{dom}/{label}"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            raise SystemExit(
                f"launchctl kickstart failed (rc={r.returncode}): "
                f"{(r.stderr or r.stdout or '').strip()[:200]}"
            )
        print("restarted.")
    elif action == "status":
        subprocess.run(["launchctl", "print", f"{dom}/{label}"])
    return 0


# ── Linux (systemd --user) ───────────────────────────────────────────


def _linux_unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / f"{UNIT}.service"


def _systemctl(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *args], check=check)


def _linux(action: str, repo: Path) -> int:
    py = _venv_python(repo)
    if action == "install":
        if not py.exists():
            raise SystemExit(f"venv python not found at {py} — run `make sync` first.")
        _require_built_frontend(repo)
        u = _linux_unit_path()
        u.parent.mkdir(parents=True, exist_ok=True)
        env_lines = "\n".join(
            f"Environment={k}={v}" for k, v in _service_environment(repo).items()
        )
        u.write_text(
            f"""[Unit]
Description=switchbay daemon
After=default.target

[Service]
Type=simple
WorkingDirectory={repo}
{env_lines}
ExecStart={py} -m switchbay serve --workspace {repo}
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
""",
            encoding="utf-8",
        )
        _systemctl("daemon-reload")
        _systemctl("enable", "--now", UNIT, check=True)
        # So it survives logout / runs at boot without an active session.
        subprocess.run(["loginctl", "enable-linger", os.environ.get("USER", "")],
                       capture_output=True)
        print("installed + started. (loginctl enable-linger set so it runs "
              "without an active login session.) Open http://127.0.0.1:8765.")
    elif action == "uninstall":
        _systemctl("disable", "--now", UNIT)
        _linux_unit_path().unlink(missing_ok=True)
        _systemctl("daemon-reload")
        print("uninstalled.")
    elif action == "stop":
        _systemctl("stop", UNIT)
        print("stopped.")
    elif action == "start":
        _systemctl("start", UNIT, check=True)
        print("started.")
    elif action == "restart":
        _systemctl("restart", UNIT, check=True)
        print("restarted.")
    elif action == "status":
        _systemctl("status", UNIT)
    return 0


# ── Windows (Scheduled Task, ONLOGON) ────────────────────────────────


def _win_launcher_path(repo: Path) -> Path:
    return repo / ".venv" / "switchbay-daemon.cmd"


def _win(action: str, repo: Path) -> int:
    py = _venv_python(repo)
    if action == "install":
        if not py.exists():
            raise SystemExit(rf"venv python not found at {py} — run `uv sync` first.")
        _require_built_frontend(repo)
        # schtasks can't set env/cwd, so generate a launcher .cmd that does.
        launcher = _win_launcher_path(repo)
        env_lines = "".join(
            f'set "{k}={v}"\r\n' for k, v in _service_environment(repo).items()
        )
        launcher.write_text(
            "@echo off\r\n"
            f'cd /d "{repo}"\r\n'
            + env_lines
            + f'"{py}" -m switchbay serve --workspace "{repo}"\r\n',
            encoding="utf-8",
        )
        subprocess.run(
            ["schtasks", "/Create", "/TN", UNIT, "/TR", f'"{launcher}"',
             "/SC", "ONLOGON", "/RL", "LIMITED", "/F"],
            check=True,
        )
        subprocess.run(["schtasks", "/Run", "/TN", UNIT], capture_output=True)
        print("installed + started (Scheduled Task, runs at logon). "
              "Open http://127.0.0.1:8765 and Install the app from your browser.")
    elif action == "uninstall":
        subprocess.run(["schtasks", "/End", "/TN", UNIT], capture_output=True)
        subprocess.run(["schtasks", "/Delete", "/TN", UNIT, "/F"], capture_output=True)
        _win_launcher_path(repo).unlink(missing_ok=True)
        print("uninstalled.")
    elif action in ("stop",):
        subprocess.run(["schtasks", "/End", "/TN", UNIT], capture_output=True)
        stop_daemon_pid()
        print("stopped.")
    elif action in ("start", "restart"):
        subprocess.run(["schtasks", "/End", "/TN", UNIT], capture_output=True)
        subprocess.run(["schtasks", "/Run", "/TN", UNIT], check=True)
        print(f"{action}ed.")
    elif action == "status":
        subprocess.run(["schtasks", "/Query", "/TN", UNIT, "/V", "/FO", "LIST"])
    return 0


# ── Dispatch ─────────────────────────────────────────────────────────


ACTIONS = ("install", "uninstall", "start", "stop", "restart", "status")


def run(action: str) -> int:
    """Entry point for `python -m switchbay service <action>`."""
    if action not in ACTIONS:
        print(f"unknown service action: {action!r}; expected one of {', '.join(ACTIONS)}")
        return 2
    repo = _repo_root()
    if sys.platform == "darwin":
        impl = _mac
    elif sys.platform.startswith("linux"):
        impl = _linux
    elif sys.platform == "win32":
        impl = _win
    else:
        print(f"unsupported platform for service management: {sys.platform}")
        return 2
    if action == "install":
        _ensure_uv()  # pack extras install via `uv pip install`
    rc = impl(action, repo)
    # After a successful install, bundle our first-party skills.
    if action == "install" and rc == 0:
        _install_bundled_skills()
    return rc


# ── In-app restart support ───────────────────────────────────────────
# The daemon exposes an in-UI "Restart" affordance (Settings button +
# /start slash). It runs `make restart` — but only when THIS process is
# the installed always-on service; under `make dev-daemon` a restart
# would kickstart a *second* daemon onto the same port.


def is_installed() -> bool:
    """Is the always-on service registered for this user? (Cheap file /
    task check — does not prove it's currently running.)"""
    try:
        if sys.platform == "darwin":
            return _mac_plist_path().is_file()
        if sys.platform.startswith("linux"):
            return _linux_unit_path().is_file()
        if sys.platform == "win32":
            r = subprocess.run(
                ["schtasks", "/Query", "/TN", UNIT],
                capture_output=True, text=True,
            )
            return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False
    return False


def is_managed() -> bool:
    """Best-effort: is THIS running process the installed service (rather
    than a foreground `make dev-daemon`)? A restart must act only when
    true, or a service restart spawns a rival daemon on the same port.

    macOS: launchd sets `XPC_SERVICE_NAME` to our label and reparents us
    to launchd (ppid 1). Linux systemd --user likewise reparents to the
    manager (ppid 1). Windows / all: ``SWITCHBAY_SERVICE=1`` is stamped
    into the installed launcher. We require the service to also be
    installed."""
    if not is_installed():
        return False
    flag = (os.environ.get("SWITCHBAY_SERVICE") or "").strip().lower()
    if flag in ("1", "true", "yes"):
        return True
    if sys.platform == "darwin" and os.environ.get("XPC_SERVICE_NAME") == LABEL:
        return True
    try:
        return os.name == "posix" and os.getppid() == 1
    except Exception:  # noqa: BLE001
        return False


def spawn_restart() -> None:
    """Fire ``python -m switchbay service restart`` detached so it
    survives this process's death. No Make (Windows packaging has none).
    Caller must have checked `is_managed()`."""
    repo = _repo_root()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo / "src")
    argv = [sys.executable, "-m", "switchbay", "service", "restart"]
    kwargs: dict = {
        "cwd": str(repo),
        "env": env,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        flags = 0
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        if flags:
            kwargs["creationflags"] = flags
        subprocess.Popen(argv, **kwargs)
        return
    subprocess.Popen(argv, start_new_session=True, **kwargs)
