"""Provider-retry fallback decision matrix (#12): a card is offered only
on retryable/capacity/billing errors AND only when another provider is
keyed. Never a silent switch."""

from __future__ import annotations

from switchbay import daemon, llmgateway
from switchbay.llmgateway import base


class _FakeProvider:
    def __init__(self, label, keyed):
        self.LABEL = label
        self._keyed = keyed

    def has_key(self):
        return self._keyed


def _patch_providers(monkeypatch, providers):
    monkeypatch.setattr(llmgateway, "PROVIDERS", providers)

    def _get(pid):
        return providers[pid]

    monkeypatch.setattr(llmgateway, "get", _get)


async def _run(monkeypatch, providers, failed_pid, err):
    _patch_providers(monkeypatch, providers)
    broadcasts = []

    async def _fake_broadcast(_app, msg):
        broadcasts.append(msg)

    monkeypatch.setattr(daemon, "_broadcast", _fake_broadcast)
    app = {}
    offered = await daemon._offer_provider_retry(
        app, "hi", thread_id="t1", workspace=daemon.Path("/tmp"),
        failed_pid=failed_pid, err=err,
    )
    return offered, broadcasts, app


async def test_offers_on_ratelimit_with_alternative(monkeypatch):
    providers = {
        "anthropic": _FakeProvider("Anthropic", True),
        "openai": _FakeProvider("OpenAI", True),
    }
    err = base.ProviderError("overloaded", code="rate-limit")
    offered, broadcasts, app = await _run(monkeypatch, providers, "anthropic", err)
    assert offered is True
    assert len(broadcasts) == 1
    # A pending retry record was stashed for the decide endpoint.
    assert app["provider_retries"]


async def test_no_offer_when_no_other_keyed_provider(monkeypatch):
    providers = {
        "anthropic": _FakeProvider("Anthropic", True),
        "openai": _FakeProvider("OpenAI", False),  # not keyed
    }
    err = base.ProviderError("overloaded", code="rate-limit")
    offered, broadcasts, _ = await _run(monkeypatch, providers, "anthropic", err)
    assert offered is False
    assert broadcasts == []


async def test_no_offer_on_nonretryable_auth_error(monkeypatch):
    providers = {
        "anthropic": _FakeProvider("Anthropic", True),
        "openai": _FakeProvider("OpenAI", True),
    }
    err = base.ProviderError("bad key", code="auth")
    offered, _, _ = await _run(monkeypatch, providers, "anthropic", err)
    assert offered is False


async def test_offers_on_billing_message_even_if_code_generic(monkeypatch):
    providers = {
        "anthropic": _FakeProvider("Anthropic", True),
        "openai": _FakeProvider("OpenAI", True),
    }
    # Anthropic surfaces "credit balance too low" as an http/server error;
    # the message hint should still trigger the offer.
    err = base.ProviderError("Your credit balance is too low", code="http")
    offered, _, _ = await _run(monkeypatch, providers, "anthropic", err)
    assert offered is True
