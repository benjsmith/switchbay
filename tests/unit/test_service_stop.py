"""Windows stop must never taskkill /IM python.exe."""

from __future__ import annotations

from switchbay import service


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
