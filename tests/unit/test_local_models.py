"""Hardware top-3 + registry + GGUF resolve smoke tests."""

from __future__ import annotations

from switchbay import local_models, localllm


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
    assert snap.as_posix() in argv
    assert "--model" in argv


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
