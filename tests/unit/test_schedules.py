"""Workspace Auto schedules."""

from __future__ import annotations

import time

from switchbay import schedules


def test_due_immediately_then_after_interval(tmp_path):
    item = schedules.create(
        tmp_path, title="night", prompt="do work", frequency="hourly",
    )
    assert schedules.is_due(item, now=time.time())
    schedules.mark_started(tmp_path, item["id"], "run-x")
    loaded = schedules.get(tmp_path, item["id"])
    assert loaded is not None
    assert loaded["run_count"] == 1
    assert loaded["last_run_at"]
    assert not schedules.is_due(loaded, now=loaded["last_run_at"] + 10)
    schedules.mark_finished(tmp_path, item["id"])
    done = schedules.get(tmp_path, item["id"])
    assert done is not None
    assert done["running_run_id"] is None
    assert not schedules.is_due(done, now=done["last_run_at"] + 10)
    assert schedules.is_due(done, now=done["last_run_at"] + 3601)


def test_pending_running_id_is_stale(tmp_path):
    item = schedules.create(tmp_path, title="night", prompt="do work", frequency="hourly")
    schedules.mark_started(tmp_path, item["id"], "pending")
    loaded = schedules.get(tmp_path, item["id"])
    assert loaded is not None
    assert not schedules.is_due(loaded, now=time.time() + 10_000)
    schedules.clear_stale_running(tmp_path, set())
    cleared = schedules.get(tmp_path, item["id"])
    assert cleared is not None
    assert cleared["running_run_id"] is None


def test_until_at_stops_due(tmp_path):
    item = schedules.create(tmp_path, title="window", prompt="p", frequency="hourly")
    now = time.time()
    updated = schedules.update(tmp_path, item["id"], {"until_at": now + 60})
    assert updated is not None
    assert schedules.is_due(updated, now=now)
    assert not schedules.is_due(updated, now=now + 120)


def test_expire_windows_disables_and_returns_explicit_desk(tmp_path):
    now = time.time()
    item = schedules.create(
        tmp_path, title="Wiki curator",
        prompt="Curate this wiki for the current desk window.",
        frequency="hourly",
    )
    schedules.update(tmp_path, item["id"], {"until_at": now - 10})
    data = schedules.load(tmp_path)
    for it in data["items"]:
        if it["id"] == item["id"]:
            it["desk_id"] = "wiki-curator"
    schedules.save(tmp_path, data)
    ended = schedules.expire_windows(tmp_path, now=now)
    assert ended == ["wiki-curator"]
    loaded = schedules.get(tmp_path, item["id"])
    assert loaded is not None
    assert loaded["enabled"] is False
    assert schedules.expire_windows(tmp_path, now=now) == []


def test_expire_windows_does_not_guess_auto(tmp_path):
    now = time.time()
    item = schedules.create(
        tmp_path, title="nightly", prompt="/curate this wiki", frequency="hourly",
    )
    schedules.update(tmp_path, item["id"], {"until_at": now - 10})
    assert schedules.expire_windows(tmp_path, now=now) == []
    loaded = schedules.get(tmp_path, item["id"])
    assert loaded is not None
    assert loaded["enabled"] is False


def test_update_and_delete(tmp_path):
    item = schedules.create(tmp_path, title="a", prompt="p", frequency="daily")
    sid = item["id"]
    updated = schedules.update(tmp_path, sid, {"title": "b", "enabled": False})
    assert updated is not None
    assert updated["title"] == "b"
    assert updated["enabled"] is False
    assert not schedules.is_due(updated)
    assert schedules.delete(tmp_path, sid)
    assert schedules.get(tmp_path, sid) is None


def test_global_store_and_list_all(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    ws = tmp_path / "wiki-a"
    ws.mkdir()
    local = schedules.create(ws, title="desk", prompt="/curate this wiki", frequency="hourly")
    glob = schedules.create(None, title="all-curate", prompt="/curate", frequency="daily")
    rows = schedules.list_all([str(ws)])
    assert [r["title"] for r in rows] == ["all-curate", "desk"]
    assert rows[0]["scope"] == "global"
    assert rows[0]["workspace"] is None
    assert rows[1]["scope"] == "workspace"
    assert rows[1]["workspace"] == str(ws)
    found = schedules.locate(glob["id"], [str(ws)])
    assert found is not None
    store, item = found
    assert store is None
    assert item["title"] == "all-curate"
    found_ws = schedules.locate(local["id"], [str(ws)])
    assert found_ws is not None
    assert found_ws[0] == ws
