"""Desk working / quiet / dismissed."""

from __future__ import annotations

from pathlib import Path

from switchbay.kernel import (
    DESK_CURATE,
    STATE_DISMISSED,
    STATE_QUIET,
    STATE_WORKING,
    dismiss,
    dismiss_run,
    get,
    quiet,
    seat,
    window_ended,
)


def test_seat_working_then_quiet(tmp_path: Path):
    rec = seat(
        tmp_path, DESK_CURATE,
        chief_provider="grok-build",
        chief_model="grok-4.6",
        run_id="run-1",
        org=[{"package": "curator", "reports_to": "chief"}],
    )
    assert rec.state == STATE_WORKING
    q = quiet(tmp_path, DESK_CURATE)
    assert q is not None
    assert q.state == STATE_QUIET
    assert q.chief_provider == "grok-build"
    assert q.org  # org survives quiet
    assert q.run_id is None


def test_schedule_window_end_is_quiet_not_dismiss(tmp_path: Path):
    seat(tmp_path, DESK_CURATE, chief_provider="anthropic", chief_model="opus", run_id="r")
    assert window_ended({"until_at": 1}, now=2) is True
    quiet(tmp_path, DESK_CURATE)
    rec = get(tmp_path, DESK_CURATE)
    assert rec is not None
    assert rec.state == STATE_QUIET
    assert rec.state != STATE_DISMISSED


def test_stop_dismisses(tmp_path: Path):
    seat(tmp_path, DESK_CURATE, chief_provider="anthropic", chief_model="opus", run_id="run-9")
    hit = dismiss_run(tmp_path, "run-9")
    assert DESK_CURATE in hit
    rec = get(tmp_path, DESK_CURATE)
    assert rec is not None
    assert rec.state == STATE_DISMISSED
    assert rec.org == []


def test_quiet_ignores_overlapping_newer_run(tmp_path: Path):
    seat(
        tmp_path, DESK_CURATE,
        chief_provider="x", chief_model="y", run_id="run-old",
    )
    seat(
        tmp_path, DESK_CURATE,
        chief_provider="x", chief_model="y", run_id="run-new",
    )
    q = quiet(tmp_path, DESK_CURATE, run_id="run-old")
    assert q is not None
    assert q.state == STATE_WORKING
    assert q.run_id == "run-new"
    q2 = quiet(tmp_path, DESK_CURATE, run_id="run-new")
    assert q2 is not None
    assert q2.state == STATE_QUIET
    assert q2.run_id is None


def test_quiet_does_not_revive_dismissed(tmp_path: Path):
    seat(tmp_path, DESK_CURATE, chief_provider="x", chief_model="y")
    dismiss(tmp_path, DESK_CURATE)
    q = quiet(tmp_path, DESK_CURATE)
    assert q is not None
    assert q.state == STATE_DISMISSED


def test_window_ended_false_when_open():
    assert window_ended({"until_at": 9_999_999_999}, now=100) is False
    assert window_ended({"until_at": None}, now=100) is False
