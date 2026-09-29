"""CE viewer supervisor: bind tracking + retarget-on-mistarget."""

from __future__ import annotations

from pathlib import Path

from switchbay import ce_viewer_supervisor as ce


def test_bound_workspace_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(ce, "_state_dir", lambda: tmp_path)
    assert ce.bound_workspace() is None
    ws = (tmp_path / "ws-a").resolve()
    ws.mkdir()
    ce._set_bound_workspace(ws)
    assert ce.bound_workspace() == ws
    ce._set_bound_workspace(None)
    assert ce.bound_workspace() is None


def test_start_idempotent_same_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(ce, "_state_dir", lambda: tmp_path)
    ws = (tmp_path / "ws-bio").resolve()
    ws.mkdir()
    (ws / "wiki").mkdir()
    ce._set_bound_workspace(ws)
    monkeypatch.setattr(ce, "is_healthy", lambda **_: True)
    monkeypatch.setattr(ce, "_read_pid", lambda: 42)

    out = ce.start(ws)
    assert out["ok"] is True
    assert out["already_running"] is True
    assert out["retargeted"] is False
    assert out["workspace"] == str(ws)


def test_start_retargets_when_bound_differs(tmp_path, monkeypatch):
    monkeypatch.setattr(ce, "_state_dir", lambda: tmp_path)
    old = (tmp_path / "ws-old").resolve()
    new = (tmp_path / "ws-new").resolve()
    old.mkdir()
    new.mkdir()
    (new / "wiki").mkdir()
    ce._set_bound_workspace(old)

    calls: list[str] = []

    monkeypatch.setattr(ce, "is_healthy", lambda **_: calls.count("stop") == 0)
    monkeypatch.setattr(ce, "_read_pid", lambda: None)

    def fake_stop():
        calls.append("stop")
        ce._set_bound_workspace(None)
        return {"ok": True, "stopped": True, "pid": 1}

    monkeypatch.setattr(ce, "stop", fake_stop)
    # Avoid real spawn: stub Popen + health becoming true after stop.
    class FakeProc:
        pid = 99

        def poll(self):
            return None

    spawned: list[list[str]] = []

    def fake_popen(argv, **kwargs):
        spawned.append(list(argv))
        calls.append("spawn")
        return FakeProc()

    # After stop, is_healthy flips; after spawn, health loop should succeed.
    health_checks = {"n": 0}

    def health(**_):
        # Before stop: True (triggers retarget). After stop: False until spawn.
        if "stop" not in calls:
            return True
        if "spawn" not in calls:
            return False
        health_checks["n"] += 1
        return health_checks["n"] >= 1

    monkeypatch.setattr(ce, "is_healthy", health)
    monkeypatch.setattr(ce.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(ce, "bundle_ready", lambda _w: True)
    monkeypatch.setattr(
        ce.cebridge,
        "ce_root",
        lambda: tmp_path / "ce-root",
    )
    (tmp_path / "ce-root" / "scripts").mkdir(parents=True)
    (tmp_path / "ce-root" / "scripts" / "viewer.sh").write_text("#!/bin/bash\n")
    (tmp_path / "ce-root" / "scripts" / "viewer_server.py").write_text("#x\n")
    monkeypatch.setattr(ce.cebridge, "has_wiki", lambda _w: True)
    monkeypatch.setattr(
        ce.cebridge,
        "output_dir",
        lambda w: tmp_path / "cache" / Path(w).name,
    )
    cache = tmp_path / "cache" / new.name
    cache.mkdir(parents=True)
    (cache / "index.html").write_text("<html></html>")
    (cache / "data.json").write_text("{}")

    out = ce.start(new)
    assert "stop" in calls
    assert "spawn" in calls
    assert out["ok"] is True
    assert out["retargeted"] is True
    assert out["already_running"] is False
    assert out["mode"] == "serve_only"
    assert out["workspace"] == str(new)
    assert ce.bound_workspace() == new
    # Serve-only argv must not invoke viewer.sh (no forced rebuild).
    assert spawned and "viewer_server.py" in spawned[0][-4]
    assert "viewer.sh" not in " ".join(spawned[0])


def test_spawn_argv_build_when_cache_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        ce.cebridge,
        "ce_root",
        lambda: tmp_path / "ce-root",
    )
    (tmp_path / "ce-root" / "scripts").mkdir(parents=True)
    (tmp_path / "ce-root" / "scripts" / "viewer.sh").write_text("x")
    (tmp_path / "ce-root" / "scripts" / "viewer_server.py").write_text("x")
    monkeypatch.setattr(
        ce.cebridge,
        "output_dir",
        lambda w: tmp_path / "cache" / Path(w).name,
    )
    ws = tmp_path / "ws"
    ws.mkdir()
    argv, mode = ce._spawn_argv(ws, 8766)
    assert mode == "build_and_serve"
    assert argv[0] == "bash"
    assert argv[2] == "serve"
