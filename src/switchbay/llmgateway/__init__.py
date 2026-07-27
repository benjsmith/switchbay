"""Provider-agnostic LLM gateway.

Multi-provider plumbing patterned on read-really-fast/src/providers/
(see log.md for the survey). Each provider is a module with a stable
shape declared in `base.PROVIDER_FIELDS`; this package's `__init__`
just builds a registry and exposes `list_providers()` / `get()`.

What lives here:
  base.py       — ProviderError + canonical request/response types
  anthropic.py  — Claude (streaming via SSE; tools land in J.2)

What does NOT live here:
  - Per-call rate-limiting / backoff. Rely on retry-on-error in the
    UI for now.
"""

from __future__ import annotations

from . import (
    anthropic, claude_code, gemini, github_copilot, grok_build, llamacpp,
    ollama, openai, openai_codex, xai,
)
from .base import (
    ChatRequest, ChunkEvent, DoneChunk, ProviderError, ReasoningChunk,
    TextChunk, ToolUseChunk,
)

# Order matters for the Settings UI (it renders in iteration order).
# Subscriptions first, then BYOK, then local.
PROVIDERS = {
    # Subscriptions (Grok Build 2nd, after Claude) …
    claude_code.ID: claude_code,
    grok_build.ID: grok_build,
    openai_codex.ID: openai_codex,
    github_copilot.ID: github_copilot,
    # … then BYOK APIs (xAI Grok 2nd, after Anthropic) …
    anthropic.ID: anthropic,
    xai.ID: xai,
    openai.ID: openai,
    gemini.ID: gemini,
    # … then local.
    llamacpp.ID: llamacpp,
    ollama.ID: ollama,
}


def list_providers() -> list[dict]:
    """Public list — for the Settings UI. Includes a `has_key` flag so
    the UI can show "configured" vs "needs key" without exposing the
    key itself."""
    out = []
    for p in PROVIDERS.values():
        info = dict(p.PROVIDER)
        info["has_key"] = p.has_key()
        out.append(info)
    return out


def get(provider_id: str):
    p = PROVIDERS.get(provider_id)
    if p is None:
        raise ProviderError(f"unknown provider: {provider_id}", code="unsupported")
    return p


def default_provider_id() -> str:
    """Provider used when the user hasn't picked one explicitly."""
    return anthropic.ID


def capabilities(provider_id: str) -> dict:
    """This provider's declared capabilities dict (empty on unknown)."""
    p = PROVIDERS.get(provider_id)
    if p is None:
        return {}
    return dict(p.PROVIDER.get("capabilities") or {})


def can_execute(provider_id: str) -> bool:
    """True iff this provider can EXECUTE work — run curiosity-engine /
    curiosity-merge scripts and edit files directly — rather than only
    PROPOSE changes through switchbay's tool registry. See
    `base.CAPABILITY_NOTES`. Curate/ingest routing requires this; a
    provider without it degrades a curation run into a pile of
    proposals (the 2026-07-24 curator bug)."""
    caps = capabilities(provider_id)
    return bool(caps.get("shell")) and bool(caps.get("file_write"))


__all__ = [
    "ChatRequest", "ChunkEvent", "DoneChunk", "ProviderError",
    "ReasoningChunk", "TextChunk", "ToolUseChunk",
    "PROVIDERS", "list_providers", "get", "default_provider_id",
    "capabilities", "can_execute",
]
