"""Live-search / free-text-install layer of local_models.

These cover the pure logic (no network): quant parsing, sidecar-file
rejection, RAM-fit selection, the off-task heuristic, and the removal of
the catalog's hardcoded family bias. The HF calls themselves are stubbed.
"""

from __future__ import annotations

import pytest

from switchbay import local_models as lm


# ── quant parsing ───────────────────────────────────────────────────

@pytest.mark.parametrize(("fname", "want"), [
    ("Qwen3.6-27B-Q4_K_M.gguf", "Q4_K_M"),
    ("Ornith-1.0-35B-UD-Q5_K_M.gguf", "Q5_K_M"),
    ("model.Q8_0.gguf", "Q8_0"),
    ("Llama-3.2-3B-Instruct-IQ4_XS.gguf", "IQ4_XS"),
    ("Ornith-1.0-35B-MXFP4_MOE.gguf", "MXFP4_MOE"),
    ("something-without-a-quant.gguf", None),
])
def test_parse_quant(fname, want):
    assert lm.parse_quant(fname) == want


# ── file selection ──────────────────────────────────────────────────

def _tree(rows):
    return [{"type": "file", "path": p, "size": s} for p, s in rows]


def test_gguf_files_rejects_projector_sidecars(monkeypatch):
    """A repo's `mmproj-F32.gguf` is a multimodal projector, not the
    model — and its high-precision tag makes it win a naive best-quant
    pick. Regression: `resolve_repo_candidate` once served one."""
    monkeypatch.setattr(lm, "_hf_get", lambda *a, **k: _tree([
        ("mmproj-F32.gguf", 1_840_000_000),
        ("Qwen3.6-27B-Q5_K_M.gguf", 19_510_000_000),
        ("Qwen3.6-27B-Q4_K_M.gguf", 16_000_000_000),
    ]))
    files = lm.gguf_files("owner/repo")
    assert [f["file"] for f in files] == [
        "Qwen3.6-27B-Q5_K_M.gguf", "Qwen3.6-27B-Q4_K_M.gguf",
    ]


def test_gguf_files_collapses_shards(monkeypatch):
    monkeypatch.setattr(lm, "_hf_get", lambda *a, **k: _tree([
        ("big-Q8_0-00001-of-00003.gguf", 10_000_000_000),
        ("big-Q8_0-00002-of-00003.gguf", 10_000_000_000),
        ("big-Q8_0-00003-of-00003.gguf", 5_000_000_000),
    ]))
    files = lm.gguf_files("owner/repo")
    assert len(files) == 1
    assert files[0]["size_gb"] == pytest.approx(25.0, abs=0.01)
    assert len(files[0]["parts"]) == 3
    assert files[0]["file"].endswith("00001-of-00003.gguf")


def test_gguf_files_drops_incomplete_shard_sets(monkeypatch):
    monkeypatch.setattr(lm, "_hf_get", lambda *a, **k: _tree([
        ("big-Q8_0-00001-of-00003.gguf", 10_000_000_000),
        ("big-Q8_0-00002-of-00003.gguf", 10_000_000_000),
    ]))
    assert lm.gguf_files("owner/repo") == []


def test_pick_gguf_respects_ram_budget():
    files = [
        {"file": "a-Q8_0.gguf", "quant": "Q8_0", "size_gb": 36.0, "rank": 3},
        {"file": "a-Q5_K_M.gguf", "quant": "Q5_K_M", "size_gb": 19.5, "rank": 8},
        {"file": "a-Q4_K_M.gguf", "quant": "Q4_K_M", "size_gb": 16.0, "rank": 12},
    ]
    # 48 GB → budget 21.6 GB: best quant that fits is Q5_K_M.
    assert lm.pick_gguf_for_ram(files, 48.0)["quant"] == "Q5_K_M"
    # 128 GB → everything fits, take the best.
    assert lm.pick_gguf_for_ram(files, 128.0)["quant"] == "Q8_0"
    # 8 GB → nothing fits; fall back to the smallest rather than refuse.
    assert lm.pick_gguf_for_ram(files, 8.0)["quant"] == "Q4_K_M"


def test_pick_gguf_honours_explicit_quant():
    files = [
        {"file": "a-Q8_0.gguf", "quant": "Q8_0", "size_gb": 36.0, "rank": 3},
        {"file": "a-Q4_K_M.gguf", "quant": "Q4_K_M", "size_gb": 16.0, "rank": 12},
    ]
    assert lm.pick_gguf_for_ram(files, 48.0, "Q8_0")["quant"] == "Q8_0"
    assert lm.pick_gguf_for_ram(files, 48.0, "Q2_K") is None


# ── ranking ─────────────────────────────────────────────────────────

def test_score_carries_no_family_preference():
    """Regression: `agent` family used to get a flat +8, which pinned
    one catalog model to the top of every list on any machine ≥24 GB."""
    base = {"min_ram_gb": 16, "ideal_ram_gb": 32, "backend": "llamacpp"}
    agent = {**base, "family": "agent"}
    general = {**base, "family": "general"}
    coding = {**base, "family": "coding"}
    scores = {lm._score(e, 48.0) for e in (agent, general, coding)}
    assert len(scores) == 1, "family must not influence hardware fit"


def test_ram_envelope_tracks_weight_size():
    small = lm._ram_envelope(4.0)
    big = lm._ram_envelope(20.0)
    assert small["min_ram_gb"] < big["min_ram_gb"]
    assert big["min_ram_gb"] == pytest.approx(44.4, abs=0.1)


def test_popularity_bonus_is_log_scaled_and_bounded():
    tiny = lm._popularity_bonus({"downloads": 10, "likes": 1})
    huge = lm._popularity_bonus({"downloads": 50_000_000, "likes": 100_000})
    assert tiny < huge <= 18.0


# ── recommendation gate ─────────────────────────────────────────────

@pytest.mark.parametrize("repo", [
    "HauhauCS/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive",
    "DavidAU/Qwen3.6-27B-Fable-Fusion-711-Uncensored-Heretic-NM-DAU-NEO-MAX-MTP-GGUF",
    "someone/Model-abliterated-GGUF",
])
def test_off_task_finetunes_are_flagged(repo):
    assert lm.looks_off_task(repo) is True


@pytest.mark.parametrize("repo", [
    "unsloth/Qwen3.6-27B-GGUF",
    "bartowski/Llama-3.2-3B-Instruct-GGUF",
    "deepreinforce-ai/Ornith-1.0-9B-GGUF",
])
def test_mainline_models_are_not_flagged(repo):
    assert lm.looks_off_task(repo) is False


def test_curated_search_drops_off_task_and_unknown_publishers(monkeypatch):
    monkeypatch.setattr(lm, "_hf_get", lambda *a, **k: [
        {"id": "unsloth/Qwen3.6-27B-GGUF", "downloads": 3_000_000, "tags": []},
        {"id": "rando/Model-Uncensored-GGUF", "downloads": 900_000, "tags": []},
        {"id": "whoever/Plain-GGUF", "downloads": 500_000, "tags": []},
    ])
    curated = [h["repo"] for h in lm.hf_search_gguf(curated=True, limit=10)]
    assert curated == ["unsloth/Qwen3.6-27B-GGUF"]
    # …but free-text search stays ungated: the user can install anything.
    everything = [h["repo"] for h in lm.hf_search_gguf(curated=False, limit=10)]
    assert len(everything) == 3


# ── free-text resolution ────────────────────────────────────────────

def test_resolve_rejects_non_repo_ids():
    out = lm.resolve_repo_candidate("just-a-name")
    assert out["ok"] is False and "owner/name" in out["error"]


def test_resolve_reports_missing_gguf_helpfully(monkeypatch):
    monkeypatch.setattr(lm, "_hf_get", lambda *a, **k: [])
    monkeypatch.setattr(lm, "hf_model_info", lambda repo: None)
    out = lm.resolve_repo_candidate("mlx-community/Qwen3.6-27B-4bit", ram=48)
    assert out["ok"] is False and "GGUF" in out["error"]


def test_resolve_builds_installable_candidate(monkeypatch):
    monkeypatch.setattr(lm, "_hf_get", lambda *a, **k: _tree([
        ("Qwen3.6-27B-Q5_K_M.gguf", 19_510_000_000),
    ]))
    monkeypatch.setattr(lm, "hf_model_info", lambda repo: {"downloads": 725_170})
    monkeypatch.setattr(lm, "is_installed", lambda cid: False)
    out = lm.resolve_repo_candidate("unsloth/Qwen3.6-27B-GGUF", ram=48)
    assert out["ok"] is True
    assert out["quant"] == "Q5_K_M"
    assert out["backend"] == "llamacpp"
    assert out["id"] == "hf:unsloth/qwen3.6-27b-gguf"
    assert out["fits"] is True
    assert out["min_ram_gb"] > 0


def test_resolve_ollama_validates_tag_shape(monkeypatch):
    monkeypatch.setattr(lm.shutil, "which", lambda n: "/usr/local/bin/ollama")
    monkeypatch.setattr(lm, "ollama_list_tags", set)
    monkeypatch.setattr(lm, "load_registry", lambda: {"installed": {}})
    assert lm.resolve_ollama_candidate("qwen3.6:27b")["ok"] is True
    assert lm.resolve_ollama_candidate("bad tag!")["ok"] is False


def test_resolve_ollama_without_ollama_installed(monkeypatch):
    monkeypatch.setattr(lm.shutil, "which", lambda n: None)
    out = lm.resolve_ollama_candidate("qwen3.6:27b")
    assert out["ok"] is False and "ollama.com" in out["error"]


# ── MLX ─────────────────────────────────────────────────────────────

def test_mlx_status_is_honest_off_apple_silicon(monkeypatch):
    monkeypatch.setattr(lm, "mlx_supported", lambda: False)
    monkeypatch.setattr(lm.sys, "platform", "linux")
    st = lm.mlx_status()
    assert st["supported"] is False and st["installed"] is False
    assert "macOS" in st["reason"]


def test_resolve_mlx_needs_weights(monkeypatch):
    monkeypatch.setattr(lm, "mlx_supported", lambda: True)
    monkeypatch.setattr(lm, "_hf_get", lambda *a, **k: _tree([
        ("README.md", 1000),
    ]))
    out = lm.resolve_mlx_candidate("mlx-community/whatever", ram=48)
    assert out["ok"] is False and "safetensors" in out["error"]


def test_resolve_mlx_sums_shard_sizes(monkeypatch):
    monkeypatch.setattr(lm, "mlx_supported", lambda: True)
    monkeypatch.setattr(lm, "_hf_get", lambda *a, **k: _tree([
        ("model-00001-of-00002.safetensors", 8_000_000_000),
        ("model-00002-of-00002.safetensors", 8_050_000_000),
        ("config.json", 900),
    ]))
    monkeypatch.setattr(lm, "hf_model_info", lambda repo: None)
    monkeypatch.setattr(lm, "is_installed", lambda cid: False)
    out = lm.resolve_mlx_candidate("mlx-community/Qwen3.6-27B-4bit", ram=48)
    assert out["ok"] is True
    assert out["weights_gb"] == pytest.approx(16.05, abs=0.01)
    assert out["quant"] == "4bit"
    assert out["backend"] == "mlx"
