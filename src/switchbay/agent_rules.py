"""User-defined rail shortcuts: "when I say X, do Y".

A rule is `{trigger, action}` — the user types `trigger`, the daemon
runs `action` instead of dispatching to chat. Rules persist across
sessions (workspace scope today; per-user scope is a future
extension). Stored at `<workspace>/.workbench/state/agent_rules.json`.

Two ways to create a rule:
  · Natural language: "when I say show me Mistral, /view Mistral".
    The daemon's user_input handler detects the shape via regex and
    registers it before chat dispatch sees it.
  · Tool call: `register_rule(trigger=…, action=…)`. Tool-capable
    agents (anthropic, …) can do this themselves when the user says
    something like "remember that". Once the MCP bridge lands,
    claude-code gets the same affordance.

Action grammar (today): a literal slash command, e.g. "/view Mistral".
Trigger matching today: exact-text, case-insensitive. Pattern triggers
("show me {X}") are a future improvement; the schema reserves a
`pattern` field for them.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any

log = logging.getLogger("switchbay.agent_rules")


def _path(workspace: Path) -> Path:
    return workspace / ".workbench" / "state" / "agent_rules.json"


def load(workspace: Path) -> list[dict[str, Any]]:
    p = _path(workspace)
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rules = data.get("rules") if isinstance(data, dict) else None
    return rules if isinstance(rules, list) else []


def save(workspace: Path, rules: list[dict[str, Any]]) -> None:
    p = _path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"rules": rules}, indent=2) + "\n",
        encoding="utf-8",
    )


def add(workspace: Path, trigger: str, action: str) -> dict[str, Any]:
    """Append a rule. Returns the stored record (with assigned id)."""
    trigger = (trigger or "").strip()
    action = (action or "").strip()
    if not trigger or not action:
        raise ValueError("trigger and action are required")
    rules = load(workspace)
    rule = {
        "id": uuid.uuid4().hex[:10],
        "created_at": time.time(),
        "trigger": trigger,
        "action": action,
        "scope": "workspace",
    }
    # De-dupe — replace any existing rule with the same trigger so
    # users can update a rule by re-saying the same "when I say…".
    rules = [r for r in rules if _norm(r.get("trigger", "")) != _norm(trigger)]
    rules.append(rule)
    save(workspace, rules)
    return rule


def remove(workspace: Path, rule_id: str) -> bool:
    rules = load(workspace)
    n = len(rules)
    rules = [r for r in rules if r.get("id") != rule_id]
    if len(rules) == n:
        return False
    save(workspace, rules)
    return True


def match(workspace: Path, text: str) -> dict[str, Any] | None:
    """Return the first rule whose trigger exactly matches `text`
    (case-insensitive, whitespace-trimmed). Today's matching is
    deliberately strict — pattern-based triggers come later."""
    norm = _norm(text)
    if not norm:
        return None
    for r in load(workspace):
        if _norm(r.get("trigger", "")) == norm:
            return r
    return None


def _norm(s: str) -> str:
    return (s or "").strip().lower()


# ── NL detection: "when I say X, do Y" / "from now on X means Y" ──


# Capture group 1 = trigger phrase, group 2 = action.
# Matches:
#   "when I say show me X, /view X"
#   "when i say 'show me X' you should /view X"
#   "from now on, 'show me X' means /view X"
#   "remember: when I say X, do /view X"
_NL_RULE_PATTERNS = [
    # Quoted trigger, any connector (most explicit form).
    re.compile(
        r"""^\s*(?:please\s+)?(?:remember\s*[:,]\s*)?
            when\s+(?:I|i)\s+say\s+
            ['"](?P<trigger>[^'"]+)['"]
            \s*[,;]?\s*
            (?:you\s+(?:should\s+)?)?\s*(?:please\s+)?
            (?:run|use|invoke|do|just\s+)?\s*
            (?P<action>.+?)\s*[.!]?\s*$
        """,
        re.IGNORECASE | re.VERBOSE,
    ),
    # Unquoted trigger followed by "you should".
    re.compile(
        r"""^\s*(?:please\s+)?(?:remember\s*[:,]\s*)?
            when\s+(?:I|i)\s+say\s+(?P<trigger>.+?)
            \s+you\s+should\s+(?P<action>.+?)\s*[.!]?\s*$
        """,
        re.IGNORECASE | re.VERBOSE,
    ),
    # Unquoted trigger followed by a comma + optional connector.
    re.compile(
        r"""^\s*(?:please\s+)?(?:remember\s*[:,]\s*)?
            when\s+(?:I|i)\s+say\s+(?P<trigger>.+?)
            \s*,\s*(?:you\s+(?:should\s+)?)?(?:please\s+)?
            (?:run|use|invoke|do|just\s+)?\s*
            (?P<action>.+?)\s*[.!]?\s*$
        """,
        re.IGNORECASE | re.VERBOSE,
    ),
    # "from now on, X means Y"
    re.compile(
        r"""^\s*from\s+now\s+on\s*[,]?\s*
            ['"]?(?P<trigger>.+?)['"]?
            \s+means\s+
            (?P<action>.+?)\s*[.!]?\s*$
        """,
        re.IGNORECASE | re.VERBOSE,
    ),
]


def detect_nl_rule(text: str) -> tuple[str, str] | None:
    """If `text` looks like a rule registration, return (trigger,
    action). Otherwise None."""
    for pat in _NL_RULE_PATTERNS:
        m = pat.match(text)
        if m:
            trig = (m.group("trigger") or "").strip().strip("'\"").strip()
            act = (m.group("action") or "").strip().strip("'\"").strip()
            if trig and act:
                return trig, act
    return None
