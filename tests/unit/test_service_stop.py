"""Windows stop must never taskkill /IM python.exe."""

from __future__ import annotations

import json

from switchbay import admin_policy, service


def test_stop_daemon_pid_windows_uses_pid_not_image(monkeypatch, tmp_path):
    pidfile = tmp_path / "daemon.pid"
    pidfile.write_text("4242\n", encoding="utf-8")
    monkeypatch.setattr(service, "_pid_path", lambda: pidfile)
    monkeypatch.setattr(service.sys, "platform", "win32")
    ran: list[list[str]] = []

    def fake_run(argv, **_k):
        ran.append(list(argv))
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(service.subprocess, "run", fake_run)
    service.stop_daemon_pid()
    assert ran == [["taskkill", "/PID", "4242", "/T", "/F"]]
    assert not pidfile.exists()


def test_stamped_profile_from_file(tmp_path, monkeypatch):
    monkeypatch.delenv("SWITCHBAY_PROFILE", raising=False)
    assert service._stamped_profile(tmp_path) is None
    (tmp_path / "SWITCHBAY_PROFILE").write_text("enterprise\n", encoding="utf-8")
    assert service._stamped_profile(tmp_path) == "enterprise"


def test_service_environment_stamps_profile(tmp_path, monkeypatch):
    monkeypatch.delenv("SWITCHBAY_PROFILE", raising=False)
    (tmp_path / "SWITCHBAY_PROFILE").write_text("enterprise\n", encoding="utf-8")
    env = service._service_environment(tmp_path)
    assert env["SWITCHBAY_PROFILE"] == "enterprise"
    assert env["SWITCHBAY_SERVICE"] == "1"
    assert env["PYTHONUNBUFFERED"] == "1"


def test_service_environment_open_omits_profile(tmp_path, monkeypatch):
    monkeypatch.delenv("SWITCHBAY_PROFILE", raising=False)
    env = service._service_environment(tmp_path)
    assert "SWITCHBAY_PROFILE" not in env


def test_spawn_restart_does_not_invoke_make(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "_repo_root", lambda: tmp_path)
    popped: list[list[str]] = []

    def fake_popen(argv, **_k):
        popped.append(list(argv))
        return None

    monkeypatch.setattr(service.subprocess, "Popen", fake_popen)
    service.spawn_restart()
    assert popped and popped[0][-2:] == ["service", "restart"]
    assert "make" not in popped[0]


def test_run_enterprise_user_only_on_install():
    assert service.run("status", enterprise_user=True) == 2


def test_mac_plist_stdio_is_devnull(tmp_path, monkeypatch):
    """launchd must not hold the rotating daemon log fd."""
    repo = tmp_path / "repo"
    py = repo / ".venv" / "bin" / "python"
    if service.sys.platform == "win32":
        py = repo / ".venv" / "Scripts" / "python.exe"
    py.parent.mkdir(parents=True)
    py.write_text("", encoding="utf-8")
    plist = tmp_path / "LaunchAgents" / "com.switchbay.daemon.plist"
    monkeypatch.setattr(service, "_mac_plist_path", lambda: plist)
    service._mac_write_plist(repo)
    text = plist.read_text(encoding="utf-8")
    assert "<key>StandardOutPath</key><string>/dev/null</string>" in text
    assert "<key>StandardErrorPath</key><string>/dev/null</string>" in text
    assert "switchbay-daemon.log" not in text


def test_main_passes_enterprise_user_flag(monkeypatch):
    seen: dict[str, object] = {}

    def fake_run(action, *, enterprise_user=False):
        seen["action"] = action
        seen["enterprise_user"] = enterprise_user
        return 0

    monkeypatch.setattr(service, "run", fake_run)
    from switchbay.__main__ import main
    assert main(["service", "install", "--enterprise-user"]) == 0
    assert seen == {"action": "install", "enterprise_user": True}


def test_run_install_enterprise_user_stamps(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(service.sys, "platform", "darwin")
    monkeypatch.setattr(service, "_mac", lambda action, repo: 0)
    monkeypatch.setattr(service, "_ensure_uv", lambda: None)
    monkeypatch.setattr(service, "_install_bundled_skills", lambda: None)
    monkeypatch.delenv("SWITCHBAY_PROFILE", raising=False)
    admin_policy.reset_cache()
    rc = service.run("install", enterprise_user=True)
    assert rc == 0
    dest = tmp_path / "admin.json"
    assert dest.is_file()
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert data["profile"] == "enterprise"
    assert data["features"]["in_app_update"] is False
    import os
    assert os.environ.get("SWITCHBAY_PROFILE") == "enterprise"
    admin_policy.reset_cache()
