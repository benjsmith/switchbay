"""Media generation prefs catalog + set/get."""

from __future__ import annotations

from switchbay import media_settings


def test_catalog_covers_modalities():
    for m in media_settings.MODALITIES:
        providers = media_settings.providers_for(m)
        assert providers, f"no providers for {m}"
        assert all("models" in p and p["models"] for p in providers)


def test_set_clear_choice(tmp_path, monkeypatch):
    monkeypatch.setattr(
        media_settings.app_settings, "load", lambda: {},
    )
    store: dict = {}

    def _save(data):
        store.clear()
        store.update(data)

    monkeypatch.setattr(media_settings.app_settings, "save", _save)
    monkeypatch.setattr(
        media_settings.app_settings, "load", lambda: dict(store),
    )
    monkeypatch.setattr(media_settings, "provider_has_key", lambda _p: True)

    assert media_settings.get_choice("image") is None
    out = media_settings.set_choice(
        "image", provider="xai", model="grok-imagine-image",
    )
    assert out == {"provider": "xai", "model": "grok-imagine-image"}
    assert media_settings.get_choice("image") == out
    eff = media_settings.effective("image")
    assert eff and eff.get("ok") is True

    media_settings.set_choice("image", provider=None)
    assert media_settings.get_choice("image") is None


def test_rejects_unsupported_provider():
    try:
        media_settings.set_choice("image", provider="anthropic")
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "does not support" in str(e)


def test_status_payload_shape(monkeypatch):
    monkeypatch.setattr(media_settings, "provider_has_key", lambda _p: False)
    monkeypatch.setattr(media_settings.app_settings, "load", lambda: {})
    payload = media_settings.status_payload()
    assert "modalities" in payload
    for m in media_settings.MODALITIES:
        assert m in payload["modalities"]
        assert payload["modalities"][m]["available"] is False
