"""Desk working / quiet / dismissed."""

from __future__ import annotations

import time
from pathlib import Path

from switchbay.kernel import (
    DESK_AUTO,
    DESK_CODE,
    DESK_CURATE,
    DESK_DECK,
    DESK_PROJECTS,
    STATE_DISMISSED,
    STATE_QUIET,
    STATE_WORKING,
    choose_desk,
    dismiss,
    dismiss_run,
    get,
    list_standing,
    looks_like_deck,
    quiet,
    quiet_run,
    seat,
    window_ended,
)
from switchbay import orchestrator_fs


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
    quiet(tmp_path, DESK_CURATE, keep_run=True)
    rec = get(tmp_path, DESK_CURATE)
    assert rec is not None
    assert rec.state == STATE_QUIET
    assert rec.state != STATE_DISMISSED
    assert rec.run_id == "r"


def test_expire_standing_desk_keeps_run_id(tmp_path: Path):
    from switchbay import schedules
    seat(
        tmp_path, DESK_CURATE,
        chief_provider="x", chief_model="y", run_id="run-curate",
    )
    item = schedules.create(
        tmp_path, title="curate window", prompt="/curate", frequency="hourly",
    )
    now = time.time()
    schedules.update(tmp_path, item["id"], {"until_at": now - 1})
    data = schedules.load(tmp_path)
    for it in data["items"]:
        if it["id"] == item["id"]:
            it["desk_id"] = DESK_CURATE
    schedules.save(tmp_path, data)
    ended = schedules.expire_windows(tmp_path, now=now)
    assert ended == [DESK_CURATE]
    quiet(tmp_path, DESK_CURATE, keep_run=True)
    rec = get(tmp_path, DESK_CURATE)
    assert rec is not None
    assert rec.state == STATE_QUIET
    assert rec.run_id == "run-curate"


def test_stop_quiets_live_run(tmp_path: Path):
    seat(
        tmp_path, DESK_CODE,
        chief_provider="anthropic", chief_model="opus", run_id="run-9",
        org=[{"package": "code-explore", "reports_to": "chief"}],
    )
    hit = quiet_run(tmp_path, "run-9")
    assert DESK_CODE in hit
    rec = get(tmp_path, DESK_CODE)
    assert rec is not None
    assert rec.state == STATE_QUIET
    assert rec.org  # roster survives stop
    assert rec.run_id == "run-9"  # Stop freezes the DAG id for Start


def test_dismiss_run_tears_down(tmp_path: Path):
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


def test_list_standing_skips_dismissed(tmp_path: Path):
    seat(tmp_path, DESK_CURATE, chief_provider="x", chief_model="y", run_id="r1")
    seat(tmp_path, DESK_CODE, chief_provider="x", chief_model="y", run_id="r2")
    quiet(tmp_path, DESK_CURATE, run_id="r1")
    dismiss(tmp_path, DESK_CODE)
    ids = {r.desk_id for r in list_standing(tmp_path)}
    assert DESK_CURATE in ids
    assert DESK_CODE not in ids
    curate = get(tmp_path, DESK_CURATE)
    assert curate is not None
    assert curate.state == STATE_QUIET


def test_dismiss_clears_standing_org(tmp_path: Path):
    seat(tmp_path, DESK_CODE, chief_provider="x", chief_model="y", run_id="run-9")
    orchestrator_fs.save_org(tmp_path, {
        "orchestration_id": "run-9",
        "nodes": [{"node_id": "chief", "kind": "chief"}],
    })
    assert orchestrator_fs.load_org(tmp_path) is not None
    dismiss(tmp_path, DESK_CODE)
    assert orchestrator_fs.load_org(tmp_path) is None


def test_dismissing_curate_preserves_code_org(tmp_path: Path):
    seat(tmp_path, DESK_CURATE, chief_provider="x", chief_model="y", run_id="run-curate")
    quiet(tmp_path, DESK_CURATE)
    seat(tmp_path, DESK_CODE, chief_provider="x", chief_model="y", run_id="run-code")
    orchestrator_fs.save_org(tmp_path, {
        "orchestration_id": "run-code",
        "nodes": [{"node_id": "chief", "kind": "chief"}],
    })
    dismiss(tmp_path, DESK_CURATE)
    org = orchestrator_fs.load_org(tmp_path)
    assert org is not None
    assert org["orchestration_id"] == "run-code"


def test_choose_desk_named_commands_always_seat():
    assert choose_desk(command="curate") == DESK_CURATE
    assert choose_desk(command="curator", strategy="single", lookup=True) == DESK_CURATE
    assert choose_desk(task_kind="curation") == DESK_CURATE
    assert choose_desk(command="work") == DESK_PROJECTS
    assert choose_desk(command="steer") == DESK_PROJECTS
    assert choose_desk(command="code") == DESK_CODE
    assert choose_desk(command="deck") == DESK_DECK


def test_choose_desk_curate_seats_even_when_single_lookup():
    assert choose_desk(
        command="curate",
        strategy="single",
        n_investigators=1,
        lookup=True,
    ) == DESK_CURATE


def test_choose_desk_lookup_is_oneshot():
    assert choose_desk(
        text="what do we know about attention",
        strategy="fast_lookup",
        lookup=True,
    ) is None
    assert choose_desk(
        text="what do we know about transformers",
        strategy="single",
        lookup=True,
    ) is None
    assert choose_desk(
        text="What do we know about HTML slideshows?",
        strategy="fast_lookup",
        lookup=True,
    ) is None
    assert choose_desk(
        text="What do we know about the project roadmap?",
        strategy="single",
        lookup=True,
    ) is None
    assert choose_desk(
        text="what is in the charter",
        strategy="single",
        lookup=True,
    ) is None
    assert not looks_like_deck("What do we know about HTML slideshows?")
    assert not looks_like_deck("tell me about the slide deck")


def test_choose_desk_deeper_work_reuses_auto():
    assert choose_desk(
        text="write a plan for the hedge desk overnight",
        strategy="single",
    ) == DESK_AUTO
    assert choose_desk(
        text="compare Bahdanau and Vaswani",
        strategy="investigate_verify_synthesize",
        n_investigators=2,
        include_verify=True,
        research=True,
    ) == DESK_AUTO


def test_choose_desk_slideshow_reuses_one_deck():
    assert looks_like_deck("Revise the existing HTML slideshow")
    assert looks_like_deck("make a slide deck from the wiki")
    assert looks_like_deck("Revise the HTML deck")
    assert looks_like_deck("Revise the existing HTML deck")
    assert looks_like_deck("Regenerate this slide deck")
    assert looks_like_deck("create_slideshow")
    assert not looks_like_deck("what do we know about attention")
    first = choose_desk(text="make a slideshow about Bahdanau")
    second = choose_desk(text="revise the existing HTML slideshow")
    third = choose_desk(text="Revise the existing HTML deck")
    assert first == DESK_DECK
    assert second == DESK_DECK
    assert third == DESK_DECK
    assert first == second == third


def test_seat_revives_dismissed_curate(tmp_path: Path):
    seat(tmp_path, DESK_CURATE, chief_provider="x", chief_model="y", run_id="old")
    dismiss(tmp_path, DESK_CURATE)
    rec = seat(
        tmp_path, DESK_CURATE,
        chief_provider="grok-build", chief_model="grok-4.6", run_id="new",
    )
    assert rec.state == STATE_WORKING
    assert rec.run_id == "new"
    standing = {r.desk_id for r in list_standing(tmp_path)}
    assert DESK_CURATE in standing


def test_seat_persists_each_desk_objective(tmp_path: Path):
    seat(
        tmp_path, DESK_CODE,
        chief_provider="x", chief_model="y",
        run_id="r1", objective="implement the patch",
    )
    seat(
        tmp_path, DESK_DECK,
        chief_provider="x", chief_model="y",
        run_id="r2", objective="make a slideshow",
    )
    quiet(tmp_path, DESK_CODE, keep_run=True)
    code = get(tmp_path, DESK_CODE)
    deck = get(tmp_path, DESK_DECK)
    assert code is not None and deck is not None
    assert code.objective == "implement the patch"
    assert deck.objective == "make a slideshow"


def test_curate_constrained_is_local_only():
    from switchbay.daemon import _curate_constrained
    assert _curate_constrained(local=True) is True
    assert _curate_constrained(local=True, text="tables") is True
    assert _curate_constrained(local=True, text="for 10 mins") is False
    assert _curate_constrained(local=True, text="overnight") is False
    assert _curate_constrained(local=False) is False
    assert _curate_constrained(local=False, text="for 10 mins") is False


def test_schedule_desk_launch_parses_desk_slashes():
    from switchbay.daemon import _parse_schedule_prompt, _schedule_desk_launch
    spec, args = _schedule_desk_launch("/curate for 10 mins")
    assert spec is not None and spec["desk_id"] == "curate"
    assert args == "for 10 mins"
    spec, args = _schedule_desk_launch("/work")
    assert spec is not None and spec["desk_id"] == "projects"
    spec, args = _schedule_desk_launch("/code implement the parser")
    assert spec is not None and spec["desk_id"] == "code"
    assert args == "implement the parser"
    spec, _ = _schedule_desk_launch("what do we know about attention")
    assert spec is None
    spec, _ = _schedule_desk_launch("/curate stop")
    assert spec is None
    spec, _ = _schedule_desk_launch("make a slideshow about Bahdanau")
    assert spec is None
    spec, _ = _schedule_desk_launch("/deck make slides")
    assert spec is None
    kind, spec, args = _parse_schedule_prompt("/curate stop")
    assert kind == "skip" and spec is not None
    kind, spec, args = _parse_schedule_prompt("/work dismiss")
    assert kind == "skip"


def test_seat_desk_now_stands_curate_before_dispatch(tmp_path: Path):
    from switchbay.daemon import _desk_spec, _seat_desk_now
    spec = _desk_spec("curate")
    assert spec is not None
    assert spec["staff"] != "/curate"
    _seat_desk_now(
        tmp_path, spec, "for 10 mins",
        provider="grok-build", model="grok-4.6",
    )
    rec = get(tmp_path, DESK_CURATE)
    assert rec is not None
    assert rec.state == STATE_WORKING
    assert rec.objective == "for 10 mins"
    assert rec.chief_provider == "grok-build"
    standing = {r.desk_id for r in list_standing(tmp_path)}
    assert DESK_CURATE in standing


def test_seat_desk_now_stands_work_and_code(tmp_path: Path):
    from switchbay.daemon import _desk_spec, _seat_desk_now
    work, code = _desk_spec("work"), _desk_spec("code")
    assert work is not None and code is not None
    _seat_desk_now(
        tmp_path, work, "staff the plan",
        provider="grok-build", model="grok-4.6",
    )
    _seat_desk_now(
        tmp_path, code, "implement the parser",
        provider="grok-build", model="grok-4.6",
    )
    standing = {r.desk_id for r in list_standing(tmp_path)}
    assert DESK_PROJECTS in standing
    assert DESK_CODE in standing


def test_ws_response_disables_permessage_deflate():
    from switchbay.daemon import _ws_response
    ws = _ws_response()
    assert ws._compress in (False, 0)


def test_dispatch_error_surface_broadcasts_when_headless():
    import asyncio
    from switchbay.daemon import _make_dispatch_error_surface

    seen: list = []

    class _Task:
        def exception(self):
            return RuntimeError("boom")

    async def _run():
        app = {"ws_clients": set()}

        async def fake_broadcast(_app, msg):
            seen.append(msg)

        import switchbay.daemon as d
        orig = d._broadcast
        d._broadcast = fake_broadcast  # type: ignore[method-assign]
        try:
            cb = _make_dispatch_error_surface(app, None)
            cb(_Task())  # type: ignore[arg-type]
            await asyncio.sleep(0)
        finally:
            d._broadcast = orig

    asyncio.run(_run())
    assert seen
    blob = str(seen[0])
    assert "boom" in blob


def test_ce_action_prompt_duration_is_focus_not_mode():
    from switchbay.daemon import _ce_action_prompt
    p = _ce_action_prompt("curate", "for 10 mins", local=False) or ""
    assert "Focus: for 10 mins" in p
    assert "Mode:" not in p


def test_seat_desk_now_keeps_live_run_id(tmp_path: Path):
    from switchbay.daemon import _desk_spec, _seat_desk_now
    spec = _desk_spec("curate")
    assert spec is not None
    seat(
        tmp_path, DESK_CURATE,
        chief_provider="grok-build", chief_model="grok-4.6",
        run_id="run-live", objective="old",
    )
    _seat_desk_now(
        tmp_path, spec, "for 10 mins",
        provider="grok-build", model="grok-4.6",
    )
    rec = get(tmp_path, DESK_CURATE)
    assert rec is not None
    assert rec.state == STATE_WORKING
    assert rec.run_id == "run-live"
    assert rec.objective == "for 10 mins"


def test_curate_wave_prime_skips_duration_token(tmp_path: Path, monkeypatch):
    from switchbay.daemon import _curate_wave_prime_system
    seen: dict = {}

    def fake_prime(_ws, payload=None):
        seen["payload"] = payload
        return {"ok": True, "mode": "repair"}

    monkeypatch.setattr("switchbay.ce_host.wave_prime", fake_prime)
    _curate_wave_prime_system(tmp_path, "for 10 mins", local=False)
    assert seen["payload"] == {}
    _curate_wave_prime_system(tmp_path, "tables", local=False)
    assert seen["payload"] == {"mode": "tables"}
    assert _curate_wave_prime_system(tmp_path, "tables", local=True) == ""
