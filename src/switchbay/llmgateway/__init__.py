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
    meta, mlx, muse_code, ollama, openai, openai_codex, xai,
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
    muse_code.ID: muse_code,
    openai_codex.ID: openai_codex,
    github_copilot.ID: github_copilot,
    # … then BYOK APIs (xAI Grok 2nd, after Anthropic) …
    anthropic.ID: anthropic,
    xai.ID: xai,
    meta.ID: meta,
    openai.ID: openai,
    gemini.ID: gemini,
    # … then local. MLX leads on Apple silicon (native unified-memory
    # path); it self-hides via has_key()/supported() elsewhere.
    llamacpp.ID: llamacpp,
    mlx.ID: mlx,
    ollama.ID: ollama,
}


def list_providers() -> list[dict]:
    """Public list — for the Settings UI. Includes a `has_key` flag so
    the UI can show "configured" vs "needs key" without exposing the
    key itself. Admin policy may hide providers entirely."""
    from .. import admin_policy
    out = []
    for p in PROVIDERS.values():
        info = dict(p.PROVIDER)
        if not admin_policy.provider_allowed(str(info.get("id") or "")):
            continue
        info["has_key"] = p.has_key()
        installed_fn = getattr(p, "is_installed", None)
        info["installed"] = bool(installed_fn()) if callable(installed_fn) else info["has_key"]
        out.append(info)
    return out


def get(provider_id: str):
    p = PROVIDERS.get(provider_id)
    if p is None:
        raise ProviderError(f"unknown provider: {provider_id}", code="unsupported")
    return p


def default_provider_id() -> str:
    """Provider used when the user hasn't picked one explicitly."""
    from .. import admin_policy
    if admin_policy.profile() == "enterprise":
        for pid in admin_policy.preferred_provider_order():
            if pid in PROVIDERS:
                return pid
        return github_copilot.ID
    return anthropic.ID


def reasoning_options(provider_id: str, model: str | None = None) -> list[dict]:
    """Reasoning-effort options for `model` on `provider_id`.

    Empty when the provider has no reasoning control, or when THIS model
    doesn't take one — the answer is per model, not per provider (see
    `base.REASONING_NOTES`). Callers render whatever comes back and hide
    the control on an empty list; nobody outside a provider module may
    invent an effort id.
    """
    p = PROVIDERS.get(provider_id)
    fn = getattr(p, "reasoning_options", None) if p is not None else None
    if fn is None:
        return []
    try:
        opts = fn(model)
    except Exception:  # noqa: BLE001
        return []
    return [o for o in (opts or []) if isinstance(o, dict) and o.get("id")]


def supports_reasoning_effort(provider_id: str, model: str | None = None) -> bool:
    return bool(reasoning_options(provider_id, model))


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


def can_curate(provider_id: str) -> bool:
    """True if this provider can drive a curate/ingest run.

    CLI agents execute CE scripts in their own shell. HTTP / local
    models do the same via Switch Bay ``ce_run`` tools (no shell
    needed). Either path is enough — refusing Copilot/MLX here is
    what made them report they “can't curate” until the user asked
    what tools they have.
    """
    if can_execute(provider_id):
        return True
    caps = capabilities(provider_id)
    return bool(caps.get("tools"))


__all__ = [
    "ChatRequest", "ChunkEvent", "DoneChunk", "ProviderError",
    "ReasoningChunk", "TextChunk", "ToolUseChunk",
    "PROVIDERS", "list_providers", "get", "default_provider_id",
    "capabilities", "can_execute", "can_curate",
]
