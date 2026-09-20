"""Thin client / mapper over okstratr harness registry (SSOT)."""

from __future__ import annotations

import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from switchbay import okstratr_harness


def _okstratr_list_payload(**overrides):
    base = {
        "ok": True,
        "path": "/tmp/harnesses.toml",
        "enabled": ["grok", "claude"],
        "preference": ["grok", "claude"],
        "defaults": {"adapter": "herdr", "backend": "herdr"},
        "backend": "herdr",
        "harnesses": [
            {
                "id": "grok",
                "label": "Grok",
                "herdr_kind": "grok",
                "enabled": True,
                "installed": True,
                "bin_names": ["grok"],
                "default_model": "grok-4.6",
                "models": ["grok-4.6", "grok-4"],
                "effort": {"trivial": "grok-4.6", "normal": "grok-4.6"},
                "settings": {"reasoning": "low"},
                "notes": "",
            },
            {
                "id": "claude",
                "label": "Claude",
                "herdr_kind": "claude",
                "enabled": True,
                "installed": False,
                "bin_names": ["claude"],
                "default_model": "claude-haiku",
                "models": ["claude-haiku"],
                "effort": {},
                "settings": {},
                "notes": "install claude",
            },
            {
                "id": "codex",
                "label": "Codex",
                "enabled": False,
                "installed": False,
                "default_model": "gpt-5",
                "models": ["gpt-5"],
                "effort": {},
                "settings": {},
                "notes": "",
            },
        ],
        "blackboard": {"duration_days": 3.0, "chip": "bb: 3d"},
    }
    base.update(overrides)
    return base


def test_normalize_registry_maps_rows():
    view = okstratr_harness.normalize_registry(_okstratr_list_payload())
    assert view["ok"] is True
    assert view["ssot"] == "okstratr"
    assert view["enabled"] == ["grok", "claude"]
    assert view["backend"] == "herdr"
    assert len(view["harnesses"]) == 3
    grok = view["harnesses"][0]
    assert grok["id"] == "grok"
    assert grok["enabled"] is True
    assert grok["default_model"] == "grok-4.6"
    assert "grok-4.6" in grok["models"]
    assert view["embed_paths"]["list"] == "/embed/okstratr/api/harness"
    assert view["blackboard"]["chip"] == "bb: 3d"


def test_normalize_skips_bad_rows_and_fills_defaults():
    view = okstratr_harness.normalize_registry(
        {
            "harnesses": [
                "nope",
                {"label": "missing id"},
                {"id": "pi", "enabled": 1, "models": "bad"},
            ]
        }
    )
    assert view["ssot"] == "okstratr"
    assert len(view["harnesses"]) == 1
    assert view["harnesses"][0]["id"] == "pi"
    assert view["harnesses"][0]["models"] == []
    assert view["harnesses"][0]["enabled"] is True


def test_normalize_none_is_empty_ssot_view():
    view = okstratr_harness.normalize_registry(None)
    assert view["ok"] is True
    assert view["ssot"] == "okstratr"
    assert view["harnesses"] == []
    assert view["enabled"] == []


def test_upstream_url_defaults(monkeypatch):
    monkeypatch.delenv("SWITCHBAY_OKSTRATR_UPSTREAM", raising=False)
    assert okstratr_harness.upstream_url("list") == "http://127.0.0.1:8767/api/harness"
    assert (
        okstratr_harness.upstream_url("enable")
        == "http://127.0.0.1:8767/api/harness/enable"
    )


def test_upstream_url_rejects_non_loopback(monkeypatch):
    monkeypatch.setenv("SWITCHBAY_OKSTRATR_UPSTREAM", "http://evil.example:8767")
    with pytest.raises(okstratr_harness.OkstratrHarnessError):
        okstratr_harness.upstream_url("list")


@pytest.mark.asyncio
async def test_call_harness_list_against_stub(monkeypatch):
    """Server-side client hits loopback stub with X-Okstratr-Host."""
    seen: dict[str, str] = {}

    async def upstream(request: web.Request) -> web.Response:
        seen["host"] = request.headers.get("X-Okstratr-Host", "")
        seen["path"] = request.path
        return web.json_response(_okstratr_list_payload())

    up = web.Application()
    up.router.add_get("/api/harness", upstream)
    async with TestServer(up) as server:
        base = f"http://127.0.0.1:{server.port}"
        monkeypatch.setenv("SWITCHBAY_OKSTRATR_UPSTREAM", base)
        view = await okstratr_harness.list_harnesses()
    assert seen["host"] == "switchbay"
    assert seen["path"] == "/api/harness"
    assert view["ssot"] == "okstratr"
    assert any(h["id"] == "grok" for h in view["harnesses"])


@pytest.mark.asyncio
async def test_call_harness_enable_posts_id(monkeypatch):
    seen: dict = {}

    async def upstream(request: web.Request) -> web.Response:
        seen["path"] = request.path
        seen["body"] = await request.json()
        payload = _okstratr_list_payload()
        # pretend enable flipped codex on
        for h in payload["harnesses"]:
            if h["id"] == "codex":
                h["enabled"] = True
        payload["enabled"] = ["grok", "claude", "codex"]
        return web.json_response(payload)

    up = web.Application()
    up.router.add_post("/api/harness/enable", upstream)
    async with TestServer(up) as server:
        monkeypatch.setenv(
            "SWITCHBAY_OKSTRATR_UPSTREAM", f"http://127.0.0.1:{server.port}"
        )
        view = await okstratr_harness.enable_harness("codex")
    assert seen["path"] == "/api/harness/enable"
    assert seen["body"]["id"] == "codex"
    assert "codex" in view["enabled"]


@pytest.mark.asyncio
async def test_call_harness_set_posts_key_value(monkeypatch):
    seen: dict = {}

    async def upstream(request: web.Request) -> web.Response:
        seen["body"] = await request.json()
        return web.json_response(_okstratr_list_payload())

    up = web.Application()
    up.router.add_post("/api/harness/set", upstream)
    async with TestServer(up) as server:
        monkeypatch.setenv(
            "SWITCHBAY_OKSTRATR_UPSTREAM", f"http://127.0.0.1:{server.port}"
        )
        await okstratr_harness.set_harness_value(
            "harness.grok.default_model", "grok-4"
        )
    assert seen["body"] == {
        "key": "harness.grok.default_model",
        "value": "grok-4",
    }


@pytest.mark.asyncio
async def test_daemon_routes_thin_client(monkeypatch):
    """GET/POST /api/okstratr/harness* shell without embed path knowledge."""
    from switchbay import daemon

    state = {"enabled": ["grok"]}

    async def list_h(request: web.Request) -> web.Response:
        return web.json_response(
            _okstratr_list_payload(enabled=list(state["enabled"]))
        )

    async def enable_h(request: web.Request) -> web.Response:
        body = await request.json()
        hid = body.get("id")
        if hid and hid not in state["enabled"]:
            state["enabled"].append(hid)
        return web.json_response(
            _okstratr_list_payload(enabled=list(state["enabled"]))
        )

    async def disable_h(request: web.Request) -> web.Response:
        body = await request.json()
        hid = body.get("id")
        state["enabled"] = [x for x in state["enabled"] if x != hid] or ["grok"]
        return web.json_response(
            _okstratr_list_payload(enabled=list(state["enabled"]))
        )

    async def set_h(request: web.Request) -> web.Response:
        await request.json()
        return web.json_response(_okstratr_list_payload())

    async def reload_h(request: web.Request) -> web.Response:
        return web.json_response(
            {"ok": True, "reloaded": True, "config": _okstratr_list_payload()}
        )

    up = web.Application()
    up.router.add_get("/api/harness", list_h)
    up.router.add_post("/api/harness/enable", enable_h)
    up.router.add_post("/api/harness/disable", disable_h)
    up.router.add_post("/api/harness/set", set_h)
    up.router.add_post("/api/harness/reload", reload_h)

    async with TestServer(up) as server:
        monkeypatch.setenv(
            "SWITCHBAY_OKSTRATR_UPSTREAM", f"http://127.0.0.1:{server.port}"
        )
        app = web.Application()
        app.router.add_get(
            "/api/okstratr/harness", daemon.handle_okstratr_harness_get
        )
        app.router.add_post(
            "/api/okstratr/harness/enable", daemon.handle_okstratr_harness_enable
        )
        app.router.add_post(
            "/api/okstratr/harness/disable", daemon.handle_okstratr_harness_disable
        )
        app.router.add_post(
            "/api/okstratr/harness/set", daemon.handle_okstratr_harness_set
        )
        app.router.add_post(
            "/api/okstratr/harness/reload", daemon.handle_okstratr_harness_reload
        )
        async with TestClient(TestServer(app)) as client:
            r = await client.get("/api/okstratr/harness")
            assert r.status == 200
            data = await r.json()
            assert data["ssot"] == "okstratr"
            assert data["ok"] is True

            r = await client.post(
                "/api/okstratr/harness/enable", json={"id": "claude"}
            )
            assert r.status == 200
            data = await r.json()
            assert "claude" in data["enabled"]

            r = await client.post(
                "/api/okstratr/harness/disable", json={"id": "claude"}
            )
            assert r.status == 200
            data = await r.json()
            assert "claude" not in data["enabled"]

            r = await client.post(
                "/api/okstratr/harness/set",
                json={"key": "backend", "value": "direct"},
            )
            assert r.status == 200
            assert (await r.json())["ssot"] == "okstratr"

            r = await client.post("/api/okstratr/harness/reload", json={})
            assert r.status == 200
            assert (await r.json())["ssot"] == "okstratr"


@pytest.mark.asyncio
async def test_daemon_route_502_when_upstream_down(monkeypatch):
    from switchbay import daemon

    # Bind nothing on a high port — connection refused.
    monkeypatch.setenv("SWITCHBAY_OKSTRATR_UPSTREAM", "http://127.0.0.1:1")
    app = web.Application()
    app.router.add_get("/api/okstratr/harness", daemon.handle_okstratr_harness_get)
    async with TestClient(TestServer(app)) as client:
        r = await client.get("/api/okstratr/harness")
        assert r.status == 502
        data = await r.json()
        assert data["ok"] is False
        assert data["ssot"] == "okstratr"
