"""Tool allowlist for the VS Code plugin (no HTTP daemon).

The plugin spawns ``python -m switchbay.mcp_server`` as a stdio worker
with ``CSWY_PROFILE=vscode``. This module is the allowlist that profile
loads. Anything that round-trips to ``:8765`` (sheet/table live tabs,
plot/sketch *show*, A2A threads, split-proposal HTTP) stays out so a
missing daemon cannot hang a tool call.

The PWA rail still uses ``agents.rail_default.ALLOWED_TOOLS``.
"""

from __future__ import annotations

import os
from typing import Any

from .agents import rail_default

# Tools whose handlers HTTP to the PWA daemon. Keep this set in sync
# with ``tools._daemon_json`` callers and the A2A/split HTTP helpers.
DAEMON_COUPLED: frozenset[str] = frozenset({
    "sheet_context",
    "sheet_select",
    "sheet_set_formula",
    "sheet_set_values",
    "table_context",
    "table_run_sql",
    "plot_show",
    "sketch_show",
    "list_threads",
    "ask_thread",
    "recall_rail",
    "propose_split",
})

PROFILE_ENV = "CSWY_PROFILE"
PLUGIN_PROFILES = frozenset({"vscode", "plugin"})

# Copilot already has a terminal tool. Do not expose ``run_command`` on
# the plugin MCP server — when that server is sandboxed, VS Code
# auto-approves its tools, and a shell would skip Copilot's terminal
# allowlist.
PLUGIN_OMIT: frozenset[str] = frozenset({
    "run_command",
})

DAEMON_UNAVAILABLE = (
    "this tool talks to the Switch Bay PWA daemon (:8765), "
    "which is not part of the VS Code plugin"
)


def is_plugin_profile() -> bool:
    return os.environ.get(PROFILE_ENV, "").strip().lower() in PLUGIN_PROFILES


def daemon_unavailable() -> dict[str, Any]:
    return {"ok": False, "error": DAEMON_UNAVAILABLE}


def _plugin_tools() -> tuple[str, ...]:
    return tuple(
        name for name in rail_default.ALLOWED_TOOLS
        if name not in DAEMON_COUPLED and name not in PLUGIN_OMIT
    )


ALLOWED_TOOLS: tuple[str, ...] = _plugin_tools()
