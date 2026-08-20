"""Enterprise admin policy: provider allow-list + feature flags."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from aiohttp.test_utils import make_mocked_request

from switchbay import admin_policy, daemon, llmgateway


@pytest.fixture
def enterprise_env(monkeypatch):
    monkeypatch.setenv("SWITCHBAY_PROFILE", "enterprise")
    monkeypatch.delenv("SWITCHBAY_ADMIN_POLICY", raising=False)
    admin_policy.reset_cache()
    yield
    admin_policy.reset_cache()


def test_enterprise_default_allows_copilot_and_local(enterprise_env):
    assert admin_policy.provider_allowed("github_copilot")
    assert admin_policy.provider_allowed("llamacpp")
    assert admin_policy.provider_allowed("mlx")
    assert admin_policy.provider_allowed("ollama")
    assert not admin_policy.provider_allowed("anthropic")
    assert not admin_policy.provider_allowed("claude-code")
    assert not admin_policy.feature_enabled("in_app_update")
    assert not admin_policy.feature_enabled("ce_auto_setup")
    assert not admin_policy.feature_enabled("uv_python_install")
    assert not admin_policy.feature_enabled("install_skills_npx")
    assert not admin_policy.feature_enabled("scan_other_app_caches")
    assert not admin_policy.feature_enabled("hf_model_download")
    assert admin_policy.feature_enabled("user_mcp_servers")


def test_open_profile_allows_hosted_apis(monkeypatch):
    monkeypatch.setenv("SWITCHBAY_PROFILE", "open")
    admin_policy.reset_cache()
    assert admin_policy.DEFAULT_PROFILE == "open"
    assert admin_policy.provider_allowed("anthropic")
    assert admin_policy.feature_enabled("in_app_update")
    assert admin_policy.feature_enabled("ce_auto_setup")
    assert admin_policy.feature_enabled("hf_model_download")
    assert llmgateway.default_provider_id() == "anthropic"


def test_default_profile_is_open_without_env(monkeypatch):
    monkeypatch.delenv("SWITCHBAY_PROFILE", raising=False)
    monkeypatch.delenv("SWITCHBAY_ADMIN_POLICY", raising=False)
    admin_policy.reset_cache()
    assert admin_policy.DEFAULT_PROFILE == "open"
    assert admin_policy.profile() == "open"
    assert admin_policy.feature_enabled("hf_model_download")
    assert llmgateway.default_provider_id() == "anthropic"


def test_windows_programdata_candidate_path(monkeypatch):
    monkeypatch.setattr(admin_policy.sys, "platform", "win32")
    monkeypatch.setenv("PROGRAMDATA", r"C:\ProgramData")
    monkeypatch.delenv("SWITCHBAY_ADMIN_POLICY", raising=False)
    joined = [str(p) for p in admin_policy.candidate_paths()]
    assert any("ProgramData" in p and "SwitchBay" in p and p.endswith("admin.json") for p in joined)


def test_mlx_denied_on_non_darwin(monkeypatch, enterprise_env):
    monkeypatch.setattr(admin_policy.sys, "platform", "win32")
    assert not admin_policy.provider_allowed("mlx")
    assert admin_policy.provider_allowed("github_copilot")
    assert admin_policy.provider_allowed("ollama")


def test_admin_can_enable_hf_downloads(tmp_path: Path, monkeypatch, enterprise_env):
    p = tmp_path / "admin.json"
    p.write_text(json.dumps({
        "profile": "enterprise",
        "features": {"hf_model_download": True},
    }), encoding="utf-8")
    monkeypatch.setenv("SWITCHBAY_ADMIN_POLICY", str(p))
    admin_policy.reset_cache()
    assert admin_policy.feature_enabled("hf_model_download")
    assert not admin_policy.feature_enabled("in_app_update")


def test_file_can_reenable_a_provider(tmp_path: Path, monkeypatch, enterprise_env):
    p = tmp_path / "admin.json"
    p.write_text(json.dumps({
        "profile": "enterprise",
        "providers": {"anthropic": True},
        "features": {"in_app_update": True},
    }), encoding="utf-8")
    monkeypatch.setenv("SWITCHBAY_ADMIN_POLICY", str(p))
    admin_policy.reset_cache()
    assert admin_policy.provider_allowed("anthropic")
    assert admin_policy.provider_allowed("github_copilot")
    assert not admin_policy.provider_allowed("openai")
    assert admin_policy.feature_enabled("in_app_update")
    assert not admin_policy.feature_enabled("ce_auto_setup")


def test_list_providers_hides_disabled(monkeypatch, enterprise_env):
    ids = {p["id"] for p in llmgateway.list_providers()}
    assert "github_copilot" in ids
    assert "llamacpp" in ids
    assert "anthropic" not in ids
    assert "claude-code" not in ids


def test_default_provider_id_is_copilot_on_enterprise(enterprise_env):
    assert llmgateway.default_provider_id() == "github_copilot"


@pytest.mark.asyncio
async def test_update_endpoint_403_when_locked(enterprise_env):
    req = make_mocked_request("POST", "/api/update", app={})
    resp = await daemon.handle_update(req)
    assert resp.status == 403
    import json as _json
    body = _json.loads(resp.body)
    assert "in_app_update" in body["error"]
