"""okstratr.host_notify → rail protocol.notice mapping."""

from __future__ import annotations

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from switchbay import host_notify


def _env(**overrides):
    base = {
        "type": "okstratr.host_notify",
        "v": 1,
        "kind": "schedule.start",
        "schedule_id": "sched-1",
        "desk": "auto",
        "title": "Morning digest",
        "body": "Running hedge-fund desk.",
        "progress": {"pct": None, "phase": "start", "detail": ""},
        "ts": "2026-09-19T08:00:00Z",
    }
    base.update(overrides)
    return base


def test_validate_ok():
    env, err = host_notify.validate_envelope(_env())
    assert err is None
    assert env is not None


def test_validate_rejects_wrong_type():
    env, err = host_notify.validate_envelope(_env(type="other"))
    assert env is None
    assert "type" in (err or "")


def test_format_includes_title_and_meta():
    text = host_notify.format_rail_text(_env())
    assert "[okstratr]" in text
    assert "Morning digest" in text
    assert "desk=auto" in text
    assert "id=sched-1" in text
    assert "Running hedge-fund desk." in text


def test_format_progress():
    text = host_notify.format_rail_text(
        _env(
            kind="schedule.progress",
            progress={"pct": 40, "phase": "fetch", "detail": "n=3"},
        )
    )
    assert "40%" in text
    assert "fetch" in text


def test_notice_from_envelope_is_protocol_notice():
    msg = host_notify.notice_from_envelope(_env())
    text = host_notify._notice_text(msg)
    assert text and "Morning digest" in text


@pytest.mark.asyncio
async def test_apply_broadcasts_via_app_helper():
    seen: list[dict] = []

    async def _bc(app, msg):
        seen.append(msg)

    app = {"_broadcast_fn": _bc}
    result = await host_notify.apply_host_notify(app, _env())
    assert result["ok"] is True
    assert result["broadcast"] is True
    assert len(seen) == 1
    assert "Morning digest" in (result.get("text") or "")


@pytest.mark.asyncio
async def test_http_host_notify_endpoint_broadcasts():
    """POST /api/okstratr/host-notify posts envelope → rail notice."""
    from switchbay import daemon

    seen: list[dict] = []

    async def _bc(app, msg):
        seen.append(msg)

    app = web.Application()
    app["workspace"] = "/tmp"
    app["ws_clients"] = set()
    app["_broadcast_fn"] = _bc
    app.router.add_post("/api/okstratr/host-notify", daemon.handle_okstratr_host_notify)

    async with TestClient(TestServer(app)) as client:
        resp = await client.post("/api/okstratr/host-notify", json=_env())
        assert resp.status == 200
        data = await resp.json()
        assert data["ok"] is True
        assert data["broadcast"] is True
        assert "Morning digest" in (data.get("text") or "")
    assert len(seen) == 1
