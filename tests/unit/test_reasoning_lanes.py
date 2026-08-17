"""Lane-aware reasoning-effort resolution.

Every dispatch lane already resolves its own provider+model — the rail
from the picker, micro-edits from their fast-model setting, CE/routed
work from the ladder rung — so effort resolves against whichever pair
the lane landed on. These pin that, plus the per-lane fallback for when
that pair carries no effort of its own.
"""

from __future__ import annotations

import pytest

from switchbay import llm_config, routing_status, verbs


PICKER = ("xai", "grok-4.5")          # offers low / high
LADDER = ("anthropic", "claude-sonnet-4-6")   # offers off / low / medium / high


@pytest.fixture(autouse=True)
def _picker_is_xai():
    llm_config.set_default_provider(PICKER[0])
    llm_config.set_model(*PICKER)


# ── the pair's own effort wins ──────────────────────────────────────

def test_rung_effort_wins_over_the_pairs_stored_effort():
    """Same model, cheaper think — the other way to weaken a rung."""
    llm_config.set_reasoning_effort(*LADDER, "high")
    assert routing_status.effort_for(*LADDER, "ladder", rung_effort="low") == "low"
    assert routing_status.effort_for(*LADDER, "ladder") == "high"


def test_lane_uses_the_effort_of_the_model_it_routed_to():
    """Setting an effort on a model covers every lane that routes there
    — that IS "inherit the ladder's setting" / "use the micro-edit
    setting", without a parallel config tree."""
    llm_config.set_reasoning_effort(*LADDER, "medium")
    assert routing_status.effort_for(*LADDER, "ladder") == "medium"
    assert routing_status.effort_for(*LADDER, "micro") == "medium"
    assert routing_status.effort_for(*LADDER, "background") == "medium"


def test_different_models_keep_separate_efforts():
    llm_config.set_reasoning_effort(*PICKER, "low")
    llm_config.set_reasoning_effort(*LADDER, "high")
    assert routing_status.effort_for(*PICKER, "rail") == "low"
    assert routing_status.effort_for(*LADDER, "ladder") == "high"


# ── fallback policy ─────────────────────────────────────────────────

def test_background_inherits_the_picker_by_default():
    """The point of the change: background work should track what the
    user asked for interactively, not silently revert to provider
    defaults."""
    llm_config.set_reasoning_effort(*PICKER, "high")
    assert routing_status.effort_for(*LADDER, "ladder") == "high"
    assert routing_status.effort_for(*LADDER, "background") == "high"


def test_rail_never_inherits_from_itself():
    """The rail IS the picker — with nothing set it sends nothing,
    rather than looping back through the inherit branch."""
    assert routing_status.effort_for(*PICKER, "rail") is None


def test_provider_default_policy_sends_nothing():
    llm_config.set_reasoning_effort(*PICKER, "high")
    llm_config.set_reasoning_policy("background", llm_config.POLICY_DEFAULT)
    assert routing_status.effort_for(*LADDER, "background") is None
    # …and only that lane is affected.
    assert routing_status.effort_for(*LADDER, "ladder") == "high"


def test_pinned_policy_overrides_everything():
    """"Always think hard when curating", whatever the ladder points at."""
    llm_config.set_reasoning_effort(*LADDER, "low")
    llm_config.set_reasoning_policy("ladder", "high")
    assert routing_status.effort_for(*LADDER, "ladder") == "high"
    assert routing_status.effort_for(*LADDER, "background") == "low"


def test_pinned_policy_is_dropped_when_the_model_cannot_take_it():
    """A lane pinned to `medium` routing to a model that only offers
    low/high falls back rather than sending an invalid value."""
    llm_config.set_reasoning_policy("ladder", "medium")
    assert routing_status.effort_for("xai", "grok-4.5", "ladder") is None


# ── coercion across providers ───────────────────────────────────────

def test_inheritance_is_coerced_to_the_target_models_options():
    """xai has no `medium`; inheriting one from an Anthropic picker must
    degrade to the provider default, not send a value xai rejects."""
    llm_config.set_default_provider("anthropic")
    llm_config.set_model("anthropic", "claude-sonnet-4-6")
    llm_config.set_reasoning_effort("anthropic", "claude-sonnet-4-6", "medium")
    assert routing_status.effort_for("xai", "grok-4.5", "background") is None
    # A value both offer does carry across.
    llm_config.set_reasoning_effort("anthropic", "claude-sonnet-4-6", "high")
    assert routing_status.effort_for("xai", "grok-4.5", "background") == "high"


def test_models_without_a_dial_always_resolve_to_none():
    """No dial → nothing sent, whatever the picker says and whatever the
    lane policy is. `openai/gpt-4o` is a non-reasoning model; codex
    exposes no effort flag at all."""
    llm_config.set_reasoning_effort(*PICKER, "high")
    for lane in llm_config.LANES:
        assert routing_status.effort_for("openai", "gpt-4o", lane) is None
        assert routing_status.effort_for("openai-codex", "gpt-5", lane) is None


def test_cli_providers_inherit_like_any_other():
    """claude-code and grok-build DO have verified `--effort` flags, so
    they take part in inheritance rather than being permanently opted
    out (which is what an unverified "no options" declaration did)."""
    llm_config.set_reasoning_effort(*PICKER, "high")
    assert routing_status.effort_for("claude-code", "opus", "ladder") == "high"
    assert routing_status.effort_for("grok-build", "grok-4.5", "ladder") == "high"
    # `xhigh` exists only on claude — it must not leak to grok.
    llm_config.set_reasoning_effort("claude-code", "opus", "xhigh")
    llm_config.set_default_provider("claude-code")
    llm_config.set_model("claude-code", "opus")
    assert routing_status.effort_for("claude-code", "opus", "rail") == "xhigh"
    assert routing_status.effort_for("grok-build", "grok-4.5", "ladder") is None


def test_resolution_never_raises_on_a_bad_provider():
    assert routing_status.effort_for("nope-not-a-provider", "x", "rail") is None


# ── policy storage ──────────────────────────────────────────────────

def test_policy_defaults_to_inherit_and_clears_back_to_it():
    assert llm_config.get_reasoning_policy("background") == llm_config.POLICY_INHERIT
    llm_config.set_reasoning_policy("background", llm_config.POLICY_DEFAULT)
    assert llm_config.get_reasoning_policy("background") == llm_config.POLICY_DEFAULT
    llm_config.set_reasoning_policy("background", None)
    assert llm_config.get_reasoning_policy("background") == llm_config.POLICY_INHERIT
    assert "reasoning_policy" not in llm_config.load()


def test_unknown_lane_is_refused():
    with pytest.raises(ValueError):
        llm_config.set_reasoning_policy("not-a-lane", "high")


# ── the /effort command ─────────────────────────────────────────────

def test_effort_verb_is_registered():
    """A coding CLI's own /effort is consumed by the rail's slash router
    before any provider sees it, so Switch Bay has to own the command
    for typing it to do anything."""
    v = verbs.lookup("effort")
    assert v is not None
    assert verbs.lookup("reasoning") is v
    assert verbs.lookup("think") is v
