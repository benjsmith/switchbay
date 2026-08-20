"""Enterprise egress gate."""

from __future__ import annotations

import pytest

from switchbay import admin_policy, http


def test_open_allows_any_host(monkeypatch):
    monkeypatch.setenv("SWITCHBAY_PROFILE", "open")
    admin_policy.reset_cache()
    http.assert_egress("https://example.com/x")


def test_enterprise_allows_loopback_and_copilot(monkeypatch):
    monkeypatch.setenv("SWITCHBAY_PROFILE", "enterprise")
    monkeypatch.delenv("SWITCHBAY_ADMIN_POLICY", raising=False)
    admin_policy.reset_cache()
    http.assert_egress("http://127.0.0.1:8878/v1/models")
    http.assert_egress("https://api.githubcopilot.com/chat/completions")
    with pytest.raises(PermissionError):
        http.assert_egress("https://huggingface.co/api/models")


def test_enterprise_hf_flag_opens_huggingface(tmp_path, monkeypatch):
    p = tmp_path / "admin.json"
    p.write_text(
        '{"profile":"enterprise","features":{"hf_model_download":true}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("SWITCHBAY_PROFILE", "enterprise")
    monkeypatch.setenv("SWITCHBAY_ADMIN_POLICY", str(p))
    admin_policy.reset_cache()
    http.assert_egress("https://huggingface.co/api/models")
