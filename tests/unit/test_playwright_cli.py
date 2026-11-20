"""Local Playwright CLI: install skip, enterprise off, skill wired when on."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from switchbay import (
    admin_policy,
    llm_config,
    permissions,
    playwright_cli,
    skillkit,
    tools,
)
from switchbay.agents import rail_default
from switchbay.mcp_server import _list_tools


def _write_skill(root: Path) -> None:
    dest = root / "playwright-cli"
    dest.mkdir(parents=True)
    (dest / "SKILL.md").write_text(
        "---\nname: playwright-cli\ndescription: Browse pages.\n---\n"
        "# Browser\n\nOpen a page, then snapshot.\n",
        encoding="utf-8",
    )


def _isolate_skills(monkeypatch, root: Path) -> None:
    monkeypatch.setattr(skillkit, "_global_skill_roots", lambda: [root])


def _recording_runner(calls: list):
    def runner(argv, *, cwd, env, timeout):
        calls.append((list(argv), timeout, dict(env)))
        if len(argv) >= 2 and argv[1] == "install" and "--prefix" in argv:
            prefix = Path(argv[argv.index("--prefix") + 1])
            pkg = prefix / "node_modules" / "@playwright" / "cli"
            pkg.mkdir(parents=True)
            (pkg / "package.json").write_text(
                json.dumps({"version": playwright_cli.CLI_VERSION}),
                encoding="utf-8",
            )
            exe = playwright_cli.cli_path(prefix)
            exe.parent.mkdir(parents=True, exist_ok=True)
            if exe.suffix.lower() == ".cmd":
                exe.write_text("@echo off\r\n", encoding="utf-8")
            else:
                exe.write_text("#!/bin/sh\n", encoding="utf-8")
                exe.chmod(0o755)
        return subprocess.CompletedProcess(argv, 0, "", "")

    return runner


def test_windows_cli_shim_is_cmd(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(playwright_cli.os, "name", "nt")
    monkeypatch.setattr(playwright_cli, "_home", lambda: tmp_path)
    assert playwright_cli.cli_path(tmp_path).name == "playwright-cli.cmd"
    assert playwright_cli.bin_link().name == "playwright-cli.cmd"


def test_browser_revisions_do_not_replace_e2e_browsers():
    assert playwright_cli.CLI_VERSION == "0.1.23"
    assert playwright_cli.CLI_PLAYWRIGHT == "1.65.0-alpha-2026-10-30"
    cli = playwright_cli.CLI_BROWSER_REVISIONS
    e2e = playwright_cli.E2E_BROWSER_REVISIONS
    assert cli["chromium"] != e2e["chromium"]
    assert cli["firefox"] != e2e["firefox"]
    assert cli["webkit"] != e2e["webkit"]
    # Same ffmpeg revision: one shared build, not a second copy.
    assert cli["ffmpeg"] == e2e["ffmpeg"] == "1013"


def test_install_skip_flag_does_not_run(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("installer ran")

    monkeypatch.setattr(playwright_cli, "_default_runner", boom)
    result = playwright_cli.install(skip=True, runner=boom)
    assert result.status == "skipped"
    assert result.reason == "installer flag --no-browser"
    assert result.commands == []


def test_enterprise_skips_install_and_hides_skill_and_tool(
    tmp_path: Path, monkeypatch,
):
    monkeypatch.setenv("SWITCHBAY_PROFILE", "enterprise")
    admin_policy.reset_cache()
    root = tmp_path / "skills"
    _write_skill(root)
    _isolate_skills(monkeypatch, root)

    def boom(*_a, **_k):
        raise AssertionError("installer ran")

    result = playwright_cli.install(
        runner=boom, node_major=20, npm_bin="npm",
    )
    assert result.status == "skipped"
    assert result.reason == "admin policy browser_use=false"
    assert playwright_cli.browser_use_enabled() is False
    assert "playwright-cli" not in {
        sk.name for sk in skillkit.list_skills(tmp_path)
    }
    names = {
        spec["name"] for spec in rail_default.tools_for_provider(local=False)
    }
    assert "playwright_cli" not in names
    listed = {
        t["name"] for t in _list_tools(["playwright_cli", "search_wiki"])["tools"]
    }
    assert listed == {"search_wiki"}
    denied = tools.execute(
        "playwright_cli", tmp_path, {"argv": ["snapshot"]},
    )
    assert denied["ok"] is False
    assert "browser_use" in denied["error"]
    shell = tools.execute(
        "run_command", tmp_path, {"argv": ["playwright-cli", "open", "https://example.com"]},
    )
    assert shell["ok"] is False
    assert permissions.hard_deny_reason(
        "Bash", {"command": "playwright-cli snapshot"},
    )
    admin_policy.reset_cache()


def test_admin_can_turn_browser_use_back_on(tmp_path: Path, monkeypatch):
    policy = tmp_path / "admin.json"
    policy.write_text(json.dumps({
        "profile": "enterprise",
        "features": {"browser_use": True},
    }), encoding="utf-8")
    monkeypatch.setenv("SWITCHBAY_PROFILE", "enterprise")
    monkeypatch.setenv("SWITCHBAY_ADMIN_POLICY", str(policy))
    admin_policy.reset_cache()
    assert admin_policy.feature_enabled("browser_use") is True
    assert playwright_cli.skip_reason(skip=False) is None
    admin_policy.reset_cache()


def test_install_pins_cli_skill_and_browsers(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(playwright_cli, "_home", lambda: home)
    calls: list = []
    result = playwright_cli.install(
        runner=_recording_runner(calls),
        with_deps=False,
        node_major=20,
        npm_bin="npm",
    )
    assert result.status == "installed", result.reason
    npm_argv, npm_timeout, npm_env = calls[0]
    assert npm_env.get("NO_UPDATE_NOTIFIER") == "1"
    assert npm_argv[0] == "npm"
    assert npm_argv[-1] == "@playwright/cli@0.1.23"
    assert "@latest" not in npm_argv
    assert npm_timeout == playwright_cli.NPM_TIMEOUT_S
    skill_argv, _skill_timeout, _skill_env = calls[1]
    assert skill_argv[1:] == ["install", "--skills=agents", "-g"]
    browser_argv, browser_timeout, _browser_env = calls[2]
    assert browser_argv[1:] == ["install-browser"]
    assert browser_timeout == playwright_cli.BROWSER_TIMEOUT_S
    assert playwright_cli.bin_link().is_file()
    assert playwright_cli.installed_version() == "0.1.23"

    calls.clear()
    again = playwright_cli.install(
        runner=_recording_runner(calls),
        with_deps=True,
        node_major=20,
        npm_bin="npm",
    )
    assert again.status == "installed", again.reason
    assert all("--prefix" not in argv for argv, _timeout, _env in calls)
    assert calls[-1][0][1:] == ["install-browser", "--with-deps"]


def test_old_node_fails_before_npm():
    def boom(*_a, **_k):
        raise AssertionError("npm ran")

    result = playwright_cli.install(
        runner=boom, node_major=18, npm_bin="npm", with_deps=False,
    )
    assert result.status == "failed"
    assert "20" in result.reason
    assert result.commands == []


def test_user_setting_does_not_skip_install():
    llm_config.set_browser_use(False)
    assert playwright_cli.skip_reason(skip=False) is None
    llm_config.set_browser_use(True)


def test_skill_and_tool_wired_when_enabled(tmp_path: Path, monkeypatch):
    root = tmp_path / "skills"
    _write_skill(root)
    _isolate_skills(monkeypatch, root)
    llm_config.set_browser_use(True)
    admin_policy.reset_cache()
    found = skillkit.get_skill(tmp_path, "playwright-cli")
    assert found is not None
    assert "Open a page" in found.body
    names = {
        spec["name"] for spec in rail_default.tools_for_provider(local=False)
    }
    assert "playwright_cli" in names
    spec = next(
        s for s in rail_default.tools_for_provider(local=False)
        if s["name"] == "playwright_cli"
    )
    assert "0.1.23" in spec["description"]
    listed = {
        t["name"] for t in _list_tools(["playwright_cli"])["tools"]
    }
    assert listed == {"playwright_cli"}

    seen: dict = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["cwd"] = kwargs.get("cwd")
        return subprocess.CompletedProcess(
            argv, 0, stdout="Page URL: https://example.com\n", stderr="",
        )

    monkeypatch.setattr(playwright_cli.subprocess, "run", fake_run)
    monkeypatch.setattr(playwright_cli, "cli_binary", lambda: "/opt/pw/playwright-cli")
    out = tools.execute(
        "playwright_cli", tmp_path,
        {"argv": ["open", "https://example.com"]},
    )
    assert out["ok"] is True
    assert seen["argv"] == [
        "/opt/pw/playwright-cli", "-s=switchbay", "open", "https://example.com",
    ]
    assert seen["cwd"] == str(tmp_path)
    assert "example.com" in out["stdout"]

    tools.execute(
        "playwright_cli", tmp_path,
        {"argv": ["playwright-cli", "-s=other", "snapshot"]},
    )
    assert seen["argv"][1:] == ["-s=other", "snapshot"]


def test_user_setting_hides_skill_and_tool(tmp_path: Path, monkeypatch):
    root = tmp_path / "skills"
    _write_skill(root)
    _isolate_skills(monkeypatch, root)
    llm_config.set_browser_use(False)

    def boom(*_a, **_k):
        raise AssertionError("browser ran")

    monkeypatch.setattr(playwright_cli.subprocess, "run", boom)
    assert skillkit.get_skill(tmp_path, "playwright-cli") is None
    names = {
        spec["name"] for spec in rail_default.tools_for_provider(local=False)
    }
    assert "playwright_cli" not in names
    listed = _list_tools(["playwright_cli", "list_skills"])["tools"]
    assert [t["name"] for t in listed] == ["list_skills"]
    out = tools.execute("playwright_cli", tmp_path, {"argv": ["snapshot"]})
    assert out["ok"] is False
    assert "Settings" in out["error"]
    blocked = tools.execute(
        "run_command", tmp_path,
        {"argv": ["npx", "-y", "@playwright/cli@0.1.25", "--help"]},
    )
    assert blocked["ok"] is False
    assert "0.1.23" in blocked["error"]
    llm_config.set_browser_use(True)


def test_service_install_forwards_skip(tmp_path, monkeypatch, capsys):
    from switchbay import service

    monkeypatch.setattr(service, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(service.sys, "platform", "linux")
    monkeypatch.setattr(service, "_linux", lambda action, repo: 0)
    monkeypatch.setattr(service, "_ensure_uv", lambda: None)
    monkeypatch.setattr(service, "_install_bundled_skills", lambda: None)
    assert service.run("install", skip_browser=True) == 0
    out = capsys.readouterr().out
    assert "playwright-cli: SKIPPED (installer flag --no-browser)" in out


def test_settings_toggle_and_enterprise_lock(monkeypatch):
    import asyncio

    from switchbay import daemon

    class Req:
        def __init__(self, body):
            self._body = body

        async def json(self):
            return self._body

    resp = asyncio.run(daemon.handle_llm_harness(Req({"browser": False})))
    assert resp.status == 200
    assert llm_config.get_browser_use() is False
    resp = asyncio.run(daemon.handle_llm_harness(Req({"browser": True})))
    assert resp.status == 200
    assert llm_config.get_browser_use() is True

    monkeypatch.setenv("SWITCHBAY_PROFILE", "enterprise")
    admin_policy.reset_cache()
    resp = asyncio.run(daemon.handle_llm_harness(Req({"browser": True})))
    assert resp.status == 403
    assert llm_config.get_browser_use() is True
    admin_policy.reset_cache()


def test_npx_other_cli_is_hard_denied():
    reason = permissions.hard_deny_reason(
        "Bash", {"command": "npx -y @playwright/cli@latest --help"},
    )
    assert reason
    assert "0.1.23" in reason
    assert permissions.hard_deny_reason(
        "Bash", {"command": "npx -y skills add benjsmith/curiosity-engine"},
    ) is None
