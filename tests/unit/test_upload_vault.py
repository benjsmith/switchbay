"""POST /api/upload-vault: the graph sidebar's raw upload into vault/raw/.

Mirrors CE's viewer_server.py route of the same name, which edit.js was
forked against.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest
from aiohttp import FormData, MultipartWriter, web
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request

from switchbay import daemon

ROOT = Path(__file__).resolve().parents[2]
EDIT_JS = ROOT / "frontend" / "src" / "widgets" / "graph" / "static" / "edit.js"


def _app(ws: Path) -> web.Application:
    app = web.Application()
    app["workspace"] = ws
    app.router.add_post("/api/upload-vault", daemon.handle_upload_vault)
    return app


def _form(*files: tuple[str, bytes]) -> FormData:
    # Same shape edit.js builds: one `file` field per chosen file. Browsers
    # send the filename unescaped, so don't let aiohttp percent-encode it.
    form = FormData(quote_fields=False)
    for name, data in files:
        form.add_field("file", data, filename=name,
                       content_type="application/octet-stream")
    return form


def test_edit_js_posts_to_a_registered_daemon_route(tmp_path: Path) -> None:
    src = EDIT_JS.read_text(encoding="utf-8")
    m = re.search(r"fetch\('(/api/upload-vault)',\s*\{\s*method:\s*'POST'", src)
    assert m, "edit.js no longer posts the upload to /api/upload-vault"
    app = daemon.build_app(tmp_path)
    req = make_mocked_request("POST", m.group(1), app=app)

    match = asyncio.run(app.router.resolve(req))
    assert match.http_exception is None
    assert match.handler is daemon.handle_upload_vault


async def test_multi_file_upload_lands_in_vault_raw(tmp_path: Path) -> None:
    async with TestClient(TestServer(_app(tmp_path))) as client:
        resp = await client.post(
            "/api/upload-vault",
            data=_form(("notes.txt", b"hello"), ("b c.md", b"# second\n")),
        )
        assert resp.status == 200
        body = await resp.json()
    assert body == {"ok": True, "saved": ["notes.txt", "b_c.md"]}
    raw = tmp_path / "vault" / "raw"
    assert (raw / "notes.txt").read_bytes() == b"hello"
    assert (raw / "b_c.md").read_bytes() == b"# second\n"
    # No staging/temp leftovers.
    assert sorted(p.name for p in raw.iterdir()) == ["b_c.md", "notes.txt"]


async def test_same_name_replaces_existing_file(tmp_path: Path) -> None:
    raw = tmp_path / "vault" / "raw"
    raw.mkdir(parents=True)
    (raw / "a.txt").write_bytes(b"old")
    async with TestClient(TestServer(_app(tmp_path))) as client:
        resp = await client.post("/api/upload-vault", data=_form(("a.txt", b"new")))
        assert resp.status == 200
    assert (raw / "a.txt").read_bytes() == b"new"


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        # Same outputs as CE's viewer_server._safe_vault_filename.
        ("report.pdf", "report.pdf"),
        ("my report (v2).pdf", "my_report__v2_.pdf"),
        ("../../escape.txt", "escape.txt"),
        ("/etc/passwd", "passwd"),
        ("résumé.docx", "r_sum_.docx"),
        ("a-b_c.d.txt", "a-b_c.d.txt"),
    ],
)
def test_sanitiser_matches_ce_rules(given: str, expected: str) -> None:
    assert daemon._safe_vault_filename(given) == expected


@pytest.mark.parametrize("given", [".env", "..", "dir/.hidden"])
def test_sanitiser_refuses_dot_names(given: str) -> None:
    with pytest.raises(ValueError):
        daemon._safe_vault_filename(given)


async def test_traversal_name_stays_inside_vault_raw(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    async with TestClient(TestServer(_app(ws))) as client:
        resp = await client.post(
            "/api/upload-vault", data=_form(("../../escape.txt", b"x")),
        )
        assert resp.status == 200
        assert (await resp.json())["saved"] == ["escape.txt"]
    assert (ws / "vault" / "raw" / "escape.txt").read_bytes() == b"x"
    assert not (tmp_path / "escape.txt").exists()


async def test_dot_filename_is_refused(tmp_path: Path) -> None:
    async with TestClient(TestServer(_app(tmp_path))) as client:
        resp = await client.post("/api/upload-vault", data=_form((".env", b"x")))
        assert resp.status == 400
        assert (await resp.json())["error"] == "invalid filename"
    assert not (tmp_path / "vault" / "raw" / ".env").exists()


async def test_size_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert daemon.UPLOAD_VAULT_MAX_BYTES == 50 * 1024 * 1024
    monkeypatch.setattr(daemon, "UPLOAD_VAULT_MAX_BYTES", 1000)
    async with TestClient(TestServer(_app(tmp_path))) as client:
        ok = await client.post("/api/upload-vault", data=_form(("ok.bin", b"x" * 1000)))
        assert ok.status == 200
        big = await client.post("/api/upload-vault", data=_form(("big.bin", b"x" * 1001)))
        assert big.status == 413
        assert "too large" in (await big.json())["error"]
    raw = tmp_path / "vault" / "raw"
    assert (raw / "ok.bin").stat().st_size == 1000
    assert sorted(p.name for p in raw.iterdir()) == ["ok.bin"]


async def test_rejects_requests_without_files(tmp_path: Path) -> None:
    async with TestClient(TestServer(_app(tmp_path))) as client:
        resp = await client.post("/api/upload-vault", json={"file": "x"})
        assert resp.status == 400
        assert (await resp.json())["error"] == "multipart/form-data required"

        only_text = MultipartWriter("form-data")
        only_text.append("just text").set_content_disposition("form-data", name="note")
        resp = await client.post("/api/upload-vault", data=only_text)
        assert resp.status == 400
        assert (await resp.json())["error"] == "no file part with filename"

        # Plain fields next to a file are ignored, as in CE.
        mixed = FormData()
        mixed.add_field("note", "ignored")
        mixed.add_field("file", b"x", filename="a.txt")
        resp = await client.post("/api/upload-vault", data=mixed)
        assert resp.status == 200
        assert (await resp.json())["saved"] == ["a.txt"]
