"""Phase 4a: same-origin embed reverse-proxy allowlist + routing."""

from __future__ import annotations

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from switchbay import embed_proxy


def test_loopback_hosts_accepted():
    assert embed_proxy.is_loopback_host("127.0.0.1")
    assert embed_proxy.is_loopback_host("localhost")
    assert embed_proxy.is_loopback_host("::1")
    assert embed_proxy.is_loopback_host("[::1]")


def test_non_loopback_hosts_rejected():
    assert not embed_proxy.is_loopback_host("example.com")
    assert not embed_proxy.is_loopback_host("8.8.8.8")
    assert not embed_proxy.is_loopback_host("10.0.0.1")
    assert not embed_proxy.is_loopback_host("")


def test_assert_loopback_upstream_ok():
    assert embed_proxy.assert_loopback_upstream("http://127.0.0.1:8766") == (
        "http://127.0.0.1:8766"
    )
    assert embed_proxy.assert_loopback_upstream("http://localhost:8767/") == (
        "http://localhost:8767"
    )


def test_assert_loopback_upstream_rejects_remote():
    with pytest.raises(embed_proxy.UpstreamNotLoopback):
        embed_proxy.assert_loopback_upstream("http://evil.example:8766")
    with pytest.raises(embed_proxy.UpstreamNotLoopback):
        embed_proxy.assert_loopback_upstream("http://192.168.1.5:8766")


def test_match_embed_prefix():
    assert embed_proxy.match_embed_prefix("/embed/ce") == ("/embed/ce", "/")
    assert embed_proxy.match_embed_prefix("/embed/ce/") == ("/embed/ce", "/")
    assert embed_proxy.match_embed_prefix("/embed/ce/api/health") == (
        "/embed/ce",
        "/api/health",
    )
    assert embed_proxy.match_embed_prefix("/embed/okstratr/observer/") == (
        "/embed/okstratr",
        "/observer/",
    )
    assert embed_proxy.match_embed_prefix("/api/health") is None
    assert embed_proxy.match_embed_prefix("/embed/other") is None


def test_build_upstream_url_defaults(monkeypatch):
    monkeypatch.delenv("SWITCHBAY_CE_UPSTREAM", raising=False)
    monkeypatch.delenv("SWITCHBAY_OKSTRATR_UPSTREAM", raising=False)
    assert embed_proxy.build_upstream_url("/embed/ce", "/api/x", "") == (
        "http://127.0.0.1:8766/api/x"
    )
    assert embed_proxy.build_upstream_url(
        "/embed/okstratr", "/observer/", "host=x"
    ) == "http://127.0.0.1:8767/observer/?host=x"


def test_filter_request_headers_injects_host():
    h = embed_proxy.filter_request_headers(
        {"Accept": "application/json", "Host": "127.0.0.1:8765",
         "X-CE-Host": "forged"},
        host_header=embed_proxy.HOST_HEADER_CE,
        host_value="switchbay",
    )
    assert h["X-CE-Host"] == "switchbay"
    assert "Host" not in h
    assert h["Accept"] == "application/json"


def test_upstream_allowed_allowlist(monkeypatch):
    monkeypatch.delenv("SWITCHBAY_CE_UPSTREAM", raising=False)
    monkeypatch.delenv("SWITCHBAY_OKSTRATR_UPSTREAM", raising=False)
    assert embed_proxy.upstream_allowed("http://127.0.0.1:8766/foo")
    assert embed_proxy.upstream_allowed("http://127.0.0.1:8767/bar")
    assert not embed_proxy.upstream_allowed("http://127.0.0.1:9999/x")
    assert not embed_proxy.upstream_allowed("http://example.com/")


def test_env_override_must_still_be_loopback(monkeypatch):
    monkeypatch.setenv("SWITCHBAY_CE_UPSTREAM", "http://evil.example:8766")
    with pytest.raises(embed_proxy.UpstreamNotLoopback):
        embed_proxy.embed_targets()


@pytest.mark.asyncio
async def test_proxy_forwards_with_host_header(monkeypatch):
    """End-to-end: embed proxy hits a loopback stub and injects X-*-Host."""
    seen: dict[str, str] = {}

    async def upstream_handler(request: web.Request) -> web.Response:
        seen["path"] = request.path
        seen["x_ce"] = request.headers.get("X-CE-Host", "")
        seen["x_ok"] = request.headers.get("X-Okstratr-Host", "")
        return web.json_response({"ok": True, "path": request.path})

    up_app = web.Application()
    up_app.router.add_get("/api/health", upstream_handler)
    up_app.router.add_get("/observer/", upstream_handler)
    up_server = TestServer(up_app)
    await up_server.start_server()
    try:
        # Force loopback literal — TestServer may report 0.0.0.0.
        base = f"http://127.0.0.1:{up_server.port}"
        monkeypatch.setenv("SWITCHBAY_CE_UPSTREAM", base)
        monkeypatch.setenv("SWITCHBAY_OKSTRATR_UPSTREAM", base)

        app = web.Application()
        embed_proxy.register_routes(app)
        async with TestClient(TestServer(app)) as client:
            r = await client.get("/embed/ce/api/health")
            assert r.status == 200
            body = await r.json()
            assert body["ok"] is True
            assert seen["path"] == "/api/health"
            assert seen["x_ce"] == "switchbay"

            seen.clear()
            r2 = await client.get("/embed/okstratr/observer/")
            assert r2.status == 200
            assert seen["path"] == "/observer/"
            assert seen["x_ok"] == "switchbay"
    finally:
        await up_server.close()


@pytest.mark.asyncio
async def test_proxy_rejects_if_upstream_env_not_loopback(monkeypatch):
    monkeypatch.setenv("SWITCHBAY_CE_UPSTREAM", "http://203.0.113.1:8766")
    app = web.Application()
    embed_proxy.register_routes(app)
    async with TestClient(TestServer(app)) as client:
        r = await client.get("/embed/ce/api/health")
        assert r.status == 502
        data = await r.json()
        assert "loopback" in data["error"].lower()

def test_client_accepts_gzip():
    assert embed_proxy.client_accepts_gzip({"Accept-Encoding": "gzip, deflate"})
    assert embed_proxy.client_accepts_gzip({"Accept-Encoding": "br, gzip;q=1.0"})
    assert not embed_proxy.client_accepts_gzip({"Accept-Encoding": "identity"})
    assert not embed_proxy.client_accepts_gzip({"Accept-Encoding": "gzip;q=0"})
    assert not embed_proxy.client_accepts_gzip({})


def test_is_compressible_payload():
    assert embed_proxy.is_compressible_payload(
        "application/json", "/data.json", size=5000
    )
    assert embed_proxy.is_compressible_payload(
        "application/json; charset=utf-8", "/x", size=5000
    )
    assert embed_proxy.is_compressible_payload(None, "/static/main.js", size=5000)
    assert not embed_proxy.is_compressible_payload(
        "application/json", "/data.json", size=100
    )
    assert not embed_proxy.is_compressible_payload(
        "image/png", "/logo.png", size=500_000
    )


def test_maybe_gzip_body_compresses_json():
    raw = (b'{"n":' + b'"' + b"x" * 4000 + b'"}')
    headers = {"Content-Type": "application/json", "Cache-Control": "no-store"}
    body, out = embed_proxy.maybe_gzip_body(
        raw, headers, accept_gzip=True, path="/data.json"
    )
    assert out.get("Content-Encoding") == "gzip"
    assert "Accept-Encoding" in out.get("Vary", "")
    assert len(body) < len(raw)
    import gzip as gz
    assert gz.decompress(body) == raw


def test_maybe_gzip_body_skips_when_client_rejects():
    raw = b"{" + b"x" * 4000 + b"}"
    headers = {"Content-Type": "application/json"}
    body, out = embed_proxy.maybe_gzip_body(
        raw, headers, accept_gzip=False, path="/data.json"
    )
    assert "Content-Encoding" not in out
    assert body == raw


@pytest.mark.asyncio
async def test_proxy_gzips_large_json(monkeypatch):
    """Browser Accept-Encoding: gzip → proxy compresses upstream plain JSON."""
    raw = b'{"pages":' + (b"[" + b'"p",' * 2000 + b'null]') + b"}"

    async def upstream_handler(request: web.Request) -> web.Response:
        return web.Response(
            status=200,
            body=raw,
            headers={"Content-Type": "application/json"},
        )

    up_app = web.Application()
    up_app.router.add_get("/data.json", upstream_handler)
    up_server = TestServer(up_app)
    await up_server.start_server()
    try:
        base = f"http://127.0.0.1:{up_server.port}"
        monkeypatch.setenv("SWITCHBAY_CE_UPSTREAM", base)
        monkeypatch.setenv("SWITCHBAY_OKSTRATR_UPSTREAM", base)

        app = web.Application()
        embed_proxy.register_routes(app)
        async with TestClient(TestServer(app)) as client:
            r = await client.get(
                "/embed/ce/data.json",
                headers={"Accept-Encoding": "gzip"},
            )
            assert r.status == 200
            assert r.headers.get("Content-Encoding") == "gzip"
            import gzip as gz
            buf = await r.read()
            # aiohttp TestClient may auto-decompress; prefer raw if encoded.
            if r.headers.get("Content-Encoding") == "gzip":
                # TestClient keeps encoding header; body may already be raw.
                try:
                    decoded = gz.decompress(buf)
                except OSError:
                    decoded = buf  # already decompressed by client
            else:
                decoded = buf
            assert decoded == raw
            assert len(buf) < len(raw) or decoded == raw
    finally:
        await up_server.close()
