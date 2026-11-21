"""Provider selection, keys, and one-shot JSON helpers.

Split out of switchbay.daemon so this concept has its own module.
The daemon re-exports every name; tests that monkeypatch
switchbay.daemon still apply, because patched helpers are read
back through _daemon_ns at call time.

Run: python -m switchbay serve --workspace PATH
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import asyncio
import json
import logging
import uuid
from aiohttp import web
from switchbay import admin_policy
from switchbay import llm_config
from switchbay import llmgateway
from switchbay import micro_edits
from switchbay import model_cache
from switchbay import protocol
from switchbay import routing_status
from switchbay import secrets

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

# ── LLM gateway endpoints ────────────────────────────────────────────


def _resolve_default_provider() -> str:
    """User-set default if one is saved, else the first provider that
    has a configured key, else the gateway's static default."""
    saved = llm_config.get_default_provider()
    if (
        saved and saved in llmgateway.PROVIDERS
        and admin_policy.provider_allowed(saved)
    ):
        return saved
    for pid, provider in llmgateway.PROVIDERS.items():
        if not admin_policy.provider_allowed(pid):
            continue
        if provider.has_key():
            return pid
    return llmgateway.default_provider_id()

def _policy_block(feature: str) -> web.Response | None:
    if admin_policy.feature_enabled(feature):
        return None
    return web.json_response(
        {"ok": False, "error": admin_policy.feature_error(feature)},
        status=403,
    )

async def _offer_provider_retry(
    app: web.Application,
    text: str,
    *,
    thread_id: str | None,
    workspace: Path,
    failed_pid: str,
    err: llmgateway.ProviderError,
) -> bool:
    """When a run dies on a transient/capacity/billing error and OTHER
    keyed providers are idle, offer a one-click retry on one of them
    (audit #12). Returns True iff a card was broadcast. The user stays in
    control of cost/privacy — we never silently switch vendors."""
    retryable = bool(getattr(err, "retryable", False)) or err.code in _daemon_ns._RETRYABLE_CODES
    msg = str(err).lower()
    if not retryable and not any(h in msg for h in _daemon_ns._BILLING_HINTS):
        return False
    alternatives = [
        {"id": pid, "label": prov.LABEL}
        for pid, prov in llmgateway.PROVIDERS.items()
        if pid != failed_pid and prov.has_key()
    ]
    if not alternatives:
        return False
    try:
        failed_label = llmgateway.get(failed_pid).LABEL
    except llmgateway.ProviderError:
        failed_label = failed_pid
    rid = f"retry-{uuid.uuid4().hex[:8]}"
    app.setdefault("provider_retries", {})[rid] = {
        "text": text, "thread_id": thread_id, "workspace": str(workspace),
    }
    await _daemon_ns._broadcast(app, protocol.custom({
        "type": "provider_retry_offer",
        "id": rid,
        "failed_provider": failed_pid,
        "failed_label": failed_label,
        "code": err.code,
        "message": str(err),
        "alternatives": alternatives,
    }))
    return True

def _effective_model(pid: str) -> str:
    """Model the daemon will send to `pid` for the next chat: user
    pick (llm_config) if set, else the provider's static default."""
    user = llm_config.get_model(pid)
    if user:
        return user
    try:
        provider = llmgateway.get(pid)
    except llmgateway.ProviderError:
        return ""
    return str(provider.PROVIDER.get("default_model", ""))

async def _oneshot_json(
    provider: Any, model: str | None, prompt: str, workspace: Path,
    *, max_tokens: int = 512,
) -> dict[str, Any] | None:
    """Single non-streaming-to-the-user LLM call that returns parsed
    JSON. Collects the streamed text, extracts the first JSON object,
    and parses it. Returns None on any failure. Used by cheap
    classifier/explainer paths (not the rail loop)."""
    # Provider modules expose ID / PROVIDER["id"]; derive here so
    # callers need not pass pid (several call sites have no pid in scope).
    pid = str(getattr(provider, "ID", "") or "")
    if not pid:
        prov_meta = getattr(provider, "PROVIDER", None)
        if isinstance(prov_meta, dict):
            pid = str(prov_meta.get("id") or "")
    req = llmgateway.ChatRequest(
        messages=[{"role": "user", "content": prompt}],
        model=model, max_tokens=max_tokens, workspace=str(workspace),
        reasoning_effort=_daemon_ns._effort_for(pid, model, "background") if pid else None,
    )
    text = ""
    async for ev in provider.chat_stream(req):
        if isinstance(ev, llmgateway.TextChunk):
            text += ev.text
        elif isinstance(ev, llmgateway.DoneChunk):
            break
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None

async def handle_llm_providers(request: web.Request) -> web.Response:
    # has_key() for local backends can walk a large HF cache — keep it
    # off the event loop so the Agent Dashboard does not freeze.
    providers = await asyncio.to_thread(llmgateway.list_providers)
    # Available providers must show a live model list (Settings and
    # the rail picker share this payload). Await a refresh when the
    # cache is stale so the first open after a new-Mac install isn't
    # a 24h-stale suggestion list. Unavailable providers stay cheap.
    stale = [
        p["id"] for p in providers
        if p.get("has_key") and not model_cache.get_cached(p["id"])[1]
    ]
    if stale:
        await asyncio.gather(
            *(model_cache.refresh(pid) for pid in stale),
            return_exceptions=True,
        )
    for p in providers:
        pid = p["id"]
        p["chosen_model"] = llm_config.get_model(pid)
        models, fresh = model_cache.get_cached(pid)
        p["models"] = models
        p["models_fresh"] = fresh
        if not fresh:
            model_cache.kick_background_refresh(pid)
    current = _daemon_ns._resolve_default_provider()
    default_model = _daemon_ns._effective_model(current)
    # Effective routing: CE actions + micro-edits may deliberately run
    # on a different rung than the headline default. Surface any such
    # override (+ weak-model-with-destructive-scope warnings) so the
    # picker shows what actually runs, not just what's selected.
    try:
        routing = routing_status.compute(
            request.app["workspace"], current, default_model,
        )
    except Exception:  # noqa: BLE001
        log.exception("routing_status.compute failed")
        routing = None
    from switchbay.kernel.harness_pi import pi_binary
    from switchbay.kernel.harness import pi_harness_permitted
    from switchbay import playwright_cli
    pi_bin = pi_binary()
    admin_pi = admin_policy.feature_enabled("pi_harness")
    user_pi = llm_config.get_pi_harness()
    return web.json_response({
        "providers": providers,
        "keychain_available": secrets.available(),
        "keychain_backend": secrets.backend_name(),
        "default_provider": current,
        "default_model": default_model,
        "routing": routing,
        "policy": admin_policy.public_view(),
        "browser": playwright_cli.status_view(),
        "harness": {
            "pi": {
                "admin_allowed": admin_pi,
                "user_enabled": user_pi,
                "installed": pi_bin is not None,
                "binary": pi_bin,
                "used": bool(admin_pi and user_pi and pi_bin),
                "permitted": pi_harness_permitted(),
            },
        },
    })

async def handle_llm_harness(request: web.Request) -> web.Response:
    """User toggles for the Pi harness and the local browser.

    Admin policy can still deny either one. The body may set ``pi``,
    ``browser``, or both.
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    if "pi" not in body and "browser" not in body:
        return web.json_response(
            {"error": "expected {pi: bool} or {browser: bool}"},
            status=400,
        )
    if "pi" in body and not admin_policy.feature_enabled("pi_harness"):
        return web.json_response(
            {"error": admin_policy.feature_error("pi_harness")},
            status=403,
        )
    if "browser" in body and not admin_policy.feature_enabled("browser_use"):
        return web.json_response(
            {"error": admin_policy.feature_error("browser_use")},
            status=403,
        )
    out: dict[str, Any] = {"ok": True}
    if "pi" in body:
        llm_config.set_pi_harness(bool(body.get("pi")))
        from switchbay.kernel.harness_pi import pi_binary
        from switchbay.kernel.harness import pi_harness_permitted
        out["pi"] = {
            "admin_allowed": True,
            "user_enabled": llm_config.get_pi_harness(),
            "installed": pi_binary() is not None,
            "used": pi_harness_permitted() and pi_binary() is not None,
        }
    if "browser" in body:
        llm_config.set_browser_use(bool(body.get("browser")))
        from switchbay import playwright_cli
        out["browser"] = playwright_cli.status_view()
    return web.json_response(out)

async def handle_llm_set_default(request: web.Request) -> web.Response:
    """Set the default provider, the model to use with the current
    default, or both. The body may include either `provider`, `model`,
    or both. `model: null` clears the per-provider override and falls
    back to the provider's static default."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)

    pid = body.get("provider")
    if pid is not None:
        pid = str(pid)
        if pid not in llmgateway.PROVIDERS:
            return web.json_response(
                {"error": f"unknown provider: {pid}"}, status=400,
            )
        if not admin_policy.provider_allowed(pid):
            return web.json_response(
                {"error": f"provider disabled by admin policy: {pid}"},
                status=403,
            )
        if not llmgateway.get(pid).has_key():
            return web.json_response(
                {"error": "cannot set default to a provider with no key configured"},
                status=400,
            )
        llm_config.set_default_provider(pid)
        # Seed missing ladder rungs for new users (micro-edits use trivial).
        try:
            micro_edits.ensure_ladder_defaults(pid)
        except Exception:  # noqa: BLE001
            log.exception("ensure_ladder_defaults failed for %s", pid)

    if "model" in body:
        # Targets the provider just set, or the current default if no
        # provider was supplied. Keeps the picker UI a single round-trip.
        target = pid or _daemon_ns._resolve_default_provider()
        model = body.get("model")
        force = bool(body.get("force"))
        if model is None or model == "":
            llm_config.set_model(target, None)
        elif isinstance(model, str):
            if not force:
                allowed, fresh = model_cache.get_cached(target)
                try:
                    prov = llmgateway.get(target)
                    static = list(prov.PROVIDER.get("model_suggestions") or [])
                    default_m = str(prov.PROVIDER.get("default_model") or "")
                except Exception:  # noqa: BLE001
                    static, default_m = [], ""
                known = set(allowed or []) | set(static)
                if default_m:
                    known.add(default_m)
                # Only reject when we have a non-empty known set; empty
                # means offline/unfetched — don't trap the user.
                if known and model not in known:
                    return web.json_response({
                        "error": (
                            f"unknown model {model!r} for {target}. "
                            "Pick from the list, or pass force:true to pin it."
                        ),
                        "known": sorted(known)[:40],
                    }, status=400)
            llm_config.set_model(target, model)
        else:
            return web.json_response(
                {"error": "model must be a string or null"}, status=400,
            )

    current = _daemon_ns._resolve_default_provider()
    try:
        micro_edits.ensure_ladder_defaults(current)
    except Exception:  # noqa: BLE001
        pass
    return web.json_response({
        "ok": True,
        "default_provider": current,
        "model": _daemon_ns._effective_model(current),
    })

async def handle_llm_set_key(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    pid = str(body.get("provider", ""))
    key = str(body.get("key", ""))
    if pid not in llmgateway.PROVIDERS:
        return web.json_response({"error": f"unknown provider: {pid}"}, status=400)
    if not key.strip():
        return web.json_response({"error": "key is empty"}, status=400)
    if not secrets.set_key(pid, key.strip()):
        return web.json_response(
            {"error": "OS keychain unavailable; cannot persist key"}, status=500
        )
    try:
        micro_edits.ensure_ladder_defaults(pid)
    except Exception:  # noqa: BLE001
        log.exception("ensure_ladder_defaults after key set")
    return web.json_response({"ok": True})

async def handle_llm_delete_key(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    pid = str(body.get("provider", ""))
    if pid not in llmgateway.PROVIDERS:
        return web.json_response({"error": f"unknown provider: {pid}"}, status=400)
    secrets.delete_key(pid)
    return web.json_response({"ok": True})

async def handle_llm_refresh_models(request: web.Request) -> web.Response:
    """Force a re-query of one provider's model list — for the Settings
    UI's "Refresh" button. Returns the fresh list immediately. Pass
    `provider` in the body, or omit for all providers in parallel."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}
    pid = body.get("provider") if isinstance(body, dict) else None
    if pid:
        models = await model_cache.refresh(str(pid))
        return web.json_response({"ok": True, "provider": pid, "models": models})
    out: dict[str, list[str]] = {}
    for known in llmgateway.PROVIDERS.keys():
        out[known] = await model_cache.refresh(known)
    return web.json_response({"ok": True, "models": out})
