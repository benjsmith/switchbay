"""Machine-level admin policy. The daemon never writes this file.

This *enterprise* branch defaults to profile ``enterprise`` even with
no file on disk: GitHub Copilot + local models only, and the runtime
hooks that EDR (SentinelOne et al.) flags — ``uv python install``,
``npx skills add``, CE ``setup.sh``, in-app git/npx updates, walking
other apps' HF caches — stay off unless an admin file turns them on.

Search order (first existing file wins):

  1. ``$SWITCHBAY_ADMIN_POLICY``
  2. ``/Library/Application Support/SwitchBay/admin.json``  (macOS MDM)
  3. ``/etc/switchbay/admin.json``
  4. ``<repo>/admin.json``  (optional drop-in next to the checkout)

``SWITCHBAY_PROFILE=open`` restores mainline behaviour (every
provider, every feature) without a file. ``SWITCHBAY_PROFILE=enterprise``
is the default on this branch.

The file is admin-owned. Do not put it in ``~/.config/switchbay`` —
that tree is user-writable and the daemon *does* write there.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger("switchbay.admin_policy")

# This branch's baked default. mainline stays "open".
DEFAULT_PROFILE = "enterprise"

ENTERPRISE_PROVIDERS: frozenset[str] = frozenset({
    "github_copilot",
    "llamacpp",
    "mlx",
    "ollama",
})

# Feature flags. True = allowed. Enterprise defaults lock the ones
# that download, mutate the machine, or phone home outside Copilot.
FEATURE_DEFAULTS_OPEN: dict[str, bool] = {
    "in_app_update": True,
    "install_skills_npx": True,
    "ce_auto_setup": True,
    "uv_python_install": True,
    "scan_other_app_caches": True,
    "hf_model_download": True,
    "comms_streams": True,
    "github_share": True,
    "media_generation": True,
    "user_mcp_servers": True,
    "watch_folders": True,
}

FEATURE_DEFAULTS_ENTERPRISE: dict[str, bool] = {
    **FEATURE_DEFAULTS_OPEN,
    "in_app_update": False,
    "install_skills_npx": False,
    "ce_auto_setup": False,
    "uv_python_install": False,
    "scan_other_app_caches": False,
    "hf_model_download": False,
    "comms_streams": False,
    "github_share": False,
    "media_generation": False,
    # MCP / watch folders stay on — they are local and admin-useful.
    "user_mcp_servers": True,
    "watch_folders": True,
}

_cache: dict[str, Any] | None = None
_cache_key: tuple[str, ...] | None = None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def candidate_paths() -> list[Path]:
    out: list[Path] = []
    env = (os.environ.get("SWITCHBAY_ADMIN_POLICY") or "").strip()
    if env:
        out.append(Path(env).expanduser())
    if sys.platform == "darwin":
        out.append(Path("/Library/Application Support/SwitchBay/admin.json"))
    out.append(Path("/etc/switchbay/admin.json"))
    out.append(_repo_root() / "admin.json")
    return out


def _existing_path() -> Path | None:
    for p in candidate_paths():
        try:
            if p.is_file():
                return p
        except OSError:
            continue
    return None


def _profile_override() -> str | None:
    raw = (os.environ.get("SWITCHBAY_PROFILE") or "").strip().lower()
    if raw in ("open", "enterprise"):
        return raw
    return None


def _read_file(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("admin policy %s unreadable: %s", path, e)
        return {}
    return data if isinstance(data, dict) else {}


def load(*, force: bool = False) -> dict[str, Any]:
    """Resolved policy. Cached per (path, mtime, env profile)."""
    global _cache, _cache_key
    path = _existing_path()
    mtime = ""
    if path is not None:
        try:
            mtime = str(path.stat().st_mtime_ns)
        except OSError:
            mtime = "err"
    key = (
        str(path) if path else "",
        mtime,
        os.environ.get("SWITCHBAY_PROFILE") or "",
        os.environ.get("SWITCHBAY_ADMIN_POLICY") or "",
    )
    if not force and _cache is not None and _cache_key == key:
        return _cache
    file_data = _read_file(path) if path is not None else {}
    env_profile = _profile_override()
    file_profile = str(file_data.get("profile") or "").strip().lower()
    profile = env_profile or file_profile or DEFAULT_PROFILE
    if profile not in ("open", "enterprise"):
        profile = DEFAULT_PROFILE

    features = dict(
        FEATURE_DEFAULTS_ENTERPRISE if profile == "enterprise"
        else FEATURE_DEFAULTS_OPEN
    )
    raw_feat = file_data.get("features")
    if isinstance(raw_feat, dict):
        for k, v in raw_feat.items():
            if k in features:
                features[k] = bool(v)

    providers: dict[str, bool] = {}
    raw_prov = file_data.get("providers")
    if isinstance(raw_prov, dict):
        for k, v in raw_prov.items():
            kid = str(k).strip()
            if kid:
                providers[kid] = bool(v)

    resolved = {
        "profile": profile,
        "source": str(path) if path else None,
        "features": features,
        "providers": providers,
    }
    _cache, _cache_key = resolved, key
    return resolved


def reset_cache() -> None:
    """Tests only."""
    global _cache, _cache_key
    _cache, _cache_key = None, None


def profile() -> str:
    return str(load()["profile"])


def feature_enabled(name: str) -> bool:
    feats = load()["features"]
    if name not in feats:
        return True
    return bool(feats[name])


def feature_error(name: str) -> str:
    return f"disabled by admin policy ({name})"


def provider_allowed(provider_id: str) -> bool:
    pid = (provider_id or "").strip()
    if not pid:
        return False
    data = load()
    explicit = data["providers"]
    if pid in explicit:
        return bool(explicit[pid])
    if data["profile"] == "enterprise":
        return pid in ENTERPRISE_PROVIDERS
    return True


def preferred_provider_order() -> tuple[str, ...]:
    """First allowed provider id, Copilot then local, then the rest."""
    preferred = ("github_copilot", "llamacpp", "mlx", "ollama")
    return tuple(p for p in preferred if provider_allowed(p))


def public_view() -> dict[str, Any]:
    """Safe JSON for the Settings UI (no filesystem internals beyond path)."""
    data = load()
    return {
        "profile": data["profile"],
        "source": data["source"],
        "features": dict(data["features"]),
        "providers": dict(data["providers"]),
    }
