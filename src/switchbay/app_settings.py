"""General user-level application preferences.

Distinct from `llm_config` (LLM provider/model prefs) and `workspaces`
(the workspace registry): this is the catch-all for small global toggles
that aren't tied to a single subsystem. Stored next to the other config
at `$XDG_CONFIG_HOME/switchbay/settings.json` (default
`~/.config/switchbay/settings.json`).

Shape (all keys optional; absent → documented default):

  {
    "rail_history_local": true,   # see below
    "workspaces_home": "~/Workspaces"   # see below
  }

`rail_history_local` — where the per-workspace rail-history DB
(`conversations.db`) lives:
  * true (default) — in the machine-local state root (see `statedir`),
    off any sync service: fast + corruption-safe, but does not roam.
    This is the default because a live WAL-mode SQLite file on a sync
    service corrupts when the db and its -wal/-shm sidecars upload out
    of step (the charter forbids sqlite on synced paths).
  * false — inside `<workspace>/.workbench/state/`, so it ROAMS across
    machines with whatever sync service backs the workspace folder.
    Opt-in for users who want chat history to follow them, accepting the
    corruption risk; the robust long-term form is to roam an export
    rather than the live DB.
"""

from __future__ import annotations

import json
from typing import Any

from . import workspaces
from . import atomicio


def _path():
    return workspaces.config_dir() / "settings.json"


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


def get_rail_history_local() -> bool:
    # Default TRUE: a live WAL-mode SQLite file on a cloud-sync service
    # (iCloud/Dropbox/OneDrive) corrupts when the db and its -wal/-shm
    # sidecars upload out of step — the charter forbids sqlite on synced
    # paths. Machine-local is the safe default; users who want history to
    # roam opt in via the Settings toggle (stored `false`, preserved by
    # the explicit default here). On the next boot after this change,
    # `_ensure_rail_history_location` migrates an existing in-workspace DB
    # (+ sidecars) into the state root.
    return bool(load().get("rail_history_local", True))


def set_rail_history_local(value: bool) -> None:
    data = load()
    data["rail_history_local"] = bool(value)
    save(data)


# `embedding_backend` — which backend powers Tier-3 semantic recall:
#   * "auto" (default) — LOCAL only: fastembed (ONNX) if installed, else
#     sentence-transformers, else FTS-only. Nothing leaves the machine.
#   * "openai" / "gemini" — VENDOR API: rail text is sent to that
#     provider's embeddings endpoint (reuses its configured key). Opt-in
#     ONLY — it trades the local-privacy guarantee for zero local ML.
# A vendor backend requesting a wrong/absent key fails soft to FTS-only.
_EMBED_BACKENDS = ("auto", "openai", "gemini")


def get_embedding_backend() -> str:
    v = str(load().get("embedding_backend") or "auto").strip().lower()
    return v if v in _EMBED_BACKENDS else "auto"


def set_embedding_backend(value: str) -> None:
    v = str(value or "auto").strip().lower()
    if v not in _EMBED_BACKENDS:
        raise ValueError(f"embedding_backend must be one of {_EMBED_BACKENDS}")
    data = load()
    data["embedding_backend"] = v
    save(data)


# `workspaces_home` — the fixed home directory where NEW workspaces
# born inside switchbay (merge results, split-offs, wizard-created)
# land, and where the migrate-into-home affordance moves existing
# ones (stage-5 design pass, 2026-07-05). Default `~/Workspaces`.
# The ONE user decision is cloud tracking: pointing it at
# `~/Documents/Workspaces` (or a Dropbox/Drive path) makes every
# workspace roam via that service — supported (the daemon is robust
# to synced workspaces) at the usual sync-eviction latency cost.

_WORKSPACES_HOME_DEFAULT = "~/Workspaces"


def get_workspaces_home() -> str:
    """The configured home as stored (may contain `~`)."""
    raw = str(load().get("workspaces_home") or "").strip()
    return raw or _WORKSPACES_HOME_DEFAULT


def workspaces_home_path():
    """The expanded home path. NOT created here — callers mkdir on
    first real use so a mere Settings read never litters $HOME."""
    from pathlib import Path
    import os
    return Path(os.path.expanduser(get_workspaces_home()))


def set_workspaces_home(value: str) -> None:
    data = load()
    data["workspaces_home"] = str(value).strip() or _WORKSPACES_HOME_DEFAULT
    save(data)
