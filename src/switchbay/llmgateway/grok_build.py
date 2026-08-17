"""Grok Build (xAI) as a subprocess-backed provider.

Grok Build is xAI's agentic coding CLI (launched May 2026), the direct
counterpart of Claude Code / OpenAI Codex: a subscription-backed
(`SuperGrok` / `X Premium+`) terminal agent invoked as `grok`, with
native MCP support (zero-reconfig from a Claude Code MCP setup). We wrap
it the same way as `claude_code.py` — spawn the CLI per turn, parse its
line-delimited streaming-json events into our canonical ChunkEvents.

Validated against a live `grok` 0.2.93 install (2026-07-10):
  · headless single-turn: `grok -p "<prompt>" --output-format
    streaming-json --cwd <workspace> [--model M] [--rules <sys>]
    [--resume <session_id>]`.
  · streaming-json is TOKEN-level, distinct event types:
      {"type":"thought","data":"…"}  → reasoning (chain-of-thought)
      {"type":"text","data":"…"}     → response text
      {"type":"end","stopReason":"EndTurn","sessionId":"…"} → done
    (no per-turn usage in streaming-json today → tokens stay None.)
  · `--rules` APPENDS to grok's own system prompt (Claude Code's
    --append-system-prompt); `--system-prompt-override` would replace
    it, which we don't want. `-p/--single` prints and exits.
  · CLI default model is `grok-4.6` as of grok 1.0.3 (grok-build-0.1 is
    API-only, not a CLI model). We do NOT pass `--always-approve`.

MCP tool bridge (done, validated live): `_ensure_mcp` registers
switchbay's MCP server in `<workspace>/.grok/config.toml` (project
scope, idempotent) so grok exposes our tools; the spawn passes
`--trust` (project-scoped MCP is gated on folder trust) and
`--allow "MCPTool(switchbay__*)"` so they run without an interactive
approval `-p` mode can't answer. Without `--trust`, Grok refuses to
start repo-local MCP servers ("folder untrusted") and the model sees
an empty tool list. Grok permission rules use Claude-compat prefixes
for built-ins but MCPTool(server__tool) for MCP — `mcp__switchbay__*`
NEVER matches (Grok strips the mcp__ prefix). grok's streaming-json does NOT surface tool_use
events (tools run silently in the MCP layer) — the tools still
execute in the subprocess and their effects land via the daemon's
run-end scans (reports.created_since / the proposal scan), same as
claude_code.

Shell / edit / write (amended 2026-07-24)
-----------------------------------------
These used to be stripped outright (`--disallowed-tools
run_terminal_cmd,search_replace` + `--deny Bash/Edit/Write`) on the
theory that curation should go through the `propose_*` MCP tools. That
turned out to break curation rather than constrain it: the model
ladder's `normal` rung routes `/curate` here (see
`daemon._ce_action_provider`), and a curator with no shell cannot run
curiosity-engine's scripts at all — it reads the wiki and hands every
single change back as a user proposal.

Now grok gets the SAME scoped surface claude-code has, mediated by a
`PreToolUse` hook in `<workspace>/.grok/hooks/` that POSTs to
switchbay's `/api/permission/request`:

  · CE / curiosity-merge call shapes (scripts pinned to their skill
    roots, git pinned to the wiki repo, writes pinned to the wiki /
    .curator / vault dirs) are auto-approved by `is_pre_approved`
    (via `ce_toolscope`) — no card.
  · everything else blocks on the rail approval card — the same
    dialog and the same remembered-approvals store claude-code uses.

Unlike claude-code, grok's `--allow`/`--deny` rules can't carry the
approval flow: its hook fires BEFORE the rules and can only DENY, and
headless `-p` cancels anything not explicitly allowed. So grok runs
under `bypassPermissions`, where the hook is the sole gate (hook-deny
+ hard `--deny` rules still apply; everything else is approved). The
scoped `ce_toolscope.all_rules()` are still passed as `--allow`, but
only as a fallback for the case where an admin disables bypass mode —
under bypass they are inert. See the authorization-order note at the
spawn site.

Two Grok-specific hazards this has to handle, both verified against
the 0.2.106 docs (`~/.grok/docs/user-guide/10-hooks.md`):

  1. Grok hooks **fail OPEN** — a hook that times out, crashes, or
     prints nothing lets the tool call proceed. claude-code's hook
     falls through to its static allowlist instead. So our hook must
     emit an explicit `{"decision":"deny"}` on every failure path, and
     the hook timeout must exceed the rail card's own timeout or a
     slow human becomes an auto-approve.
  2. The payload and verdict vocabulary differ: Grok sends camelCase
     (`toolName` / `toolInput`) and expects `{"decision":"allow"}`,
     where claude-code sends snake_case (`tool_name` / `tool_input`)
     and expects `"approve"`. The shared hook script speaks both.

Hard denies (home/filesystem-wide scans) stay as `--deny` flags: those
are refused server-side by `permissions.hard_deny_reason` too, but
keeping them at the CLI layer means grok never even attempts the call
that would trip a macOS TCC dialog.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import sys
from pathlib import Path
from typing import AsyncIterator

from .. import ce_toolscope, workspaces
from . import base

log = logging.getLogger("switchbay.llm.grok_build")

ID = "grok-build"
LABEL = "Grok Build"
BINARY = "grok"
DEFAULT_MODEL = "grok-4.6"

# CLI `--deny` aborts the process on an unknown prefix (config-file
# load only warns). Grok 1.0.4 recognized names — docs
# 22-permissions-and-safety.md "Tool Names":
#   Bash, Read, Edit (and Write), Grep (and Glob), MCPTool,
#   WebFetch, WebSearch.
# NotebookEdit / NotebookRead / Shell used to be listed as aliases
# and now hard-fail spawn ("unsupported tool prefix"). Never pass
# those as `--deny`.
DENY_PREFIXES = frozenset({
    "Bash", "Read", "Edit", "Write", "Grep", "Glob",
    "MCPTool", "WebFetch", "WebSearch", "*",
})

# Home / filesystem-wide scans that trip macOS TCC. The rail
# (`permissions.hard_deny_reason`) refuses these too; blocking at
# the CLI layer means grok never attempts the call. Notebook edits
# are no longer a Grok permission prefix — the PreToolUse hook
# still denies a NotebookEdit tool if a future CLI reintroduces it.
HARD_DENY_RULES = (
    "Bash(find /Users*)",
    "Bash(find ~*)",
    "Bash(find /*)",
    "Bash(mdfind*)",
    "Bash(locate /*)",
)


def deny_argv(rules: tuple[str, ...] | list[str] = HARD_DENY_RULES) -> list[str]:
    """`--deny` flag pairs, skipping prefixes this grok CLI rejects."""
    out: list[str] = []
    for rule in rules:
        prefix = rule.split("(", 1)[0]
        if prefix not in DENY_PREFIXES:
            log.warning(
                "skipping grok --deny %s: unsupported prefix %s",
                rule, prefix)
            continue
        out.extend(["--deny", rule])
    return out


def parse_tool_call(evt: dict) -> tuple[str, str, dict] | None:
    """Map a grok streaming-json tool event to (id, name, input).

    Grok 1.0.x `streaming-json` uses ACP field names (`toolCallId`,
    `toolName`, `rawInput`) — not Claude's `id`/`name`/`input`.
    Missing those used to emit empty TOOL () rows in the rail and
    Agents panel. `tool_call_update` is progress, not a new call.
    """
    if not isinstance(evt, dict):
        return None
    etype = evt.get("type")
    if etype not in ("tool_use", "tool_call"):
        return None
    name = (
        evt.get("name") or evt.get("tool") or evt.get("toolName")
        or evt.get("title") or ""
    )
    name = str(name).strip()
    if not name:
        return None
    raw = evt.get("input") or evt.get("arguments") or evt.get("rawInput")
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raw = {"value": raw}
    tid = str(
        evt.get("id") or evt.get("toolUseId") or evt.get("toolCallId") or ""
    )
    return tid, name, raw

PROVIDER = {
    "id": ID,
    "label": LABEL,
    "category": "subscription",
    "default_model": DEFAULT_MODEL,
    "binary": BINARY,
    "auth_help": (
        "Install Grok Build (`curl -fsSL https://x.ai/cli/install.sh | "
        "bash`) and sign in with your SuperGrok / X Premium+ subscription "
        "(`grok` → /login). Needs the `grok` binary on PATH."
    ),
    # Seed only — list_models() reads `grok models` / ~/.grok/models_cache.json
    # so the picker tracks the installed CLI. grok-build-0.1 is API-only.
    "model_suggestions": [
        "grok-4.6",
        "grok-4.5",
        "grok-composer-2.5-fast",
    ],
    "capabilities": {
        "chat": True,
        "streaming": True,
        "tools": False,
        # Execution surface — see base.CAPABILITY_NOTES.
        # spawns the grok CLI; scoped by ce_toolscope + rail card.
        "shell": True,
        "file_write": True,
        "key_validation": True,
    },
}


def grok_binary() -> str | None:
    """Resolve the `grok` CLI.

    launchd/systemd agents often have a slim PATH that still includes
    ``~/.local/bin`` but not ``~/.grok/bin`` (the installer's primary
    drop). Probe both plus PATH.
    """
    found = shutil.which(BINARY)
    if found:
        return found
    home = Path.home()
    for cand in (
        home / ".grok" / "bin" / BINARY,
        home / ".local" / "bin" / BINARY,
    ):
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    return None


def is_installed() -> bool:
    return grok_binary() is not None


def _signed_in() -> bool:
    """Grok Build stores OAuth in ~/.grok/auth.json (keyed by issuer)."""
    p = Path.home() / ".grok" / "auth.json"
    if not p.is_file():
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and any(bool(v) for v in data.values())


def has_key() -> bool:
    """Available = CLI present *and* signed in."""
    return is_installed() and _signed_in()


_DEFAULT_MODEL_RE = re.compile(r"^Default model:\s+(\S+)", re.I)
_BULLET_MODEL_RE = re.compile(r"^\s*[\*\-•]\s+(\S+)")


def parse_models_cli(text: str) -> list[str]:
    """Parse `grok models` human output. Default first, then the rest."""
    default: str | None = None
    found: list[str] = []
    in_list = False
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        dm = _DEFAULT_MODEL_RE.match(line)
        if dm:
            default = dm.group(1)
            continue
        if line.lower().startswith("available models"):
            in_list = True
            continue
        if not in_list:
            continue
        bm = _BULLET_MODEL_RE.match(raw)
        if bm:
            mid = bm.group(1)
            if mid not in found:
                found.append(mid)
            continue
        # Next prose section ends the list.
        if line[0].isalnum():
            in_list = False
    if default and default not in found:
        found.insert(0, default)
    elif default and found and found[0] != default:
        found = [default] + [m for m in found if m != default]
    return found


def models_from_cache(path: Path | None = None) -> list[str]:
    """Read ~/.grok/models_cache.json (same list the CLI refreshes)."""
    p = path or (Path.home() / ".grok" / "models_cache.json")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, dict):
        return []
    out: list[str] = []
    for mid, rec in models.items():
        if not isinstance(mid, str) or not mid:
            continue
        info = rec.get("info") if isinstance(rec, dict) else None
        if isinstance(info, dict) and info.get("hidden"):
            continue
        out.append(mid)
    return out


async def list_models() -> list[str]:
    """Live CLI catalogue — `grok models`, then the CLI's own cache.

    The xAI HTTP provider lists api.x.ai models; this lists what the
    *subscription CLI* will actually accept via ``--model``.
    """
    binary = grok_binary()
    if binary:
        try:
            proc = await asyncio.create_subprocess_exec(
                binary, "models",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _err = await asyncio.wait_for(proc.communicate(), timeout=8.0)
            parsed = parse_models_cli(stdout.decode("utf-8", errors="replace"))
            if parsed:
                return parsed
        except Exception:  # noqa: BLE001
            log.warning("grok models failed — falling back to cache", exc_info=True)
    return models_from_cache()


def _content_to_text(content: object) -> str:
    if isinstance(content, list):
        return " ".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return str(content)


def _flatten_messages(messages: list[dict]) -> str:
    parts: list[str] = []
    for m in messages:
        role = str(m.get("role", "user"))
        parts.append(f"{role.upper()}: {_content_to_text(m.get('content', ''))}")
    return "\n\n".join(parts)


def _strip_legacy_mcp_servers(cfg: Path) -> None:
    """Drop pre-rename MCP server stanzas (product was briefly called
    switchyard). Grok merges `grok mcp add` and never removes old
    keys, so a leftover `[mcp_servers.switchyard]` kept a dead server
    alive next to switchbay."""
    try:
        txt = cfg.read_text(encoding="utf-8")
    except OSError:
        return
    if "mcp_servers.switchyard" not in txt and "switchyard.mcp_server" not in txt:
        return
    # TOML is line-oriented enough here: drop any [mcp_servers.switchyard]
    # table (and its indented/key=value body) until the next top-level
    # table header. Also drop a lone wrong module path if present.
    lines = txt.splitlines(keepends=True)
    out: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            skipping = stripped in (
                "[mcp_servers.switchyard]",
                "[mcp_servers.switchyard.env]",
            )
            if skipping:
                continue
        if skipping:
            # Continue skipping until next table; blank lines inside
            # the legacy block stay dropped.
            if stripped.startswith("["):
                skipping = False
                # fall through to emit this new table header
            else:
                continue
        out.append(line)
    new = "".join(out)
    if new != txt:
        try:
            cfg.write_text(new, encoding="utf-8")
            log.info("stripped legacy mcp_servers.switchyard from %s", cfg)
        except OSError:
            log.exception("failed to strip legacy MCP server from %s", cfg)


async def _ensure_mcp(workspace: Path) -> None:
    """Register switchbay's MCP server in <workspace>/.grok/config.toml
    (project scope) so grok exposes our tools (create_report, propose_*,
    wiki tools). Idempotent + guarded — only runs `grok mcp add` when the
    config is missing or its command path is stale, so it's a one-time
    cost per workspace. `grok mcp add` merges (never clobbers other
    project config). Best-effort: a failure just means chat-only."""
    from . import claude_code_settings as ccs
    spec = ccs.mcp_server_spec(workspace)
    cfg = workspace / ".grok" / "config.toml"
    if cfg.is_file():
        _strip_legacy_mcp_servers(cfg)
    try:
        if cfg.is_file():
            txt = cfg.read_text(encoding="utf-8")
            if "[mcp_servers.switchbay]" in txt and spec["command"] in txt:
                return
    except OSError:
        pass
    argv = [grok_binary() or "grok", "mcp", "add", "switchbay", spec["command"]]
    for k, v in spec["env"].items():
        argv += ["-e", f"{k}={v}"]
    argv += ["-s", "project", "--"] + list(spec["args"])
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(workspace),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await asyncio.wait_for(proc.wait(), timeout=15)
    except Exception:  # noqa: BLE001
        log.exception("grok mcp add failed (chat still works)")
    # User-registered stdio MCP servers (mcpstore). Each is `grok mcp add`
    # (idempotent merge). Their tools appear as `<name>__tool` and card
    # through the rail like any other tool under bypassPermissions —
    # only switchbay's own tools are on the promptless floor.
    try:
        from .. import mcpstore

        for s in mcpstore.enabled_servers():
            if s["transport"] != "stdio" or not s.get("command") or s["name"] == "switchbay":
                continue
            uargv = [grok_binary() or "grok", "mcp", "add", s["name"], s["command"]]
            for k, v in (s.get("env") or {}).items():
                uargv += ["-e", f"{k}={v}"]
            uargv += ["-s", "project", "--"] + list(s.get("args") or [])
            try:
                up = await asyncio.create_subprocess_exec(
                    *uargv, cwd=str(workspace),
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                await asyncio.wait_for(up.wait(), timeout=15)
            except Exception:  # noqa: BLE001
                log.exception("grok mcp add %s failed", s["name"])
    except Exception:  # noqa: BLE001
        log.exception("failed to enumerate user MCP servers for grok")
    if cfg.is_file():
        _strip_legacy_mcp_servers(cfg)


# Grok's hook timeout is a hard kill, and a killed hook FAILS OPEN.
# It must therefore outlast the rail card's own wait
# (permissions.REQUEST_TIMEOUT_S = 1800s) — otherwise a user who takes
# too long to click Approve gets a silent auto-approve instead of the
# deny they'd expect. Padded past it so the daemon always decides
# first and the hook exits normally with an explicit verdict.
HOOK_TIMEOUT_S = 1860


def hooks_path(workspace: Path) -> Path:
    return workspace / ".grok" / "hooks" / "switchbay-permission.json"


def _daemon_port() -> int:
    try:
        return int(os.environ.get("CSWY_DAEMON_PORT") or "8765")
    except ValueError:
        return 8765


def _ensure_hooks(workspace: Path, daemon_port: int) -> None:
    """Install the PreToolUse hook that routes grok's unlisted tool
    calls to switchbay's rail approval card.

    Project-scoped hooks live in `<workspace>/.grok/hooks/*.json` and
    are gated on folder trust — the spawn already passes `--trust` for
    the MCP server, and Grok unifies trust across MCP/LSP/hooks, so
    the same grant covers this.

    Reuses claude_code_settings' hook script verbatim (it speaks both
    dialects); only the invocation differs. Best-effort: if this can't
    be written we do NOT proceed with a scoped-shell spawn, because an
    un-hooked grok would silently auto-deny everything outside the
    static allowlist rather than card it. The caller checks the return
    of `_ensure_hooks_ok`.
    """
    from . import claude_code_settings as ccs

    script = ccs.write_permission_hook(workspace)
    cfg = {
        "hooks": {
            "PreToolUse": [
                {
                    # Empty matcher = every tool. Grok maps Claude tool
                    # names onto its own (Bash → run_terminal_command),
                    # so a name-based matcher would need both spellings.
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"{sys.executable} {script} {daemon_port}",
                            "timeout": HOOK_TIMEOUT_S,
                            "env": {
                                "CSWY_HOOK_DIALECT": "grok",
                                "CSWY_HOOK_PROVIDER": ID,
                                "CSWY_HOOK_TIMEOUT": str(HOOK_TIMEOUT_S - 30),
                            },
                        },
                    ],
                },
            ],
        },
    }
    p = hooks_path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(cfg, indent=2) + "\n"
    try:
        if p.read_text(encoding="utf-8") == content:
            return
    except OSError:
        pass
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, p)


def _ensure_hooks_ok(workspace: Path, daemon_port: int) -> bool:
    """True when the approval hook is installed. False means we must
    fall back to the old propose-only surface — see chat_stream."""
    try:
        _ensure_hooks(workspace, daemon_port)
        return hooks_path(workspace).is_file()
    except Exception:  # noqa: BLE001
        log.exception("failed to install grok permission hook")
        return False


def _verify_workspace(raw: str | None) -> Path:
    if not raw:
        raise base.ProviderError(
            "grok_build refuses to spawn without an explicit workspace cwd",
            code="server")
    p = Path(raw)
    if not p.is_absolute() or not p.is_dir():
        raise base.ProviderError(
            f"grok_build workspace must be an absolute existing directory: {raw}",
            code="server")
    if not workspaces.is_within_home(p):
        raise base.ProviderError(
            f"grok_build refuses to run with workspace outside {workspaces.home_label()}",
            code="server")
    return p.resolve()


# ── Reasoning effort ────────────────────────────────────────────────
# `grok --reasoning-effort <EFFORT>` (alias `--effort`) — "Reasoning
# effort for reasoning models". Enum verified against the installed
# binary: an unknown value is a hard error listing the valid set, so
# this must stay in step with the CLI rather than be assumed.
#
# Narrower than the API provider's low/high because the CLI accepts a
# middle rung; gated to reasoning-capable models for the same reason as
# `xai` — the flag is meaningless on the others.

_NON_REASONING_HINTS = ("non-reasoning", "composer")
_XHIGH_SINCE = (4, 6)  # grok-4.6 CLI menu advertises xhigh; 4.5 does not.


def _model_version(model: str) -> tuple[int, int] | None:
    m = re.search(r"grok-(\d+)(?:\.(\d+))?", model)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2) or 0)


def reasoning_options(model: str | None = None) -> list[dict]:
    m = (model or DEFAULT_MODEL or "").lower()
    if any(h in m for h in _NON_REASONING_HINTS):
        return []
    opts = [
        base.reasoning_option("low", "Low", "fast and much cheaper"),
        base.reasoning_option("medium", "Medium", "balanced"),
        base.reasoning_option("high", "High", "for planning and hard problems"),
    ]
    ver = _model_version(m)
    if ver is not None and ver >= _XHIGH_SINCE:
        opts.append(base.reasoning_option(
            "xhigh", "Extra high", "highest effort — grok-4.6+"))
    return opts


async def chat_stream(req: base.ChatRequest) -> AsyncIterator[base.ChunkEvent]:
    binary = grok_binary()
    if not binary:
        raise base.ProviderError(
            "`grok` not found on PATH. Install Grok Build: "
            "`curl -fsSL https://x.ai/cli/install.sh | bash`.",
            code="missing-key")

    workspace = _verify_workspace(req.workspace)
    # Register switchbay's MCP tools for this workspace (idempotent) so
    # grok can call create_report / propose_* / the wiki tools.
    await _ensure_mcp(workspace)
    prompt = (_content_to_text(req.messages[-1].get("content", ""))
              if req.session_id and req.messages else _flatten_messages(req.messages))

    argv = [binary, "-p", prompt, "--output-format", "streaming-json",
            "--cwd", str(workspace),
            # Project-scoped MCP (`.grok/config.toml`) is gated on folder
            # trust. Without --trust, Grok leaves switchbay's MCP server
            # unloaded ("folder untrusted") and the model sees zero
            # Switch Bay tools — then falls back to Edit/Write, which we
            # deny. Workspaces are already path-checked by
            # `_verify_workspace` (absolute, under home).
            "--trust",
            # Let grok run switchbay's (non-destructive) MCP tools
            # without an interactive approval it can't answer in -p mode.
            # Grok rule form is MCPTool(server__tool) — NOT Claude's
            # mcp__server__tool (those never match; tools then appear
            # "unavailable" and the model falls back to Edit/Write which
            # we deliberately deny).
            "--allow", "MCPTool(switchbay__*)",
            ]

    effort = base.coerce_effort(req.reasoning_effort, reasoning_options(req.model))
    if effort:
        argv.extend(["--reasoning-effort", effort])

    # Scoped shell/edit/write via hook-mediated approval (2026-07-24 —
    # see module docstring).
    #
    # Grok's authorization order (docs 22-permissions-and-safety.md):
    # the PreToolUse hook fires FIRST and can only DENY — "a hook that
    # allows a call does not skip the checks below." In headless `-p`
    # mode any call without a matching allow rule is CANCELLED at the
    # prompt step. So a `--allow` list alone can't let the user approve
    # a novel call from the rail, and a hook `allow` alone can't either
    # — the call still falls through to the `-p` auto-cancel.
    #
    # `bypassPermissions` is the one mode where a hook is authoritative:
    # it short-circuits AFTER hooks + deny rules, so the hook's deny
    # still blocks and everything the hook doesn't deny is approved.
    # That makes our fail-closed hook the single gate — identical in
    # spirit to how claude-code's PreToolUse hook governs its spawn.
    # is_pre_approved() (incl. ce_toolscope) approves CE/CM calls with
    # no card; everything else shows a rail card the user can approve.
    #
    # We only enter this mode when the hook is actually installed: with
    # bypassPermissions and NO hook, grok would auto-approve everything
    # (minus hard denies). If the hook can't be written we fall back to
    # the old propose-only surface instead — safe, if less capable.
    hooked = _ensure_hooks_ok(workspace, _daemon_port())
    if hooked:
        argv.extend(["--permission-mode", "bypassPermissions"])
        # Belt-and-suspenders: bypassPermissions makes the hook the gate,
        # so these `--allow` rules are normally inert (the hook fires and
        # approves/cards first). They matter only if an admin disables
        # bypass mode via requirements.toml — then grok falls back to
        # `-p` deny-by-default, and without an explicit allow the CE
        # scripts would cancel and re-break curation. Scoped exactly to
        # the CE / curiosity-merge call shapes.
        for rule in ce_toolscope.all_rules(workspace):
            argv.extend(["--allow", rule])
    else:
        log.warning(
            "grok permission hook unavailable — falling back to "
            "propose-only tools for %s", workspace)
        # Two layers, two naming schemes:
        #  · --disallowed-tools uses *internal* tool IDs and removes
        #    the tools entirely (docs: run_terminal_cmd, not Bash).
        #  · --deny uses Claude-compat permission prefixes. Unknown
        #    prefixes (Shell, NotebookEdit, …) abort the spawn — see
        #    DENY_PREFIXES / deny_argv().
        argv.extend([
            "--disallowed-tools", "run_terminal_cmd,search_replace",
            *deny_argv(("Bash(*)", "Edit(*)", "Write(*)")),
        ])

    # Hard denies stay unconditional. `permissions.hard_deny_reason`
    # refuses these server-side too, but blocking at the CLI layer
    # means grok never attempts the call that trips a macOS TCC
    # dialog ("… would like to access data from other apps").
    argv.extend(deny_argv())
    if req.system:
        # `--rules` APPENDS to grok's own system prompt (its
        # --append-system-prompt equivalent); layers switchbay's rules
        # on top without replacing the CLI's tool-use know-how.
        argv.extend(["--rules", req.system])
    if req.model:
        argv.extend(["--model", req.model])
    if req.session_id:
        argv.extend(["--resume", req.session_id])

    # Strip vendor API keys so the CLI uses the subscription auth path,
    # never a fall-through to the xAI API; drop venv leftovers too.
    env = {k: v for k, v in os.environ.items()
           if k not in {"XAI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
                        "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "PYTHONPATH"}}
    from .. import cebridge
    env = cebridge.inject_skill_env(env)

    log.info("spawning grok in cwd=%s", workspace)
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=str(workspace), env=env, limit=16 * 1024 * 1024)
    except FileNotFoundError as e:
        raise base.ProviderError(f"failed to spawn grok: {e}",
                                 code="missing-key", cause=e) from e

    stop_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    session_id: str | None = req.session_id
    if proc.stdout is None:
        raise base.ProviderError("grok subprocess produced no stdout", code="server")

    try:
        async for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            etype = evt.get("type")
            if etype == "text":
                d = evt.get("data")
                if isinstance(d, str) and d:
                    yield base.TextChunk(text=d)
            elif etype == "thought":
                d = evt.get("data")
                if isinstance(d, str) and d:
                    yield base.ReasoningChunk(text=d)
            elif etype in ("tool_use", "tool_call"):
                parsed = parse_tool_call(evt)
                if parsed is None:
                    continue
                yield base.ToolUseChunk(
                    id=parsed[0], name=parsed[1], input=parsed[2])
            elif etype == "end":
                stop_reason = evt.get("stopReason") or stop_reason
                sid = evt.get("sessionId")
                if isinstance(sid, str) and sid:
                    session_id = sid
                usage = evt.get("usage") or {}
                input_tokens = usage.get("input_tokens", input_tokens)
                output_tokens = usage.get("output_tokens", output_tokens)
            elif etype == "error":
                raise base.ProviderError(
                    f"Grok Build error: "
                    f"{evt.get('message') or evt.get('data') or 'unknown'}",
                    code="server")
    finally:
        try:
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except (asyncio.TimeoutError, ProcessLookupError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    if proc.returncode and proc.returncode != 0:
        err = (await proc.stderr.read() if proc.stderr else b"").decode(errors="replace")
        raise base.ProviderError(
            f"grok exited {proc.returncode}: {err.strip()[:300] or 'no stderr'}",
            code="server")

    yield base.DoneChunk(
        input_tokens=input_tokens, output_tokens=output_tokens,
        stop_reason=stop_reason, session_id=session_id)


async def validate_key(*, workspace: str | None = None) -> bool:
    if not has_key():
        raise base.ProviderError("`grok` binary not found on PATH", code="missing-key")
    req = base.ChatRequest(
        messages=[{"role": "user", "content": "respond with the word: ping"}],
        max_tokens=8, workspace=workspace)
    async for _ in chat_stream(req):
        pass
    return True
