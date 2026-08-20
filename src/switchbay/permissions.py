"""Permission gate for rail-spawned agent subprocesses.

Claude Code and Codex both run under tight built-in allowlists (the
former via `--settings permissions.allow`, the latter via
`--sandbox workspace-write`). Anything outside those defaults
auto-denies — which protects the user but also means routine ops
like `pip install`, `npm test`, or writing outside the cwd can't
happen at all from the rail.

This module bridges the gap with an inline rail dialog:

  · agent's PreToolUse hook (claude-code) or sandbox-denial path
    (codex) calls `request(...)` to register a pending permission.
  · `request(...)` awaits an asyncio.Event and returns the verdict
    once the user clicks Approve / Deny in the rail.
  · `decide(...)` from the frontend resolves that Event.
  · "Approve + remember" persists the pattern under
    `<workspace>/.workbench/state/permission-allow.json`, so future
    matching calls short-circuit without re-prompting.

The store is in-memory for the live request set, on-disk for the
remembered patterns. Restarting the daemon drops in-flight prompts
(safe — the hook subprocess times out and the agent retries) but
preserves remembered approvals.
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from . import atomicio, ce_toolscope

log = logging.getLogger("switchbay.permissions")


ALLOW_FILE = "permission-allow.json"
# Generous: a single-user local app shouldn't auto-deny while the user
# reads the request or works through a backlog of prompts from several
# concurrent agents. 30 min; the frontend is told when it lapses so the
# card never lingers as a dead "pending" row.
REQUEST_TIMEOUT_S = 1800.0


@dataclass
class PendingRequest:
    """One in-flight permission request. The `event` is set when the
    user clicks Approve / Deny in the rail; `decision` then carries
    'approve' | 'deny' (and `remember` if the pattern should persist)."""
    req_id: str
    workspace: str
    provider: str
    tool: str
    tool_input: dict[str, Any]
    run_id: str | None
    pattern: str
    created_at: float
    thread_id: str | None = None
    """Rail thread that owns the requesting CLI session, when the
    daemon spawned it for one. None = external session (bench,
    scripts, background agents) — the card renders out-of-thread."""
    origin: str | None = None
    """Human label for where an external request came from (its cwd,
    home-compacted). None for thread-owned requests."""
    origin_path: str | None = None
    """Absolute cwd of an external session, when known — lets the UI
    open a shell there to watch it. None for thread-owned requests or
    old hooks that don't forward cwd."""
    event: asyncio.Event = field(default_factory=asyncio.Event)
    decision: str | None = None
    remember: bool = False


# Single shared registry — request ids are universally unique, no need
# to scope by app instance.
_PENDING: dict[str, PendingRequest] = {}

# Session-scoped allows (in-memory, per workspace): cleared on daemon
# restart. "Allow all Read this session" lands here rather than the
# persisted allow-list, so it doesn't outlive the run.
_SESSION_ALLOW: dict[str, set[str]] = {}


# ── On-disk remembered allow list ─────────────────────────────────


def _allow_path(workspace: Path) -> Path:
    return workspace / ".workbench" / "state" / ALLOW_FILE


def _load_allow(workspace: Path) -> list[str]:
    p = _allow_path(workspace)
    if not p.is_file():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    return [str(x) for x in raw if isinstance(x, str)]


def _save_allow(workspace: Path, patterns: list[str]) -> None:
    p = _allow_path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    # De-dup while preserving order so the user-facing list stays
    # stable across approvals.
    seen: set[str] = set()
    out: list[str] = []
    for pat in patterns:
        if pat in seen:
            continue
        seen.add(pat)
        out.append(pat)
    atomicio.write_json_atomic(p, out)


def list_allowed(workspace: Path) -> list[str]:
    return _load_allow(workspace)


def revoke(workspace: Path, pattern: str) -> None:
    """Drop one remembered pattern. Settings panel calls this when the
    user wants to take an approval back."""
    cur = _load_allow(workspace)
    _save_allow(workspace, [p for p in cur if p != pattern])


def add_pattern(workspace: Path, pattern: str) -> list[str]:
    """Append a pattern to the workspace's allow list without going
    through the request/decide dance. Used by Settings UI controls
    (e.g. the Codex elevated-sandbox toggle) that directly express
    "I want this pattern allowed forever". Returns the new list."""
    cur = _load_allow(workspace)
    if pattern not in cur:
        cur.append(pattern)
    _save_allow(workspace, cur)
    return cur


# ── Pattern matching ──────────────────────────────────────────────


def pattern_for(tool: str, tool_input: dict[str, Any]) -> str:
    """Canonical wildcard pattern derived from a tool call. Matches
    claude-code's allowlist syntax for familiarity:

        Bash(npm test*)       — bash command prefix
        Bash(<exact>)         — bash command exact
        Read(<abs-path>)      — file-scope tools
        Edit(<abs-path>)
        Write(<abs-path>)

    Anything else: `<Tool>(<input-excerpt>)`.
    """
    if tool == "Bash":
        cmd = str(tool_input.get("command") or "").strip()
        # Prefix-match the binary + first arg so `npm test --watch`
        # is covered by the same approval that grants `npm test`.
        head = " ".join(cmd.split()[:2])
        return f"Bash({head}*)" if head else f"Bash({cmd[:40]})"
    if tool in ("Read", "Edit", "Write", "NotebookEdit"):
        path = str(tool_input.get("file_path") or tool_input.get("path") or "")
        return f"{tool}({path})" if path else f"{tool}(*)"
    # Generic shape — include a short input excerpt so the user can
    # tell two calls apart.
    blob = json.dumps(tool_input, sort_keys=True)[:80]
    return f"{tool}({blob})"


def _builtin_allow(workspace: Path) -> list[str]:
    """Patterns approved WITHOUT asking, ever — the zero-friction
    floor (added 2026-07-05 after a wiki question cost five approval
    cards). Only provably-safe read paths belong here:

      · mcp__switchbay__* — our own tool registry: curated,
        read-mostly, workspace-scoped by construction (this is what
        makes the wiki tools promptless).
      · Skill / TodoWrite / BashOutput — the CLI's bookkeeping + doc
        loads; reading a SKILL.md is not an action.
      · Grep / Glob — read-only search primitives.
      · Read under THIS workspace — reading workspace files IS the
        grounding path; an approval card for it is pure friction.

    Bash deliberately stays out of this list: shell commands keep the
    card (and the agent is steered to the wiki tools instead). The one
    exception is handled separately in `ce_scope_allows` — CE's and
    curiosity-merge's own scripts, matched on the FULL command rather
    than the two-token pattern this list is compared against."""
    ws = str(workspace.resolve()).rstrip("/")
    out = [
        "mcp__switchbay__*",
        # Grok strips the `mcp__` prefix and names MCP calls
        # `switchbay__<tool>` (the server slug is unambiguous — it's
        # our own registry), so match that form too or grok's
        # propose_*/wiki tools would card on every call.
        "switchbay__*",
        "Skill(*)",
        "TodoWrite(*)",
        "BashOutput(*)",
        "Grep(*)",
        "Glob(*)",
        # claude-code's internal deferred-tool schema lookup — pure
        # metadata read; carding it (seen live: the wiki-tools
        # ToolSearch select) is friction with zero safety value.
        "ToolSearch(*)",
        f"Read({ws}/*)",
    ]
    # Global skill installs (Read only). Cat/head of SKILL.md must not
    # trip the home-scan hard-deny — the rail is allowed to see these.
    try:
        from . import skillkit
        for root in skillkit.skill_read_roots():
            out.append(f"Read({root}/*)")
    except Exception:  # noqa: BLE001
        pass
    return out


def ce_scope_allows(
    workspace: Path, tool: str, tool_input: dict[str, Any],
) -> bool:
    """True iff this call is one of the curiosity-engine /
    curiosity-merge shapes that curation genuinely needs.

    This exists because `pattern_for` keeps only the first two tokens
    of a Bash command, so `Bash(uv run*)` cannot distinguish CE's
    `uv run python3 <skill>/scripts/sweep.py` from `uv run` anything
    else. Pre-approving at pattern granularity would be a blanket
    grant; matching the whole command here keeps the scope exact.

    Without this the curator has no executable path at all: every CE
    script call cards, and a non-interactive (`-p`) CLI turns the
    whole curation into a list of proposals. That was the 2026-07-24
    bug.
    """
    if tool == "Bash":
        return ce_toolscope.allows_command(
            workspace, str(tool_input.get("command") or ""),
        )
    if tool in ("Edit", "Write", "NotebookEdit"):
        path = str(tool_input.get("file_path") or tool_input.get("path") or "")
        return ce_toolscope.allows_write(workspace, path)
    return False


def is_pre_approved(
    workspace: Path,
    pattern: str,
    *,
    tool: str | None = None,
    tool_input: dict[str, Any] | None = None,
) -> bool:
    """True iff the pattern matches a built-in safe default, one of
    the workspace's remembered approvals (persisted), or a
    session-scoped allow. Uses fnmatch so `Bash(npm test*)` matches
    `Bash(npm test)` and `Bash(npm test --watch)`, and a tool-level
    `Read(*)` matches every `Read(...)`.

    Hard-denied filesystem scans never pre-approve — even if a past
    "Approve + remember" saved `Bash(find*)`."""
    if tool and tool_input is not None and hard_deny_reason(tool, tool_input):
        return False
    # CE/CM scope is checked on the full call, before the coarse
    # pattern comparison below (which cannot express it).
    if tool and tool_input is not None and ce_scope_allows(
        workspace, tool, tool_input,
    ):
        return True
    if tool and tool_input is not None and _skill_read_allows(tool, tool_input):
        return True
    allows = _builtin_allow(workspace)
    allows.extend(_load_allow(workspace))
    allows.extend(_SESSION_ALLOW.get(str(workspace), ()))
    for allow in allows:
        if fnmatch.fnmatch(pattern, allow) or fnmatch.fnmatch(allow, pattern):
            return True
    return False


# ── Hard deny: home / filesystem-wide scans ────────────────────────
# Agents (esp. Grok/Claude) repeatedly shell out `find /Users/…` or
# `find ~` looking for tools; on modern macOS that trips a TCC dialog
# ("python would like to access data from other apps"). Prompt text
# already forbids this — we also block it server-side so it cannot
# be approved away or pre-allowed via Bash(find:*).

_SCAN_BIN = re.compile(
    r"(?:^|[\s;&|(`])(?:sudo\s+)?(?:/usr/bin/|/bin/)?"
    r"(?:find|fd|bfs|mdfind|locate)\b",
    re.IGNORECASE,
)
# Roots that leave the workspace and hit privacy-protected areas.
_SCAN_ROOT = re.compile(
    r"(?:^|[\s=])(?:"
    r"/(?:Users|home|Volumes|private|System)(?:/|[\s\"';|&;]|$)"
    r"|~(?:/|[\s\"';|&;]|$)"
    r"|\$\{?HOME\}?(?:/|[\s\"';|&;]|$)"
    r"|/(?:[\s\"';|&;]|$)"   # bare `find /`
    r")",
    re.IGNORECASE,
)
# `ls/tree/du ~` and friends — same privacy hit without using find.
_LIST_HOME = re.compile(
    r"(?:^|[\s;&|(`])(?:sudo\s+)?(?:/bin/|/usr/bin/)?"
    r"(?:ls|tree|du|chmod|chown|rm|cp|mv|cat|head|tail|rg|grep)\b"
    r"[^\n]*?(?:^|[\s\"'])(?:~|/Users(?:/|$)|/home(?:/|$)|\$\{?HOME\}?)",
    re.IGNORECASE | re.MULTILINE,
)

_HARD_DENY_MSG = (
    "Blocked: home- or filesystem-wide scans are not allowed "
    "(they trigger macOS privacy prompts and leave the workspace). "
    "Stay under the workspace cwd and use Grep/Glob, wiki tools, or "
    "`find . …` for local search."
)


# Spotlight / locate are whole-machine indexes — always out of scope.
_ALWAYS_DENY_BIN = re.compile(
    r"(?:^|[\s;&|(`])(?:sudo\s+)?(?:/usr/bin/|/bin/)?"
    r"(?:mdfind|locate)\b",
    re.IGNORECASE,
)


_SKILL_READ_BIN = re.compile(
    r"^(?:cat|head|tail|less|more|ls|wc|file|stat)\b",
    re.IGNORECASE,
)


def _skill_read_allows(tool: str, tool_input: dict[str, Any]) -> bool:
    """True if this is a read of a global skill install (SKILL.md /
    scripts). Write/edit of those trees still cards."""
    from . import skillkit
    if tool in ("Read", "Grep", "Glob"):
        path = str(
            tool_input.get("file_path")
            or tool_input.get("path")
            or tool_input.get("pattern")
            or "",
        )
        # Glob pattern like `/Users/…/.agents/skills/**`
        path = path.replace("**", "").rstrip("/*")
        return skillkit.path_is_skill_read(path)
    if tool in ("Bash", "Shell", "bash", "command_execution"):
        return _bash_is_skill_read(str(tool_input.get("command") or tool_input.get("cmd") or ""))
    return False


def _bash_is_skill_read(cmd: str) -> bool:
    """`cat ~/.agents/skills/foo/SKILL.md` and friends — not `ls ~`."""
    from . import skillkit
    t = (cmd or "").strip()
    if not t or not _SKILL_READ_BIN.match(t):
        return False
    if any(ch in t for ch in (";", "|", "&", "`", "$(", ">", "<", "\n")):
        return False
    tokens = t.split()[1:]
    paths = [
        tok.strip("'\"") for tok in tokens
        if tok.startswith(("~", "/", "$HOME", "${HOME}"))
        or "/skills/" in tok.replace("\\", "/")
    ]
    if not paths:
        return False
    return all(skillkit.path_is_skill_read(p) for p in paths)


def hard_deny_reason(tool: str, tool_input: dict[str, Any]) -> str | None:
    """Return a human reason if this tool call is always denied.

    Covers Bash/Shell (and any tool input with a shell `command`/`cmd`
    field) that walks `/Users`, `~`, `$HOME`, `/`, `/Volumes`, etc.
    Returns None when the call may proceed to the normal allow/card
    path. Workspace-local scans stay allowed (`find . …`, `ls wiki`).

    `tool` is accepted for call-site symmetry with the permission hook
    but the decision is based on the shell command string.
    """
    _ = tool
    cmd = str(
        tool_input.get("command")
        or tool_input.get("cmd")
        or "",
    ).strip()
    if not cmd:
        return None

    # mdfind / locate always hit the whole machine (TCC + out of scope)
    if _ALWAYS_DENY_BIN.search(cmd):
        return _HARD_DENY_MSG
    # find / fd / bfs aimed outside the workspace
    if _SCAN_BIN.search(cmd) and _SCAN_ROOT.search(cmd):
        return _HARD_DENY_MSG
    # `find /` bare (root of the volume)
    if re.search(r"\bfind\s+/\s*$", cmd) or re.search(r"\bfind\s+/\s+", cmd):
        return _HARD_DENY_MSG
    # ls/tree/du of home — except a read confined to a skill install.
    if _LIST_HOME.search(cmd) and not _bash_is_skill_read(cmd):
        return _HARD_DENY_MSG
    return None


# ── Request / decide cycle ────────────────────────────────────────


def _expire_stale_pending() -> None:
    """Drop permission cards older than REQUEST_TIMEOUT_S so a wedged
    hook cannot accumulate tool_input blobs forever."""
    now = time.time()
    stale = [
        rid for rid, rec in _PENDING.items()
        if now - rec.created_at > REQUEST_TIMEOUT_S
    ]
    for rid in stale:
        rec = _PENDING.pop(rid, None)
        if rec is not None:
            rec.decision = "deny"
            rec.event.set()


def register(
    *, workspace: Path, provider: str, tool: str,
    tool_input: dict[str, Any], run_id: str | None,
    thread_id: str | None = None, origin: str | None = None,
    origin_path: str | None = None,
) -> PendingRequest:
    """Create a new pending request. Caller is responsible for awaiting
    the returned `req.event` and reading `req.decision`."""
    _expire_stale_pending()
    req_id = uuid.uuid4().hex[:12]
    rec = PendingRequest(
        req_id=req_id,
        workspace=str(workspace),
        provider=provider,
        tool=tool,
        tool_input=tool_input,
        run_id=run_id,
        pattern=pattern_for(tool, tool_input),
        created_at=time.time(),
        thread_id=thread_id,
        origin=origin,
        origin_path=origin_path,
    )
    _PENDING[req_id] = rec
    return rec


def get_pending(req_id: str) -> PendingRequest | None:
    return _PENDING.get(req_id)


def list_pending() -> list[PendingRequest]:
    """Snapshot of all pending requests across workspaces — used by
    fresh WS connections to backfill any dialogs the user hasn't
    answered yet."""
    _expire_stale_pending()
    return list(_PENDING.values())


def resolve(
    req_id: str, *, decision: str, remember: bool,
    pattern: str | None = None, session: bool = False,
) -> PendingRequest | None:
    """Set the verdict and signal the waiting hook subprocess. Drops
    the entry from the registry once signalled — the hook reads its
    decision from the returned record before pop completes.

    `pattern` overrides the stored pattern (e.g. a tool-level `Read(*)`
    instead of the call's specific `Read(/path)`). `session` stores it
    in the in-memory session allow (cleared on restart) rather than the
    persisted allow-list."""
    rec = _PENDING.pop(req_id, None)
    if rec is None:
        return None
    rec.decision = decision
    rec.remember = remember
    if decision == "approve" and (remember or session):
        pat = (pattern or "").strip() or rec.pattern
        if session:
            _SESSION_ALLOW.setdefault(str(rec.workspace), set()).add(pat)
        else:
            cur = _load_allow(Path(rec.workspace))
            if pat not in cur:
                cur.append(pat)
            _save_allow(Path(rec.workspace), cur)
    rec.event.set()
    return rec


async def await_decision(rec: PendingRequest) -> str:
    """Wait for `decision` to land or timeout. On timeout we deny by
    default — safer than approving a request the user never saw."""
    try:
        await asyncio.wait_for(rec.event.wait(), timeout=REQUEST_TIMEOUT_S)
    except asyncio.TimeoutError:
        _PENDING.pop(rec.req_id, None)
        log.warning("permission request %s timed out (default deny)", rec.req_id)
        return "deny"
    return rec.decision or "deny"
