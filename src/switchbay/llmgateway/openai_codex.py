"""OpenAI Codex CLI provider — subscription-backed, subprocess-driven.

Mirror of `claude_code.py` for OpenAI's coding-agent CLI. The Codex
CLI handles auth and billing via the user's ChatGPT subscription, so
no API key lives in our keychain. Daemon spawns `codex` with cwd
hardwired to the active workspace and parses its stream output.

Trade-offs vs. the OpenAI BYOK provider:
  + No API key — uses the user's ChatGPT subscription auth.
  + Multi-turn via `exec resume <session_id>`, so the rail can
    replay long conversations without re-sending the full history.
  - Per-turn process spawn adds startup latency.
  - The CLI streams items, not tokens — text arrives once per
    `agent_message` completion rather than smoothly.
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
from .. import permissions
from . import base, claude_code_settings

log = logging.getLogger("switchbay.llm.openai_codex")

ID = "openai-codex"
LABEL = "OpenAI Codex"
# When the codex CLI is installed, list_models() reads the live model
# list from ~/.codex/models_cache.json — that's the source of truth.
# This static default and `model_suggestions` only matter for users
# whose CLI hasn't run yet; intentionally generic.
DEFAULT_MODEL = "gpt-5.5"
BINARY = "codex"

PROVIDER = {
    "id": ID,
    "label": LABEL,
    "category": "subscription",
    "default_model": DEFAULT_MODEL,
    "binary": BINARY,
    "auth_help": (
        "Install the codex CLI (https://github.com/openai/codex) and "
        "authenticate via your ChatGPT Plus/Pro subscription. Once "
        "logged in, switchbay reuses that auth — no API key stored."
    ),
    "model_suggestions": [
        # Preview fallbacks; live list_models() overrides these from
        # the codex CLI's own cache once it's been run.
        "gpt-5.5",
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5.3-codex",
    ],
    "capabilities": {
        "chat": True,
        "streaming": True,
        "tools": False,
        # Execution surface — see base.CAPABILITY_NOTES.
        # spawns codex with --sandbox workspace-write.
        "shell": True,
        "file_write": True,
        "key_validation": True,
    },
}


def has_key() -> bool:
    """For subscription providers, "has_key" is "is the CLI installed
    and on PATH?". The actual auth state lives inside the CLI's own
    config; we treat its presence as readiness and let chat dispatch
    surface auth errors if needed."""
    return shutil.which(BINARY) is not None


def _verify_workspace(workspace: str | None) -> Path:
    """Defence in depth — same hardening as claude_code: cwd MUST be
    an absolute directory inside the user's home. Anywhere else and
    we refuse to spawn."""
    if not workspace:
        raise base.ProviderError(
            "Codex provider requires an active workspace.",
            code="missing-key",
        )
    p = Path(workspace)
    if not p.is_absolute():
        raise base.ProviderError(
            f"workspace must be absolute: {workspace}", code="bad-url",
        )
    if not p.is_dir():
        raise base.ProviderError(
            f"workspace not a directory: {workspace}", code="bad-url",
        )
    try:
        p.resolve().relative_to(Path.home().resolve())
    except ValueError as e:
        raise base.ProviderError(
            f"refusing to spawn codex outside home: {workspace}",
            code="bad-url", cause=e,
        ) from e
    return p


def _content_to_text(content) -> str:
    """Coerce a message `content` field (string OR list of blocks)
    into plain text for codex's single-prompt argument."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out: list[str] = []
        for block in content:
            if isinstance(block, dict):
                t = block.get("text")
                if isinstance(t, str):
                    out.append(t)
                    continue
            out.append(json.dumps(block))
        return "\n".join(out)
    return json.dumps(content)


def _flatten_messages(messages: list[dict]) -> str:
    """Codex `exec` takes a single prompt argument on first turn. We
    collapse the canonical message list into role-tagged blocks the
    way claude-code's first-turn prompt does. Subsequent turns use
    `exec resume <session_id> <last-user-message>` instead — codex
    keeps the prior thread state itself."""
    parts: list[str] = []
    for m in messages:
        role = m.get("role") or "user"
        text = _content_to_text(m.get("content"))
        parts.append(f"<{role}>\n{text}\n</{role}>")
    return "\n\n".join(parts)


def _is_no_rollout(msg: str) -> bool:
    """codex `exec resume <id>` had no saved rollout for that thread — the
    id semantics differ across CLI versions, or the session wasn't persisted."""
    m = (msg or "").lower()
    return "no rollout" in m or "thread/resume" in m


async def chat_stream(req: base.ChatRequest) -> AsyncIterator[base.ChunkEvent]:
    """Stream a chat turn through `codex exec --json` (first turn) or
    `codex exec resume <session_id> --json` (subsequent turns). Parses
    the line-delimited event stream into TextChunks, ToolUseChunks
    (one per shell command codex runs), and a final DoneChunk with
    usage + thread_id.

    If a resume fails because codex has no saved rollout for the thread
    (`thread/resume: no rollout found …`), fall back to a FRESH turn that
    replays the full flattened history — the rail keeps working instead of
    dead-ending on a lost session."""
    workspace = _verify_workspace(req.workspace)
    if not has_key():
        raise base.ProviderError(
            f"`{BINARY}` CLI not found. {PROVIDER['auth_help']}",
            code="missing-key",
        )
    if req.session_id:
        produced = False
        try:
            async for ev in _stream_codex(req, workspace, req.session_id):
                produced = produced or isinstance(
                    ev, (base.TextChunk, base.ToolUseChunk))
                yield ev
            return
        except base.ProviderError as e:
            if produced or not _is_no_rollout(str(e)):
                raise
            log.warning(
                "codex resume: no rollout for thread %s — retrying fresh "
                "with full history", req.session_id,
            )
    async for ev in _stream_codex(req, workspace, None):
        yield ev


async def _stream_codex(
    req: base.ChatRequest, workspace, resume_id: str | None,
) -> AsyncIterator[base.ChunkEvent]:
    """One codex `exec` (resume_id=None) or `exec resume <resume_id>` run."""

    # On resume, codex already has the prior thread state — only send
    # the new user turn. Falls back to flattening on first turn or if
    # the message list ends on a non-user role (defensive).
    if resume_id and req.messages and req.messages[-1].get("role") == "user":
        prompt = _content_to_text(req.messages[-1].get("content"))
    else:
        prompt = _flatten_messages(req.messages)
    if req.system and not resume_id:
        # Codex doesn't have a separate system flag; fold the system
        # prompt into the prompt arg as a leading <system> block on
        # the first turn.
        prompt = f"<system>\n{req.system}\n</system>\n\n{prompt}"
    elif req.system and resume_id:
        # Re-inject system + live focus on every resume. The first-turn
        # system block is frozen in the rollout; sheet/table/sketch
        # focus and tool policy change after turn 1. Keep this as a
        # full system-update (not a truncated focus-only delta) so
        # rail_default + focus lines stay authoritative.
        prompt = (
            f"<system-update>\n{req.system}\n</system-update>\n\n{prompt}"
        )

    argv: list[str] = [BINARY, "exec"]
    if resume_id:
        # `exec resume` inherits the prior session's sandbox + cwd
        # from the recorded session metadata, and rejects --sandbox /
        # -C / --add-dir as unknown args. Only --json, --model, -c,
        # and --skip-git-repo-check carry over.
        argv += ["resume", resume_id, "--json", "--skip-git-repo-check"]
    else:
        # Codex doesn't expose user-script hooks like claude-code's
        # PreToolUse, so per-tool gating from switchbay's rail isn't
        # possible. Compromise: if the workspace has explicitly
        # remembered the `_codex:full-access` sentinel pattern (set
        # from Settings → Permissions), spawn with the wide-open
        # sandbox. Otherwise stick to workspace-write — same default
        # as before this commit, no behavioural regression for users
        # who never opt in.
        sandbox = (
            "danger-full-access"
            if permissions.is_pre_approved(workspace, "_codex:full-access")
            else "workspace-write"
        )
        argv += [
            "--json",
            "--sandbox", sandbox,
            "--skip-git-repo-check",
            "-C", str(workspace),
        ]
    # Inject the switchbay MCP server via `-c mcp_servers.…` TOML
    # overrides. Codex doesn't have a `--mcp-config <file>` flag like
    # claude-code; instead it loads `[mcp_servers.NAME]` tables from
    # ~/.codex/config.toml, and `-c` lets us add one inline without
    # touching the user's file. `-c` is accepted by both `exec` and
    # `exec resume`, so both paths see the identical tool surface.
    argv.extend(_mcp_overrides(workspace))
    if req.model:
        argv.extend(["--model", req.model])
    argv.append(prompt)

    # Strip OPENAI_API_KEY so the CLI commits to the subscription auth
    # the user logged in with via `codex login`. Mirrors the
    # ANTHROPIC_API_KEY strip in claude_code.py.
    env = {
        k: v for k, v in os.environ.items()
        if k not in {
            "OPENAI_API_KEY",
            "VIRTUAL_ENV",
            "UV_PROJECT_ENVIRONMENT",
            "PYTHONPATH",
        }
    }

    log.info(
        "spawning codex in cwd=%s sandbox=workspace-write mode=%s",
        workspace, "resume" if resume_id else "fresh",
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(workspace),
            env=env,
            # Same StreamReader-buffer headroom as claude_code: codex
            # JSONL lines can include long tool outputs.
            limit=16 * 1024 * 1024,
        )
    except FileNotFoundError as e:
        raise base.ProviderError(
            f"failed to spawn codex: {e}", code="missing-key", cause=e,
        ) from e

    if proc.stdout is None:
        raise base.ProviderError("codex subprocess produced no stdout", code="server")

    input_tokens: int | None = None
    output_tokens: int | None = None
    stop_reason: str | None = None
    session_id: str | None = resume_id

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
            if etype == "thread.started":
                tid = evt.get("thread_id")
                if isinstance(tid, str):
                    session_id = tid
            elif etype == "item.started":
                item = evt.get("item") or {}
                # Treat any non-message item start as a tool_use the
                # CLI is about to run. command_execution is the common
                # one (Bash); future codex versions may add more (file
                # edits, web fetches if enabled, …) — they'll surface
                # the same way without parser changes.
                itype = item.get("type")
                if itype and itype != "agent_message":
                    name, tool_input = _item_to_tool(item)
                    yield base.ToolUseChunk(
                        id=str(item.get("id", "")),
                        name=name,
                        input=tool_input,
                    )
            elif etype == "item.completed":
                item = evt.get("item") or {}
                itype = item.get("type")
                if itype == "agent_message":
                    text = item.get("text") or ""
                    if isinstance(text, str) and text:
                        yield base.TextChunk(text=text)
                # Tool completions have aggregated_output we *could*
                # surface as a synthetic tool_result — daemon already
                # synthesises one downstream, so we leave the heavy
                # lifting there for now.
            elif etype == "turn.completed":
                usage = evt.get("usage") or {}
                input_tokens = usage.get("input_tokens", input_tokens)
                output_tokens = usage.get("output_tokens", output_tokens)
                stop_reason = "end_turn"
            elif etype == "turn.failed":
                err = evt.get("error") or {}
                msg_text = (err.get("message") if isinstance(err, dict) else None) or "codex turn failed"
                raise base.ProviderError(
                    f"Codex: {msg_text}", code="server",
                )
    finally:
        # Reap the process; drain stderr for diagnostics if it exited.
        try:
            if proc.returncode is None:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=2.0)
        except (asyncio.TimeoutError, ProcessLookupError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    # If codex exited non-zero without emitting `turn.failed` (e.g.
    # rejected an unknown CLI flag before the event loop started),
    # the loop above sees no events and we'd otherwise return a
    # silent empty DoneChunk. Surface stderr as a ProviderError so
    # the rail shows the actual failure.
    rc = proc.returncode
    if rc is not None and rc != 0 and stop_reason is None:
        stderr_bytes = b""
        if proc.stderr is not None:
            try:
                stderr_bytes = await asyncio.wait_for(proc.stderr.read(), timeout=1.0)
            except asyncio.TimeoutError:
                pass
        msg = stderr_bytes.decode("utf-8", errors="replace").strip() or f"codex exited rc={rc}"
        raise base.ProviderError(f"Codex: {msg}", code="server")

    yield base.DoneChunk(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        stop_reason=stop_reason,
        session_id=session_id,
    )


def _toml_str(s: str) -> str:
    """TOML basic-string literal. Same escape rules as JSON for our
    inputs (paths, env values), so json.dumps is a safe encoder."""
    return json.dumps(s, ensure_ascii=False)


def _mcp_overrides(workspace: Path) -> list[str]:
    """Build the `-c mcp_servers.<name>.…` argv flags that register
    the switchbay MCP server with the codex CLI for this spawn.
    Each `-c` value parses as TOML. We emit three overrides — command,
    args, env — rather than one inline-table to keep escaping simple.
    """
    def _server_flags(name: str, command: str, args: list, env: dict) -> list[str]:
        args_toml = "[" + ", ".join(_toml_str(a) for a in args) + "]"
        env_toml = "{" + ", ".join(
            f"{k} = {_toml_str(str(v))}" for k, v in env.items()) + "}"
        prefix = f"mcp_servers.{name}"
        return [
            "-c", f"{prefix}.command={_toml_str(command)}",
            "-c", f"{prefix}.args={args_toml}",
            "-c", f"{prefix}.env={env_toml}",
        ]

    name = claude_code_settings.MCP_SERVER_NAME
    spec = claude_code_settings.mcp_server_spec(workspace)
    flags = _server_flags(name, spec["command"], spec["args"], spec["env"])
    # User-registered stdio MCP servers (mcpstore). codex TOML mcp_servers
    # is stdio (command/args/env); http servers are skipped here — they
    # still reach claude-code/grok.
    try:
        from .. import mcpstore

        for s in mcpstore.enabled_servers():
            if s["transport"] == "stdio" and s.get("command") and s["name"] != name:
                flags += _server_flags(
                    s["name"], s["command"], s.get("args", []), s.get("env", {}))
    except Exception:  # noqa: BLE001
        log.exception("failed to merge user MCP servers for codex")
    return flags


def _item_to_tool(item: dict) -> tuple[str, dict]:
    """Map a codex `item` dict to (tool_name, tool_input) the rail
    can render. Today's known kinds are best-effort named so the rail
    label reads naturally; unknown kinds fall through with the raw
    type as the name."""
    itype = str(item.get("type") or "unknown")
    if itype == "command_execution":
        return ("Bash", {"command": item.get("command", "")})
    return (itype, {k: v for k, v in item.items() if k not in {"id", "type"}})


def _codex_models_cache_path() -> Path:
    return Path.home() / ".codex" / "models_cache.json"


async def list_models() -> list[str]:
    """Read the codex CLI's own model cache (~/.codex/models_cache.json),
    which the CLI refreshes against OpenAI on its own cadence. We just
    surface what's in it — that's the same list the user sees inside
    `codex` itself, so the switchbay picker stays in lockstep with
    whatever the CLI considers default. Falls back to static
    suggestions when the cache file isn't present (CLI not installed
    or never run)."""
    cache_path = _codex_models_cache_path()
    if not cache_path.is_file():
        return []
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = data.get("models") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        # `visibility="list"` is the codex CLI's own marker for models
        # the user should see in pickers (vs internal/preview entries).
        if it.get("visibility") and it.get("visibility") != "list":
            continue
        slug = it.get("slug")
        if isinstance(slug, str) and slug:
            out.append(slug)
    # Preserve the cache's order — codex uses `priority` to put the
    # default model first, which is what we want too.
    seen: set[str] = set()
    deduped: list[str] = []
    for m in out:
        if m not in seen:
            seen.add(m)
            deduped.append(m)
    return deduped


async def validate_key(*, workspace: str | None = None) -> bool:
    """Settings → Test: just confirm the CLI is installed. Auth state
    inside the CLI is harder to introspect without running it."""
    del workspace
    if not has_key():
        raise base.ProviderError(
            f"`{BINARY}` CLI not found on PATH. "
            "Install from https://github.com/openai/codex.",
            code="missing-key",
        )
    return True
