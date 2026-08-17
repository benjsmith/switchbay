"""Muse Code (Meta) as a subprocess-backed provider.

Muse Code is Meta's agentic coding CLI (public beta August 2026), the
direct counterpart of Claude Code / Codex / Grok Build: a terminal
agent invoked as `muse`, billed through a Meta Model API key or a
browser sign-in. We wrap it the same way as those siblings — spawn
the CLI per turn, parse JSONL events into canonical ChunkEvents.

Validated against the published docs (https://dev.meta.ai/docs/muse-code,
2026-08), not a live binary in this checkout:

  · headless: `muse exec [--json] "<prompt>"` (or `--prompt-file`)
  · `--workspace <path>` roots policy-gated tools
  · `--model`, `--reasoning-effort` (minimal/low/medium/high/xhigh;
    `none` unsupported; `ultra` is client-side multi-agent, not sent)
  · `--session-id <uuid>` continues a headless session
    (`muse resume` is interactive-only)
  · `--trust-workspace` so project AGENTS.md / skills load
  · `--disable-approval` keeps the OS sandbox but skips prompts that
    headless `-p` can't answer. We do NOT pass `--yolo` (that also
    drops the sandbox).
  · `--json` emits JSONL on stdout. The live event schema is not
    fully published; `parse_exec_event` accepts the shapes we have
    seen in sibling CLIs plus the session-log envelope.

Safety note (v1)
----------------
Claude Code and Grok Build mediate novel tool calls through
Switch Bay's rail approval card (PreToolUse hook). Muse Code's hook
payload dialect has not been validated against a live binary yet, so
this spawn relies on Meta's sandbox + `--disable-approval` rather
than our card. In-workspace writes and ordinary shell resolve by
Muse's static policy; dangerous shapes still go through Muse's own
reviewer. Switch Bay MCP is not registered per-workspace yet
(Muse's MCP block lives in the user settings file and is not
workspace-scoped). CE scripts still run because the CLI has a real
shell (`can_execute` is True).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from pathlib import Path
from typing import AsyncIterator

from .. import workspaces
from . import base

log = logging.getLogger("switchbay.llm.muse_code")

ID = "muse-code"
LABEL = "Muse Code"
BINARY = "muse"
DEFAULT_MODEL = "muse-spark-1.2"

PROVIDER = {
    "id": ID,
    "label": LABEL,
    "category": "subscription",
    "default_model": DEFAULT_MODEL,
    "binary": BINARY,
    "auth_help": (
        "Install Muse Code (`curl -fsSL https://dev.meta.ai/install.sh | "
        "sh`) and sign in (`muse` → browser or paste a Meta API key). "
        "Headless/CI can set META_API_KEY. Needs the `muse` binary on PATH."
    ),
    "model_suggestions": [
        "muse-spark-1.2",
        "muse-spark-1.1",
        "muse-spark-1.2-contributor",
    ],
    "capabilities": {
        "chat": True,
        "streaming": True,
        "tools": False,
        # spawns the muse CLI; sandbox stays on (no --yolo).
        "shell": True,
        "file_write": True,
        "key_validation": True,
    },
}


def muse_binary() -> str | None:
    """Resolve the `muse` CLI, including common installer drops."""
    found = shutil.which(BINARY)
    if found:
        return found
    home = Path.home()
    for cand in (
        home / ".local" / "bin" / BINARY,
        home / ".muse" / "bin" / BINARY,
    ):
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    return None


def is_installed() -> bool:
    return muse_binary() is not None


def _signed_in() -> bool:
    if os.environ.get("META_API_KEY"):
        return True
    home = Path.home()
    for cand in (
        home / ".muse" / "auth.json",
        home / ".config" / "muse" / "auth.json",
        home / ".muse" / "credentials.json",
    ):
        if cand.is_file() and cand.stat().st_size > 8:
            return True
    return False


def has_key() -> bool:
    """Available = CLI present *and* some auth marker exists."""
    return is_installed() and _signed_in()


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


def _verify_workspace(raw: str | None) -> Path:
    if not raw:
        raise base.ProviderError(
            "muse_code refuses to spawn without an explicit workspace cwd",
            code="server")
    p = Path(raw)
    if not p.is_absolute() or not p.is_dir():
        raise base.ProviderError(
            f"muse_code workspace must be an absolute existing directory: {raw}",
            code="server")
    if not workspaces.is_within_home(p):
        raise base.ProviderError(
            f"muse_code refuses to run with workspace outside {workspaces.home_label()}",
            code="server")
    return p.resolve()


# ── Reasoning effort ────────────────────────────────────────────────
# `muse --reasoning-effort` / `muse exec --reasoning-effort`.
# Docs: none is unsupported; ultra is client-side multi-agent (we
# don't send it — it is not deeper per-call reasoning).


def reasoning_options(model: str | None = None) -> list[dict]:
    del model
    return [
        base.reasoning_option("minimal", "Minimal", "shortest reasoning pass"),
        base.reasoning_option("low", "Low", "light reasoning"),
        base.reasoning_option("medium", "Medium", "balanced"),
        base.reasoning_option("high", "High", "deep reasoning"),
        base.reasoning_option("xhigh", "Extra high", "maximum per-call depth"),
    ]


def _kind_of(evt: dict) -> str:
    payload = evt.get("payload") if isinstance(evt.get("payload"), dict) else {}
    inner = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    for cand in (
        evt.get("type"), evt.get("event"), evt.get("kind"),
        evt.get("payload_type"),
        inner.get("kind") if isinstance(inner, dict) else None,
        payload.get("type"), payload.get("kind"),
    ):
        if isinstance(cand, str) and cand:
            return cand
    return ""


def _session_id_of(evt: dict) -> str | None:
    payload = evt.get("payload") if isinstance(evt.get("payload"), dict) else {}
    for blob in (evt, payload):
        if not isinstance(blob, dict):
            continue
        for key in ("session_id", "sessionId", "session"):
            val = blob.get(key)
            if isinstance(val, str) and val:
                return val
    return None


def _pick_text(*vals: object) -> str:
    for v in vals:
        if isinstance(v, str) and v:
            return v
    return ""


def _text_from(evt: dict) -> str:
    payload = evt.get("payload") if isinstance(evt.get("payload"), dict) else {}
    item = evt.get("item") if isinstance(evt.get("item"), dict) else {}
    msg = evt.get("message") if isinstance(evt.get("message"), dict) else {}
    # Claude-shaped content blocks.
    for blob in (msg, payload, evt):
        content = blob.get("content") if isinstance(blob, dict) else None
        if isinstance(content, list):
            joined = _content_to_text(content)
            if joined.strip():
                return joined
        if isinstance(content, str) and content:
            return content
    return _pick_text(
        evt.get("data"), evt.get("text"), evt.get("delta"),
        payload.get("text") if isinstance(payload, dict) else None,
        payload.get("delta") if isinstance(payload, dict) else None,
        item.get("text") if isinstance(item, dict) else None,
        msg.get("text") if isinstance(msg, dict) else None,
    )


def parse_exec_event(evt: dict) -> list[base.ChunkEvent]:
    """Map one `muse exec --json` object to zero or more ChunkEvents.

    Defensive: the live JSONL schema is not fully published. Accept
    grok-like `{type, data}`, claude-like `{type: assistant, message}`,
    codex-like `{type: item.completed, item}`, and the session-log
    envelope `{payload_type, payload}`.
    """
    if not isinstance(evt, dict):
        return []
    kind = _kind_of(evt).lower()
    out: list[base.ChunkEvent] = []

    if any(s in kind for s in ("error", "failed", "fail")):
        msg = _text_from(evt) or evt.get("message") or evt.get("error") or kind
        raise base.ProviderError(f"Muse Code error: {msg}", code="server")

    if any(s in kind for s in ("thought", "reasoning", "thinking")):
        text = _text_from(evt)
        if text:
            out.append(base.ReasoningChunk(text=text))
        return out

    if any(s in kind for s in (
        "tool_use", "tool_call", "tool.started", "item.started",
        "tool_batch.effect.started",
    )):
        item = evt.get("item") if isinstance(evt.get("item"), dict) else {}
        payload = evt.get("payload") if isinstance(evt.get("payload"), dict) else {}
        inner = payload.get("event") if isinstance(payload.get("event"), dict) else {}
        name = (
            item.get("type") or evt.get("name") or evt.get("tool")
            or inner.get("operation")
        )
        if name and str(name) not in ("agent_message", "text", "assistant"):
            out.append(base.ToolUseChunk(
                id=str(item.get("id") or evt.get("id") or ""),
                name=str(name),
                input=item if item else {
                    k: evt[k] for k in ("command", "path", "input")
                    if k in evt
                },
            ))
        return out

    # Visible assistant text. Skip audit-log envelopes that happen
    # to carry a string field (`record`, `session.*`, `*.effect.*`).
    if kind.startswith("session") or "effect" in kind or kind == "record":
        return out
    if kind == "" or any(s in kind for s in (
        "text", "assistant", "message", "output", "delta",
        "agent_message", "item.completed",
    )):
        text = _text_from(evt)
        if text:
            out.append(base.TextChunk(text=text))
    return out


def build_argv(
    *,
    binary: str,
    prompt: str,
    workspace: Path,
    model: str | None,
    effort: str | None,
    session_id: str | None,
) -> list[str]:
    """Headless spawn argv. Kept pure so tests can pin the flag set."""
    argv = [
        binary, "exec", "--json",
        "--workspace", str(workspace),
        "--trust-workspace",
        # Headless cannot answer an approval prompt. Sandbox stays on
        # (we never pass --yolo).
        "--disable-approval",
    ]
    if model:
        argv.extend(["--model", model])
    if effort:
        argv.extend(["--reasoning-effort", effort])
    if session_id:
        argv.extend(["--session-id", session_id])
    argv.append(prompt)
    return argv


async def chat_stream(req: base.ChatRequest) -> AsyncIterator[base.ChunkEvent]:
    binary = muse_binary()
    if not binary:
        raise base.ProviderError(
            "`muse` not found on PATH. Install Muse Code: "
            "`curl -fsSL https://dev.meta.ai/install.sh | sh`.",
            code="missing-key")

    workspace = _verify_workspace(req.workspace)
    prompt = (
        _content_to_text(req.messages[-1].get("content", ""))
        if req.session_id and req.messages
        else _flatten_messages(req.messages)
    )
    if req.system:
        # No documented --rules / --append-system-prompt on muse exec.
        # Prepend standing rules to the user prompt so they still land.
        prompt = f"{req.system}\n\n{prompt}"

    effort = base.coerce_effort(req.reasoning_effort, reasoning_options(req.model))
    argv = build_argv(
        binary=binary,
        prompt=prompt,
        workspace=workspace,
        model=req.model,
        effort=effort,
        session_id=req.session_id,
    )

    env = {
        k: v for k, v in os.environ.items()
        if k not in {"VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "PYTHONPATH"}
    }
    from .. import cebridge
    env = cebridge.inject_skill_env(env)
    # If the user stored a Meta Model API key in Settings, let the CLI
    # use it when META_API_KEY isn't already in the environment.
    if not env.get("META_API_KEY") and not env.get("MODEL_API_KEY"):
        try:
            from .. import secrets
            stored = secrets.get("meta")
        except Exception:  # noqa: BLE001
            stored = None
        if stored:
            env["META_API_KEY"] = stored

    log.info("spawning muse exec in cwd=%s", workspace)
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=str(workspace), env=env, limit=16 * 1024 * 1024)
    except FileNotFoundError as e:
        raise base.ProviderError(
            f"failed to spawn muse: {e}", code="missing-key", cause=e,
        ) from e

    session_id: str | None = req.session_id
    input_tokens: int | None = None
    output_tokens: int | None = None
    stop_reason: str | None = None
    if proc.stdout is None:
        raise base.ProviderError("muse subprocess produced no stdout", code="server")

    try:
        async for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                # Non-JSON line: treat as assistant text (muse exec
                # without --json prints the answer this way).
                yield base.TextChunk(text=line + "\n")
                continue
            if not isinstance(evt, dict):
                continue
            sid = _session_id_of(evt)
            if sid:
                session_id = sid
            usage = evt.get("usage") if isinstance(evt.get("usage"), dict) else {}
            input_tokens = usage.get("input_tokens", input_tokens)
            output_tokens = usage.get("output_tokens", output_tokens)
            kind = _kind_of(evt).lower()
            if any(s in kind for s in ("result", "end", "completed", "session.end")):
                stop_reason = evt.get("stop_reason") or stop_reason or "end_turn"
            for chunk in parse_exec_event(evt):
                yield chunk
    finally:
        try:
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except (asyncio.TimeoutError, ProcessLookupError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    if proc.returncode and proc.returncode != 0:
        err = (await proc.stderr.read() if proc.stderr else b"").decode(
            errors="replace")
        raise base.ProviderError(
            f"muse exited {proc.returncode}: {err.strip()[:300] or 'no stderr'}",
            code="server")

    yield base.DoneChunk(
        input_tokens=input_tokens, output_tokens=output_tokens,
        stop_reason=stop_reason, session_id=session_id)


async def list_models() -> list[str]:
    """Best-effort: `muse models` if the CLI grows the subcommand.

    Today the published CLI has no list-models command; an empty
    return lets model_cache fall back to model_suggestions.
    """
    binary = muse_binary()
    if not binary:
        return []
    try:
        proc = await asyncio.create_subprocess_exec(
            binary, "models",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _err = await asyncio.wait_for(proc.communicate(), timeout=8.0)
    except Exception:  # noqa: BLE001
        return []
    if proc.returncode not in (0, None):
        return []
    text = stdout.decode("utf-8", errors="replace")
    found: list[str] = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("*-•").strip()
        if line.startswith("muse-") and line.split()[0] not in found:
            found.append(line.split()[0])
    return found


async def validate_key(*, workspace: str | None = None) -> bool:
    if not has_key():
        raise base.ProviderError("`muse` binary not found on PATH", code="missing-key")
    del workspace
    return True
