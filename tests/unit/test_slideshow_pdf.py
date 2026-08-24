"""Slideshow PDF renderer contract (16:9 pages, resolved assets)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from aiohttp import web

from switchbay import daemon, slideshow_html


def test_pdf_renderer_script_exists_and_prints_16x9():
    renderer = (
        Path(__file__).resolve().parents[2]
        / "frontend" / "scripts" / "render-slideshow-pdf.mjs"
    )
    assert renderer.is_file()
    text = renderer.read_text(encoding="utf-8")
    assert "13.333in" in text
    assert "7.5in" in text
    assert "printBackground" in text
    assert "preferCSSPageSize" in text
    assert "document.fonts.ready" in text


@pytest.mark.asyncio
async def test_pdf_handler_writes_vault_export(tmp_path: Path, monkeypatch):
    slideshow_html.write_slideshow(
        tmp_path,
        "demo",
        title="Demo",
        slides=[{"layout": "title", "heading": "Hi"}],
    )
    staging = tmp_path / "vault" / "exports" / ".demo.rendering.pdf"

    class _Proc:
        returncode = 0

        async def communicate(self):
            staging.parent.mkdir(parents=True, exist_ok=True)
            staging.write_bytes(b"%PDF-1.4 test\n")
            return b"ok", None

        def kill(self) -> None:
            return None

    async def _exec(*_args, **_kwargs):
        return _Proc()

    async def _broadcast(*_args, **_kwargs):
        return None

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _exec)
    monkeypatch.setattr(daemon.shutil, "which", lambda _name: "/usr/bin/node")
    monkeypatch.setattr(daemon, "_broadcast", _broadcast)

    app = web.Application()
    app["workspace"] = tmp_path
    app["daemon_port"] = 8765
    app.router.add_post("/api/slideshows/pdf", daemon.handle_slideshow_pdf)

    from aiohttp.test_utils import TestClient, TestServer

    async with TestServer(app) as server:
        async with TestClient(server) as client:
            response = await client.post("/api/slideshows/pdf", json={"slug": "demo"})
            body = await response.json()
            assert response.status == 200, body
            assert body["ok"] is True
            assert body["path"] == "vault/exports/demo.pdf"
    assert (tmp_path / "vault" / "exports" / "demo.pdf").is_file()
    assert not staging.exists()
