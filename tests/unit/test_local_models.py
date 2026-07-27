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
