"""cebridge ensure-venv guard: missing workspace .venv → setup before build.

Protects against the post-migrate 0-edge graph (migrate skips .venv by
design; without self-heal, wiki_render emits nodes-only).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from switchbay import cebridge


@pytest.fixture
def wiki_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "wiki").mkdir(parents=True)
    (ws / "wiki" / "index.md").write_text("# hi\n", encoding="utf-8")
    return ws


def test_has_workspace_venv_false_when_missing(wiki_ws: Path) -> None:
    assert cebridge.has_workspace_venv(wiki_ws) is False


def test_venv_python_too_new_detects_314() -> None:
    assert cebridge.venv_python_too_new((3, 14)) is True
    assert cebridge.venv_python_too_new((3, 13)) is False
    assert cebridge.venv_python_too_new((3, 12)) is False
    assert cebridge.venv_python_too_new(None) is False


def test_inject_skill_env_sets_scripts_dir(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "ce"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "setup.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(cebridge, "ce_root", lambda: root)
    env = cebridge.inject_skill_env({})
    assert env["CURIOSITY_ENGINE_SCRIPTS_DIR"] == str(root / "scripts")
    assert env["CURIOSITY_ENGINE_SKILL_DIR"] == str(root)


def test_skill_is_installed_false_without_scripts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cebridge, "ce_root", lambda: tmp_path / "missing-ce")
    assert cebridge.skill_is_installed() is False


def test_has_workspace_venv_true_with_bin_python(wiki_ws: Path) -> None:
    py = wiki_ws / ".venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text("#!/bin/sh\n", encoding="utf-8")
    assert cebridge.has_workspace_venv(wiki_ws) is True


@pytest.mark.asyncio
async def test_ensure_venv_skips_when_present(
    wiki_ws: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    py = wiki_ws / ".venv" / "bin" / "python3"
    py.parent.mkdir(parents=True)
    py.write_text("x", encoding="utf-8")
    setup = AsyncMock(return_value=(True, "ran"))
    monkeypatch.setattr(cebridge, "setup", setup)
    ok, msg = await cebridge.ensure_venv(wiki_ws)
    assert ok is True
    assert "already" in msg
    setup.assert_not_awaited()


@pytest.mark.asyncio
async def test_ensure_venv_runs_setup_when_missing(
    wiki_ws: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup = AsyncMock(return_value=(True, "ok setup"))
    monkeypatch.setattr(cebridge, "setup", setup)
    ok, msg = await cebridge.ensure_venv(wiki_ws)
    assert ok is True
    assert msg == "ok setup"
    setup.assert_awaited_once_with(wiki_ws)


@pytest.mark.asyncio
async def test_build_calls_ensure_venv_when_no_venv(
    wiki_ws: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default ensure_env=True runs setup before viewer.sh when .venv absent."""
    ensure = AsyncMock(return_value=(True, "setup ok"))
    monkeypatch.setattr(cebridge, "ensure_venv", ensure)

    # Fake viewer.sh + successful subprocess + data.json write.
    scripts = wiki_ws / "fake-ce" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "viewer.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(cebridge, "ce_root", lambda: wiki_ws / "fake-ce")

    out_dir = wiki_ws / "cache-out"
    out_dir.mkdir()
    monkeypatch.setattr(cebridge, "output_dir", lambda _ws: out_dir)

    import asyncio

    async def fake_exec(*_a, **_k):
        (out_dir / "data.json").write_text(
            '{"nodes":[{"id":"a","type":"note"}],"edges":[],'
            '"pages":{},"palette":{}}',
            encoding="utf-8",
        )
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", b""))
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    # Also stub disk-truth helpers so they don't need a real CE tree.
    monkeypatch.setattr(cebridge, "resync_types_from_disk", lambda *_a, **_k: None)
    monkeypatch.setattr(cebridge, "inject_deck_nodes", lambda *_a, **_k: None)
    monkeypatch.setattr(cebridge, "_override_palette", lambda *_a, **_k: None)
    monkeypatch.setattr(cebridge, "_backfill_unclassified_types", lambda *_a, **_k: None)
    monkeypatch.setattr("switchbay.wiki_sync.inject_on_disk_pages", lambda *_a, **_k: 0)

    data = await cebridge.build(wiki_ws)
    assert data is not None
    ensure.assert_awaited_once_with(wiki_ws)
    assert len(data.get("nodes") or []) == 1


@pytest.mark.asyncio
async def test_build_skips_ensure_when_disabled(
    wiki_ws: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure = AsyncMock(return_value=(True, "should not run"))
    monkeypatch.setattr(cebridge, "ensure_venv", ensure)

    scripts = wiki_ws / "fake-ce" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "viewer.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(cebridge, "ce_root", lambda: wiki_ws / "fake-ce")

    out_dir = wiki_ws / "cache-out"
    out_dir.mkdir()
    monkeypatch.setattr(cebridge, "output_dir", lambda _ws: out_dir)

    async def fake_exec(*_a, **_k):
        (out_dir / "data.json").write_text(
            '{"nodes":[],"edges":[],"pages":{},"palette":{}}',
            encoding="utf-8",
        )
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", b""))
        return proc

    monkeypatch.setattr(
        __import__("asyncio"), "create_subprocess_exec", fake_exec,
    )
    monkeypatch.setattr(cebridge, "resync_types_from_disk", lambda *_a, **_k: None)
    monkeypatch.setattr(cebridge, "inject_deck_nodes", lambda *_a, **_k: None)
    monkeypatch.setattr(cebridge, "_override_palette", lambda *_a, **_k: None)
    monkeypatch.setattr(cebridge, "_backfill_unclassified_types", lambda *_a, **_k: None)
    monkeypatch.setattr("switchbay.wiki_sync.inject_on_disk_pages", lambda *_a, **_k: 0)

    data = await cebridge.build(wiki_ws, ensure_env=False)
    assert data is not None
    ensure.assert_not_awaited()
