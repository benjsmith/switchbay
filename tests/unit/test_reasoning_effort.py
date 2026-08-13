"""Reasoning effort — the third picker dimension.

The load-bearing property is that options are per MODEL, not per
provider: sending `reasoning_effort` to a non-reasoning model is a 400
from most APIs, so "the provider supports it" is not a safe proxy for
"this model accepts it". These pin the gating, the id→wire translation
for each shape (enum vs token budget vs boolean), and the guard that
drops a stale effort rather than sending it.
"""

from __future__ import annotations

import pytest

from switchbay import llm_config, llmgateway
from switchbay.llmgateway import anthropic, base, gemini, llamacpp, ollama, openai, xai


# ── per-model gating ────────────────────────────────────────────────

@pytest.mark.parametrize(("model", "expect"), [
    ("grok-4.5", ["low", "high"]),
    ("grok-4.20-0309-non-reasoning", []),
    ("grok-build-0.1", []),
])
def test_xai_gates_on_model(model, expect):
    assert [o["id"] for o in xai.reasoning_options(model)] == expect


@pytest.mark.parametrize(("model", "has"), [
    ("gpt-5", True), ("o3", True), ("o3-mini", True), ("o1", True),
    ("gpt-4o", False), ("gpt-4.1", False),
])
def test_openai_gates_on_reasoning_families(model, has):
    assert bool(openai.reasoning_options(model)) is has


def test_cli_provider_efforts_match_the_installed_binaries():
    """These enums were read off the real CLIs (`claude --effort` warns
    and lists its valid set; `grok --reasoning-effort` hard-errors with
    its own). If a CLI changes its enum these must follow — sending an
    unknown value is a warning-and-ignore on claude and a failed run on
    grok."""
    assert [o["id"] for o in llmgateway.reasoning_options("claude-code", "opus")] == [
        "low", "medium", "high", "xhigh", "max",
    ]
    assert [o["id"] for o in llmgateway.reasoning_options("grok-build", "grok-4.5")] == [
        "low", "medium", "high",
    ]
    assert [o["id"] for o in llmgateway.reasoning_options("grok-build", "grok-4.6")] == [
        "low", "medium", "high", "xhigh",
    ]
    assert [o["id"] for o in llmgateway.reasoning_options("muse-code", "muse-spark-1.2")] == [
        "minimal", "low", "medium", "high", "xhigh",
    ]
    assert [o["id"] for o in llmgateway.reasoning_options("meta", "muse-spark-1.2")] == [
        "minimal", "low", "medium", "high", "xhigh",
    ]


def test_gateway_returns_empty_for_providers_genuinely_without_the_control():
    """codex exposes no effort flag; copilot's HTTP shape hasn't been
    verified. Declaring none is what keeps the UI honest."""
    for pid in ("openai-codex", "github_copilot"):
        assert llmgateway.reasoning_options(pid, "whatever") == []
        assert llmgateway.supports_reasoning_effort(pid) is False


def test_gateway_survives_a_provider_that_raises(monkeypatch):
    monkeypatch.setattr(
        xai, "reasoning_options",
        lambda model=None: (_ for _ in ()).throw(RuntimeError("boom")))
    assert llmgateway.reasoning_options("xai", "grok-4.5") == []


def test_gateway_drops_malformed_option_rows(monkeypatch):
    monkeypatch.setattr(
        xai, "reasoning_options",
        lambda model=None: [{"id": "low", "label": "Low"}, {"label": "no id"}, "junk"])
    assert [o["id"] for o in llmgateway.reasoning_options("xai", "grok-4.5")] == ["low"]


# ── coercion guard ──────────────────────────────────────────────────

def test_coerce_effort_drops_unknown_ids():
    opts = xai.reasoning_options("grok-4.5")
    assert base.coerce_effort("low", opts) == "low"
    # A setting that outlived the model it was chosen for.
    assert base.coerce_effort("medium", opts) is None
    assert base.coerce_effort(None, opts) is None
    assert base.coerce_effort("low", []) is None


# ── wire translation: enum ──────────────────────────────────────────

def _req(**kw):
    return base.ChatRequest(messages=[{"role": "user", "content": "hi"}], **kw)


def test_chat_request_defaults_to_no_effort():
    assert _req().reasoning_effort is None


def test_xai_sends_native_enum():
    req = _req(model="grok-4.5", reasoning_effort="low")
    opts = xai.reasoning_options(req.model)
    assert base.coerce_effort(req.reasoning_effort, opts) == "low"


def test_xai_omits_effort_on_non_reasoning_model():
    req = _req(model="grok-4.20-0309-non-reasoning", reasoning_effort="low")
    assert base.coerce_effort(
        req.reasoning_effort, xai.reasoning_options(req.model)) is None


# ── wire translation: token budget ──────────────────────────────────

def test_anthropic_maps_effort_to_a_thinking_budget():
    assert anthropic._thinking_block("low", 8192) == {
        "type": "enabled", "budget_tokens": 2048,
    }
    assert anthropic._thinking_block(base.REASONING_OFF, 8192) is None
    assert anthropic._thinking_block(None, 8192) is None


def test_anthropic_budget_never_starves_the_reply():
    """budget_tokens must stay under max_tokens, and well under it —
    a budget that eats the allowance yields thinking with an empty body,
    the same failure the local `reasoning` flag exists to avoid."""
    block = anthropic._thinking_block("high", 4096)
    assert block is not None
    assert block["budget_tokens"] <= 4096 * 0.5
    # Too small to split at all → omit rather than send an invalid pair.
    assert anthropic._thinking_block("high", 1024) is None


def test_gemini_budget_table_covers_every_advertised_option():
    ids = {o["id"] for o in gemini.reasoning_options()}
    assert ids <= set(gemini._THINKING_BUDGETS)
    assert gemini._THINKING_BUDGETS[base.REASONING_OFF] == 0


# ── wire translation: boolean ───────────────────────────────────────

def test_local_providers_offer_an_honest_two_state_toggle():
    for mod in (llamacpp, ollama):
        ids = [o["id"] for o in mod.reasoning_options()]
        assert ids == [base.REASONING_OFF, "on"], mod.__name__


def test_llamacpp_effort_maps_to_enable_thinking():
    cfg = {"reasoning": True}
    assert llamacpp._thinking_enabled(_req(reasoning_effort="on"), cfg) is True
    assert llamacpp._thinking_enabled(
        _req(reasoning_effort=base.REASONING_OFF), cfg) is False
    # Unset → the Settings default.
    assert llamacpp._thinking_enabled(_req(), cfg) is True
    assert llamacpp._thinking_enabled(_req(), {"reasoning": False}) is False


def test_explicit_reasoning_bool_beats_the_effort_setting():
    """The one-shot drafting path passes reasoning=False explicitly; a
    picker effort must not override it back on."""
    cfg = {"reasoning": True}
    req = _req(reasoning=False, reasoning_effort="on")
    assert llamacpp._thinking_enabled(req, cfg) is False


# ── storage ─────────────────────────────────────────────────────────

def test_effort_is_stored_per_provider_and_model():
    llm_config.set_reasoning_effort("xai", "grok-4.5", "low")
    llm_config.set_reasoning_effort("xai", "grok-4.3", "high")
    assert llm_config.get_reasoning_effort("xai", "grok-4.5") == "low"
    assert llm_config.get_reasoning_effort("xai", "grok-4.3") == "high"
    assert llm_config.get_reasoning_effort("openai", "grok-4.5") is None


def test_clearing_removes_the_key_entirely():
    llm_config.set_reasoning_effort("xai", "grok-4.5", "low")
    llm_config.set_reasoning_effort("xai", "grok-4.5", None)
    assert llm_config.get_reasoning_effort("xai", "grok-4.5") is None
    assert "reasoning_effort" not in llm_config.load()


def test_effort_does_not_disturb_existing_prefs():
    llm_config.set_default_provider("xai")
    llm_config.set_model("xai", "grok-4.5")
    llm_config.set_reasoning_effort("xai", "grok-4.5", "high")
    assert llm_config.get_default_provider() == "xai"
    assert llm_config.get_model("xai") == "grok-4.5"
