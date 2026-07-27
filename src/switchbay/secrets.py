"""API-key storage backed by the OS-native credential store.

`keyring` selects the right backend per platform:
  macOS:   Keychain (`security` framework)
  Linux:   Secret Service (gnome-keyring / KWallet) via DBus
  Windows: Credential Manager (DPAPI under the hood)

Keys NEVER touch our config files in plaintext. If no keychain backend
is configured (e.g. headless Linux with no DBus), `keyring` falls back
to a "fail" / "null" backend; `available()` reports this so the UI can
warn the user instead of silently dropping their key.

Convention:
  service = "switchbay"
  username = provider id ("anthropic" / "openai" / …)
  password = the API key
"""

from __future__ import annotations

import logging

import keyring
from keyring.backends.fail import Keyring as FailKeyring
from keyring.errors import KeyringError

log = logging.getLogger("switchbay.secrets")

SERVICE = "switchbay"


def available() -> bool:
    """True if a real keychain backend is configured (not the fail backend)."""
    return not isinstance(keyring.get_keyring(), FailKeyring)


def backend_name() -> str:
    """Human-readable backend identifier, for the Settings UI."""
    return type(keyring.get_keyring()).__name__


def get(provider: str) -> str | None:
    if not available():
        return None
    try:
        return keyring.get_password(SERVICE, provider)
    except KeyringError as e:
        log.warning("keyring get failed for %s: %s", provider, e)
        return None


def set_key(provider: str, key: str) -> bool:
    if not available():
        return False
    try:
        keyring.set_password(SERVICE, provider, key)
        return True
    except KeyringError as e:
        log.warning("keyring set failed for %s: %s", provider, e)
        return False


def delete_key(provider: str) -> bool:
    if not available():
        return False
    try:
        keyring.delete_password(SERVICE, provider)
        return True
    except KeyringError:
        return False


def has(provider: str) -> bool:
    return get(provider) is not None
