"""Settings, core-skill status, and okstratr harness routes.

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
import logging
from aiohttp import web
from switchbay import admin_policy
from switchbay import app_settings
from switchbay import ce_viewer_supervisor
from switchbay import cebridge
from switchbay import conversations
from switchbay import core_skills
from switchbay import host_notify
from switchbay import media_settings
from switchbay import okstratr_harness
from switchbay import okstratr_supervisor
from switchbay import statedir
from switchbay.agents import orchestration_policy

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

async def handle_settings_get(request: web.Request) -> web.Response:
    """General app preferences (see app_settings). Read-only mirror of
    settings.json plus a couple of derived, display-only fields."""
    workspace: Path = request.app["workspace"]
    local = app_settings.get_rail_history_local()
    # Which vendor embedding backends are usable right now (have a key),
    # so the Settings UI can offer only the ones that would actually work.
    vendor_keyed = {
        b: conversations._vendor_key(conversations._VENDOR_EMBED[b]["provider"]) is not None
        for b in conversations._VENDOR_EMBED
    }
    media = await asyncio.to_thread(media_settings.status_payload)
    return web.json_response({
        "rail_history_local": local,
        # Where the rail-history DB actually resolves right now, and
        # whether that location is currently a cloud-sync placeholder.
        "rail_history_path": str(statedir.conversations_db(workspace, local=local)),
        "workspace_synced": statedir.sync_service_hint(workspace),
        "embedding_backend": app_settings.get_embedding_backend(),
        "embedding_vendors_keyed": vendor_keyed,
        "media": media,
        "orchestration_preference": orchestration_policy.get_preference(),
        "orchestration_denied_models": orchestration_policy.get_denied_models(workspace),
        **_daemon_ns._desk_live_view(workspace),
        "proxied_skill_embeds": app_settings.get_proxied_skill_embeds(),
        # The Graph tab is CE's viewer through /embed/ce. Without a CE
        # install the shell hides it; Files, RAG, Agents keep working.
        "ce_graph": cebridge.graph_availability(workspace),
    })

async def handle_settings_post(request: web.Request) -> web.Response:
    """Update app preferences (rail history, embeddings, media)."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    workspace: Path = request.app["workspace"]
    if "rail_history_local" in body:
        want = bool(body["rail_history_local"])
        had = app_settings.get_rail_history_local()
        app_settings.set_rail_history_local(want)
        if want != had:
            # Move the active workspace's DB to the new location off the
            # event loop — the file may be on a slow sync service. Other
            # workspaces migrate lazily on their next activation.
            try:
                await asyncio.to_thread(
                    statedir.migrate_conversations_db, workspace, local=want
                )
            except Exception:  # noqa: BLE001
                log.exception("rail-history relocation failed for %s", workspace)
    if "orchestration_preference" in body:
        orchestration_policy.set_preference(body["orchestration_preference"])
    if "desk_max_live_workers" in body:
        try:
            app_settings.set_desk_max_live_workers(int(body["desk_max_live_workers"]))
        except (TypeError, ValueError) as e:
            return web.json_response({"error": str(e)}, status=400)
    if "orchestration_denied_models" in body:
        raw = body["orchestration_denied_models"]
        if raw is None:
            orchestration_policy.set_denied_models([], workspace=workspace)
        elif isinstance(raw, list):
            orchestration_policy.set_denied_models(
                [str(x) for x in raw], workspace=workspace,
            )
        else:
            return web.json_response(
                {"error": "orchestration_denied_models must be a list"},
                status=400,
            )
    if "embedding_backend" in body:
        try:
            app_settings.set_embedding_backend(str(body["embedding_backend"]))
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        # Re-select the backend on next use; the drain's reconcile then
        # rebuilds the index if the vector space changed.
        conversations.reset_embedder()
    if "proxied_skill_embeds" in body:
        want = bool(body["proxied_skill_embeds"])
        had = app_settings.get_proxied_skill_embeds()
        app_settings.set_proxied_skill_embeds(want)
        # Proxied flag only switches Graph/Agents UI panels. Core skills
        # (CE + okstratr) stay supervised either way (Ben lock / C1).
        if want and not had:
            async def _kick() -> None:
                ce_out = await asyncio.to_thread(
                    ce_viewer_supervisor.start, workspace,
                )
                oks_out = await asyncio.to_thread(
                    okstratr_supervisor.start, workspace,
                )
                log.info("core skills kick via settings: ce=%s oks=%s", ce_out, oks_out)
            asyncio.create_task(_kick())
    # Media: { media: { image?: {provider, model}|null, video?: …, voice?: … } }
    if "media" in body and isinstance(body["media"], dict):
        if not admin_policy.feature_enabled("media_generation"):
            return web.json_response(
                {"error": admin_policy.feature_error("media_generation")},
                status=403,
            )
        for modality, rec in body["media"].items():
            if modality not in media_settings.MODALITIES:
                return web.json_response(
                    {"error": f"unknown media modality {modality!r}"},
                    status=400,
                )
            try:
                if rec is None or rec is False:
                    await asyncio.to_thread(
                        media_settings.set_choice, modality, provider=None,
                    )
                elif isinstance(rec, dict):
                    await asyncio.to_thread(
                        media_settings.set_choice,
                        modality,
                        provider=str(rec.get("provider") or "") or None,
                        model=str(rec.get("model") or "") or None,
                    )
                else:
                    return web.json_response(
                        {"error": f"media.{modality} must be object or null"},
                        status=400,
                    )
            except ValueError as e:
                return web.json_response({"error": str(e)}, status=400)
    return await handle_settings_get(request)

async def handle_core_skills_status(request: web.Request) -> web.Response:
    """C1 shared status: CE + okstratr + wiki_build."""
    workspace: Path = request.app["workspace"]
    return web.json_response(core_skills.status(workspace))

async def handle_okstratr_host_notify(request: web.Request) -> web.Response:
    """C2 path-native notify: okstratr → Switchbay rail (protocol.notice)."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"ok": False, "error": "invalid json"}, status=400)
    result = await host_notify.apply_host_notify(request.app, body)
    status = 200 if result.get("ok") else 400
    return web.json_response(result, status=status)

async def handle_okstratr_harness_get(request: web.Request) -> web.Response:
    """Thin client: GET okstratr harness registry (SSOT). No Switchbay allowlist."""
    try:
        data = await okstratr_harness.list_harnesses(request.app)
    except okstratr_harness.OkstratrHarnessError as e:
        return okstratr_harness.error_response(e)
    return web.json_response(data)

async def handle_okstratr_harness_enable(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"ok": False, "error": "invalid json"}, status=400)
    hid = str((body or {}).get("id") or (body or {}).get("harness") or "").strip()
    try:
        data = await okstratr_harness.enable_harness(hid, app=request.app)
    except okstratr_harness.OkstratrHarnessError as e:
        return okstratr_harness.error_response(e)
    return web.json_response(data)

async def handle_okstratr_harness_disable(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"ok": False, "error": "invalid json"}, status=400)
    hid = str((body or {}).get("id") or (body or {}).get("harness") or "").strip()
    try:
        data = await okstratr_harness.disable_harness(hid, app=request.app)
    except okstratr_harness.OkstratrHarnessError as e:
        return okstratr_harness.error_response(e)
    return web.json_response(data)

async def handle_okstratr_harness_set(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"ok": False, "error": "invalid json"}, status=400)
    key = str((body or {}).get("key") or "").strip()
    value = (body or {}).get("value")
    if value is None:
        value = ""
    try:
        data = await okstratr_harness.set_harness_value(
            key, str(value), app=request.app
        )
    except okstratr_harness.OkstratrHarnessError as e:
        return okstratr_harness.error_response(e)
    return web.json_response(data)

async def handle_okstratr_harness_reload(request: web.Request) -> web.Response:
    try:
        data = await okstratr_harness.reload_harnesses(request.app)
    except okstratr_harness.OkstratrHarnessError as e:
        return okstratr_harness.error_response(e)
    return web.json_response(data)

async def handle_orchestration_policy_get(request: web.Request) -> web.Response:
    """Inspectable Auto-orchestration policy + hard bounds. No secrets.

    Scoped to the focused workspace — each vault has its own recipe
    weights. Priors fill in until that desk has outcomes.
    """
    workspace: Path = request.app["workspace"]
    return web.json_response(orchestration_policy.inspect_state(workspace))

async def handle_orchestration_models_get(request: web.Request) -> web.Response:
    """Catalog the chief of staff may draw from, plus the denylist.

    Runs off the event loop: listing keyed providers can walk a large
    Hugging Face cache (MLX/llama.cpp ``has_key``).
    """
    workspace: Path = request.app["workspace"]

    def _payload() -> dict:
        return {
            "models": orchestration_policy.list_orchestrator_catalog(
                workspace=workspace,
            ),
            "denied": orchestration_policy.get_denied_models(workspace),
            "preference": orchestration_policy.get_preference(),
            "workspace": str(workspace),
        }

    return web.json_response(await asyncio.to_thread(_payload))

async def handle_orchestration_models_post(request: web.Request) -> web.Response:
    """Update the chief-of-staff model allowlist for the active workspace.

    Body: ``{key, allowed}`` toggles one catalog row,
    ``{provider, allowed: false}`` unchecks that provider,
    or ``{denied: ["provider/model", ...]}`` replaces the denylist.
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    workspace: Path = request.app["workspace"]
    if "denied" in body:
        raw = body.get("denied")
        if raw is None:
            pass
        elif not isinstance(raw, list):
            return web.json_response({"error": "denied must be a list"}, status=400)
    elif "provider" in body:
        pid = str(body.get("provider") or "").strip()
        if not pid:
            return web.json_response({"error": "provider required"}, status=400)
    elif "key" in body:
        key = str(body.get("key") or "").strip()
        if not key:
            return web.json_response({"error": "key required"}, status=400)
    else:
        return web.json_response(
            {"error": "expected {key, allowed}, {provider, allowed}, or {denied}"},
            status=400,
        )

    def _apply() -> dict:
        if "denied" in body:
            raw = body.get("denied")
            orchestration_policy.set_denied_models(
                [] if raw is None else [str(x) for x in raw],
                workspace=workspace,
            )
        elif "provider" in body:
            pid = str(body.get("provider") or "").strip()
            if body.get("allowed"):
                catalog = orchestration_policy.list_orchestrator_catalog(
                    workspace=workspace,
                )
                denied = [
                    str(row.get("key") or "")
                    for row in catalog
                    if str(row.get("provider") or "") != pid
                    and not row.get("allowed")
                    and row.get("key")
                ]
                orchestration_policy.set_denied_models(denied, workspace=workspace)
            else:
                orchestration_policy.deny_provider(pid, workspace=workspace)
        else:
            orchestration_policy.set_model_allowed(
                str(body.get("key") or "").strip(),
                bool(body.get("allowed")),
                workspace=workspace,
            )
        return {
            "ok": True,
            "models": orchestration_policy.list_orchestrator_catalog(
                workspace=workspace,
            ),
            "denied": orchestration_policy.get_denied_models(workspace),
            "preference": orchestration_policy.get_preference(),
            "workspace": str(workspace),
        }

    return web.json_response(await asyncio.to_thread(_apply))
