"""Reasoning-effort policy and the effort slash command.

Split out of switchbay.daemon so this concept has its own module.
The daemon re-exports every name; tests that monkeypatch
switchbay.daemon still apply, because patched helpers are read
back through _daemon_ns at call time.

Run: python -m switchbay serve --workspace PATH
"""
from __future__ import annotations

from pathlib import Path
import asyncio
import json
from aiohttp import web
from switchbay import llm_config
from switchbay import llmgateway
from switchbay import modestore
from switchbay import protocol
from switchbay import routing_status

from switchbay.httpapi._ns import _daemon_ns

def _effort_for(
    provider_id: str, model: str | None, lane: str = "background",
    *,
    rung: str | None = None,
    workspace: Path | None = None,
    rung_effort: str | None = None,
) -> str | None:
    """Reasoning effort for a dispatch — see `routing_status.effort_for`.

    Thin wrapper that supplies the daemon's notion of the current picker
    provider (which falls back to a configured default when the user has
    never chosen one). Pass `rung` + `workspace` (or `rung_effort`) so
    a ladder row's own effort wins over the pair default.
    """
    if rung_effort is None and rung and workspace is not None:
        rung_effort = modestore.rung_effort(workspace, rung)
    return routing_status.effort_for(
        provider_id, model, lane,
        picker_provider=_daemon_ns._resolve_default_provider(),
        rung_effort=rung_effort,
    )

async def _handle_effort_slash(
    app: web.Application, ws: web.WebSocketResponse, args: str,
) -> None:
    """`/effort [level|auto]` — read or set the current model's effort.

    Same store the rail's corner control reads, so the two never
    disagree. Bare `/effort` lists what THIS model accepts, because the
    options are per model and guessing is what we're trying to avoid.
    """
    pid = _daemon_ns._resolve_default_provider()
    model = llm_config.get_model(pid)
    if model is None:
        try:
            model = str(
                llmgateway.get(pid).PROVIDER.get("default_model") or "") or None
        except llmgateway.ProviderError:
            model = None

    opts = await asyncio.to_thread(llmgateway.reasoning_options, pid, model)
    label = f"{pid} · {model}" if model else pid
    if not opts:
        await ws.send_json(protocol.notice(
            f"{label} has no reasoning-effort setting — nothing to change. "
            "Models that do: Anthropic, Gemini, OpenAI o-series/gpt-5, "
            "xAI reasoning models, and the local backends.",
            kind="slash",
        ))
        return

    ids = [str(o["id"]) for o in opts]
    arg = (args or "").strip().lower()
    current = routing_status.effort_for(pid, model, "rail", picker_provider=pid)

    if not arg or arg in ("status", "show", "?"):
        lines = ", ".join(
            f"**{i}**" if i == current else i for i in ids)
        await ws.send_json(protocol.notice(
            f"reasoning effort · {label} — currently "
            f"{current or 'provider default'}. Options: {lines}, auto. "
            f"Set with `/effort <level>`.",
            kind="slash",
        ))
        return

    if arg in ("auto", "default", "clear", "off-setting", "unset"):
        await asyncio.to_thread(llm_config.set_reasoning_effort, pid, model, None)
        await _daemon_ns._broadcast(app, protocol.custom({
            "type": "reasoning_effort",
            "provider": pid, "model": model, "effort": None,
        }))
        await ws.send_json(protocol.notice(
            f"reasoning effort cleared for {label} — using the provider default.",
            kind="slash",
        ))
        return

    if arg not in ids:
        await ws.send_json(protocol.notice(
            f"{label} doesn't offer effort {arg!r}. Options: "
            f"{', '.join(ids)}, auto.",
            kind="slash",
        ))
        return

    await asyncio.to_thread(llm_config.set_reasoning_effort, pid, model, arg)
    await _daemon_ns._broadcast(app, protocol.custom({
        "type": "reasoning_effort",
        "provider": pid, "model": model, "effort": arg,
    }))
    hint = next((str(o.get("hint") or "") for o in opts if o["id"] == arg), "")
    await ws.send_json(protocol.notice(
        f"reasoning effort → **{arg}** for {label}"
        + (f" ({hint})" if hint else "") + ".",
        kind="slash",
    ))

async def handle_reasoning_options(request: web.Request) -> web.Response:
    """What reasoning efforts THIS provider+model accepts, plus the
    user's current pick.

    Query: ?provider=<id>&model=<id>. Both default to the rail picker's
    current selection so the rail control can call it bare.
    """
    q = request.rel_url.query
    pid = (q.get("provider") or "").strip() or _daemon_ns._resolve_default_provider()
    model = (q.get("model") or "").strip() or None
    if model is None:
        try:
            model = llm_config.get_model(pid) or str(
                llmgateway.get(pid).PROVIDER.get("default_model") or "") or None
        except llmgateway.ProviderError:
            model = None
    options = await asyncio.to_thread(llmgateway.reasoning_options, pid, model)
    return web.json_response({
        "provider": pid,
        "model": model,
        "options": options,
        "selected": _daemon_ns._effort_for(pid, model),
    })

async def handle_reasoning_effort_set(request: web.Request) -> web.Response:
    """Persist a reasoning effort. Body: {provider?, model?, effort}.

    `effort: null` clears it (back to the provider's own default). An id
    the provider doesn't advertise for that model is refused rather than
    stored — the UI renders from the same list, so a rejection here means
    a stale client.
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}
    pid = str((body or {}).get("provider") or "").strip() or _daemon_ns._resolve_default_provider()
    model = str((body or {}).get("model") or "").strip() or None
    raw = (body or {}).get("effort")
    effort = str(raw).strip() if isinstance(raw, str) and raw.strip() else None

    if model is None:
        try:
            model = llm_config.get_model(pid) or str(
                llmgateway.get(pid).PROVIDER.get("default_model") or "") or None
        except llmgateway.ProviderError:
            model = None

    if effort is not None:
        opts = await asyncio.to_thread(llmgateway.reasoning_options, pid, model)
        if not llmgateway.base.coerce_effort(effort, opts):
            return web.json_response({
                "error": (
                    f"{pid}/{model} doesn't offer reasoning effort "
                    f"{effort!r}"
                ),
                "options": opts,
            }, status=400)

    await asyncio.to_thread(
        llm_config.set_reasoning_effort, pid, model, effort)
    await _daemon_ns._broadcast(request.app, protocol.custom({
        "type": "reasoning_effort",
        "provider": pid, "model": model, "effort": effort,
    }))
    return web.json_response({
        "ok": True, "provider": pid, "model": model, "effort": effort,
    })

async def handle_reasoning_policy(request: web.Request) -> web.Response:
    """Per-lane fallback policy — what a lane does when the model it
    resolved to carries no effort of its own.

    GET  → {lanes: {lane: policy}}
    POST → {lane, policy}  ("inherit" | "default" | an effort id)

    Lanes: `rail` (the corner picker), `micro` (micro-edits), `ladder`
    (CE / routed work — inherits its rung's model, so setting the rung's
    effort is usually what you want), `background` (titles, triage).
    """
    if request.method == "GET":
        lanes = {
            lane: await asyncio.to_thread(llm_config.get_reasoning_policy, lane)
            for lane in llm_config.LANES
        }
        return web.json_response({
            "lanes": lanes,
            "inherit": llm_config.POLICY_INHERIT,
            "default": llm_config.POLICY_DEFAULT,
        })
    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}
    lane = str((body or {}).get("lane") or "").strip()
    raw = (body or {}).get("policy")
    policy = str(raw).strip() if isinstance(raw, str) and raw.strip() else None
    if lane not in llm_config.LANES:
        return web.json_response(
            {"error": f"unknown lane {lane!r}", "lanes": list(llm_config.LANES)},
            status=400)
    try:
        await asyncio.to_thread(llm_config.set_reasoning_policy, lane, policy)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({
        "ok": True, "lane": lane,
        "policy": await asyncio.to_thread(llm_config.get_reasoning_policy, lane),
    })
