from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from switchbay import admin_policy, cebridge


@pytest.fixture
def bundled_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    install = tmp_path / "install"
    script = install / "vendor" / "curiosity-engine" / "scripts" / "setup.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SWITCHBAY_PROFILE", "enterprise")
    monkeypatch.delenv("SWITCHBAY_ADMIN_POLICY", raising=False)
    monkeypatch.setattr(admin_policy, "install_root", lambda: install)
    monkeypatch.setattr(cebridge, "ce_root", lambda: script.parents[1])
    monkeypatch.setattr(
        cebridge, "install_skill",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not install")),
    )
    monkeypatch.setattr(
        cebridge, "ensure_pinned_venv", AsyncMock(return_value=(True, "venv ready")),
    )
    admin_policy.reset_cache()
    yield workspace, script
    admin_policy.reset_cache()


@pytest.mark.asyncio
async def test_enterprise_setup_runs_only_bundled_script_noninteractively(
    bundled_setup, monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, script = bundled_setup
    captured: dict = {}

    class Process:
        returncode = 0

        async def communicate(self):
            return b"ready", b""

        def kill(self):
            raise AssertionError("setup should not time out")

    async def spawn(*argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return Process()

    monkeypatch.setenv("VIRTUAL_ENV", "/untrusted/venv")
    monkeypatch.setenv("PYTHONPATH", "/untrusted/pythonpath")
    monkeypatch.setattr(cebridge.asyncio, "create_subprocess_exec", spawn)

    ok, output = await cebridge.setup(workspace)

    assert ok and "ready" in output
    assert captured["argv"] == ("bash", str(script.resolve()), "--yes")
    assert captured["kwargs"]["cwd"] == str(workspace.resolve())
    assert captured["kwargs"]["env"]["CURIOSITY_ENGINE_NONINTERACTIVE"] == "1"
    assert "VIRTUAL_ENV" not in captured["kwargs"]["env"]
    assert "PYTHONPATH" not in captured["kwargs"]["env"]


@pytest.mark.asyncio
async def test_enterprise_setup_rejects_nonbundled_script(
    bundled_setup, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, _script = bundled_setup
    other = tmp_path / "global-skill"
    (other / "scripts").mkdir(parents=True)
    (other / "scripts" / "setup.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(cebridge, "ce_root", lambda: other)
    spawn = AsyncMock()
    monkeypatch.setattr(cebridge.asyncio, "create_subprocess_exec", spawn)

    ok, output = await cebridge.setup(workspace)

    assert ok is False
    assert "only the bundled, resolved" in output
    spawn.assert_not_awaited()


@pytest.mark.asyncio
async def test_enterprise_setup_honours_explicit_admin_denial(
    bundled_setup, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, _script = bundled_setup
    policy = tmp_path / "admin.json"
    policy.write_text(json.dumps({
        "profile": "enterprise",
        "features": {"ce_bundled_setup": False},
    }), encoding="utf-8")
    monkeypatch.setenv("SWITCHBAY_ADMIN_POLICY", str(policy))
    admin_policy.reset_cache()

    ok, output = await cebridge.setup(workspace)

    assert ok is False
    assert "ce_bundled_setup" in output


@pytest.mark.asyncio
async def test_enterprise_setup_timeout_is_killed(
    bundled_setup, monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, _script = bundled_setup

    class Process:
        returncode = None

        def __init__(self):
            self.calls = 0
            self.killed = False

        async def communicate(self):
            self.calls += 1
            if self.calls == 1:
                raise asyncio.TimeoutError
            return b"", b""

        def kill(self):
            self.killed = True

    process = Process()

    async def spawn(*_argv, **_kwargs):
        return process

    monkeypatch.setattr(cebridge.asyncio, "create_subprocess_exec", spawn)

    ok, output = await cebridge.setup(workspace)

    assert ok is False
    assert "timed out after 15 minutes" in output
    assert process.killed is True
