"""User prefs for generative media: image, video, voice.

Rail workflows (sketch figure insert, HTML artifact video, realtime
voice) are not fully wired yet — this module is the settings + catalog
layer so the UI can pick a provider/model when a supporting key is
present, and future tools call ``effective(modality)``.

Catalog is curated (not scraped): only backends we intend to call with
the existing BYOK keys (xAI Imagine / Voice, OpenAI images / TTS /
Realtime). Models younger than 48h are avoided per project policy when
picking defaults; ids here are stable product names from vendor docs.

Stored in app settings.json under ``media``:

  {
    "media": {
      "image": {"provider": "xai", "model": "grok-imagine-image"},
      "video": {"provider": "xai", "model": "grok-imagine-video"},
      "voice": {"provider": "openai", "model": "gpt-4o-mini-tts"}
    }
  }

Empty / missing = "unset" (no auto-spend until the user picks).
"""

from __future__ import annotations

from typing import Any

from . import app_settings, secrets

MODALITIES = ("image", "video", "voice")

# provider_id → capability → model ids (first is default when user
# selects that provider for the modality).
CATALOG: dict[str, dict[str, list[str]]] = {
    "xai": {
        "image": [
            "grok-imagine-image",
            "grok-imagine-image-quality",
        ],
        "video": [
            "grok-imagine-video",
            "grok-imagine-video-1.5",
        ],
        "voice": [
            # Grok TTS (/v1/tts) — voice names: eve, ara, leo, rex, sal
            "grok-voice",
        ],
    },
    "openai": {
        "image": [
            "gpt-image-1",
            "dall-e-3",
        ],
        "video": [
            # Sora when the account has access; picker still shows it
            # so a entitled key can select it.
            "sora-2",
            "sora-2-pro",
        ],
        "voice": [
            "gpt-4o-mini-tts",
            "gpt-4o-realtime-preview",
            "tts-1",
            "tts-1-hd",
        ],
    },
}

_PROVIDER_LABELS = {
    "xai": "xAI Grok",
    "openai": "OpenAI",
}

_MODALITY_BLURBS = {
    "image": (
        "Still images for sketch slides, wiki figures, or HTML artifacts."
    ),
    "video": (
        "Short clips for HTML presentations / intro-style decks "
        "(embed on a slide or artifact tab)."
    ),
    "voice": (
        "Speech / realtime voice for future rail or artifact playback "
        "(not the chat rail by default)."
    ),
}


def _media_block() -> dict[str, Any]:
    data = app_settings.load()
    raw = data.get("media")
    return raw if isinstance(raw, dict) else {}


def get_choice(modality: str) -> dict[str, str] | None:
    """Return ``{provider, model}`` or None if unset."""
    if modality not in MODALITIES:
        raise ValueError(f"unknown modality {modality!r}")
    rec = _media_block().get(modality)
    if not isinstance(rec, dict):
        return None
    provider = str(rec.get("provider") or "").strip()
    model = str(rec.get("model") or "").strip()
    if not provider:
        return None
    return {"provider": provider, "model": model}


def set_choice(
    modality: str,
    *,
    provider: str | None,
    model: str | None = None,
) -> dict[str, str] | None:
    """Persist choice. ``provider=None`` or empty clears the modality."""
    if modality not in MODALITIES:
        raise ValueError(f"unknown modality {modality!r}")
    data = app_settings.load()
    media = data.get("media")
    if not isinstance(media, dict):
        media = {}
    media = dict(media)
    pid = (provider or "").strip()
    if not pid:
        media.pop(modality, None)
        data["media"] = media
        app_settings.save(data)
        return None
    if pid not in CATALOG or modality not in CATALOG[pid]:
        raise ValueError(
            f"provider {pid!r} does not support {modality}"
        )
    models = CATALOG[pid][modality]
    mid = (model or "").strip() or (models[0] if models else "")
    if mid and mid not in models:
        # Allow forward-compat ids the user pastes later; still persist.
        pass
    media[modality] = {"provider": pid, "model": mid}
    data["media"] = media
    app_settings.save(data)
    return {"provider": pid, "model": mid}


def provider_has_key(provider_id: str) -> bool:
    if secrets.has(provider_id):
        return True
    import os
    env_map = {
        "xai": ("XAI_API_KEY",),
        "openai": ("OPENAI_API_KEY",),
    }
    for e in env_map.get(provider_id, ()):
        if os.environ.get(e):
            return True
    return False


def providers_for(modality: str) -> list[dict[str, Any]]:
    """Providers that advertise this modality, with key + models."""
    if modality not in MODALITIES:
        raise ValueError(f"unknown modality {modality!r}")
    out: list[dict[str, Any]] = []
    for pid, caps in CATALOG.items():
        models = caps.get(modality) or []
        if not models:
            continue
        out.append({
            "id": pid,
            "label": _PROVIDER_LABELS.get(pid, pid),
            "models": list(models),
            "default_model": models[0],
            "has_key": provider_has_key(pid),
        })
    return out


def effective(modality: str) -> dict[str, Any] | None:
    """Resolved choice for tools: None if unset or provider unkeyed.

    Future rail tools should call this before spending — never auto-
    default to a paid media model without an explicit Settings pick.
    """
    choice = get_choice(modality)
    if not choice:
        return None
    if not provider_has_key(choice["provider"]):
        return {
            **choice,
            "ok": False,
            "error": f"no API key for {choice['provider']}",
        }
    models = (CATALOG.get(choice["provider"]) or {}).get(modality) or []
    model = choice["model"] or (models[0] if models else "")
    return {
        "ok": True,
        "modality": modality,
        "provider": choice["provider"],
        "model": model,
        "label": _PROVIDER_LABELS.get(choice["provider"], choice["provider"]),
    }


def status_payload() -> dict[str, Any]:
    """Shape for GET /api/settings (and future /api/media)."""
    modalities: dict[str, Any] = {}
    for m in MODALITIES:
        providers = providers_for(m)
        choice = get_choice(m)
        modalities[m] = {
            "blurb": _MODALITY_BLURBS[m],
            "providers": providers,
            "choice": choice,
            "effective": effective(m),
            "available": any(p["has_key"] for p in providers),
        }
    return {
        "modalities": modalities,
        "note": (
            "Prefs only — generation tools (sketch figure, HTML video "
            "embed, voice playback) land later and will read these "
            "choices. Unset means switchbay will not auto-call paid "
            "media APIs."
        ),
    }
