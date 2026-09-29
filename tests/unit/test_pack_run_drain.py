"""CE pack-queue → Switchbay rail drain (no real LLM seats)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from switchbay import pack_run_drain


def _write_run(ws: Path, run_id: str, **fields) -> Path:
    d = ws / ".workbench" / "pack-runs"
    d.mkdir(parents=True, exist_ok=True)
    rec = {
        "run_id": run_id,
        "pack": "demo",
        "action": "open-deck",
        "path": "vault/raw/deck.pptx",
        "status": "queued",
        "kind": "pack:demo:open-deck",
    }
    rec.update(fields)
    p = d / f"{run_id}.json"
    p.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    return p


async def _wait_inflight_clear(app, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while app.get("pack_run_inflight"):
        if asyncio.get_running_loop().time() > deadline:
            app["pack_run_inflight"].clear()
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)


def test_list_queued_and_write_status(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_run(ws, "run-aaa")
    _write_run(ws, "run-bbb", status="running")
    _write_run(ws, "run-ccc", status="accepted")
    queued = pack_run_drain.list_queued_runs(ws)
    ids = {r["run_id"] for r in queued}
    assert ids == {"run-aaa", "run-ccc"}

    updated = pack_run_drain.write_run_status(
        ws, "run-aaa", "running", note="seated",
    )
    assert updated is not None
    assert updated["status"] == "running"
    assert updated["note"] == "seated"
    disk = json.loads(
        (ws / ".workbench" / "pack-runs" / "run-aaa.json").read_text()
    )
    assert disk["status"] == "running"
    assert disk["note"] == "seated"


def test_build_pack_prompt_matches_handle_pack_action():
    prompt = pack_run_drain.build_pack_prompt(
        "demo", "open-deck", "vault/raw/deck.pptx",
    )
    assert 'load_skill("demo-open-deck")' in prompt
    assert "`vault/raw/deck.pptx`" in prompt
    assert "`demo` pack is active" in prompt


@pytest.mark.asyncio
async def test_drain_once_with_mocked_dispatch(tmp_path: Path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_run(ws, "run-ok")

    monkeypatch.setattr(
        pack_run_drain.packstore,
        "get_pack",
        lambda _ws, name: (
            {"name": name, "enabled": True} if name == "demo" else None
        ),
    )
    monkeypatch.setattr(
        pack_run_drain.skillkit,
        "get_skill",
        lambda _ws, name: (
            MagicMock(name=name) if name == "demo-open-deck" else None
        ),
    )

    seen: list[dict] = []

    async def fake_dispatch(app, **kwargs):
        seen.append(kwargs)
        app.setdefault("runs", {})[kwargs["run_id"]] = {}

    # Avoid importing daemon's error-surface during unit drain.
    monkeypatch.setattr(
        pack_run_drain, "_error_surface", lambda _app, _rid: (lambda _t: None),
    )

    app = {"workspace": ws, "runs": {}, "pack_run_inflight": set()}
    summary = await pack_run_drain.drain_once(app, dispatch_fn=fake_dispatch)
    assert summary["drained"] == ["run-ok"]
    assert summary["errors"] == []

    await _wait_inflight_clear(app)
    assert len(seen) == 1
    assert seen[0]["run_id"] == "run-ok"
    assert "demo-open-deck" in seen[0]["text"]
    disk = json.loads(
        (ws / ".workbench" / "pack-runs" / "run-ok.json").read_text()
    )
    assert disk["status"] == "done"


@pytest.mark.asyncio
async def test_drain_marks_failed_disabled_pack(tmp_path: Path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_run(ws, "run-off", pack="demo", action="open-deck")

    monkeypatch.setattr(
        pack_run_drain.packstore,
        "get_pack",
        lambda *_a, **_k: {"name": "demo", "enabled": False},
    )
    monkeypatch.setattr(
        pack_run_drain.skillkit,
        "get_skill",
        lambda *_a, **_k: MagicMock(),
    )
    monkeypatch.setattr(
        pack_run_drain, "_error_surface", lambda _app, _rid: (lambda _t: None),
    )

    called: list[str] = []

    async def fake_dispatch(app, **kwargs):
        called.append(kwargs["run_id"])

    app = {"workspace": ws, "runs": {}, "pack_run_inflight": set()}
    summary = await pack_run_drain.drain_once(app, dispatch_fn=fake_dispatch)
    assert called == []
    assert any(e["run_id"] == "run-off" for e in summary["errors"])
    disk = json.loads(
        (ws / ".workbench" / "pack-runs" / "run-off.json").read_text()
    )
    assert disk["status"] == "failed"
    assert "not active" in disk.get("note", "")


@pytest.mark.asyncio
async def test_drain_marks_failed_missing_skill(tmp_path: Path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_run(ws, "run-noskill", pack="demo", action="nope")

    monkeypatch.setattr(
        pack_run_drain.packstore,
        "get_pack",
        lambda *_a, **_k: {"name": "demo", "enabled": True},
    )
    monkeypatch.setattr(
        pack_run_drain.skillkit,
        "get_skill",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        pack_run_drain, "_error_surface", lambda _app, _rid: (lambda _t: None),
    )

    async def fake_dispatch(app, **kwargs):
        raise AssertionError("should not dispatch")

    app = {"workspace": ws, "runs": {}, "pack_run_inflight": set()}
    summary = await pack_run_drain.drain_once(app, dispatch_fn=fake_dispatch)
    assert summary["drained"] == []
    assert any(e["run_id"] == "run-noskill" for e in summary["errors"])
    disk = json.loads(
        (ws / ".workbench" / "pack-runs" / "run-noskill.json").read_text()
    )
    assert disk["status"] == "failed"
    assert "skill not found" in disk.get("note", "")


@pytest.mark.asyncio
async def test_drain_dedupes_inflight(tmp_path: Path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_run(ws, "run-dup")
    monkeypatch.setattr(
        pack_run_drain.packstore,
        "get_pack",
        lambda *_a, **_k: {"name": "demo", "enabled": True},
    )
    monkeypatch.setattr(
        pack_run_drain.skillkit,
        "get_skill",
        lambda *_a, **_k: MagicMock(),
    )
    monkeypatch.setattr(
        pack_run_drain, "_error_surface", lambda _app, _rid: (lambda _t: None),
    )

    called: list[str] = []

    async def fake_dispatch(app, **kwargs):
        called.append(kwargs["run_id"])

    # Still queued on disk, but already claimed in-memory.
    app = {
        "workspace": ws,
        "runs": {},
        "pack_run_inflight": {"run-dup"},
    }
    summary = await pack_run_drain.drain_once(app, dispatch_fn=fake_dispatch)
    assert summary["skipped"] == ["run-dup"]
    assert summary["drained"] == []
    assert called == []


@pytest.mark.asyncio
async def test_http_packs_drain_endpoint(tmp_path: Path, monkeypatch):
    from switchbay import daemon

    ws = tmp_path / "ws"
    ws.mkdir()
    _write_run(ws, "run-http")

    monkeypatch.setattr(
        pack_run_drain.packstore,
        "get_pack",
        lambda *_a, **_k: {"name": "demo", "enabled": True},
    )
    monkeypatch.setattr(
        pack_run_drain.skillkit,
        "get_skill",
        lambda *_a, **_k: MagicMock(),
    )
    monkeypatch.setattr(
        pack_run_drain, "_error_surface", lambda _app, _rid: (lambda _t: None),
    )

    async def fake_dispatch(app, **kwargs):
        return None

    async def drain_handler(request: web.Request) -> web.Response:
        summary = await pack_run_drain.drain_once(
            request.app, dispatch_fn=fake_dispatch,
        )
        return web.json_response(summary)

    app = web.Application()
    app["workspace"] = ws
    app["pack_run_inflight"] = set()
    app["runs"] = {}
    app.router.add_post("/api/packs/drain", drain_handler)

    async with TestClient(TestServer(app)) as client:
        resp = await client.post("/api/packs/drain")
        assert resp.status == 200
        data = await resp.json()
        assert data["drained"] == ["run-http"]
        assert data["error_count"] == 0

    await _wait_inflight_clear(app)
    assert hasattr(daemon, "handle_packs_drain")
    assert callable(daemon.handle_packs_drain)
