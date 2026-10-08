"""Graph is Curiosity Engine's viewer: the shell offers it only when CE is installed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from aiohttp.test_utils import make_mocked_request

from switchbay import cebridge, daemon, media_settings


def _ce(tmp_path: Path, *, viewer: bool) -> Path:
    root = tmp_path / "ce"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "planner.py").write_text("", encoding="utf-8")
    if viewer:
        (root / "scripts" / "viewer_server.py").write_text("", encoding="utf-8")
    return root


def test_graph_unavailable_without_ce_viewer(tmp_path: Path, monkeypatch):
    root = _ce(tmp_path, viewer=False)
    monkeypatch.setattr(cebridge, "ce_root", lambda: root)
    ws = tmp_path / "ws"
    (ws / "wiki").mkdir(parents=True)
    assert cebridge.graph_availability(ws) == {"installed": False, "has_wiki": True}


def test_graph_available_with_ce_viewer(tmp_path: Path, monkeypatch):
    root = _ce(tmp_path, viewer=True)
    monkeypatch.setattr(cebridge, "ce_root", lambda: root)
    ws = tmp_path / "ws"
    ws.mkdir()
    assert cebridge.graph_availability(ws) == {"installed": True, "has_wiki": False}
    (ws / "wiki").mkdir()
    assert cebridge.graph_availability(ws) == {"installed": True, "has_wiki": True}


@pytest.mark.asyncio
async def test_settings_reports_ce_graph_and_keeps_agents_toggle(tmp_path: Path, monkeypatch):
    root = _ce(tmp_path, viewer=True)
    monkeypatch.setattr(cebridge, "ce_root", lambda: root)

    monkeypatch.setattr(media_settings, "status_payload", lambda: {})
    ws = tmp_path / "ws"
    (ws / "wiki").mkdir(parents=True)
    req = make_mocked_request("GET", "/api/settings", app={"workspace": ws})
    resp = await daemon.handle_settings_get(req)
    body = json.loads(resp.body)
    assert body["ce_graph"] == {"installed": True, "has_wiki": True}
    # The okstratr Agents toggle keeps its key and default.
    assert body["proxied_skill_embeds"] is False
