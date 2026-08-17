"""Per-provider model-list cache with daily TTL.

Hardcoded model_suggestions drift out of date — providers add and
retire models faster than we ship. This module caches each provider's
*live* model list (queried via the provider's own API) so the picker
shows what's actually available to the user. Cache TTL defaults to
24h; the daemon's `/api/llm/providers` endpoint kicks off background
refreshes when a cached entry is stale.

Usage:
    models = await model_cache.get(pid)         # cached or live
    await model_cache.refresh(pid)              # force re-query

Providers opt in by exposing `async list_models() -> list[str]`. If
absent, we fall back to PROVIDER['model_suggestions']. Errors during
a live query are swallowed (logged, not raised) — the user always
sees *some* list.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from . import llmgateway

log = logging.getLogger("switchbay.model_cache")

DEFAULT_TTL_SECONDS = 24 * 60 * 60  # 24h
# Local model lists change when the user pulls/deletes weights.
# A daily cache made the rail picker show stale llama.cpp / Ollama /
# MLX suggestions while Settings (live /api/local-models) was right.
LOCAL_TTL_SECONDS = 30
LOCAL_PROVIDER_IDS = frozenset({"mlx", "llamacpp", "ollama"})


def _ttl_for(pid: str) -> float:
    return LOCAL_TTL_SECONDS if pid in LOCAL_PROVIDER_IDS else DEFAULT_TTL_SECONDS

# pid → (fetched_at, models). Empty list when the provider opts out
# (no list_models). None until first successful fetch.
_CACHE: dict[str, tuple[float, list[str]]] = {}
# pid → in-flight refresh task. Lets us de-dupe concurrent refreshes.
_INFLIGHT: dict[str, asyncio.Task[Any]] = {}


def _static_fallback(pid: str) -> list[str]:
    try:
        provider = llmgateway.get(pid)
    except llmgateway.ProviderError:
        return []
    return list(provider.PROVIDER.get("model_suggestions") or [])


async def _fetch(pid: str) -> list[str]:
    """Run the provider's `list_models` if it has one. Returns the
    static fallback on any error so callers always get a list."""
    try:
        provider = llmgateway.get(pid)
    except llmgateway.ProviderError:
        return _static_fallback(pid)
    fn = getattr(provider, "list_models", None)
    if fn is None:
        return _static_fallback(pid)
    try:
        models = await fn()
    except Exception as e:  # noqa: BLE001
        log.warning("list_models(%s) failed: %s — falling back", pid, e)
        return _static_fallback(pid)
    if not isinstance(models, list) or not models:
        # Empty live list is truthful for local backends (nothing
        # installed). Cloud providers fall back to suggestions.
        if pid in LOCAL_PROVIDER_IDS:
            return []
        return _static_fallback(pid)
    return [str(m) for m in models]


def get_cached(pid: str) -> tuple[list[str], bool]:
    """Synchronous read. Returns (models, is_fresh). Models can be the
    static fallback when nothing has been cached yet. `is_fresh`
    indicates whether the cache is within TTL."""
    entry = _CACHE.get(pid)
    if entry is None:
        return _static_fallback(pid), False
    fetched_at, models = entry
    fresh = time.time() - fetched_at < _ttl_for(pid)
    return list(models), fresh


async def refresh(pid: str) -> list[str]:
    """Force a re-query for `pid`. De-dupes concurrent calls — multiple
    callers asking at once share the same in-flight task."""
    inflight = _INFLIGHT.get(pid)
    if inflight is not None and not inflight.done():
        return await inflight
    task = asyncio.create_task(_fetch(pid))
    _INFLIGHT[pid] = task
    try:
        models = await task
    finally:
        _INFLIGHT.pop(pid, None)
    _CACHE[pid] = (time.time(), models)
    return models


async def get(pid: str) -> list[str]:
    """Return cached models if fresh, else refresh and return."""
    models, fresh = get_cached(pid)
    if fresh:
        return models
    return await refresh(pid)


def kick_background_refresh(pid: str, *, loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Fire-and-forget refresh for stale entries. Used by the providers
    endpoint so the UI gets the cached value immediately while the
    background task updates it for next time."""
    if pid in _INFLIGHT:
        return
    runner = loop or asyncio.get_event_loop()
    runner.create_task(refresh(pid))


async def warm_all(provider_ids: list[str]) -> None:
    """Refresh every listed provider in parallel. Called at daemon
    startup so the very first /api/llm/providers fetch already has
    fresh data."""
    await asyncio.gather(
        *(refresh(pid) for pid in provider_ids), return_exceptions=True,
    )
