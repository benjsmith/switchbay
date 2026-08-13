"""routing_status: honest display of where CE actions / micro-edits
actually run, plus the weak-model-with-destructive-scope warning.

Also covers the capability gate in llmgateway (can_execute) and the
CE-action routing rule it feeds (the 2026-07-24 curator/model-mismatch
bug: default said Opus, curate ran on a shell-less provider).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from switchbay import llmgateway, modestore, routing_status


# ── capability gate ────────────────────────────────────────────────


def test_cli_providers_can_execute():
    assert llmgateway.can_execute("claude-code")
    assert llmgateway.can_execute("grok-build")
    assert llmgateway.can_execute("openai-codex")
    assert llmgateway.can_execute("muse-code")


def test_http_and_local_providers_cannot_execute():
    for pid in ("anthropic", "openai", "gemini", "xai", "meta", "llamacpp", "ollama"):
        assert not llmgateway.can_execute(pid), pid


def test_unknown_provider_cannot_execute():
    assert not llmgateway.can_execute("does-not-exist")


# ── weak-model heuristic ───────────────────────────────────────────


@pytest.mark.parametrize("model", [
    "claude-haiku-4-5-20251001", "gpt-5.4-mini", "grok-composer-2.5-fast",
    "gemini-2.5-flash", "qwen25_coder_7b", "some-8b-instruct", "model-nano",
])
def test_weak_models_flagged(model):
    assert routing_status.is_weak_model(model)


@pytest.mark.parametrize("model", [
    "claude-opus-4-8", "claude-sonnet-5", "grok-4.5", "gpt-5.6", "",
])
def test_strong_models_not_flagged(model):
    assert not routing_status.is_weak_model(model)


# ── routing summary ────────────────────────────────────────────────


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / ".workbench").mkdir()
    return tmp_path


def _set_ladder(monkeypatch, ws, ladder):
    """Force effective_ladder to a fixed shape without touching global
    settings on the test machine. `ladder` is a rung->{provider,model} map."""
    monkeypatch.setattr(modestore, "effective_ladder", lambda _w: dict(ladder or {}))
    # micro-edits are decoupled from the ladder — pin them off by default.
    monkeypatch.setattr(
        routing_status, "micro_edit_route", lambda _w: (None, None))


def test_pinned_hard_rung_is_orchestrator_override(monkeypatch, ws):
    # hard rung = the curate orchestrator. Pinned to a capable provider →
    # surfaced as an override (the picker headline is Opus).
    _set_ladder(monkeypatch, ws,
                {"hard": {"provider": "grok-build", "model": "grok-4.5"}})
    r = routing_status.compute(ws, "claude-code", "claude-opus-4-8")
    kinds = {o["kind"]: o for o in r["overrides"]}
    assert kinds["ce-orchestrator"]["provider"] == "grok-build"
    assert kinds["ce-orchestrator"]["model"] == "grok-4.5"
    assert r["warnings"] == []  # grok-4.5 is strong


def test_unset_hard_rung_follows_picker(monkeypatch, ws):
    # No hard rung → orchestrator follows the picker → NOT an override.
    _set_ladder(monkeypatch, ws,
                {"normal": {"provider": "grok-build", "model": "grok-4.5"}})
    r = routing_status.compute(ws, "claude-code", "claude-opus-4-8")
    assert all(o["kind"] != "ce-orchestrator" for o in r["overrides"])
    # workers (normal rung) ARE surfaced.
    assert any(o["kind"] == "ce-workers" for o in r["overrides"])


def test_propose_only_hard_rung_not_orchestrator_override(monkeypatch, ws):
    # A shell-less hard rung can't orchestrate curation → falls back to
    # the picker, so it must NOT be advertised as an orchestrator override.
    _set_ladder(monkeypatch, ws,
                {"hard": {"provider": "llamacpp", "model": "qwen25_coder_7b"}})
    r = routing_status.compute(ws, "claude-code", "claude-opus-4-8")
    assert all(o["kind"] != "ce-orchestrator" for o in r["overrides"])


def test_weak_worker_rung_warns(monkeypatch, ws):
    # claude-code CAN execute; 'haiku' workers are weak → the risky
    # pairing the user asked to be warned about.
    _set_ladder(monkeypatch, ws,
                {"normal": {"provider": "claude-code", "model": "haiku"}})
    r = routing_status.compute(ws, "claude-code", "claude-opus-4-8")
    assert any(w["kind"] == "weak-destructive" and w["scope"] == "ce-workers"
               for w in r["warnings"])


def test_no_ladder_no_overrides(monkeypatch, ws):
    _set_ladder(monkeypatch, ws, {})
    r = routing_status.compute(ws, "claude-code", "claude-opus-4-8")
    assert r["overrides"] == []
    assert r["warnings"] == []


def test_micro_edit_model_is_an_override(monkeypatch, ws):
    _set_ladder(monkeypatch, ws, {})
    monkeypatch.setattr(
        routing_status, "micro_edit_route",
        lambda _w: ("grok-build", "grok-composer-2.5-fast"))
    r = routing_status.compute(ws, "claude-code", "claude-opus-4-8")
    micro = [o for o in r["overrides"] if o["kind"] == "micro-edit"]
    assert micro and micro[0]["model"] == "grok-composer-2.5-fast"
    # micro-edits don't get CE's destructive shell scope → no weak warning.
    assert r["warnings"] == []
