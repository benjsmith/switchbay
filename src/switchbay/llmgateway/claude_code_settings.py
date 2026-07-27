"""Generate the per-workspace `.claude/settings.json` allowlist that
constrains the spawned Claude Code CLI to safe, workspace-scoped
operations.

CE pioneered this pattern (its setup.sh writes a workspace's
.claude/settings.json with a long permissions.allow array). Switch Bay
adopts the same shape but writes its OWN file at
`<workspace>/.workbench/state/claude-code-settings.json` and points
the spawned CLI at it via `--settings <path>`. That keeps switchbay's
constraints separate from any CE-managed `.claude/settings.json` the
workspace already has — claude-code stacks settings sources, so both
take effect.

The allowlist is intentionally tight: workspace-scoped Edit/Write/
Read, a curated set of read-only Bash commands, and our daemon tools
(via MCP, when that lands). Anything outside the list auto-denies in
print mode (`-p`), which is the safety floor.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

from .. import ce_toolscope

log = logging.getLogger("switchbay.claude_code_settings")

# The three generated files are rewritten before EVERY spawn. On a
# cloud-synced workspace (~/Documents = iCloud) a rewrite kicks
# fileproviderd into syncing the file, and a second open-for-write
# arriving while that's in flight fails with EDEADLK ("Resource
# deadlock avoided") — seen live when two provider spawns land close
# together (e.g. a chat dispatch + the background thread auto-titler).
# So: serialise writers in-process, skip the write entirely when the
# content is unchanged (the steady state), write via tmp + os.replace
# so the destination is never opened for write, and retry once on a
# transient OSError.
_WRITE_LOCK = threading.Lock()


def _write_if_changed(p: Path, content: str) -> None:
    with _WRITE_LOCK:
        try:
            if p.read_text(encoding="utf-8") == content:
                return
        except OSError:
            pass  # missing / unreadable → write it
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        for attempt in (1, 2):
            try:
                tmp.write_text(content, encoding="utf-8")
                os.replace(tmp, p)
                return
            except OSError:
                if attempt == 2:
                    raise
                time.sleep(0.2)


# Switch Bay-tools MCP server slug — must match the key under
# `mcpServers` in the JSON config. claude-code namespaces tool names
# as `mcp__<server>__<tool>`, so the allowlist below uses
# `mcp__switchbay__*`.
_MCP_SERVER_NAME = "switchbay"

# Bash commands the rail agent may run without a prompt. These are all
# read-only or write-to-workspace-only — no destructive operations,
# no network, no sudo. Anything missing here drops to a permission
# prompt; in `-p` mode that auto-denies.
_BASH_ALLOW = [
    # Inspection / reads — workspace-local only. `find` is intentionally
    # NOT auto-allowed: agents were running `find /Users/…` / `find ~`
    # which trips macOS "access data from other apps" TCC dialogs.
    # Prefer Grep/Glob tools, or `find .` after a card if truly needed.
    # Hard-deny of home/FS-wide scans lives in permissions.hard_deny_reason.
    "Bash(ls:*)",
    "Bash(cat:*)",
    "Bash(head:*)",
    "Bash(tail:*)",
    "Bash(wc:*)",
    "Bash(file:*)",
    "Bash(stat:*)",
    "Bash(grep:*)",
    "Bash(rg:*)",                    # ripgrep
    "Bash(awk:*)",
    "Bash(sed:* -n*:*)",             # only `sed -n` (read-mode); writes still prompt
    "Bash(tree:*)",
    "Bash(diff:*)",
    "Bash(date)",
    "Bash(pwd)",
    "Bash(echo:*)",
    "Bash(printf:*)",
    "Bash(sort:*)",
    "Bash(uniq:*)",
    "Bash(cut:*)",
    "Bash(tr:*)",
    # xargs alone is fine; chained `find … | xargs` still hits hard-deny
    # when the find side scans home.
    "Bash(xargs:*)",
    # Git read-only verbs. These run in the spawn cwd (= the
    # workspace), so they stay workspace-scoped without an explicit
    # path. Write verbs and `git -C <dir>` are NOT here — they come
    # from ce_toolscope, pinned to the wiki repo and workspace root.
    "Bash(git status*)",
    "Bash(git log*)",
    "Bash(git diff*)",
    "Bash(git show*)",
    "Bash(git branch*)",
    "Bash(git rev-parse*)",
    "Bash(git ls-files*)",
    # jq for JSON inspection
    "Bash(jq:*)",
]
# Deliberately NOT auto-allowed (2026-07-24), because each is
# arbitrary code execution wearing a narrow-looking prefix:
#   Bash(uv run python3 *:*) / Bash(uv run python *:*)
#     — ran any python file anywhere on the machine. CE's scripts are
#       now allowed by pinned skill root via ce_toolscope instead.
#   Bash(python3 -c *:*) / Bash(python -c *:*)
#     — inline source is a shell by another name.
#   Bash(git -C *:*)
#     — drove git in any repo on the machine, not just the wiki.
# All four now fall through to the rail approval card.

# Path-independent tool slugs that always go in the allowlist.
_FS_ALLOW_BASE = [
    "Glob",
    "Grep",
    "Read(/tmp/**)",
]


def _fs_allow_for_workspace(workspace: Path) -> list[str]:
    """File-scope tools — both relative and absolute forms because
    claude-code's tool calls vary: Read often passes absolute paths
    (which is what shows up in the rail when it Reads), Edit/Write
    can be either. The allowlist matches the literal file_path string,
    so we emit both `./**` (matches relative) AND `<abs>/**` (matches
    absolute paths that resolve under the workspace)."""
    abs_root = str(workspace.resolve())
    return [
        f"Edit({abs_root}/**)",
        f"Write({abs_root}/**)",
        f"Read({abs_root}/**)",
        "Edit(./**)",
        "Write(./**)",
        "Read(./**)",
    ]

# Auxiliary tools we want available without prompting.
_AUX_ALLOW = [
    "TodoWrite",
    "Skill",
    "BashOutput",          # read background bash output
    "ExitPlanMode",        # only relevant if anyone re-enables plan
    # Switch Bay's own tools, exposed via the in-tree MCP server.
    # claude-code namespaces them as `mcp__<server>__<tool>`; the
    # wildcard covers recall_rail, register_rule, list_duckdb_starters,
    # etc. as the registry grows.
    f"mcp__{_MCP_SERVER_NAME}__*",
]


def build_settings(workspace: Path, daemon_port: int) -> dict:
    """Return the dict serialised into the settings file for the given
    workspace. Single source of truth — keeps the layout tight so
    future edits stay structured.

    `daemon_port` is baked into the PreToolUse hook so the script can
    POST permission requests back to /api/permission/request. The
    hook script itself lives next to the settings file; see
    `write_permission_hook` below."""
    hook_script = _permission_hook_path(workspace)
    return {
        "permissions": {
            "allow": [
                *_fs_allow_for_workspace(workspace),
                *_FS_ALLOW_BASE,
                *_BASH_ALLOW,
                # The exact shell shapes CE + curiosity-merge need,
                # pinned to their installed skill roots. Without these
                # the curator can only propose edits — see
                # ce_toolscope's module docstring.
                *ce_toolscope.all_rules(workspace),
                *_AUX_ALLOW,
            ],
            # Belt-and-suspenders: even if a remembered user allow or an
            # older settings file auto-approved `Bash(find:*)`, deny
            # home/root finds at the CLI layer. PreToolUse hard-deny is
            # the authoritative gate; this reduces CLI-side noise.
            "deny": [
                "Bash(find /Users*)",
                "Bash(find /home*)",
                "Bash(find /Volumes*)",
                "Bash(find ~*)",
                "Bash(find $HOME*)",
                "Bash(find / *)",
                "Bash(find /*)",
                "Bash(mdfind*)",
                "Bash(locate /*)",
            ],
        },
        # PreToolUse fires for every tool call before claude-code's own
        # allowlist verdict. The hook returns `{decision: "approve"}`
        # or `{decision: "deny"}` (or `{}` to fall through to the
        # static allowlist). We route the unknowns to switchbay's
        # rail dialog and let the static `allow` list keep handling
        # the obviously-safe cases without prompting.
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"{sys.executable} {hook_script} {daemon_port}",
                            "timeout": 100,
                        },
                    ],
                },
            ],
        },
    }


def settings_path(workspace: Path) -> Path:
    return workspace / ".workbench" / "state" / "claude-code-settings.json"


def write(workspace: Path, daemon_port: int | None = None) -> Path:
    """Write the settings file for `workspace`. Idempotent — safe to
    call before every spawn so the allowlist always matches the
    current code. Also (re)writes the PreToolUse hook script so an
    updated daemon port + hook body land on the next spawn."""
    if daemon_port is None:
        try:
            daemon_port = int(os.environ.get("CSWY_DAEMON_PORT") or "8765")
        except ValueError:
            daemon_port = 8765
    return _write_internal(workspace, daemon_port)


def _write_internal(workspace: Path, daemon_port: int) -> Path:
    """Write the settings file for `workspace`. Idempotent — safe to
    call before every spawn so the allowlist always matches the
    current code. Also (re)writes the PreToolUse hook script so an
    updated daemon port + hook body land on the next spawn."""
    write_permission_hook(workspace)
    p = settings_path(workspace)
    _write_if_changed(
        p, json.dumps(build_settings(workspace, daemon_port), indent=2) + "\n",
    )
    return p


# ── PreToolUse hook script ─────────────────────────────────────────


def _permission_hook_path(workspace: Path) -> Path:
    return workspace / ".workbench" / "state" / "permission-hook.py"


_PERMISSION_HOOK_BODY = r'''#!/usr/bin/env python3
"""Switch Bay PreToolUse hook for spawned agent CLIs.

Runs once per tool invocation. Reads the CLI's event JSON from stdin,
POSTs `{provider, tool, input, run_id, cwd, origin_thread}` to
switchbay's /api/permission/request, long-polls for the verdict, and
prints the verdict back on stdout so the CLI can act on it.

`origin_thread` (env CSWY_THREAD_ID, set by the daemon's spawn) tells
the daemon which rail thread owns this CLI session; `cwd` identifies
the origin workspace. Sessions spawned outside the daemon (bench,
scripts) have neither — the rail shows their cards out-of-thread.

TWO DIALECTS (2026-07-24). The same script serves claude-code and
grok, which disagree on both halves of the contract:

                  claude-code                grok
  stdin keys      tool_name / tool_input     toolName / toolInput
                  session_id                 sessionId
  approve verdict {"decision":"approve"}     {"decision":"allow"}
  on hook error   falls through to the       FAILS OPEN — the tool
                  CLI's static allowlist     call proceeds

That last row is the dangerous one. For grok, "no output" means
"allow", so every failure path here must print an explicit deny
instead of falling silent. We detect the dialect from the payload
shape and set CSWY_HOOK_DIALECT at spawn time as a backstop.

Stay small + dependency-free — this runs in a foreign subprocess that
might not have switchbay on PYTHONPATH.
"""
import json
import os
import sys
import urllib.error
import urllib.request

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
# Must exceed permissions.REQUEST_TIMEOUT_S's practical wait: whoever
# kills us first decides, and for grok a kill means auto-approve.
TIMEOUT = float(os.environ.get("CSWY_HOOK_TIMEOUT") or "95")

try:
    raw = sys.stdin.read()
    payload = json.loads(raw or "{}")
except Exception:
    payload = {}

# camelCase keys are grok's; snake_case are claude-code's.
grok = "toolName" in payload or "hookEventName" in payload
if os.environ.get("CSWY_HOOK_DIALECT") == "grok":
    grok = True

tool = str(payload.get("tool_name") or payload.get("toolName") or "")
tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
session = str(payload.get("session_id") or payload.get("sessionId") or "")
provider = os.environ.get("CSWY_HOOK_PROVIDER") or (
    "grok-build" if grok else "claude-code")


def emit(verdict, reason=""):
    """Print in the caller's dialect and exit. `verdict` is one of
    'approve' | 'deny' | 'passthrough'."""
    if verdict == "approve":
        out = {"decision": "allow"} if grok else {"decision": "approve"}
    elif verdict == "passthrough":
        # claude-code: {} = no override, fall through to its static
        # allowlist. grok has no such fallthrough and fails open, so
        # a passthrough there must become an explicit deny.
        out = {"decision": "deny", "reason": reason} if grok else {}
    else:
        out = {"decision": "deny", "reason": reason or "denied by switchbay rail"}
    print(json.dumps(out))
    sys.exit(0)


# Empty tool name → nothing to adjudicate.
if not tool:
    emit("passthrough", "switchbay: unrecognised tool call")

req_body = json.dumps({
    "provider": provider,
    "tool": tool,
    "input": tool_input,
    "run_id": session,
    "cwd": str(payload.get("cwd") or payload.get("workspaceRoot") or ""),
    "origin_thread": os.environ.get("CSWY_THREAD_ID") or "",
}).encode()

try:
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/api/permission/request",
        data=req_body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        body = json.loads(resp.read().decode("utf-8") or "{}")
except (urllib.error.URLError, OSError, json.JSONDecodeError):
    # Daemon unreachable or timed out. claude-code falls through to
    # its static allowlist; grok would fail open, so deny explicitly.
    emit("passthrough", "switchbay: approval unavailable (daemon unreachable)")

decision = body.get("decision") or "deny"
if decision == "approve":
    emit("approve")
elif decision == "skip":
    # Source muted in the rail — Switch Bay stops mediating.
    emit("passthrough", "switchbay: mediation muted")
else:
    emit("deny")
'''


def write_permission_hook(workspace: Path) -> Path:
    p = _permission_hook_path(workspace)
    _write_if_changed(p, _PERMISSION_HOOK_BODY)
    try:
        p.chmod(0o755)
    except OSError:
        pass
    return p


# ── MCP config ─────────────────────────────────────────────────────


def mcp_config_path(workspace: Path) -> Path:
    return workspace / ".workbench" / "state" / "claude-code-mcp.json"


def _mcp_pythonpath() -> str:
    """Resolve a PYTHONPATH that finds the `switchbay` package so the
    spawned MCP server can `import switchbay.tools`. We use the same
    src/ that's already on the daemon's path; falls back to whatever
    the parent process exposes if not set."""
    here = Path(__file__).resolve()
    # Walk up from llmgateway/ to src/switchbay/llmgateway/ → src/.
    src = here.parent.parent.parent
    return str(src)


MCP_SERVER_NAME = _MCP_SERVER_NAME


def mcp_server_spec(workspace: Path) -> dict:
    """Provider-agnostic spawn descriptor for switchbay's MCP server:
    `{command, args, env}`. Talks JSON-RPC over stdio. PYTHONPATH
    points at switchbay's src so the server can import the tool
    registry without uv-syncing inside a foreign cwd. Consumed by
    claude-code (wrapped in `mcpServers` JSON) and by codex (folded
    into TOML `-c mcp_servers.<name>.…` overrides)."""
    return {
        "command": sys.executable,
        "args": ["-m", "switchbay.mcp_server"],
        "env": {
            "CSWY_WORKSPACE": str(workspace.resolve()),
            "PYTHONPATH": _mcp_pythonpath(),
            # Surface any keychain backend the parent set so tools
            # that read secrets (none today, but future-proof) work
            # without re-prompting.
            "PATH": os.environ.get("PATH", ""),
            # ask_thread routes through the daemon's local A2A
            # endpoint — the MCP subprocess needs to know the port.
            "CSWY_DAEMON_PORT": os.environ.get("CSWY_DAEMON_PORT", "8765"),
        },
    }


def build_mcp_config(workspace: Path) -> dict:
    """claude-code's `mcpServers` JSON shape: the first-party switchbay
    server plus any user-registered MCP servers (mcpstore). The
    switchbay entry always wins on a name clash (mcpstore rejects the
    reserved `switchbay` name at add time)."""
    from .. import mcpstore

    servers: dict[str, object] = {_MCP_SERVER_NAME: mcp_server_spec(workspace)}
    try:
        for name, spec in mcpstore.as_claude_mcp_servers().items():
            if name != _MCP_SERVER_NAME:
                servers[name] = spec
    except Exception:  # noqa: BLE001 — a bad user entry never breaks a spawn
        log.exception("failed to merge user MCP servers")
    return {"mcpServers": servers}


def write_mcp_config(workspace: Path) -> Path:
    """Write claude-code-mcp.json — pointed at by --mcp-config."""
    p = mcp_config_path(workspace)
    _write_if_changed(
        p, json.dumps(build_mcp_config(workspace), indent=2) + "\n",
    )
    return p
