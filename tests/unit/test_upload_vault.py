"""POST /api/upload-vault: raw uploads into vault/raw/.

Used by the Files toolbar uploader and by the CE Graph sidebar `+`
(both open UploadVaultDialog). Mirrors CE's viewer_server.py route of the
same name, which CE's own edit.js posts to.
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
UPLOAD_TS = ROOT / "frontend" / "src" / "lib" / "uploadVault.ts"


def _app(ws: Path) -> web.Application:
    app = web.Application()
    app["workspace"] = ws
    app.router.add_post("/api/upload-vault", daemon.handle_upload_vault)
    return app


def _form(*files: tuple[str, bytes]) -> FormData:
    # Same shape uploadVault.ts (and CE's edit.js) builds: one `file` field per chosen file. Browsers
    # send the filename unescaped, so don't let aiohttp percent-encode it.
    form = FormData(quote_fields=False)
    for name, data in files:
        form.add_field("file", data, filename=name,
                       content_type="application/octet-stream")
    return form


def test_uploader_posts_to_a_registered_daemon_route(tmp_path: Path) -> None:
    src = UPLOAD_TS.read_text(encoding="utf-8")
    m = re.search(r'UPLOAD_VAULT_URL\s*=\s*"(/api/upload-vault)"', src)
    assert m, "uploadVault.ts no longer posts the upload to /api/upload-vault"
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


# ── ingest option ─────────────────────────────────────────────────────

from switchbay import ingest_run_drain  # noqa: E402


def _ingest_form(ingest: str, *files: tuple[str, bytes]) -> FormData:
    form = FormData(quote_fields=False)
    form.add_field("ingest", ingest)
    for name, data in files:
        form.add_field("file", data, filename=name,
                       content_type="application/octet-stream")
    return form


@pytest.fixture
def kicks(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    calls: list[object] = []
    monkeypatch.setattr(ingest_run_drain, "kick_drain", calls.append)
    return calls


class _FakeProvider:
    def __init__(self, ready: bool) -> None:
        self.ready = ready

    def has_key(self) -> bool:
        return self.ready


def _backend(monkeypatch: pytest.MonkeyPatch, *, ce: bool, provider: bool) -> None:
    monkeypatch.setattr(daemon.cebridge, "ce_scripts_available", lambda: ce)
    monkeypatch.setattr(daemon, "_resolve_default_provider", lambda: "fake")
    monkeypatch.setattr(
        daemon.llmgateway, "get",
        lambda pid: _FakeProvider(provider and pid == "fake"),
    )


async def test_ingest_false_saves_without_queueing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kicks: list[object],
) -> None:
    _backend(monkeypatch, ce=True, provider=True)
    async with TestClient(TestServer(_app(tmp_path))) as client:
        resp = await client.post(
            "/api/upload-vault", data=_ingest_form("false", ("a.md", b"# a")),
        )
        assert resp.status == 200
        body = await resp.json()
    assert body == {"ok": True, "saved": ["a.md"]}
    assert (tmp_path / "vault" / "raw" / "a.md").is_file()
    assert not ingest_run_drain.runs_dir(tmp_path).exists()
    assert kicks == []


async def test_ingest_with_ce_queues_local_ingest_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kicks: list[object],
) -> None:
    _backend(monkeypatch, ce=True, provider=False)
    app = _app(tmp_path)
    async with TestClient(TestServer(app)) as client:
        resp = await client.post(
            "/api/upload-vault",
            data=_ingest_form("true", ("a.md", b"# a"), ("b c.csv", b"x,y\n1,2\n")),
        )
        assert resp.status == 200
        body = await resp.json()
    assert body["saved"] == ["a.md", "b_c.csv"]
    ing = body["ingest"]
    assert ing["backend"] == "local_ingest" and ing["queued"] is True
    assert [r["vault_path"] for r in ing["runs"]] == [
        "vault/raw/a.md", "vault/raw/b_c.csv",
    ]
    assert len(kicks) == 1  # one drain pass for the whole upload
    queued = ingest_run_drain.list_queued_runs(tmp_path)
    assert {r["run_id"] for r in queued} == {r["run_id"] for r in ing["runs"]}
    assert all(r["mode"] == "staged" for r in queued)
    assert not any(ingest_run_drain.wants_rail(r) for r in queued)

    # The existing drain sends them through local_ingest, not an agent.
    local_calls: list[str] = []
    dispatched: list[str] = []

    def fake_local(workspace, vault_path, rec):
        local_calls.append(vault_path)
        return {"ok": 1, "considered": 1, "failed": 0}

    async def fake_dispatch(app, **kw):
        dispatched.append(kw["run_id"])

    app["runs"] = {}
    summary = await ingest_run_drain.drain_once(
        app, local_ingest_fn=fake_local, dispatch_fn=fake_dispatch,
    )
    assert sorted(summary["drained"]) == sorted(r["run_id"] for r in ing["runs"])
    for _ in range(50):
        if not app.get("ingest_run_inflight"):
            break
        await asyncio.sleep(0.02)
    assert sorted(local_calls) == ["vault/raw/a.md", "vault/raw/b_c.csv"]
    assert dispatched == []


async def test_ingest_without_ce_uses_rail_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kicks: list[object],
) -> None:
    _backend(monkeypatch, ce=False, provider=True)
    async with TestClient(TestServer(_app(tmp_path))) as client:
        resp = await client.post(
            "/api/upload-vault", data=_ingest_form("on", ("notes.txt", b"hi")),
        )
        assert resp.status == 200
        ing = (await resp.json())["ingest"]
    assert ing["backend"] == "agent" and ing["queued"] is True
    queued = ingest_run_drain.list_queued_runs(tmp_path)
    assert len(queued) == 1 and ingest_run_drain.wants_rail(queued[0])
    assert queued[0]["vault_path"] == "vault/raw/notes.txt"
    assert len(kicks) == 1


async def test_ingest_without_any_backend_saves_and_explains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kicks: list[object],
) -> None:
    _backend(monkeypatch, ce=False, provider=False)
    async with TestClient(TestServer(_app(tmp_path))) as client:
        resp = await client.post(
            "/api/upload-vault", data=_ingest_form("true", ("notes.txt", b"hi")),
        )
        assert resp.status == 200
        body = await resp.json()
    assert body["saved"] == ["notes.txt"]
    assert (tmp_path / "vault" / "raw" / "notes.txt").read_bytes() == b"hi"
    ing = body["ingest"]
    assert ing["backend"] == "none" and ing["queued"] is False
    assert ing["runs"] == []
    assert "not ingested" in ing["message"]
    assert not ingest_run_drain.runs_dir(tmp_path).exists()
    assert kicks == []


async def test_oversized_ingest_field_is_not_buffered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kicks: list[object],
) -> None:
    _backend(monkeypatch, ce=True, provider=True)
    async with TestClient(TestServer(_app(tmp_path))) as client:
        resp = await client.post(
            "/api/upload-vault",
            data=_ingest_form("x" * 200_000 + "true", ("a.md", b"# a")),
        )
        assert resp.status == 200
        body = await resp.json()
    assert body == {"ok": True, "saved": ["a.md"]}
    assert kicks == []
