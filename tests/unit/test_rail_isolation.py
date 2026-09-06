"""Rail events from one workspace must not land in another's transcript."""

from __future__ import annotations

from pathlib import Path

from switchbay import protocol
from switchbay.daemon import _is_focused_workspace, _workspace_key


def test_notice_stamps_workspace_and_run_scope():
    msg = protocol.notice(
        "Draft in Reviews",
        kind="chat",
        workspace="/tmp/hedge-desk",
        run_id="run-abc",
        thread_id="tid-1",
    )
    inner = msg["value"]
    assert inner["type"] == "notice"
    assert inner["workspace"] == "/tmp/hedge-desk"
    assert inner["run_id"] == "run-abc"
    assert inner["thread_id"] == "tid-1"


def test_notice_omits_scope_when_unset():
    inner = protocol.notice("ok", kind="chat")["value"]
    assert "workspace" not in inner
    assert "run_id" not in inner
    assert "thread_id" not in inner


def test_thread_focused_stamps_workspace():
    inner = protocol.thread_focused(
        "tid-9", "structured-agent", workspace="/tmp/curiosity-test",
    )["value"]
    assert inner["thread_id"] == "tid-9"
    assert inner["workspace"] == "/tmp/curiosity-test"


def test_run_started_always_carries_workspace():
    ev = protocol.run_started(
        "tid-1", "run-1", "grok-build", "grok-4.6", "/tmp/hedge-desk",
    )
    assert ev["workspace"] == "/tmp/hedge-desk"
    assert ev["runId"] == "run-1"
    assert "hide_from_rail" not in ev


def test_run_started_marks_hidden_dag_workers():
    ev = protocol.run_started(
        "tid-1", "run-1-inv-0", "grok-build", "grok-4.6", "/tmp/hedge-desk",
        parent_run_id="run-1", node_kind="investigate", hide_from_rail=True,
    )
    assert ev["parent_run_id"] == "run-1"
    assert ev["node_kind"] == "investigate"
    assert ev["hide_from_rail"] is True


def test_is_focused_workspace_compares_resolved_paths(tmp_path: Path):
    app: dict = {"workspace": tmp_path / "curiosity-test"}
    (tmp_path / "curiosity-test").mkdir()
    (tmp_path / "hedge-desk").mkdir()
    assert _is_focused_workspace(app, tmp_path / "curiosity-test")
    assert _is_focused_workspace(app, tmp_path / "curiosity-test/")
    assert not _is_focused_workspace(app, tmp_path / "hedge-desk")
    assert _workspace_key(tmp_path / "a") == _workspace_key(tmp_path / "a/")
