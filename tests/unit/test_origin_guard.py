"""The local-daemon trust boundary: reject drive-by websites +
DNS-rebinding, allow legitimate local clients."""

from __future__ import annotations

import pytest
from aiohttp.test_utils import make_mocked_request

from switchbay import daemon


@pytest.mark.parametrize(
    "value,expected",
    [
        ("http://127.0.0.1:8765", "127.0.0.1"),
        ("http://localhost:5173", "localhost"),
        ("https://evil.com", "evil.com"),
        ("127.0.0.1:8765", "127.0.0.1"),
        ("evil.com", "evil.com"),
        ("http://[::1]:8765", "[::1]"),
        ("null", ""),
        ("", ""),
    ],
)
def test_hostname_of(value, expected):
    assert daemon._hostname_of(value) == expected


def _req(headers):
    return make_mocked_request("GET", "/api/tree", headers=headers)


def test_no_origin_loopback_host_allowed():
    # curl / local probes / subprocess callbacks: Host is loopback, no
    # Origin → allowed.
    assert daemon._origin_host_allowed(_req({"Host": "127.0.0.1:8765"}))


def test_loopback_origin_allowed():
    assert daemon._origin_host_allowed(
        _req({"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765"})
    )


def test_vite_dev_origin_allowed():
    assert daemon._origin_host_allowed(
        _req({"Host": "localhost:5173", "Origin": "http://localhost:5173"})
    )


def test_evil_origin_rejected():
    # Drive-by website (WS handshake / cross-origin fetch) — Origin is set
    # by the browser and cannot be a loopback origin.
    assert not daemon._origin_host_allowed(
        _req({"Host": "127.0.0.1:8765", "Origin": "https://evil.com"})
    )


def test_dns_rebinding_host_rejected():
    # Attacker rebinds evil.com → 127.0.0.1; Host carries the attacker
    # name.
    assert not daemon._origin_host_allowed(_req({"Host": "evil.com"}))


async def test_middleware_403s_cross_origin():
    async def handler(_request):
        raise AssertionError("handler should not run for a rejected origin")

    req = _req({"Host": "127.0.0.1:8765", "Origin": "https://evil.com"})
    resp = await daemon._origin_guard(req, handler)
    assert resp.status == 403


async def test_middleware_passes_local():
    called = {}

    async def handler(_request):
        called["yes"] = True
        from aiohttp import web
        return web.json_response({"ok": True})

    req = _req({"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765"})
    resp = await daemon._origin_guard(req, handler)
    assert called.get("yes")
    assert resp.status == 200
