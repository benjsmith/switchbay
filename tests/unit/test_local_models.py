"""Hardware top-3 + registry + GGUF resolve smoke tests."""

from __future__ import annotations

import json
import os
import signal
from pathlib import Path

import pytest

from switchbay import local_models, localllm
from switchbay.llmgateway import ChatRequest, llamacpp
from switchbay import daemon


def test_plan_top3_returns_up_to_three():
    for ram in (12.0, 18.0, 32.0, 64.0, 96.0):
        plan = local_models.plan_top3(ram)
        assert plan["ram_gb"] == round(ram, 1)
        if plan["ok"]:
            assert 1 <= len(plan["candidates"]) <= 3
            ids = [c["id"] for c in plan["candidates"]]
            assert len(ids) == len(set(ids))


def test_plan_top3_low_ram_prefers_small():
    plan = local_models.plan_top3(10.0)
    if plan["ok"]:
        labels = " ".join(c["id"] for c in plan["candidates"])
        assert "3b" in labels or "ollama" in labels or "llama32" in labels


def test_catalog_lookup():
    assert local_models.catalog_by_id("ornith-9b") is not None
    assert local_models.catalog_by_id("nope") is None


def test_registry_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(local_models, "_registry_path", lambda: tmp_path / "reg.json")
    local_models.register_installed("test-m", {"label": "Test", "backend": "llamacpp"})
    assert local_models.is_installed("test-m")
    out = local_models.unregister("test-m")
    assert out["ok"]
    assert not local_models.is_installed("test-m")


def test_mlx_cache_bytes_counts_in_progress_blobs(tmp_path, monkeypatch):
    hub = tmp_path / "hub"
    repo_dir = hub / "models--mlx-community--Qwen3-8B-4bit"
    blobs = repo_dir / "blobs"
    blobs.mkdir(parents=True)
    (blobs / "partial").write_bytes(b"x" * 4096)
    monkeypatch.setenv("HUGGINGFACE_HUB_CACHE", str(hub))
    monkeypatch.setattr(local_models, "_hf_hub_caches", lambda: [hub])
    assert local_models.mlx_cache_bytes("mlx-community/Qwen3-8B-4bit") == 4096


def test_scan_cached_mlx(tmp_path, monkeypatch):
    hub = tmp_path / "hub"
    snap = hub / "models--mlx-community--Qwen3-8B-4bit" / "snapshots" / "abc"
    snap.mkdir(parents=True)
    (snap / "config.json").write_text("{}", encoding="utf-8")
    (snap / "model.safetensors").write_bytes(b"x")
    monkeypatch.setenv("HUGGINGFACE_HUB_CACHE", str(hub))
    monkeypatch.setattr(local_models, "_hf_hub_caches", lambda: [hub])
    found = local_models.scan_cached_mlx()
    hit = next(m for m in found if m.get("repo") == "mlx-community/Qwen3-8B-4bit")
    assert hit["local_path"] == str(snap)
    assert "4-bit" in hit["label"]
    assert local_models.is_installed("mlx:mlx-community/qwen3-8b-4bit")


def test_scan_cached_mlx_finds_sandboxed_hub(tmp_path, monkeypatch):
    """Sandboxed Mac apps keep HF weights in a container cache."""
    empty = tmp_path / "empty-hub"
    empty.mkdir()
    boxed = (
        tmp_path / "Containers" / "com.example.sandbox" / "Data"
        / "Library" / "Caches" / "huggingface" / "hub"
    )
    snap = boxed / "models--mlx-community--Qwen3-4B-4bit" / "snapshots" / "deadbeef"
    snap.mkdir(parents=True)
    (snap / "config.json").write_text("{}", encoding="utf-8")
    (snap / "model.safetensors").write_bytes(b"x")
    (boxed / "models--mlx-community--Qwen3-4B-4bit" / "refs").mkdir(parents=True)
    (boxed / "models--mlx-community--Qwen3-4B-4bit" / "refs" / "main").write_text(
        "deadbeef", encoding="utf-8")
    monkeypatch.setenv("HUGGINGFACE_HUB_CACHE", str(empty))
    monkeypatch.setattr(
        local_models, "_hf_hub_caches",
        lambda: [empty, boxed],
    )
    found = local_models.scan_cached_mlx()
    hit = next(m for m in found if "Qwen3-4B-4bit" in str(m.get("repo")))
    assert hit["local_path"] == str(snap)
    assert hit["source"] == "app-cache"
    argv = localllm.server_args("/bin/mlx_lm.server", {
        "backend": "mlx", "port": 8888, **hit,
    })
    assert str(snap) in argv or snap.as_posix() in argv
    assert "--model" in argv


def test_mlx_wire_model_id_never_sends_alias():
    """mlx_lm.server 404s on Switch Bay aliases; chat must send the
    CLI mapping (default_model) or a persisted served_model."""
    req = ChatRequest(messages=[{"role": "user", "content": "hi"}], model="Qwen3_4bit")
    assert llamacpp.wire_model_id(req, {"backend": "mlx", "alias": "Qwen3_4bit"}) == "default_model"
    assert llamacpp.wire_model_id(
        req, {"backend": "mlx", "served_model": "/weights/qwen", "alias": "Qwen3_4bit"},
    ) == "/weights/qwen"
    assert llamacpp.wire_model_id(
        req, {"backend": "llamacpp", "alias": "ornith"},
    ) == "Qwen3_4bit"


def test_llamacpp_wire_model_falls_back_to_alias():
    req = ChatRequest(messages=[{"role": "user", "content": "hi"}])
    assert llamacpp.wire_model_id(req, {"alias": "ornith"}) == "ornith"


def test_curator_profile_stays_off_the_user_prompt():
    sys_txt = daemon._curator_profile_system("Treat X as an entity.")
    assert "Treat X as an entity." in sys_txt
    assert "Workspace curator profile" in sys_txt
    # The old helper concatenated onto the user message; that is gone.
    assert not hasattr(daemon, "_with_curator_profile")


def test_load_config_accepts_mlx(tmp_path, monkeypatch):
    p = tmp_path / "localllm.json"
    p.write_text(
        '{"backend":"mlx","repo":"mlx-community/Qwen","port":8742}',
        encoding="utf-8",
    )
    monkeypatch.setattr(localllm, "_config_path", lambda: p)
    cfg = localllm.load_config()
    assert cfg is not None
    assert cfg["backend"] == "mlx"
    assert cfg["repo"] == "mlx-community/Qwen"


def test_load_config_rejects_empty_dict(tmp_path, monkeypatch):
    p = tmp_path / "localllm.json"
    p.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(localllm, "_config_path", lambda: p)
    assert localllm.load_config() is None


def test_fuzzy_gguf_match_exact_and_case():
    files = ["Ornith-1.0-9B-Q4_K_M.gguf", "other.bin"]
    assert local_models._fuzzy_gguf_match(  # noqa: SLF001
        "ornith-1.0-9b-Q4_K_M.gguf", files,
    ) == "Ornith-1.0-9B-Q4_K_M.gguf"


def test_fuzzy_gguf_match_quant_only():
    files = ["model-Q5_K_M.gguf"]
    assert local_models._fuzzy_gguf_match(  # noqa: SLF001
        "oldname-Q5_K_M.gguf", files,
    ) == "model-Q5_K_M.gguf"


def test_allocate_port_skips_used(tmp_path, monkeypatch):
    monkeypatch.setattr(local_models, "_registry_path", lambda: tmp_path / "reg.json")
    monkeypatch.setattr(localllm, "load_config", lambda: None)
    local_models.register_installed(
        "a", {"label": "A", "backend": "llamacpp", "port": localllm.PORT},
    )
    p = local_models.allocate_port()
    assert p != localllm.PORT
    assert p in localllm.PORT_POOL


def test_watch_log_path_mlx_is_not_the_ornith_slot(tmp_path, monkeypatch):
    """Watch used to always tail llama-server.log even when MLX was
    serving — that's the Ornith bind-fail the user saw on :8878."""
    monkeypatch.setattr(localllm.statedir, "state_root", lambda: tmp_path)
    mlx_cfg = {
        "backend": "mlx",
        "candidate_id": "mlx:mlx-community/Qwen3-4B-4bit",
        "alias": "Qwen3_4B_4bit",
        "repo": "mlx-community/Qwen3-4B-4bit",
        "port": 8888,
    }
    mlx_log = localllm.watch_log_path(mlx_cfg)
    ornith_log = localllm.server_log_path()
    assert mlx_log != ornith_log
    assert mlx_log.name != "llama-server.log"
    assert "Qwen3" in mlx_log.name or "mlx" in mlx_log.name
    # Explicit id (what Settings now POSTs) matches spawn's slot key.
    assert localllm.watch_log_path(None, mlx_cfg["candidate_id"]) == mlx_log
    assert localllm.server_process_label(mlx_cfg) == "mlx-server"
    assert localllm.server_process_label(None, candidate_id=mlx_cfg["candidate_id"]) == "mlx-server"
    assert localllm.watch_log_path({
        "file": "/models/ornith.gguf", "candidate_id": "ornith-9b",
    }) == ornith_log
    assert localllm.server_process_label({"file": "/models/ornith.gguf"}) == "llama-server"


def test_managed_server_cmd_and_port_match():
    mlx = (
        "/uv/tools/mlx-lm/bin/python /Users/benj/.local/bin/mlx_lm.server "
        "--host 127.0.0.1 --port 8888 --model /weights/qwen"
    )
    llama = (
        "/opt/homebrew/bin/llama-server -m /models/ornith.gguf "
        "--host 127.0.0.1 --port 8878 --alias ornith"
    )
    assert localllm._is_managed_server_cmd(mlx)
    assert localllm._is_managed_server_cmd(llama)
    assert not localllm._is_managed_server_cmd("python -m switchbay serve")
    assert localllm._cmd_targets_port(mlx, 8888)
    assert not localllm._cmd_targets_port(mlx, 8878)
    assert localllm._cmd_targets_port(llama, 8878)


def test_managed_pids_for_port_ignores_unrelated(monkeypatch):
    monkeypatch.setattr(localllm, "_ps_pid_args", lambda: [
        (23147, "python mlx_lm.server --port 8888 --model qwen"),
        (72915, "llama-server -m ornith.gguf --port 8878"),
        (99, "python -m http.server 8888"),
        (os.getpid(), "mlx_lm.server --port 8888"),
    ])
    assert localllm._managed_pids_for_port(8888) == [23147]
    assert localllm._managed_pids_for_port(8878) == [72915]


@pytest.mark.asyncio
async def test_free_managed_port_terms_then_kills(monkeypatch):
    state = {"pids": [23147, 29467], "kills": []}

    def fake_pids(_port):
        return list(state["pids"])

    def fake_kill(pid, sig):
        state["kills"].append((pid, sig))
        sigkill = getattr(signal, "SIGKILL", None)
        if sig == sigkill or pid in state["pids"]:
            state["pids"] = [p for p in state["pids"] if p != pid]

    monkeypatch.setattr(localllm, "_managed_pids_for_port", fake_pids)
    monkeypatch.setattr(localllm.os, "kill", fake_kill)
    await localllm._free_managed_port(8888)
    assert state["pids"] == []
    assert (23147, signal.SIGTERM) in state["kills"]
    assert (29467, signal.SIGTERM) in state["kills"]


def test_running_servers_includes_orphan_llama(monkeypatch):
    """Settings listed Ornith as 'not serving' because the daemon
    only tracked children it spawned; the Aug leftover on :8878 must
    still show up so Stop is offered."""
    monkeypatch.setattr(localllm, "_ps_pid_args", lambda: [
        (72915, (
            "/opt/homebrew/bin/llama-server -m /models/ornith.gguf "
            "--host 127.0.0.1 --port 8878 --alias ornith"
        )),
        (30713, (
            "python mlx_lm.server --host 127.0.0.1 --port 8888 "
            "--model /weights/qwen"
        )),
    ])
    monkeypatch.setattr(localllm, "_pids_listening_on", lambda port: {
        8878: {72915},
        8888: {30713},
    }.get(port, set()))
    app: dict = {"localllm_servers": {}}
    installed = [
        {
            "id": "ornith-9b",
            "port": 8878,
            "alias": "ornith",
            "label": "Ornith 1.0 9B",
            "file": "/models/ornith.gguf",
            "backend": "llamacpp",
        },
        {
            "id": "mlx:qwen",
            "port": 8888,
            "label": "Qwen3-4B-4bit",
            "backend": "mlx",
        },
    ]
    rows = localllm.running_servers(app, installed)
    by_id = {r["id"]: r for r in rows}
    assert by_id["ornith-9b"]["alive"] is True
    assert by_id["ornith-9b"]["pid"] == 72915
    assert by_id["ornith-9b"]["orphan"] is True
    assert by_id["ornith-9b"]["port"] == 8878
    assert by_id["mlx:qwen"]["alive"] is True
    assert by_id["mlx:qwen"]["pid"] == 30713


def test_running_servers_ignores_failed_bind_zombie(monkeypatch):
    monkeypatch.setattr(localllm, "_ps_pid_args", lambda: [
        (99, "llama-server -m /models/ornith.gguf --port 8878"),
    ])
    monkeypatch.setattr(localllm, "_pids_listening_on", lambda _port: set())
    rows = localllm.running_servers({"localllm_servers": {}}, [
        {"id": "ornith-9b", "port": 8878, "file": "/models/ornith.gguf"},
    ])
    assert rows == []


@pytest.mark.asyncio
async def test_stop_server_frees_orphan_port(monkeypatch):
    freed: list[int] = []

    async def fake_free(port):
        freed.append(port)

    monkeypatch.setattr(localllm, "_free_managed_port", fake_free)
    await localllm.stop_server({}, "ornith-9b", port=8878)
    assert freed == [8878]


def test_port_from_cmd_and_match_installed():
    cmd = "llama-server -m /models/ornith.gguf --port 8878 --alias ornith"
    assert localllm._port_from_cmd(cmd) == 8878
    assert localllm._port_from_cmd("mlx_lm.server --port=8888 --model q") == 8888
    hit = localllm._match_installed(cmd, 8878, [
        {"id": "qwen-coder", "port": 8879},
        {"id": "ornith-9b", "port": 8878, "file": "/models/ornith.gguf"},
    ])
    assert hit is not None and hit["id"] == "ornith-9b"


def test_mlx_server_args_are_mlx_lm_not_llama(tmp_path):
    argv = localllm.server_args("/opt/homebrew/bin/python", {
        "backend": "mlx",
        "port": 8888,
        "repo": "mlx-community/Qwen3-4B-4bit",
        "candidate_id": "mlx:mlx-community/Qwen3-4B-4bit",
    })
    joined = " ".join(argv)
    assert "--model" in argv
    assert "mlx-community/Qwen3-4B-4bit" in joined
    assert "-m" not in argv
    assert ".gguf" not in joined
    assert "--alias" not in argv


@pytest.mark.asyncio
async def test_handle_localllm_watch_tails_mlx_slot(tmp_path, monkeypatch):
    mlx_cfg = {
        "backend": "mlx",
        "candidate_id": "mlx:mlx-community/Qwen3-4B-4bit",
        "alias": "Qwen3_4B_4bit",
        "port": 8888,
    }
    monkeypatch.setattr(localllm.statedir, "state_root", lambda: tmp_path)
    monkeypatch.setattr(localllm, "load_config", lambda: mlx_cfg)

    captured: dict = {}

    async def fake_spawn(app, thread_id, name=None, **kwargs):
        captured["name"] = name
        captured["thread_id"] = thread_id
        return object()

    async def fake_broadcast(_app, _msg):
        return None

    monkeypatch.setattr(daemon, "_spawn_pty_for_thread", fake_spawn)
    monkeypatch.setattr(daemon, "_broadcast", fake_broadcast)
    monkeypatch.setattr(
        daemon.conversations, "new_thread",
        lambda *a, **k: "tid-watch",
    )
    writes: list[bytes] = []
    monkeypatch.setattr(
        daemon.terminals, "write_input",
        lambda _sess, data: writes.append(data),
    )

    class _Req:
        content_length = 0
        app = {"workspace": tmp_path}

    resp = await daemon.handle_localllm_watch(_Req())
    assert resp.status == 200
    body = json.loads(resp.body)
    assert body["label"] == "mlx-server"
    assert body["thread_id"] == "tid-watch"
    log_name = Path(body["log"]).name
    assert log_name != "llama-server.log"
    assert captured["name"] == "mlx-server"
    assert writes and b"tail -n 200 -f" in writes[0]
    assert log_name.encode() in writes[0]
