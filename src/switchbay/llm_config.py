"""User-level LLM preferences (default provider + per-provider model).

Stored next to the workspaces registry at
`$XDG_CONFIG_HOME/switchbay/llm.json`. Keys themselves live in the
OS keychain (see secrets.py); this file holds non-secret prefs only:

  {
    "default_provider": "anthropic",
    "models": { "anthropic": "claude-opus-4-7",
                "claude-code": "claude-sonnet-4-6" }
  }

Each provider exposes a `default_model` and `model_suggestions` in its
PROVIDER block — those serve as fallbacks when the user hasn't picked
explicitly. We deliberately don't validate model strings here; users
can paste any id their account supports, and provider errors will
surface if the model is unknown.
"""

from __future__ import annotations

import json
from typing import Any

from . import workspaces
from . import atomicio


def _path():
    return workspaces.config_dir() / "llm.json"


def load() -> dict[str, Any]:
    p = _path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save(data: dict[str, Any]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(p, data)


def get_default_provider() -> str | None:
    val = load().get("default_provider")
    return str(val) if isinstance(val, str) and val else None


def set_default_provider(provider: str) -> None:
    data = load()
    data["default_provider"] = provider
    save(data)


def get_model(provider: str) -> str | None:
    """User-chosen model for `provider`, or None to fall back to the
    provider's static default."""
    models = load().get("models")
    if not isinstance(models, dict):
        return None
    val = models.get(provider)
    return str(val) if isinstance(val, str) and val else None


def set_model(provider: str, model: str | None) -> None:
    """Persist the user's model choice for `provider`. Pass None to
    clear it (next chat will use the provider's static default)."""
    data = load()
    models = data.get("models")
    if not isinstance(models, dict):
        models = {}
    if model:
        models[provider] = model
    else:
        models.pop(provider, None)
    data["models"] = models
    save(data)


# ── Reasoning effort ────────────────────────────────────────────────
# The third picker dimension, stored per `provider/model` rather than
# per provider: the options themselves are per model (a provider's
# reasoning models and its plain ones take different values), so one
# effort per provider would be meaningless the moment you switch model.
# Keying on the pair also means flipping between two models remembers
# what each was set to.
#
#   "reasoning_effort": { "xai/grok-4.5": "low" }
#
# Unset → absent key → the provider's own default (we send nothing),
# consistent with the rest of this file: unset means unset.


# Dispatch lanes. Each already resolves its OWN provider+model — the
# rail from the picker, micro-edits from their fast-model setting,
# routed work from the model ladder — so effort resolves against
# whichever pair that lane landed on. `LANE_POLICIES` is what happens
# when that pair carries no effort of its own.
LANES = ("rail", "micro", "ladder", "background")

POLICY_INHERIT = "inherit"
"""Fall back to the rail picker's effort, coerced to this pair's own
options (dropped if the pair doesn't offer it). The default: it means
background work tracks how hard you've said you want things thought
about, instead of silently reverting to the provider's idea."""

POLICY_DEFAULT = "default"
"""Send nothing — the provider's own default."""


def _effort_key(provider: str, model: str | None) -> str:
    return f"{provider}/{model or ''}"


def get_reasoning_effort(provider: str, model: str | None) -> str | None:
    """The user's chosen effort for this provider+model, or None."""
    efforts = load().get("reasoning_effort")
    if not isinstance(efforts, dict):
        return None
    val = efforts.get(_effort_key(provider, model))
    return str(val) if isinstance(val, str) and val else None


def set_reasoning_effort(
    provider: str, model: str | None, effort: str | None,
) -> None:
    """Persist (or clear, when `effort` is falsy) the reasoning effort
    for this provider+model."""
    data = load()
    efforts = data.get("reasoning_effort")
    if not isinstance(efforts, dict):
        efforts = {}
    key = _effort_key(provider, model)
    if effort:
        efforts[key] = effort
    else:
        efforts.pop(key, None)
    if efforts:
        data["reasoning_effort"] = efforts
    else:
        data.pop("reasoning_effort", None)
    save(data)


def get_reasoning_policy(lane: str) -> str:
    """Fallback policy for `lane` — what to do when the provider+model
    it resolved to carries no effort of its own.

    `inherit` (the default) or `default`, or an explicit effort id that
    pins the lane regardless of which model it routes to.
    """
    pol = load().get("reasoning_policy")
    if isinstance(pol, dict):
        val = pol.get(lane)
        if isinstance(val, str) and val:
            return val
    return POLICY_INHERIT


def set_reasoning_policy(lane: str, policy: str | None) -> None:
    """Set (or clear, back to `inherit`) a lane's fallback policy."""
    if lane not in LANES:
        raise ValueError(f"unknown lane: {lane}")
    data = load()
    pol = data.get("reasoning_policy")
    if not isinstance(pol, dict):
        pol = {}
    if policy and policy != POLICY_INHERIT:
        pol[lane] = policy
    else:
        pol.pop(lane, None)
    if pol:
        data["reasoning_policy"] = pol
    else:
        data.pop("reasoning_policy", None)
    save(data)
