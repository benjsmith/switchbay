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
