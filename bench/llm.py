"""Synchronous LLM call wrapper over switchbay's llmgateway — reuses its
auth, model defaults, and error handling so the bench doesn't reimplement
four vendor APIs. One-shot (non-streaming to the caller): accumulates the
provider's stream to a string.

Subscription CLIs (claude-code, openai-codex, grok-build, muse-code) are preferred
over BYOK HTTP providers for the same model family: the bench must not
burn API credits when the user has an active Code/Codex/Grok subscription.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from switchbay import llmgateway
from switchbay.llmgateway import base

# Default probe/judge pool. Subscription CLIs first within each family so
# available_providers() prefers Pro/Max / ChatGPT / SuperGrok over BYOK.
JUDGES = [
    "claude-code",   # Claude Pro/Max subscription via `claude` CLI
    "openai-codex",  # ChatGPT Plus/Pro via `codex` CLI
    "anthropic",     # BYOK api.anthropic.com (API credits — last resort)
    "openai",        # BYOK platform.openai.com
    "gemini",
    "xai",
]

# Providers that spawn a CLI and require an explicit workspace cwd.
SUBSCRIPTION_CLI = frozenset({
    "claude-code",
    "openai-codex",
    "grok-build",
    "muse-code",
})

# Prefer subscription id when a BYOK alias is requested (or vice-versa for
# model override lookup).
BYOK_TO_SUBSCRIPTION = {
    "anthropic": "claude-code",
    "openai": "openai-codex",
    "meta": "muse-code",
}
SUBSCRIPTION_TO_BYOK = {v: k for k, v in BYOK_TO_SUBSCRIPTION.items()}

# Pin the LATEST-GENERATION model per provider (charter: benchmarks always run
# on current-gen models — the gateway `default_model` is often stale).
MODEL_OVERRIDE = {
    "openai": "gpt-5.6-terra",
    "openai-codex": "gpt-5.5",
    "anthropic": "claude-sonnet-5",
    "claude-code": "claude-sonnet-5",
    "gemini": "gemini-3.5-flash",
    # xai / grok-build: gateway default grok-4.5 is current
}

# Default cwd for subscription CLIs when caller omits workspace.
_DEFAULT_BENCH_WORKSPACE = Path.home() / ".cache" / "sy-phase2-bench" / "ws"

# Same keyring service as the daemon (`secrets.SERVICE = "switchbay"`,
# account = provider id). Bench runs outside the daemon, so pull keys
# into the env vars every gateway provider falls back to. Fail-soft: a
# missing key just leaves that provider skippable.
_KEYCHAIN_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "xai": "XAI_API_KEY",
}
_keychain_loaded = False


def load_keychain_keys() -> list[str]:
    """Load switchbay keyring keys into gateway env fallbacks.

    Idempotent; returns the providers loaded this call. Called lazily by
    llm_call so every bench entry point gets keys without env plumbing.
    """
    global _keychain_loaded
    loaded: list[str] = []
    if _keychain_loaded:
        return loaded
    _keychain_loaded = True
    try:
        from switchbay import secrets as sb_secrets
    except Exception:  # noqa: BLE001
        sb_secrets = None  # type: ignore[assignment]
    for provider_id, env_name in _KEYCHAIN_ENV.items():
        if os.environ.get(env_name):
            continue
        key: str | None = None
        if sb_secrets is not None:
            try:
                key = sb_secrets.get(provider_id)
            except Exception:  # noqa: BLE001
                key = None
        if not key:
            try:
                result = subprocess.run(
                    ["security", "find-generic-password",
                     "-s", "switchbay", "-a", provider_id, "-w"],
                    capture_output=True, text=True, timeout=10)
                if result.returncode == 0 and result.stdout.strip():
                    key = result.stdout.strip()
            except (OSError, subprocess.TimeoutExpired):
                pass
        if key:
            os.environ[env_name] = key
            loaded.append(provider_id)
    return loaded


def provider_model(provider_id: str) -> str | None:
    try:
        return llmgateway.get(provider_id).PROVIDER.get("default_model")
    except Exception:
        return None


def resolve_provider(
    provider_id: str,
    *,
    prefer_subscription: bool = True,
    available: list[str] | None = None,
) -> str:
    """Map BYOK ids to subscription CLIs when preferred and available.

    `anthropic` → `claude-code` if claude-code is in `available` (or always
    when available is None and prefer_subscription). Keeps explicit
    `claude-code` / `openai-codex` unchanged.
    """
    if not prefer_subscription:
        return provider_id
    alt = BYOK_TO_SUBSCRIPTION.get(provider_id)
    if not alt:
        return provider_id
    if available is None:
        return alt  # caller will probe; assume subscription preferred
    if alt in available:
        return alt
    return provider_id


def default_workspace() -> str:
    ws = _DEFAULT_BENCH_WORKSPACE
    if not ws.is_dir():
        ws.mkdir(parents=True, exist_ok=True)
    return str(ws.resolve())


def llm_call(
    provider_id: str,
    user: str,
    *,
    system: str | None = None,
    max_tokens: int = 1024,
    model: str | None = None,
    temperature: float = 0.0,
    retries: int = 2,
    workspace: str | None = None,
) -> tuple[str, bool]:
    """Return (text, ok). ok=False on any provider error (missing key,
    credit, quota, network) so callers can skip that judge/generator.

    Subscription CLI providers (claude-code, openai-codex, grok-build)
    always get a workspace cwd — defaulting to the Phase 2 bench cache
    if the caller omits one — so they use Pro/Max / ChatGPT auth rather
    than falling through to API keys.
    """
    load_keychain_keys()
    if provider_id in SUBSCRIPTION_CLI and not workspace:
        workspace = default_workspace()

    async def _run(send_temp: bool = True) -> str:
        prov = llmgateway.get(provider_id)
        kw = dict(
            messages=[{"role": "user", "content": user}],
            system=system,
            model=model or MODEL_OVERRIDE.get(provider_id) or prov.PROVIDER.get("default_model"),
            max_tokens=max_tokens,
        )
        if workspace:
            kw["workspace"] = workspace
        if send_temp:  # newer Claude (sonnet-5, opus-4-8) reject `temperature`
            kw["temperature"] = temperature
        req = base.ChatRequest(**kw)
        out: list[str] = []
        async for ev in prov.chat_stream(req):
            if isinstance(ev, base.TextChunk):
                out.append(ev.text)
        return "".join(out).strip()

    last, send_temp = "", True
    for attempt in range(retries + 1):
        try:
            text = asyncio.run(_run(send_temp))
            if text:
                return text, True
            last = "[empty response]"
        except Exception as e:  # noqa: BLE001
            last = f"[{type(e).__name__}: {e}]"
            if "temperature" in str(e).lower() and send_temp:
                send_temp = False
                continue
            code = getattr(e, "code", "")
            if code in ("missing-key", "auth", "unsupported"):
                break
        time.sleep(1.5 * (attempt + 1))
    return last, False


def available_providers(
    pool: list[str] | None = None,
    *,
    workspace: str | None = None,
) -> list[str]:
    """Probe each provider with a trivial call; return those that answer.

    Subscription CLIs are probed with a workspace so they authenticate via
    the user's login, not a depleted BYOK key.
    """
    ws = workspace or default_workspace()
    ok = []
    for p in (pool or JUDGES):
        # Budget must exceed thinking-model reasoning (gemini-2.5-flash spends
        # tokens on hidden reasoning before emitting) or the probe reads empty.
        text, good = llm_call(
            p, "Reply with the single word: ready.",
            max_tokens=64, workspace=ws if p in SUBSCRIPTION_CLI else None,
        )
        print(f"  {p:12s} {'OK' if good else 'SKIP'}  {text[:40]!r}")
        if good:
            ok.append(p)
    return ok


if __name__ == "__main__":
    print("Probing providers:")
    avail = available_providers()
    print("usable:", avail)
