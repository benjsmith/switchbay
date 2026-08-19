"""Per-run CE-action orchestrator override (`/api/ce-action/run`).

The safety-critical part is `_resolve_ce_override`: a curate run must
never be started on a provider that can't actually curate (no shell →
propose-only). These tests exercise that gate without a running daemon.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from switchbay import daemon


def test_empty_provider_falls_back_to_default():
    # No explicit override → caller uses normal ladder routing.
    assert daemon._resolve_ce_override("", "") == (None, None, None)


def test_unknown_provider_rejected():
    pid, model, err = daemon._resolve_ce_override("nope", "")
    assert pid is None and err and "unknown provider" in err


def test_execute_capable_provider_accepted():
    # claude-code is a real, execute-capable provider. has_key = the
    # `claude` binary on PATH; mock it so the test is machine-independent.
    prov = MagicMock()
    prov.has_key.return_value = True
    prov.LABEL = "Claude Code"
    with patch("switchbay.llmgateway.get", return_value=prov), \
         patch("switchbay.llmgateway.can_curate", return_value=True), \
         patch("switchbay.daemon._effective_model", return_value="claude-opus-4-8"):
        pid, model, err = daemon._resolve_ce_override("claude-code", "")
    assert err is None
    assert pid == "claude-code"
    assert model == "claude-opus-4-8"  # filled from effective model


def test_explicit_model_preserved():
    prov = MagicMock()
    prov.has_key.return_value = True
    prov.LABEL = "Grok Build"
    with patch("switchbay.llmgateway.get", return_value=prov), \
         patch("switchbay.llmgateway.can_curate", return_value=True):
        pid, model, err = daemon._resolve_ce_override("grok-build", "grok-4.5")
    assert (pid, model, err) == ("grok-build", "grok-4.5", None)


def test_propose_only_provider_rejected():
    # A keyed but non-execute-capable provider (e.g. an HTTP one) can't
    # orchestrate a curate — reject rather than silently degrade.
    prov = MagicMock()
    prov.has_key.return_value = True
    prov.LABEL = "Anthropic"
    with patch("switchbay.llmgateway.get", return_value=prov), \
         patch("switchbay.llmgateway.can_curate", return_value=False):
        pid, model, err = daemon._resolve_ce_override("anthropic", "")
    assert pid is None
    assert err and "cannot run CE scripts" in err


def test_keyless_provider_rejected():
    prov = MagicMock()
    prov.has_key.return_value = False
    prov.LABEL = "Grok Build"
    with patch("switchbay.llmgateway.get", return_value=prov):
        pid, model, err = daemon._resolve_ce_override("grok-build", "")
    assert pid is None
    assert err and "no key" in err
