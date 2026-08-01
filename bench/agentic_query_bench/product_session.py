"""Persistent Claude Code stream-json session driver for the product pilot.

One long-lived ``claude`` process per trajectory. Examiner turns are written to
stdin as stream-json ``user`` messages; assistant/tool/result events are read
from stdout. State (skill content, conversation, tool results) persists
naturally across turns inside the one process (prereg ``session_protocol``).

The pure event logic (``parse_turn``, framing, served-model drift) is separated
from subprocess I/O so it is unit-testable without launching ``claude`` (no
model quota). ``ProductSession`` is the thin subprocess wrapper.

Env is scrubbed exactly as the daemon's provider does (ANTHROPIC_API_KEY etc.)
so the CLI commits to the subscription route and no parent uv/venv leaks in.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

# Mirror the daemon provider's scrub set (charter env-leak gotcha).
_SCRUB_ENV = {
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "VIRTUAL_ENV",
    "UV_PROJECT_ENVIRONMENT",
    "PYTHONPATH",
}


def user_line(text: str) -> str:
    """A stream-json user message line (newline-terminated)."""
    return json.dumps(
        {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}}
    ) + "\n"


@dataclass
class TurnResult:
    assistant_text: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)
    tool_uses: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    served_model: str | None = None
    session_id: str | None = None
    stop_reason: str | None = None
    is_error: bool = False
    input_tokens: int | None = None
    output_tokens: int | None = None
    num_turns: int | None = None
    cost_usd: float | None = None
    permission_denials: list[dict[str, Any]] = field(default_factory=list)


def _served_model(evt: dict[str, Any]) -> str | None:
    m = evt.get("model")
    if isinstance(m, str) and m:
        return m
    msg = evt.get("message") or {}
    m = msg.get("model")
    return m if isinstance(m, str) and m else None


def parse_turn(lines: Iterable[str]) -> TurnResult:
    """Consume stream-json lines up to and including the turn's ``result`` event."""
    tr = TurnResult()
    text_parts: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue
        tr.events.append(evt)
        etype = evt.get("type")
        sm = _served_model(evt)
        if sm:
            tr.served_model = sm
        sid = evt.get("session_id")
        if isinstance(sid, str) and sid:
            tr.session_id = sid

        if etype == "assistant":
            msg = evt.get("message") or {}
            for block in msg.get("content") or []:
                b = block or {}
                if b.get("type") == "text":
                    text_parts.append(b.get("text", "") or "")
                elif b.get("type") == "tool_use":
                    tr.tool_uses.append(
                        {"id": b.get("id", ""), "name": b.get("name", ""), "input": b.get("input") or {}}
                    )
            usage = msg.get("usage") or {}
            tr.input_tokens = usage.get("input_tokens", tr.input_tokens)
            tr.output_tokens = usage.get("output_tokens", tr.output_tokens)
        elif etype == "user":
            msg = evt.get("message") or {}
            for block in msg.get("content") or []:
                b = block or {}
                if b.get("type") == "tool_result":
                    tr.tool_results.append(
                        {"tool_use_id": b.get("tool_use_id", ""),
                         "is_error": bool(b.get("is_error")),
                         "content": b.get("content")}
                    )
        elif etype == "result":
            tr.stop_reason = evt.get("stop_reason") or tr.stop_reason
            tr.is_error = bool(evt.get("is_error")) or tr.is_error
            tr.num_turns = evt.get("num_turns", tr.num_turns)
            tr.cost_usd = evt.get("total_cost_usd", tr.cost_usd)
            usage = evt.get("usage") or {}
            tr.input_tokens = usage.get("input_tokens", tr.input_tokens)
            tr.output_tokens = usage.get("output_tokens", tr.output_tokens)
            break
    # A non-allowlisted tool that was denied surfaces as an error tool_result.
    tr.permission_denials = [
        r for r in tr.tool_results
        if r["is_error"] and _looks_like_denial(r.get("content"))
    ]
    tr.assistant_text = "".join(text_parts)
    return tr


def _looks_like_denial(content: Any) -> bool:
    text = json.dumps(content) if not isinstance(content, str) else content
    t = text.casefold()
    return any(k in t for k in ("permission", "not allowed", "denied", "requires approval"))


class ModelDriftError(RuntimeError):
    pass


class LimitError(RuntimeError):
    """The subscription limit was hit — Claude Code served the ``<synthetic>``
    placeholder model. Retriable once quota resets (distinct from real drift)."""


def _is_synthetic(served: str | None) -> bool:
    return bool(served) and "synthetic" in served.casefold()


def build_argv(
    *,
    model: str,
    settings_file: Path,
    add_dir: Path,
    mcp_config: Path | None = None,
    disallowed_tools: str | None = None,
    max_turns: int | None = None,
) -> list[str]:
    argv = [
        "claude", "-p",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--verbose",
        "--model", model,
        "--settings", str(settings_file),
        "--add-dir", str(add_dir),
    ]
    if mcp_config is not None:
        argv += ["--mcp-config", str(mcp_config)]
    if disallowed_tools:
        argv += ["--disallowed-tools", disallowed_tools]
    if max_turns is not None:
        argv += ["--max-turns", str(max_turns)]
    return argv


class ProductSession:
    """Thin wrapper over one persistent ``claude`` stream-json subprocess."""

    def __init__(
        self,
        snapshot: Path,
        *,
        model: str,
        settings_file: Path,
        mcp_config: Path | None = None,
        disallowed_tools: str | None = None,
        max_turns: int | None = 12,
        claude_bin: str = "claude",
    ):
        self.snapshot = Path(snapshot)
        self.model = model
        self.settings_file = Path(settings_file)
        self.mcp_config = Path(mcp_config) if mcp_config else None
        self.disallowed_tools = disallowed_tools
        self.max_turns = max_turns
        self.claude_bin = claude_bin
        self.proc: subprocess.Popen | None = None
        self.init_event: dict[str, Any] | None = None
        self.turns: list[TurnResult] = []

    def start(self) -> dict[str, Any]:
        argv = build_argv(
            model=self.model, settings_file=self.settings_file, add_dir=self.snapshot,
            mcp_config=self.mcp_config, disallowed_tools=self.disallowed_tools,
            max_turns=self.max_turns,
        )
        argv[0] = self.claude_bin
        env = {k: v for k, v in os.environ.items() if k not in _SCRUB_ENV}
        self.proc = subprocess.Popen(
            argv, cwd=str(self.snapshot), env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        # Do NOT block-read here: the CLI may only emit the system/init event
        # after the first stdin message arrives, so reading now could deadlock.
        # init_event is captured from the first turn's events instead.
        self.init_event = None
        return {}

    def send(self, text: str, *, expect_model: str | None = None) -> TurnResult:
        if not self.proc or self.proc.stdin is None or self.proc.stdout is None:
            raise RuntimeError("session not started")
        self.proc.stdin.write(user_line(text))
        self.proc.stdin.flush()
        tr = parse_turn(iter(self.proc.stdout.readline, ""))
        if self.init_event is None:
            for evt in tr.events:
                if evt.get("type") == "system" and evt.get("subtype") == "init":
                    self.init_event = evt
                    break
        if _is_synthetic(tr.served_model):
            # Subscription limit → synthetic placeholder. Retriable, not drift.
            raise LimitError(f"served {tr.served_model} (subscription limit hit)")
        if expect_model and tr.served_model:
            # Containment match: a served id may carry a suffix (date/[1m]) or be
            # the canonical alias resolution. Drift only if neither contains the
            # other (e.g. sonnet served for a pinned opus).
            a, b = tr.served_model.casefold(), expect_model.casefold()
            if a not in b and b not in a:
                raise ModelDriftError(f"served {tr.served_model} != pinned {expect_model}")
        self.turns.append(tr)
        return tr

    def close(self) -> str:
        if not self.proc:
            return ""
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        stderr = ""
        if self.proc.stderr:
            stderr = self.proc.stderr.read() or ""
        return stderr


def init_skill_inventory(init_event: dict[str, Any] | None) -> dict[str, Any]:
    """Extract the skill/slash-command inventory from a system/init event
    (product acceptance case 6: automatic skill discovery)."""
    ev = init_event or {}
    slash = ev.get("slash_commands") or ev.get("slashCommands") or []
    skills = ev.get("skills") or []
    return {
        "slash_commands": slash,
        "skills": skills,
        "has_curiosity_engine": any(
            "curiosity" in str(s).casefold() for s in list(slash) + list(skills)
        ),
        "tools": ev.get("tools") or [],
        "mcp_servers": ev.get("mcp_servers") or [],
        "model": ev.get("model"),
    }
