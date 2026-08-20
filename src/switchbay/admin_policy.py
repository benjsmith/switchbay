"""Machine-level admin policy. The daemon never writes this file.

Default profile is ``open`` (today's product: every provider, HF
downloads on). ``SWITCHBAY_PROFILE=enterprise`` or an admin file with
``"profile": "enterprise"`` locks to Copilot + local models and turns
off EDR-noisy hooks. Admins can flip individual flags back on — in
particular ``hf_model_download`` — in the admin file at packaging
time or via MDM overlay.

Search order (first existing file wins):

  1. ``$SWITCHBAY_ADMIN_POLICY``
  2. ``%ProgramData%\\SwitchBay\\admin.json``  (Windows MDM)
  3. ``/Library/Application Support/SwitchBay/admin.json``  (macOS MDM)
  4. ``/etc/switchbay/admin.json``
  5. ``<repo>/admin.json``  (optional drop-in next to the checkout)

``SWITCHBAY_PROFILE=open`` is the default. Enterprise payloads stamp
``SWITCHBAY_PROFILE=enterprise``.

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

# Consumer / git-checkout default. Enterprise packages stamp
# SWITCHBAY_PROFILE=enterprise (or drop an admin.json).
DEFAULT_PROFILE = "open"

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
    "interactive_terminal": True,
    "agent_run_command": True,
    "demo_workspace": True,
}

FEATURE_DEFAULTS_ENTERPRISE: dict[str, bool] = {
    **FEATURE_DEFAULTS_OPEN,
    "in_app_update": False,
    # VS Code parity: users may `npx`/`uvx skills add` unless IT locks it.
    "install_skills_npx": True,
    "ce_auto_setup": False,
    "uv_python_install": False,
    "scan_other_app_caches": False,
    "hf_model_download": False,
    "comms_streams": False,
    "github_share": False,
    "media_generation": False,
    "user_mcp_servers": True,
    "watch_folders": True,
    "interactive_terminal": True,
    "agent_run_command": True,
    "demo_workspace": False,
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
    if sys.platform == "win32":
        pd = os.environ.get("PROGRAMDATA") or r"C:\ProgramData"
        out.append(Path(pd) / "SwitchBay" / "admin.json")
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


def install_root() -> Path | None:
    env = (os.environ.get("SWITCHBAY_INSTALL_ROOT") or "").strip()
    if env:
        return Path(env).expanduser()
    repo = _repo_root()
    if (repo / "admin.baked.json").is_file() or (repo / "SWITCHBAY_PROFILE").is_file():
        return repo
    return None


def baked_path() -> Path | None:
    root = install_root()
    if root is None:
        return None
    p = root / "admin.baked.json"
    return p if p.is_file() else None


def _mtime(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return str(path.stat().st_mtime_ns)
    except OSError:
        return "err"


def _merge_features(base: dict[str, bool], overlay: Any, *, tighten_only: bool) -> dict[str, bool]:
    out = dict(base)
    if not isinstance(overlay, dict):
        return out
    for k, v in overlay.items():
        if k not in out:
            continue
        flag = bool(v)
        out[k] = bool(out[k] and flag) if tighten_only else flag
    return out


def _merge_providers(base: dict[str, bool], overlay: Any, *, tighten_only: bool) -> dict[str, bool]:
    out = dict(base)
    if not isinstance(overlay, dict):
        return out
    for k, v in overlay.items():
        kid = str(k).strip()
        if not kid:
            continue
        flag = bool(v)
        if tighten_only and kid in out:
            out[kid] = bool(out[kid] and flag)
        elif tighten_only:
            out[kid] = flag and (kid in ENTERPRISE_PROVIDERS)
        else:
            out[kid] = flag
    return out


def _as_allowlist(raw: Any, default: str | list = "*") -> str | list[str]:
    if raw is None:
        return default
    if raw == "*" or raw is True:
        return "*"
    if raw is False or raw == []:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return default


def load(*, force: bool = False) -> dict[str, Any]:
    """Resolved policy. Cached per (path, mtime, env profile)."""
    global _cache, _cache_key
    overlay_path = _existing_path()
    baked = baked_path()
    key = (
        str(overlay_path) if overlay_path else "",
        _mtime(overlay_path),
        str(baked) if baked else "",
        _mtime(baked),
        os.environ.get("SWITCHBAY_PROFILE") or "",
        os.environ.get("SWITCHBAY_ADMIN_POLICY") or "",
        os.environ.get("SWITCHBAY_INSTALL_ROOT") or "",
    )
    if not force and _cache is not None and _cache_key == key:
        return _cache
    overlay = _read_file(overlay_path) if overlay_path is not None else {}
    baked_data = _read_file(baked) if baked is not None else {}
    tighten = bool(baked_data)
    allow_override = bool(baked_data.get("allow_profile_override")) if baked_data else True
    env_profile = _profile_override()
    file_profile = str(
        (baked_data.get("profile") if baked_data else None)
        or overlay.get("profile") or ""
    ).strip().lower()
    if tighten and not allow_override:
        profile = str(baked_data.get("profile") or "enterprise").strip().lower()
    else:
        profile = env_profile or file_profile or DEFAULT_PROFILE
    if profile not in ("open", "enterprise"):
        profile = DEFAULT_PROFILE

    features = dict(
        FEATURE_DEFAULTS_ENTERPRISE if profile == "enterprise"
        else FEATURE_DEFAULTS_OPEN
    )
    features = _merge_features(features, baked_data.get("features"), tighten_only=False)
    features = _merge_features(features, overlay.get("features"), tighten_only=tighten)

    providers: dict[str, bool] = {}
    providers = _merge_providers(providers, baked_data.get("providers"), tighten_only=False)
    providers = _merge_providers(providers, overlay.get("providers"), tighten_only=tighten)

    copilot = {}
    for src in (baked_data, overlay):
        raw = src.get("copilot")
        if isinstance(raw, dict):
            copilot.update(raw)
    network = {}
    for src in (baked_data, overlay):
        raw = src.get("network")
        if isinstance(raw, dict):
            network.update(raw)
    mcp = {}
    for src in (baked_data, overlay):
        raw = src.get("mcp")
        if isinstance(raw, dict):
            mcp.update(raw)
    skills = {}
    for src in (baked_data, overlay):
        raw = src.get("skills")
        if isinstance(raw, dict):
            skills.update(raw)
    paths = {}
    for src in (baked_data, overlay):
        raw = src.get("paths")
        if isinstance(raw, dict):
            paths.update(raw)

    resolved = {
        "profile": profile,
        "source": str(overlay_path) if overlay_path else (str(baked) if baked else None),
        "baked": str(baked) if baked else None,
        "features": features,
        "providers": providers,
        "copilot": copilot,
        "network": network,
        "mcp": mcp,
        "skills": skills,
        "paths": paths,
        "allow_profile_override": allow_override,
        "tighten": tighten,
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
        return profile() != "enterprise"
    return bool(feats[name])


def feature_error(name: str) -> str:
    return f"disabled by admin policy ({name})"


def provider_allowed(provider_id: str) -> bool:
    pid = (provider_id or "").strip()
    if not pid:
        return False
    if pid == "mlx" and sys.platform != "darwin":
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
        "copilot": {
            "host": copilot_host(),
            "lock_host": copilot_lock_host(),
        },
        "mcp_allowlist": mcp_allowlist(),
        "skills_allowlist": skills_allowlist(),
        "pty_available": True,
    }


def copilot_host() -> str:
    raw = str((load().get("copilot") or {}).get("host") or "").strip()
    return raw or "github.com"


def copilot_sso_slug() -> str:
    return str((load().get("copilot") or {}).get("sso_slug") or "").strip()


def copilot_lock_host() -> bool:
    data = load()
    if "lock_host" in (data.get("copilot") or {}):
        return bool(data["copilot"]["lock_host"])
    return data["profile"] == "enterprise"


def bind_host() -> str:
    raw = str((load().get("network") or {}).get("bind_host") or "").strip()
    return raw or "127.0.0.1"


def bind_port() -> int | None:
    raw = (load().get("network") or {}).get("bind_port")
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= 65535 else None


def workspaces_home_policy() -> str | None:
    raw = str((load().get("paths") or {}).get("workspaces_home") or "").strip()
    return raw or None


def allow_synced_workspaces() -> bool:
    paths = load().get("paths") or {}
    if "allow_synced_workspaces" in paths:
        return bool(paths["allow_synced_workspaces"])
    return profile() != "enterprise"


def mcp_allowlist() -> str | list[str]:
    return _as_allowlist((load().get("mcp") or {}).get("allowlist"), "*")


def skills_allowlist() -> str | list[str]:
    return _as_allowlist((load().get("skills") or {}).get("allowlist"), "*")


def _ref_allowed(ref: str, allow: str | list[str]) -> bool:
    import fnmatch
    r = (ref or "").strip()
    if not r:
        return False
    if allow == "*":
        return True
    if not allow:
        return False
    for pat in allow:
        if fnmatch.fnmatch(r, pat) or r.startswith(pat.rstrip("*")):
            return True
    return False


def mcp_entry_allowed(name: str, command: str = "", url: str = "") -> bool:
    blob = " ".join(x for x in (name, command, url) if x)
    return _ref_allowed(blob, mcp_allowlist()) or _ref_allowed(name, mcp_allowlist())


def skills_ref_allowed(ref: str) -> bool:
    return _ref_allowed(ref, skills_allowlist())


def derived_copilot_hosts() -> list[str]:
    host = copilot_host().lower()
    out = {host}
    if host == "github.com":
        out.update({
            "api.github.com", "api.githubcopilot.com",
            "github.com", "copilot-proxy.githubusercontent.com",
        })
    else:
        out.update({host, f"api.{host}"})
    return sorted(out)


def egress_allowed(url: str) -> bool:
    from urllib.parse import urlparse
    if profile() != "enterprise":
        return True
    raw = (url or "").strip()
    if not raw:
        return False
    host = (urlparse(raw).hostname or "").lower()
    if host in ("127.0.0.1", "localhost", "::1"):
        return True
    extra = (load().get("network") or {}).get("egress_allowlist")
    allow = set(derived_copilot_hosts())
    if isinstance(extra, list) and extra:
        allow = {str(x).strip().lower() for x in extra if str(x).strip()}
    if host in allow:
        return True
    return any(host.endswith("." + h) for h in allow if h)
