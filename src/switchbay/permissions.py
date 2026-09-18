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
import contextlib
import contextvars
import fnmatch
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from . import atomicio, ce_toolscope

log = logging.getLogger("switchbay.permissions")


ALLOW_FILE = "permission-allow.json"

# Native CLI web tools and Switch Bay research tools — never on the
# builtin allow floor, never session-cached, never remembered. They
# hit a once/deny card only when the workspace web policy is on.
# Grok's internal names are web_search / web_fetch; Claude uses
# WebSearch / WebFetch. Codex has no PreToolUse: native search is
# always disabled (the `_codex:web-search` sentinel is ignored).
WEB_SEARCH_TOOLS = frozenset({
    "WebSearch", "WebFetch", "web_search", "web_fetch",
})
RESEARCH_EGRESS_TOOLS = frozenset({
    "research_search", "research_fetch",
})
CODEX_WEB_SEARCH_SENTINEL = "_codex:web-search"


def is_web_search_tool(tool: str) -> bool:
    return str(tool or "") in WEB_SEARCH_TOOLS


def _tool_basename(tool: str) -> str:
    t = str(tool or "")
    if t.startswith("mcp__"):
        parts = t.split("__")
        if len(parts) >= 3:
            return parts[-1]
    if t.startswith("switchbay__"):
        return t.split("__", 1)[-1]
    return t


def is_protected_egress(tool: str) -> bool:
    """True for native web search/fetch, research_*, and MCP aliases."""
    t = str(tool or "")
    if t in WEB_SEARCH_TOOLS or t in RESEARCH_EGRESS_TOOLS:
        return True
    if t == CODEX_WEB_SEARCH_SENTINEL:
        return True
    base = _tool_basename(t)
    if base in WEB_SEARCH_TOOLS or base in RESEARCH_EGRESS_TOOLS:
        return True
    low = base.lower().replace("-", "_")
    if low in {"websearch", "webfetch", "web_search", "web_fetch"}:
        return True
    return False


def is_protected_pattern(pattern: str) -> bool:
    p = str(pattern or "").strip()
    if not p:
        return False
    if p == CODEX_WEB_SEARCH_SENTINEL:
        return True
    tool = p.split("(", 1)[0]
    return is_protected_egress(tool)


_HTTP_URL_RE = re.compile(r"https?://", re.IGNORECASE)
_CE_URL_TOOLS = frozenset({"ce_run", "ce_ingest"})
_FETCH_SCRIPT_HINT = re.compile(
    r"(fetch|download|http|url)", re.IGNORECASE,
)
_CE_NETWORK_SCRIPTS = frozenset({
    "identifier_resolve.py",
})
_CE_RESOLVE_LOCAL_MODES = frozenset({"status", "review"})

# Unforgeable in-process consent. Never constructed from payload/env.
_CONSENT_MARK = object()
_invocation_consent: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "switchbay_web_invocation_consent", default=False,
)


class TrustedConsent:
    """Invocation-local consent that JSON/env cannot represent."""

    __slots__ = ("_mark",)

    def __init__(self, mark: object) -> None:
        self._mark = mark


def trusted_consent() -> TrustedConsent:
    return TrustedConsent(_CONSENT_MARK)


def is_trusted_consent(obj: Any) -> bool:
    return isinstance(obj, TrustedConsent) and obj._mark is _CONSENT_MARK


def invocation_approved() -> bool:
    return bool(_invocation_consent.get())


@contextlib.contextmanager
def approved_invocation():
    token = _invocation_consent.set(True)
    try:
        yield
    finally:
        _invocation_consent.reset(token)


def _payload_has_http_url(payload: dict[str, Any] | None) -> bool:
    data = payload or {}
    for key in ("url", "href", "path", "directory", "uri"):
        val = str(data.get(key) or "").strip()
        if val.lower().startswith(("http://", "https://")):
            return True
    args = data.get("args")
    if isinstance(args, str):
        blob = args
    elif isinstance(args, list):
        blob = " ".join(str(a) for a in args)
    else:
        blob = ""
    script = str(data.get("script") or "")
    return bool(_HTTP_URL_RE.search(blob) or _HTTP_URL_RE.search(script))


def needs_web_consent(tool: str, tool_input: dict[str, Any] | None = None) -> bool:
    """True when this call may hit the network and needs a once/deny card."""
    if is_protected_egress(tool):
        return True
    base = _tool_basename(tool)
    if base in _CE_URL_TOOLS or str(tool or "") in _CE_URL_TOOLS:
        payload = tool_input or {}
        script = Path(str(payload.get("script") or "")).name
        if script and not script.endswith(".py"):
            script = f"{script}.py"
        args = payload.get("args")
        if isinstance(args, str):
            arg_list = args.split()
        elif isinstance(args, list):
            arg_list = [str(a) for a in args]
        else:
            arg_list = []
        if script == "identifier_resolve.py":
            # Network only on `run --yes`. status/review are local.
            tokens = {a.strip() for a in arg_list}
            if tokens & _CE_RESOLVE_LOCAL_MODES and "run" not in tokens:
                return False
            return "run" in tokens and ("--yes" in tokens or "-y" in tokens)
        if script in _CE_NETWORK_SCRIPTS or _FETCH_SCRIPT_HINT.search(script):
            return True
        return _payload_has_http_url(payload)
    return False


def strip_forged_approval(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Drop model-supplied approval flags. Never treat them as consent."""
    data = dict(payload or {})
    for key in ("_approved", "approved", "_consent", "consent", "_web_approved"):
        data.pop(key, None)
    return data


def request_protected_sync(
    workspace: Path,
    tool: str,
    tool_input: dict[str, Any] | None = None,
    *,
    timeout: float | None = None,
) -> str:
    """Long-poll the daemon permission card. Fail closed. Never skip."""
    import urllib.error
    import urllib.request

    port = os.environ.get("CSWY_DAEMON_PORT") or "8765"
    wait = float(timeout if timeout is not None else min(REQUEST_TIMEOUT_S, 120.0))
    body = json.dumps({
        "provider": "registry",
        "tool": tool,
        "input": tool_input or {},
        "cwd": str(workspace),
        "origin_thread": os.environ.get("CSWY_THREAD_ID") or "",
    }).encode()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/permission/request",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=wait) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError, ValueError):
        return "deny"
    if not isinstance(payload, dict):
        return "deny"
    decision = str(payload.get("decision") or "deny")
    if decision == "skip":
        return "deny"
    return "approve" if decision == "approve" else "deny"


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
    "I want this pattern allowed forever". Returns the new list.

    Protected egress patterns are ignored — web search/fetch must
    never become a remembered blanket grant.
    """
    cur = _load_allow(workspace)
    if is_protected_pattern(pattern):
        return cur
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
    if tool == "Orchestration":
        action = str(tool_input.get("action") or "").strip() or "unknown"
        return f"Orchestration({action})"
    if is_web_search_tool(tool):
        if tool in {"WebFetch", "web_fetch"}:
            url = str(tool_input.get("url") or tool_input.get("href") or "")[:120]
            return f"{tool}({url})" if url else f"{tool}(*)"
        q = str(tool_input.get("query") or tool_input.get("q") or "")[:80]
        return f"{tool}({q})" if q else f"{tool}(*)"
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
    # Protected web egress never pre-approves — not via the builtin
    # MCP wildcard, not via a remembered pattern, not via session.
    if is_protected_egress(tool or "") or is_protected_pattern(pattern):
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
        if is_protected_pattern(allow):
            continue
        if fnmatch.fnmatch(pattern, allow) or fnmatch.fnmatch(allow, pattern):
            if is_protected_egress(tool or "") or is_protected_pattern(pattern):
                return False
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
    protected = (
        is_protected_egress(rec.tool)
        or is_protected_pattern(rec.pattern)
        or needs_web_consent(rec.tool, rec.tool_input)
    )
    if protected and decision == "skip":
        rec.decision = "deny"
        decision = "deny"
    if protected:
        # Forged remember / pattern / session overrides are ignored.
        rec.remember = False
        remember = False
        session = False
        pattern = None
    else:
        rec.remember = remember
    if decision == "approve" and (remember or session) and not protected:
        pat = (pattern or "").strip() or rec.pattern
        if is_protected_pattern(pat):
            rec.event.set()
            return rec
        if session:
            _SESSION_ALLOW.setdefault(str(rec.workspace), set()).add(pat)
        else:
            cur = _load_allow(Path(rec.workspace))
            if pat not in cur:
                cur.append(pat)
            _save_allow(Path(rec.workspace), cur)
    rec.event.set()
    return rec


async def mediate_protected_call(
    *,
    workspace: Path,
    tool: str,
    tool_input: dict[str, Any],
    provider: str = "switchbay",
    run_id: str | None = None,
    thread_id: str | None = None,
    broadcast: Any = None,
) -> tuple[str, str]:
    """Gate a protected web call. Returns (approve|deny, reason).

    Policy off / admin deny / timeout fail closed. Policy on shows a
    once/deny card (never remembered).
    """
    from . import protocol
    blocked = web_egress_block_reason(workspace, tool, tool_input)
    if blocked:
        return "deny", blocked
    rec = register(
        workspace=workspace, provider=provider, tool=tool,
        tool_input=tool_input, run_id=run_id, thread_id=thread_id,
    )
    if broadcast is not None:
        await broadcast(protocol.permission_request(
            req_id=rec.req_id, provider=provider, tool=tool,
            tool_input=tool_input, pattern=rec.pattern, run_id=run_id,
            thread_id=thread_id, protected=True,
        ))
    decision = await await_decision(rec)
    if broadcast is not None:
        await broadcast(protocol.permission_resolved(rec.req_id, decision))
    if decision != "approve":
        return "deny", "web egress denied"
    # Toggle-off while the card was pending must still fail closed.
    blocked = web_egress_block_reason(workspace, tool, tool_input)
    if blocked:
        return "deny", blocked
    return "approve", ""


def web_egress_block_reason(
    workspace: Path,
    tool: str,
    tool_input: dict[str, Any] | None = None,
) -> str | None:
    """Deny reason when web egress must fail closed without a card.

    None means the call may proceed to a once/deny card (policy on).
    """
    from . import web_policy
    if not needs_web_consent(tool, tool_input):
        return None
    if not web_policy.admin_allows():
        return "web egress is disabled by admin policy"
    if not web_policy.is_enabled(workspace):
        return "web egress is off for this workspace"
    payload = tool_input or {}
    url = str(payload.get("url") or payload.get("href") or "").strip()
    if url:
        from . import admin_policy
        if not admin_policy.egress_allowed(url):
            return f"web egress blocked by admin allowlist: {url}"
    return None


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
