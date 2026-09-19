"""CE ingest-queue → Switchbay local_ingest / rail drain (no real CE/LLM)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from switchbay import ingest_run_drain


def _stage_file(ws: Path, rel: str, data: bytes = b"# hello\n") -> str:
    p = ws / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return rel


def _write_run(ws: Path, run_id: str, **fields) -> Path:
    d = ws / ".workbench" / "ingest-runs"
    d.mkdir(parents=True, exist_ok=True)
    vault_path = fields.pop("vault_path", "vault/raw/note.md")
    if "vault_path" not in fields and vault_path:
        _stage_file(ws, vault_path)
    rec = {
        "run_id": run_id,
        "status": "queued",
        "kind": "ingest-upload",
        "vault_path": vault_path,
        "filename": Path(vault_path).name,
        "size": 8,
        "mode": "staged",
    }
    rec.update(fields)
    p = d / f"{run_id}.json"
    p.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    return p


async def _wait_inflight_clear(app, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while app.get("ingest_run_inflight"):
        if asyncio.get_running_loop().time() > deadline:
            app["ingest_run_inflight"].clear()
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)


def test_list_queued_and_write_status(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_run(ws, "run-aaa")
    _write_run(ws, "run-bbb", status="running")
    _write_run(ws, "run-ccc", status="accepted")
    queued = ingest_run_drain.list_queued_runs(ws)
    ids = {r["run_id"] for r in queued}
    assert ids == {"run-aaa", "run-ccc"}

    updated = ingest_run_drain.write_run_status(
        ws, "run-aaa", "running", note="seated",
    )
    assert updated is not None
    assert updated["status"] == "running"
    assert updated["note"] == "seated"
    disk = json.loads(
        (ws / ".workbench" / "ingest-runs" / "run-aaa.json").read_text()
    )
    assert disk["status"] == "running"


def test_run_path_refuses_escape(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    p = ingest_run_drain.run_path(ws, "../../etc/passwd")
    assert p.parent == ingest_run_drain.runs_dir(ws)
    assert p.name == "passwd.json"


def test_resolve_vault_path_refuses_escape(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "vault" / "raw").mkdir(parents=True)
    err = ingest_run_drain.resolve_run_vault_path(
        ws, {"vault_path": "../../etc/passwd"},
    )
    assert isinstance(err, str)
    assert "escape" in err.lower() or "invalid" in err.lower()

    err2 = ingest_run_drain.resolve_run_vault_path(
        ws, {"vault_path": "vault/raw/../../etc/passwd"},
    )
    assert isinstance(err2, str)

    err3 = ingest_run_drain.resolve_run_vault_path(
        ws, {"vault_path": "bad\x00.md"},
    )
    assert isinstance(err3, str)

    rel = _stage_file(ws, "vault/raw/ok.md")
    ok = ingest_run_drain.resolve_run_vault_path(ws, {"vault_path": rel})
    assert isinstance(ok, tuple)
    assert ok[0] == "vault/raw/ok.md"


def test_wants_rail_only_when_metadata_opts_in():
    assert ingest_run_drain.wants_rail({"mode": "staged"}) is False
    assert ingest_run_drain.wants_rail({}) is False
    assert ingest_run_drain.wants_rail({"mode": "llm"}) is True
    assert ingest_run_drain.wants_rail({"drain": "rail"}) is True
    assert ingest_run_drain.wants_rail({"prefer_rail": True}) is True
    assert ingest_run_drain.wants_rail({"use_llm": "yes"}) is True


@pytest.mark.asyncio
async def test_drain_once_local_ingest_happy(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_run(ws, "run-ok")

    seen: list[str] = []

    def fake_local(workspace, vault_path, rec):
        seen.append(vault_path)
        return {"ok": 1, "considered": 1, "failed": 0, "file": vault_path}

    app = {"workspace": ws, "runs": {}, "ingest_run_inflight": set()}
    summary = await ingest_run_drain.drain_once(
        app, local_ingest_fn=fake_local,
    )
    assert summary["drained"] == ["run-ok"]
    assert summary["errors"] == []

    await _wait_inflight_clear(app)
    assert seen == ["vault/raw/note.md"]
    disk = json.loads(
        (ws / ".workbench" / "ingest-runs" / "run-ok.json").read_text()
    )
    assert disk["status"] == "done"
    assert disk.get("drain_via") == "local_ingest"


@pytest.mark.asyncio
async def test_drain_marks_failed_on_escape(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    d = ws / ".workbench" / "ingest-runs"
    d.mkdir(parents=True)
    (d / "run-esc.json").write_text(
        json.dumps({
            "run_id": "run-esc",
            "status": "queued",
            "vault_path": "../../etc/passwd",
            "mode": "staged",
        })
        + "\n",
        encoding="utf-8",
    )

    called: list[str] = []

    def fake_local(workspace, vault_path, rec):
        called.append(vault_path)
        return {"ok": 1, "considered": 1}

    app = {"workspace": ws, "runs": {}, "ingest_run_inflight": set()}
    summary = await ingest_run_drain.drain_once(
        app, local_ingest_fn=fake_local,
    )
    assert called == []
    assert any(e["run_id"] == "run-esc" for e in summary["errors"])
    disk = json.loads((d / "run-esc.json").read_text())
    assert disk["status"] == "failed"
    assert "escape" in disk.get("note", "").lower() or "invalid" in disk.get(
        "note", ""
    ).lower()


@pytest.mark.asyncio
async def test_drain_rail_when_metadata_opts_in(tmp_path: Path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_run(ws, "run-rail", mode="llm")

    local_called: list[str] = []
    rail_seen: list[dict] = []

    def fake_local(workspace, vault_path, rec):
        local_called.append(vault_path)
        return {"ok": 1, "considered": 1}

    async def fake_dispatch(app, **kwargs):
        rail_seen.append(kwargs)
        app.setdefault("runs", {})[kwargs["run_id"]] = {}

    monkeypatch.setattr(
        ingest_run_drain, "_error_surface", lambda _app, _rid: (lambda _t: None),
    )

    app = {"workspace": ws, "runs": {}, "ingest_run_inflight": set()}
    summary = await ingest_run_drain.drain_once(
        app,
        dispatch_fn=fake_dispatch,
        local_ingest_fn=fake_local,
    )
    assert summary["drained"] == ["run-rail"]
    await _wait_inflight_clear(app)
    assert local_called == []
    assert len(rail_seen) == 1
    assert rail_seen[0]["run_id"] == "run-rail"
    assert "vault/raw/note.md" in rail_seen[0]["text"]
    disk = json.loads(
        (ws / ".workbench" / "ingest-runs" / "run-rail.json").read_text()
    )
    assert disk["status"] == "done"
    assert disk.get("drain_via") == "rail"


@pytest.mark.asyncio
async def test_drain_local_failure_marks_failed(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_run(ws, "run-bad")

    def fake_local(workspace, vault_path, rec):
        return {"error": "pypdf_missing"}

    app = {"workspace": ws, "runs": {}, "ingest_run_inflight": set()}
    summary = await ingest_run_drain.drain_once(
        app, local_ingest_fn=fake_local,
    )
    assert summary["drained"] == ["run-bad"]
    await _wait_inflight_clear(app)
    disk = json.loads(
        (ws / ".workbench" / "ingest-runs" / "run-bad.json").read_text()
    )
    assert disk["status"] == "failed"
    assert "pypdf_missing" in disk.get("note", "")


@pytest.mark.asyncio
async def test_drain_dedupes_inflight(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_run(ws, "run-dup")

    called: list[str] = []

    def fake_local(workspace, vault_path, rec):
        called.append(vault_path)
        return {"ok": 1, "considered": 1}

    app = {
        "workspace": ws,
        "runs": {},
        "ingest_run_inflight": {"run-dup"},
    }
    summary = await ingest_run_drain.drain_once(
        app, local_ingest_fn=fake_local,
    )
    assert summary["skipped"] == ["run-dup"]
    assert summary["drained"] == []
    assert called == []


@pytest.mark.asyncio
async def test_http_ingest_drain_endpoint(tmp_path: Path):
    from switchbay import daemon

    ws = tmp_path / "ws"
    ws.mkdir()
    _write_run(ws, "run-http")

    def fake_local(workspace, vault_path, rec):
        return {"ok": 1, "considered": 1, "failed": 0}

    async def drain_handler(request: web.Request) -> web.Response:
        summary = await ingest_run_drain.drain_once(
            request.app, local_ingest_fn=fake_local,
        )
        return web.json_response(summary)

    app = web.Application()
    app["workspace"] = ws
    app["ingest_run_inflight"] = set()
    app["runs"] = {}
    app.router.add_post("/api/ingest/drain", drain_handler)

    async with TestClient(TestServer(app)) as client:
        resp = await client.post("/api/ingest/drain")
        assert resp.status == 200
        data = await resp.json()
        assert data["drained"] == ["run-http"]
        assert data["error_count"] == 0

    await _wait_inflight_clear(app)
    assert hasattr(daemon, "handle_ingest_drain")
    assert callable(daemon.handle_ingest_drain)
