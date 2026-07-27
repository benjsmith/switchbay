"""Shared types + error vocabulary for LLM providers.

The error `code` vocabulary is lifted verbatim from
read-really-fast/src/providers/base.js — it's a hard-won surface and
the frontend maps each code to user-friendly text. Keep this set
stable; add codes as new failure modes appear.

Streaming model: each provider implements `chat_stream(req) ->
AsyncIterator[ChunkEvent]`. The daemon iterates and pushes each event
over the WS as AG-UI events (`TEXT_MESSAGE_*` / `RUN_FINISHED`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ErrorCode = Literal[
    "missing-key",       # provider has no API key configured
    "auth",              # 401 / 403
    "rate-limit",        # 429
    "timeout",           # request exceeded our timeout
    "network",           # DNS / connect / TLS error
    "bad-url",           # user-supplied endpoint was invalid
    "server",            # 5xx
    "http",              # other 4xx not covered above
    "cancelled",         # request was aborted (user / disconnect)
    "unsupported",       # provider doesn't support the requested capability
    "model-not-found",   # 404 against the model id
    "keychain",          # OS keychain unavailable
]


class ProviderError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: ErrorCode,
        status: int | None = None,
        retryable: bool = False,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.retryable = retryable
        if cause is not None:
            self.__cause__ = cause


CAPABILITY_NOTES = """Execution surface (`PROVIDER["capabilities"]`).

`shell` / `file_write` say whether a provider can EXECUTE work — run
curiosity-engine / curiosity-merge scripts, edit files directly — or
can only PROPOSE it back through switchbay's own tool registry
(`propose_wiki_page`, `propose_page_edit`, `create_report`, …).

Only the subprocess-CLI providers (claude-code, openai-codex,
grok-build) have a real shell. The HTTP providers — including the
local ones — are limited to the curated tool registry by
construction: there is no Bash tool to give them.

This matters for routing. A curate/ingest run sent to a provider
without `shell` cannot complete: it reads the wiki, decides what to
change, and hands every change back as a proposal. That was the
2026-07-24 curator bug, where the model ladder's `normal` rung
silently routed `/curate` to a provider spawned with `--deny Bash(*)`.
`daemon._ce_action_provider` now requires both flags before honoring
a ladder rung. See `ce_toolscope` for how the CLIs get a scoped shell
rather than an unrestricted one.
"""


@dataclass
class TextChunk:
    text: str
    type: Literal["text"] = "text"


@dataclass
class ReasoningChunk:
    """A fragment of the model's private chain-of-thought (e.g. Ornith's
    `reasoning_content`, o1/Claude extended thinking). Surfaced to the
    UI as a collapsible block for inspection, persisted separately, and
    NEVER fed back into the model's context as assistant content."""
    text: str
    type: Literal["reasoning"] = "reasoning"


@dataclass
class ToolUseChunk:
    """The model wants to invoke a tool. The daemon's agent loop picks
    this up, runs the tool via the registry, and feeds the result back
    in the next turn. `id` is the provider-assigned call id (Anthropic
    uses it to match tool_use ↔ tool_result)."""
    id: str
    name: str
    input: dict[str, Any]
    type: Literal["tool_use"] = "tool_use"


@dataclass
class DoneChunk:
    """End-of-stream marker. `stop_reason == "tool_use"` means more
    turns follow (after the daemon executes the tools).

    `session_id` is provider-specific and surfaces opaque session
    handles back to the daemon so it can stitch follow-up turns into
    the same context (e.g. Claude Code's --resume <id>)."""
    input_tokens: int | None = None
    output_tokens: int | None = None
    stop_reason: str | None = None
    session_id: str | None = None
    type: Literal["done"] = "done"


# Discriminated union the daemon iterates over.
ChunkEvent = TextChunk | ReasoningChunk | ToolUseChunk | DoneChunk


@dataclass
class ChatRequest:
    """Canonical request shape. Each provider translates to its wire format."""
    messages: list[dict[str, Any]]   # [{"role": "user"|"assistant", "content": str|list}]
    model: str | None = None
    system: str | None = None
    max_tokens: int = 4096
    temperature: float | None = None
    tools: list[dict[str, Any]] | None = None
    """Provider-shaped tool list (e.g. anthropic: {name, description,
    input_schema}). `None` = no tools, omit the field entirely."""
    session_id: str | None = None
    """Opaque continuation handle for providers that support stateful
    multi-turn (Claude Code's --resume <session_id>). When set, the
    provider should continue that conversation; messages[] is just the
    *new* turns. Providers that don't support this ignore the field."""
    workspace: str | None = None
    """Absolute filesystem path of the active workspace. Subprocess-
    backed providers (claude_code, codex, ...) MUST run with this as
    cwd and refuse paths outside it. HTTP-only providers ignore."""
    origin_thread: str | None = None
    """Rail thread that owns this dispatch, when there is one. CLI
    providers export it (CSWY_THREAD_ID) so the permission hook can
    tag its requests and the rail scopes the card to the owning
    thread. Unset for headless/background/external callers — their
    permission cards land in the rail's "other approvals" strip
    instead of any thread transcript."""
    reasoning: bool | None = None
    """Per-request reasoning override for local models (llamacpp/Ornith).
    None = use the global Settings default (ON). Set False for one-shot
    content generation (drafting a page/decision in a single turn): with
    reasoning ON the whole token budget can go to reasoning_content,
    leaving an EMPTY body (quality-trial finding). The agentic /curate
    loop leaves this None so it keeps reasoning ON. Non-local providers
    ignore it."""
