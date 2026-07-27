"""User-requested daemon stop (Settings → Quit button and `/quit`).

The stop reuses `make stop`'s proven path: a clean self-SIGTERM that the
launchd agent (KeepAlive={SuccessfulExit:false}) won't relaunch. These
tests pin the two safety-relevant behaviours:

  * a bare `/quit` asks to confirm — it does NOT stop (it ends every
    running agent), only `/quit confirm` does;
  * the actual exit is a single SIGTERM to our own pid, and is
    idempotent so the button + a racing /quit can't double-fire.

`os.kill` and `_initiate_shutdown` are patched out so no test ever
signals the test runner.
"""

from __future__ import annotations

import asyncio
import os
import signal

import pytest
from aiohttp.test_utils import make_mocked_request
from unittest.mock import AsyncMock

from switchbay import daemon, protocol, service


def test_daemon_shutdown_protocol_shape():
    msg = protocol.daemon_shutdown("user")
    # CUSTOM-wrapped so ws.ts unwraps it like every other surface event.
    assert msg["type"] == "CUSTOM"
    assert msg["name"] == "daemon.shutdown"
    assert msg["value"] == {"type": "daemon.shutdown", "reason": "user"}


@pytest.mark.asyncio
async def test_initiate_shutdown_broadcasts_then_schedules(monkeypatch):
    broadcasts: list[dict] = []
    scheduled: list[dict] = []

    async def fake_broadcast(_app, msg):
        broadcasts.append(msg)

    monkeypatch.setattr(daemon, "_broadcast", fake_broadcast)
    monkeypatch.setattr(daemon, "_schedule_daemon_exit", lambda app: scheduled.append(app))

    app: dict = {}
    await daemon._initiate_shutdown(app, reason="slash")

    assert len(broadcasts) == 1
    assert broadcasts[0]["name"] == "daemon.shutdown"
    assert broadcasts[0]["value"]["reason"] == "slash"
    assert scheduled == [app]


@pytest.mark.asyncio
async def test_initiate_shutdown_still_exits_if_broadcast_fails(monkeypatch):
    """A dead socket mid-broadcast must not block the stop."""
    scheduled: list[dict] = []

    async def boom(_app, _msg):
        raise ConnectionResetError("client vanished")

    monkeypatch.setattr(daemon, "_broadcast", boom)
    monkeypatch.setattr(daemon, "_schedule_daemon_exit", lambda app: scheduled.append(app))

    app: dict = {}
    await daemon._initiate_shutdown(app, reason="user")
    assert scheduled == [app]


@pytest.mark.asyncio
async def test_schedule_daemon_exit_sigterms_self_once(monkeypatch):
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(daemon.os, "kill", lambda pid, sig: killed.append((pid, sig)))

    app: dict = {}
    daemon._schedule_daemon_exit(app, delay=0)
    daemon._schedule_daemon_exit(app, delay=0)  # racing second call — must no-op
    # Let the (delay=0) call_later callback run.
    await asyncio.sleep(0.02)

    assert app["_quitting"] is True
    assert killed == [(os.getpid(), signal.SIGTERM)]


class _FakeWS:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, msg):
        self.sent.append(msg)


@pytest.mark.asyncio
async def test_quit_slash_bare_asks_confirmation(monkeypatch):
    initiate = AsyncMock()
    monkeypatch.setattr(daemon, "_initiate_shutdown", initiate)

    ws = _FakeWS()
    await daemon._handle_quit_slash({}, ws, "")

    initiate.assert_not_awaited()
    assert len(ws.sent) == 1
    text = ws.sent[0]["value"]["text"]
    assert "/quit confirm" in text


@pytest.mark.asyncio
@pytest.mark.parametrize("arg", ["confirm", "  CONFIRM ", "-y", "yes"])
async def test_quit_slash_confirm_initiates(monkeypatch, arg):
    initiate = AsyncMock()
    monkeypatch.setattr(daemon, "_initiate_shutdown", initiate)

    ws = _FakeWS()
    await daemon._handle_quit_slash({}, ws, arg)

    initiate.assert_awaited_once()
    assert initiate.await_args.kwargs["reason"] == "slash"


@pytest.mark.asyncio
async def test_quit_endpoint_initiates_shutdown(monkeypatch):
    initiate = AsyncMock()
    monkeypatch.setattr(daemon, "_initiate_shutdown", initiate)

    req = make_mocked_request("POST", "/api/quit", app={})
    resp = await daemon.handle_quit(req)

    assert resp.status == 200
    initiate.assert_awaited_once()
    assert initiate.await_args.kwargs["reason"] == "user"


# ── Restart (/start, /api/restart) ───────────────────────────────────


@pytest.mark.asyncio
async def test_restart_endpoint_spawns_when_managed(monkeypatch):
    spawned = []
    monkeypatch.setattr(daemon.service, "spawn_restart", lambda: spawned.append(True))

    req = make_mocked_request("POST", "/api/restart", app={"service_managed": True})
    resp = await daemon.handle_restart(req)

    assert resp.status == 200
    assert spawned == [True]


@pytest.mark.asyncio
async def test_restart_endpoint_refuses_dev_daemon(monkeypatch):
    """Not the managed service but installed → refuse (would spawn a
    rival on the port), and DON'T run make restart."""
    spawned = []
    monkeypatch.setattr(daemon.service, "spawn_restart", lambda: spawned.append(True))
    monkeypatch.setattr(daemon.service, "is_installed", lambda: True)

    req = make_mocked_request("POST", "/api/restart", app={"service_managed": False})
    resp = await daemon.handle_restart(req)

    assert resp.status == 409
    assert spawned == []


@pytest.mark.asyncio
async def test_restart_endpoint_refuses_when_not_installed(monkeypatch):
    spawned = []
    monkeypatch.setattr(daemon.service, "spawn_restart", lambda: spawned.append(True))
    monkeypatch.setattr(daemon.service, "is_installed", lambda: False)

    req = make_mocked_request("POST", "/api/restart", app={"service_managed": False})
    resp = await daemon.handle_restart(req)

    assert resp.status == 409
    assert spawned == []


@pytest.mark.asyncio
async def test_start_slash_refuses_dev_daemon_without_spawning(monkeypatch):
    spawned = []
    monkeypatch.setattr(daemon.service, "spawn_restart", lambda: spawned.append(True))
    monkeypatch.setattr(daemon.service, "is_installed", lambda: True)

    ws = _FakeWS()
    await daemon._handle_start_slash({"service_managed": False}, ws)

    assert spawned == []
    assert len(ws.sent) == 1
    assert "development daemon" in ws.sent[0]["value"]["text"]


@pytest.mark.asyncio
async def test_start_slash_spawns_when_managed(monkeypatch):
    spawned = []
    monkeypatch.setattr(daemon.service, "spawn_restart", lambda: spawned.append(True))

    ws = _FakeWS()
    await daemon._handle_start_slash({"service_managed": True}, ws)

    assert spawned == [True]
    # A "restarting…" notice precedes the spawn.
    assert ws.sent and "Restarting" in ws.sent[0]["value"]["text"]


def test_is_managed_false_when_not_installed(monkeypatch):
    monkeypatch.setattr(service, "is_installed", lambda: False)
    assert service.is_managed() is False


def test_is_managed_true_on_mac_via_xpc(monkeypatch):
    monkeypatch.setattr(service, "is_installed", lambda: True)
    monkeypatch.setattr(service.sys, "platform", "darwin")
    monkeypatch.setenv("XPC_SERVICE_NAME", service.LABEL)
    assert service.is_managed() is True


# ── Health payload (offline screen depends on repo_root) ─────────────


@pytest.mark.asyncio
async def test_health_exposes_repo_root_and_service_managed():
    """The offline/stopped screens read repo_root to build the exact
    `make -C "<repo>" restart` command; service_managed gates Restart."""
    req = make_mocked_request(
        "GET", "/api/health",
        app={"repo_root": "/Users/someone/switchbay", "service_managed": True},
    )
    resp = await daemon.handle_health(req)
    import json
    body = json.loads(resp.body)
    assert body["repo_root"] == "/Users/someone/switchbay"
    assert body["service_managed"] is True
