"""GitHub host resolution for the Copilot device flow.

The flow was hardcoded to github.com, which strands two populations:
GitHub Enterprise Server / ghe.com deployments (different OAuth
endpoints entirely), and enterprise-managed accounts on github.com whose
IdP isn't offered by the generic sign-in page.
"""

from __future__ import annotations

import pytest

from switchbay.llmgateway import github_copilot as gc


@pytest.mark.parametrize(("raw", "want"), [
    (None, "github.com"),
    ("", "github.com"),
    ("github.com", "github.com"),
    ("  GitHub.com  ", "github.com"),
    ("acme.ghe.com", "acme.ghe.com"),
    ("https://acme.ghe.com", "acme.ghe.com"),
    ("https://github.example.com/", "github.example.com"),
    ("http://ghes.internal/path/ignored", "ghes.internal"),
])
def test_host_normalisation(raw, want):
    assert gc._normalize_host(raw) == want


def test_dotcom_endpoints_are_unchanged():
    eps = gc._endpoints("github.com")
    assert eps["device_code"] == "https://github.com/login/device/code"
    assert eps["access_token"] == "https://github.com/login/oauth/access_token"
    assert eps["copilot_token"] == "https://api.github.com/copilot_internal/v2/token"
    assert eps["api_base"] == "https://api.githubcopilot.com"


def test_ghe_com_endpoints_target_the_tenant():
    eps = gc._endpoints("acme.ghe.com")
    assert eps["device_code"] == "https://acme.ghe.com/login/device/code"
    assert eps["copilot_token"].startswith("https://api.acme.ghe.com/")
    assert "github.com" not in eps["device_code"]


def test_enterprise_server_endpoints_use_api_v3():
    eps = gc._endpoints("github.example.com")
    assert eps["device_code"] == "https://github.example.com/login/device/code"
    assert "/api/v3/" in eps["copilot_token"]


def test_access_denied_explains_the_sso_case():
    eps = gc._endpoints("github.com")
    msg = gc._auth_error_help("access_denied", eps)
    assert "Enterprise Managed User" in msg
    assert "sso" in msg.lower()


def test_unknown_errors_still_surface_verbatim():
    eps = gc._endpoints("github.com")
    assert "weird_thing" in gc._auth_error_help("weird_thing", eps)


def test_host_round_trips_through_secrets(monkeypatch):
    store: dict[str, str] = {}
    monkeypatch.setattr(gc.secrets, "set_key", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(gc.secrets, "delete_key", lambda k: store.pop(k, None))
    monkeypatch.setattr(gc.secrets, "get", lambda k: store.get(k))

    assert gc.set_host("acme.ghe.com") == "acme.ghe.com"
    assert gc.get_host() == "acme.ghe.com"
    # Back to the default clears the override rather than storing it.
    assert gc.set_host("github.com") == "github.com"
    assert gc._HOST_KEY not in store
    assert gc.get_host() == "github.com"
