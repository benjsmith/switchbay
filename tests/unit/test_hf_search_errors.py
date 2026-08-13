"""HF search should surface transport errors, not silent empty lists."""

from __future__ import annotations

import pytest

from switchbay import local_models as lm


def test_hf_search_gguf_with_status_reports_error(monkeypatch):
    monkeypatch.setattr(lm, "_hf_get", lambda path, timeout=20.0: None)
    monkeypatch.setattr(lm, "last_hf_error", lambda: "TLS certificate verification failed")
    rows, err = lm.hf_search_gguf_with_status("qwen")
    assert rows == []
    assert err and "TLS" in err


def test_hf_search_gguf_with_status_ok(monkeypatch):
    monkeypatch.setattr(lm, "_hf_get", lambda path, timeout=20.0: [
        {
            "id": "unsloth/Qwen-GGUF",
            "downloads": 100,
            "likes": 1,
            "trendingScore": 2,
            "lastModified": "2026-01-01",
            "tags": ["gguf"],
        },
    ])
    rows, err = lm.hf_search_gguf_with_status("qwen")
    assert err is None
    assert rows and rows[0]["repo"] == "unsloth/Qwen-GGUF"
