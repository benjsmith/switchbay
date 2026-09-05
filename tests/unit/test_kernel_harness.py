"""Pi and Grok Build implement the same package job."""

from __future__ import annotations

from pathlib import Path

import pytest

from switchbay.kernel import NodeRequest, get_package, pick_harness
from switchbay.kernel.harness_grok import GrokBuildHarness
from switchbay.kernel.harness_pi import PACK_ROOT, pack_extension
from switchbay.kernel.packages import CURATOR_ID
from switchbay.llmgateway import base


class _FakeGrok:
    ID = "grok-build"
    DEFAULT_MODEL = "grok-4.6"

    def __init__(self) -> None:
        self.calls: list[base.ChatRequest] = []

    async def chat_stream(self, req: base.ChatRequest):
        self.calls.append(req)
        yield base.TextChunk(text="curator via grok")
        yield base.DoneChunk(stop_reason="end_turn", input_tokens=3, output_tokens=4)


@pytest.mark.asyncio
async def test_grok_harness_runs_curator_package(tmp_path: Path, monkeypatch):
    fake = _FakeGrok()
    monkeypatch.setattr("switchbay.llmgateway.get", lambda pid: fake)
    pkg = get_package(CURATOR_ID)
    assert pkg is not None
    req = NodeRequest(
        package_id=CURATOR_ID,
        system=pkg.system,
        user="curate this wiki",
        tools=list(pkg.tools),
        provider_id="grok-build",
        model="grok-4.6",
        workspace=tmp_path,
    )
    result = await GrokBuildHarness().run(req)
    assert result.error is None
    assert "curator via grok" in result.text
    assert result.harness == "grok-build"
    assert fake.calls
    assert "CURATE" in (fake.calls[0].system or "") or "curiosity-engine" in (fake.calls[0].system or "").lower()


@pytest.mark.asyncio
async def test_pi_rpc_keeps_stdin_open_until_settled(tmp_path: Path, monkeypatch):
    """EOF on Pi stdin aborts the model turn; the harness must not close early."""
    import sys
    script = tmp_path / "fake_pi.py"
    script.write_text(
        "import json, sys, time\n"
        "sys.stdout.write(json.dumps({'id':'job-1','type':'response','command':'prompt','success':True})+'\\n')\n"
        "sys.stdout.flush()\n"
        "sys.stdout.write(json.dumps({'type':'agent_start'})+'\\n')\n"
        "sys.stdout.flush()\n"
        "# If stdin was closed already, this read returns immediately.\n"
        "import select\n"
        "ready, _, _ = select.select([sys.stdin], [], [], 0.05)\n"
        "if ready and sys.stdin.read(1) == '':\n"
        "    sys.exit(0)  # harness closed stdin too soon\n"
        "sys.stdout.write(json.dumps({'type':'message_update','assistantMessageEvent':{'type':'text_delta','delta':'pong'}})+'\\n')\n"
        "sys.stdout.flush()\n"
        "sys.stdout.write(json.dumps({'type':'agent_settled'})+'\\n')\n"
        "sys.stdout.flush()\n"
        "sys.stdin.read()\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("switchbay.kernel.harness_pi.pi_binary", lambda: sys.executable)
    monkeypatch.setattr(
        "switchbay.kernel.harness_pi.pi_argv",
        lambda req, *, binary, ext: [sys.executable, str(script)],
    )
    from switchbay.kernel.harness_pi import PiHarness
    pkg = get_package(CURATOR_ID)
    result = await PiHarness().run(NodeRequest(
        package_id=CURATOR_ID,
        system=pkg.system if pkg else "",
        user="ping",
        tools=[],
        provider_id="xai",
        model="grok-4.5",
        workspace=tmp_path,
        extra={"timeout_sec": 5},
    ))
    assert result.error is None
    assert "pong" in result.text


@pytest.mark.asyncio
async def test_pi_harness_missing_binary(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("switchbay.kernel.harness_pi.pi_binary", lambda: None)
    from switchbay.kernel.harness_pi import PiHarness
    pkg = get_package(CURATOR_ID)
    result = await PiHarness().run(NodeRequest(
        package_id=CURATOR_ID,
        system=pkg.system if pkg else "",
        user="curate",
        tools=[],
        provider_id="anthropic",
        model="claude-opus-4",
        workspace=tmp_path,
    ))
    assert result.error
    assert "PATH" in result.error


def test_curator_pi_pack_is_on_disk():
    path = pack_extension(CURATOR_ID)
    assert path is not None
    text = path.read_text(encoding="utf-8")
    assert "ce_wave_prime" in text
    assert "switchbay.ce_cli" in text
    assert "no bash" in text.lower() or "no-builtin" in text or "ce_cli" in text
    assert PACK_ROOT.name == "pi_packages"


def test_same_package_two_harnesses():
    assert pick_harness(CURATOR_ID, "grok-build", pi_available=True) == "grok-build"
    assert pick_harness(CURATOR_ID, "anthropic", pi_available=True) == "pi"
    assert pick_harness(CURATOR_ID, "xai", pi_available=True) == "pi"
    assert pick_harness("slideshow", "xai", pi_available=True) == "pi"


def test_pi_argv_uses_xai_api_not_offline(tmp_path: Path):
    from switchbay.kernel.harness_pi import pack_extension, pi_argv, pi_provider_id
    pkg = get_package(CURATOR_ID)
    ext = pack_extension(CURATOR_ID)
    assert ext is not None
    req = NodeRequest(
        package_id=CURATOR_ID,
        system=pkg.system if pkg else "",
        user="curate",
        tools=[],
        provider_id="xai",
        model="grok-4.5",
        workspace=tmp_path,
    )
    argv = pi_argv(req, binary="/tmp/pi", ext=ext)
    assert "--offline" not in argv
    assert argv[argv.index("--provider") + 1] == "xai"
    assert argv[argv.index("--model") + 1] == "grok-4.5"
    assert pi_provider_id("grok-build") is None
    assert pi_provider_id("xai") == "xai"


def test_spawn_env_pythonpath_is_absolute(tmp_path: Path):
    from switchbay.kernel.harness_pi import spawn_env
    req = NodeRequest(
        package_id=CURATOR_ID, system="", user="x", tools=[],
        provider_id="xai", model="grok-4.5", workspace=tmp_path,
    )
    env = spawn_env(req)
    assert env["PYTHONPATH"].endswith("/src")
    assert env["PYTHONPATH"].startswith("/")
    assert env["SWITCHBAY_SRC"] == env["PYTHONPATH"]
    assert "ce_wave_prime" in env["SWITCHBAY_PACKAGE_TOOLS"].split(",")
    assert env["SWITCHBAY_PACKAGE_ID"] == CURATOR_ID


def test_spawn_env_injects_anthropic_key(tmp_path: Path, monkeypatch):
    from switchbay.kernel.harness_pi import spawn_env
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(
        "switchbay.secrets.get",
        lambda pid: "sk-ant-test" if pid == "anthropic" else None,
    )
    req = NodeRequest(
        package_id=CURATOR_ID, system="", user="x", tools=["ce_query"],
        provider_id="anthropic", model="claude-opus-4", workspace=tmp_path,
    )
    env = spawn_env(req)
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-test"
    assert env["SWITCHBAY_PACKAGE_TOOLS"] == "ce_query"


def test_pi_binary_env(monkeypatch, tmp_path: Path):
    fake = tmp_path / "pi"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("SWITCHBAY_PI", str(fake))
    from switchbay.kernel.harness_pi import pi_binary
    assert pi_binary() == str(fake)


def test_probe_arms_are_not_nested():
    from switchbay.kernel.probe import ARMS
    assert ARMS["grok-build"]["provider"] == "grok-build"
    assert ARMS["pi-xai"]["provider"] == "xai"
    assert ARMS["pi-xai"]["harness"] == "pi"
    assert ARMS["pi-xai"]["provider"] != "grok-build"
    assert ARMS["pi-mlx"]["provider"] == "mlx"
    assert ARMS["pi-mlx"]["harness"] == "pi"
    assert ARMS["pi-mlx"]["model"] == "default_model"


def test_slideshow_package_has_ce_query():
    from switchbay.kernel.packages import SLIDESHOW_ID, get_package as gp
    pkg = gp(SLIDESHOW_ID)
    assert pkg is not None
    assert "ce_query" in pkg.tools
    assert "create_slideshow" in pkg.tools
    pack = pack_extension(CURATOR_ID)
    assert pack is not None
    text = pack.read_text(encoding="utf-8")
    assert "ce_query" in text
    assert "create_slideshow" in text
    assert "Type.Object" in text
    assert "Type.Object({}, { additionalProperties: true })" not in text
    assert "heading: S(" in text
    assert "verb: S(" in text
    assert "query: S(" in text
    assert "title: S(" in text
    assert "summary: S(" in text
    assert "html: S(" in text
    assert "ce_lint" in text
    assert "ce_planner" in text
    assert "ce_tables" in text
    assert "ce_figures" in text
    assert "SWITCHBAY_PACKAGE_TOOLS" in text
    assert "research_search" in text
    assert "research_fetch" in text
    assert "registerProvider" in text


def test_pick_harness_mlx_is_pi():
    assert pick_harness(CURATOR_ID, "mlx", pi_available=True) == "pi"


def test_pick_harness_known_package_does_not_force_pi():
    assert pick_harness(CURATOR_ID, "github_copilot", pi_available=True) == "rail"


def test_pi_user_opt_out_blocks_availability(tmp_path: Path, monkeypatch):
    from switchbay import admin_policy, llm_config
    from switchbay.kernel.harness import pi_available, pi_harness_permitted
    monkeypatch.setenv("SWITCHBAY_PROFILE", "open")
    admin_policy.reset_cache()
    llm_config.set_pi_harness(False)
    assert llm_config.get_pi_harness() is False
    assert pi_harness_permitted() is False
    assert pi_available() is False
    llm_config.set_pi_harness(True)
    assert pi_harness_permitted() is True


def test_pi_harness_admin_flag_blocks_availability(monkeypatch):
    from switchbay import admin_policy
    from switchbay.kernel.harness import pi_available, pi_harness_permitted
    monkeypatch.setenv("SWITCHBAY_PROFILE", "enterprise")
    admin_policy.reset_cache()
    assert pi_harness_permitted() is False
    assert pi_available() is False
    admin_policy.reset_cache()


def test_pi_argv_mlx_provider(tmp_path: Path):
    from switchbay.kernel.harness_pi import pack_extension, pi_argv, spawn_env
    pkg = get_package(CURATOR_ID)
    ext = pack_extension(CURATOR_ID)
    assert ext is not None
    req = NodeRequest(
        package_id=CURATOR_ID,
        system=pkg.system if pkg else "",
        user="curate",
        tools=[],
        provider_id="mlx",
        model="default_model",
        workspace=tmp_path,
        extra={"mlx_url": "http://127.0.0.1:8888/v1", "mlx_model": "default_model"},
    )
    argv = pi_argv(req, binary="/tmp/pi", ext=ext)
    assert argv[argv.index("--provider") + 1] == "mlx"
    assert argv[argv.index("--model") + 1] == "default_model"
    env = spawn_env(req)
    assert env["SWITCHBAY_MLX_URL"] == "http://127.0.0.1:8888/v1"
    assert env["SWITCHBAY_MLX_MODEL"] == "default_model"


@pytest.mark.asyncio
async def test_pi_cancel_reaps_process(tmp_path: Path, monkeypatch):
    import os
    import sys
    import time
    script = tmp_path / "hang_pi.py"
    pid_file = tmp_path / "pid.txt"
    script.write_text(
        "import os, sys, time\n"
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
        "sys.stdout.write('{\"type\":\"agent_start\"}\\n')\n"
        "sys.stdout.flush()\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("switchbay.kernel.harness_pi.pi_binary", lambda: sys.executable)
    monkeypatch.setattr(
        "switchbay.kernel.harness_pi.pi_argv",
        lambda req, *, binary, ext: [sys.executable, str(script)],
    )
    from switchbay.kernel.harness_pi import PiHarness
    import asyncio
    pkg = get_package(CURATOR_ID)
    task = asyncio.create_task(PiHarness().run(NodeRequest(
        package_id=CURATOR_ID,
        system=pkg.system if pkg else "",
        user="hang",
        tools=[],
        provider_id="xai",
        model="grok-4.5",
        workspace=tmp_path,
        extra={"timeout_sec": 20},
    )))
    for _ in range(50):
        if pid_file.is_file() and pid_file.read_text().strip():
            break
        await asyncio.sleep(0.05)
    child = int(pid_file.read_text().strip())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    deadline = time.time() + 3
    while time.time() < deadline:
        try:
            os.kill(child, 0)
        except OSError:
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError(f"pi child {child} still alive after cancel")


def test_research_package_on_same_pack():
    from switchbay.kernel.packages import RESEARCH_ID
    pkg = get_package(RESEARCH_ID)
    assert pkg is not None
    assert pkg.pi_extension == "curator/index.ts"
    assert "research_search" in pkg.tools
