"""Two-phase, cache-excluding, iCloud-safe workspace move.

Guards against the data-loss incident where the old `shutil.move`
copied iCloud-dataless cache files (`.venv`, `.curator/uv-cache`) as
0 bytes and then deleted the good source."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from switchbay import statedir, workspaces


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Isolate the registry + home under tmp; treat everything as
    within-home so the guards don't reject tmp paths."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(workspaces, "is_within_home", lambda p: True)
    return tmp_path


def _register_inactive(ws: Path) -> None:
    """Register `ws` but leave nothing active — migrate refuses the
    active workspace, and these tests exercise the move itself."""
    workspaces.register(ws)
    data = workspaces.load()
    data["active"] = None
    workspaces.save(data)


def _make_ws(root: Path) -> Path:
    """A workspace with real data + heavy regenerable caches."""
    ws = root / "src-ws"
    (ws / "wiki").mkdir(parents=True)
    (ws / "wiki" / "page.md").write_text("real content", encoding="utf-8")
    (ws / "CLAUDE.md").write_text("charter", encoding="utf-8")
    # Regenerable caches that must NOT be copied.
    (ws / ".venv" / "lib").mkdir(parents=True)
    (ws / ".venv" / "lib" / "big.so").write_text("x" * 1000, encoding="utf-8")
    (ws / ".curator" / "uv-cache" / "pkg").mkdir(parents=True)
    (ws / ".curator" / "uv-cache" / "pkg" / "wheel").write_text("y", encoding="utf-8")
    (ws / ".curator" / "profile.md").write_text("keep me", encoding="utf-8")
    return ws


def test_migrate_copies_data_excludes_caches_keeps_source(home):
    ws = _make_ws(home)
    _register_inactive(ws)
    dest_home = home / "Workspaces"

    res = workspaces.migrate_into_home(ws, dest_home)
    assert isinstance(res, dict), res
    new = Path(res["new"])

    # Source is RETAINED (two-phase — no auto-delete).
    assert ws.is_dir()
    assert res["cleanup_pending"] is True
    # Real data copied…
    assert (new / "wiki" / "page.md").read_text(encoding="utf-8") == "real content"
    assert (new / ".curator" / "profile.md").read_text(encoding="utf-8") == "keep me"
    # …caches NOT copied.
    assert not (new / ".venv").exists()
    assert not (new / ".curator" / "uv-cache").exists()
    # Registry repointed to the new location.
    paths = workspaces.load()["paths"]
    assert str(new.resolve()) in paths
    assert str(ws.resolve()) not in paths


def test_cleanup_removes_source_only_after_confirm(home):
    ws = _make_ws(home)
    _register_inactive(ws)
    res = workspaces.migrate_into_home(ws, home / "Workspaces")
    assert isinstance(res, dict)

    out = workspaces.cleanup_migrated_source(Path(res["old"]), Path(res["new"]))
    assert isinstance(out, dict), out
    assert not ws.exists()          # source gone
    assert Path(res["new"]).is_dir()  # new copy intact


def test_cleanup_refuses_if_new_not_registered(home):
    ws = _make_ws(home)
    _register_inactive(ws)
    # A new path that was never registered → must refuse (safety).
    err = workspaces.cleanup_migrated_source(ws, home / "Workspaces" / "src-ws")
    assert isinstance(err, str)
    assert ws.is_dir()  # nothing deleted


def test_migrate_refuses_when_kept_file_is_dataless(home, monkeypatch):
    ws = _make_ws(home)
    _register_inactive(ws)
    # Pretend the real wiki page is an un-downloaded iCloud placeholder.
    target = (ws / "wiki" / "page.md").resolve()
    monkeypatch.setattr(
        statedir, "is_dataless", lambda p: Path(p).resolve() == target,
    )
    res = workspaces.migrate_into_home(ws, home / "Workspaces")
    assert isinstance(res, str)
    assert "aren't downloaded" in res
    assert not (home / "Workspaces" / "src-ws").exists()  # nothing copied
    assert ws.is_dir()


def test_migrate_ignores_dataless_inside_excluded_caches(home, monkeypatch):
    """A dataless file inside .venv/uv-cache must NOT block the move —
    those dirs are skipped entirely."""
    ws = _make_ws(home)
    _register_inactive(ws)
    cache_file = (ws / ".venv" / "lib" / "big.so").resolve()
    monkeypatch.setattr(
        statedir, "is_dataless", lambda p: Path(p).resolve() == cache_file,
    )
    res = workspaces.migrate_into_home(ws, home / "Workspaces")
    assert isinstance(res, dict), res  # succeeded despite dataless cache file


@pytest.mark.asyncio
async def test_post_migrate_env_rebuild_setup_then_build(
    home, monkeypatch,
):
    """Background post-migrate task: setup → build → cache + broadcast."""
    from switchbay import daemon

    dest = home / "Workspaces" / "moved-ws"
    dest.mkdir(parents=True)
    (dest / "wiki").mkdir()

    setup = AsyncMock(return_value=(True, "setup ok"))
    build = AsyncMock(return_value={
        "nodes": [{"id": "n1"}],
        "edges": [{"source": "n1", "target": "n1"}],
        "pages": {},
    })
    monkeypatch.setattr(daemon.cebridge, "setup", setup)
    monkeypatch.setattr(daemon.cebridge, "build", build)

    broadcasts: list[dict] = []

    async def fake_broadcast(_app, msg):
        broadcasts.append(msg)

    monkeypatch.setattr(daemon, "_broadcast", fake_broadcast)
    monkeypatch.setattr(daemon, "_log_event", lambda *a, **k: None)

    app: dict = {"graph_data_per_ws": {}, "workspace": home / "other"}
    await daemon._post_migrate_env_rebuild(app, dest)

    setup.assert_awaited_once_with(dest)
    build.assert_awaited_once()
    # ensure_env=False — setup already ran
    assert build.await_args.kwargs.get("ensure_env") is False
    cached = app["graph_data_per_ws"][str(dest.resolve())]
    assert len(cached["edges"]) == 1
    # start notice + files_changed + ready notice (at minimum)
    assert len(broadcasts) >= 2
