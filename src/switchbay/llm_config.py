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
