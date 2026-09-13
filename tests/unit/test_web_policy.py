"""Workspace web policy: default off, per-call, never blanket."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from switchbay import daemon, web_policy, workspaces


def test_default_off(tmp_path: Path):
    assert web_policy.is_enabled(tmp_path) is False
    assert web_policy.effective_enabled(tmp_path) is False


def test_toggle_persists_per_workspace(tmp_path: Path):
    web_policy.save(tmp_path, enabled=True)
    assert web_policy.is_enabled(tmp_path) is True
    other = tmp_path / "other"
    other.mkdir()
    assert web_policy.is_enabled(other) is False


def test_public_view_reflects_toggle(tmp_path: Path):
    view = web_policy.public_view(tmp_path)
    assert view["enabled"] is False
    assert view["admin_allows"] is True
    assert view["requested"] is False
    web_policy.save(tmp_path, enabled=True)
    view = web_policy.public_view(tmp_path)
    assert view["enabled"] is True
    assert view["requested"] is True


@pytest.mark.asyncio
async def test_web_policy_post_targets_originating_workspace(tmp_path, monkeypatch):
    a = tmp_path / "alpha"
    b = tmp_path / "beta"
    a.mkdir()
    b.mkdir()
    monkeypatch.setattr(workspaces, "is_within_home", lambda p: True)
    monkeypatch.setattr(
        workspaces, "resolve_path",
        lambda s, **k: Path(s).expanduser().resolve(),
    )
    broadcasts: list[dict] = []

    async def fake_broadcast(_app, msg):
        broadcasts.append(msg)

    monkeypatch.setattr(daemon, "_broadcast", fake_broadcast)
    web_policy.save(a, enabled=False)
    web_policy.save(b, enabled=True)

    class Req:
        app = {"workspace": b, "ws_clients": set()}
        rel_url = SimpleNamespace(query={})
        headers: dict[str, str] = {}

        async def json(self):
            return {"enabled": True, "workspace": str(a)}

    resp = await daemon.handle_web_policy_post(Req())  # type: ignore[arg-type]
    import json as _json
    data = _json.loads(resp.body)
    assert data["ok"] is True
    assert data["enabled"] is True
    assert Path(data["workspace"]).resolve() == a.resolve()
    assert web_policy.is_enabled(a) is True
    assert web_policy.is_enabled(b) is True, "POST must not write the newly active workspace"
    assert broadcasts
    msg0 = broadcasts[0]
    # protocol.custom wraps as AG-UI CUSTOM with name/value
    inner = msg0.get("value") if msg0.get("type") == "CUSTOM" else msg0
    assert (inner or {}).get("type") == "web_policy" or msg0.get("name") == "web_policy"


@pytest.mark.asyncio
async def test_web_policy_get_is_scoped_to_query_workspace(tmp_path, monkeypatch):
    a = tmp_path / "alpha"
    b = tmp_path / "beta"
    a.mkdir()
    b.mkdir()
    monkeypatch.setattr(workspaces, "is_within_home", lambda p: True)
    monkeypatch.setattr(
        workspaces, "resolve_path",
        lambda s, **k: Path(s).expanduser().resolve(),
    )
    web_policy.save(a, enabled=False)
    web_policy.save(b, enabled=True)

    class Req:
        app = {"workspace": b}
        rel_url = SimpleNamespace(query={"workspace": str(a)})
        headers: dict[str, str] = {}

    resp = await daemon.handle_web_policy_get(Req())  # type: ignore[arg-type]
    import json as _json
    data = _json.loads(resp.body)
    assert data["enabled"] is False
    assert Path(data["workspace"]).resolve() == a.resolve()
