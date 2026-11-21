"""Comms curation routing and ingest into the wiki.

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
import time
import uuid
from aiohttp import web
from switchbay import admin_policy
from switchbay import llmgateway
from switchbay import modestore
from switchbay import protocol
from switchbay import streams

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

def _comms_curation_pair_ok(
    pid: str | None,
    model: str | None,
    *,
    denied: list[str] | tuple[str, ...] | set[str] | None,
) -> bool:
    """Keyed, allowlisted, file-capable CLI (shell + file_write).

    Direct Comms curation calls ``chat_stream`` with no tools / ToolUse
    loop, so HTTP ``can_curate`` (tools-only) providers cannot write.
    Grok Build qualifies via ``can_execute``.
    """
    from switchbay.agents import orchestration_policy as orch_pol
    if not pid:
        return False
    if not admin_policy.provider_allowed(pid):
        return False
    if not orch_pol.model_allowed(pid, model, denied):
        return False
    try:
        provider = llmgateway.get(pid)
    except llmgateway.ProviderError:
        return False
    try:
        keyed = bool(provider.has_key())
    except Exception:  # noqa: BLE001
        keyed = False
    if not keyed:
        return False
    return bool(llmgateway.can_execute(pid))

def _comms_curation_route(workspace: Path | None) -> tuple[str | None, str | None]:
    """File-capable CLI routing (can_execute), plus model allowlists.

    Direct Comms curation has no ToolUse loop, so HTTP tools-only
    providers are skipped. Does not add a second source-approval
    prompt: Comms sources are already explicitly approved.
    """
    from switchbay.agents import orchestration_policy as orch_pol
    ws = Path(workspace) if workspace is not None else None
    denied = orch_pol.get_denied_models(ws) if ws is not None else orch_pol.get_denied_models()
    candidates: list[tuple[str | None, str | None]] = []
    if ws is not None:
        try:
            candidates.append(_daemon_ns._ce_action_provider(ws))
        except Exception:  # noqa: BLE001
            log.exception("comms curator CE-action route failed")
        try:
            hint_pid, hint_model = _daemon_ns._auto_roster_pair(ws)
            picked = orch_pol.pick_chief_pair(
                default_provider=hint_pid,
                default_model=hint_model,
                preference=orch_pol.get_preference(),
                workspace=ws,
            )
            candidates.append(picked)
        except Exception:  # noqa: BLE001
            log.exception("comms curator roster route failed")
    for pid, prov in llmgateway.PROVIDERS.items():
        try:
            keyed = bool(prov.has_key())
        except Exception:  # noqa: BLE001
            keyed = False
        if keyed:
            candidates.append((pid, _daemon_ns._effective_model(pid)))
    seen: set[tuple[str, str | None]] = set()
    for pid, model in candidates:
        if not pid:
            continue
        key = (pid, model)
        if key in seen:
            continue
        seen.add(key)
        if _comms_curation_pair_ok(pid, model, denied=denied):
            return pid, model
    return None, None

def _comms_user_ingest_error(raw: str | None) -> str:
    """Short user-facing ingest failure. No implementation details."""
    low = str(raw or "").lower()
    if not low.strip():
        return "Could not add this to the wiki. It stays approved."
    if "revok" in low:
        return "This source was revoked before it could be added."
    if "comms_streams" in low or "disabled by admin" in low:
        return "Comms ingestion is turned off by policy."
    if "allowlist" in low:
        return "This workspace is not allowed for the account."
    if "no wiki commit" in low or "produced no wiki" in low:
        return "Nothing new was added to the wiki. It stays queued."
    if "provider" in low or "configured" in low or "curator" in low or "file-capable" in low:
        return "No file-capable curator is available for this workspace."
    if "retrieve" in low or "fetch" in low or "not connected" in low:
        return "Could not retrieve the approved mail. It stays approved."
    return "Could not add this to the wiki. It stays approved."

async def _triage_events(
    app: web.Application, acct: dict[str, Any], events: list[dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], list[str]] | None:
    """Smart routing + relevance filter in ONE classifier call
    (trivial rung, un-logged like the titler / purge matcher).
    Returns ({workspace_path: its events}, skipped_event_ids) — the
    skip bin is discarded uncurated, which is the first line against
    irrelevant wiki entries. None = triage unavailable (no key /
    provider error) — the caller leaves the messages PENDING rather
    than guessing a route (no privileged workspace to fall back on)."""
    choice_paths = streams.allowed_workspaces(acct)
    descriptors = [
        await asyncio.to_thread(streams.workspace_descriptor, p)
        for p in choice_paths
    ]
    try:
        pid, model = modestore.resolve_for_difficulty(Path(choice_paths[0]), "trivial")
        if pid is None:
            pid = _daemon_ns._resolve_default_provider()
            model = _daemon_ns._effective_model(pid)
        provider = llmgateway.get(pid)
        if not provider.has_key():
            return None
        req = llmgateway.ChatRequest(
            messages=[{"role": "user",
                       "content": streams.triage_prompt(events, descriptors)}],
            model=model or provider.PROVIDER.get("default_model"),
            max_tokens=1500,
            reasoning_effort=_daemon_ns._effort_for(pid, model, "background"),
            temperature=0.0,
            workspace=choice_paths[0],
        )
        accumulated = ""
        async for ev in provider.chat_stream(req):
            if isinstance(ev, llmgateway.TextChunk):
                accumulated += ev.text
            if isinstance(ev, llmgateway.DoneChunk):
                break
        # Entries may be ints OR nested lists (multi-workspace spans),
        # so grab the outermost array rather than a flat-only regex.
        start, end = accumulated.find("["), accumulated.rfind("]")
        arr = json.loads(accumulated[start:end + 1]) if 0 <= start < end else []
    except Exception:  # noqa: BLE001 — classifier is an optimisation
        log.exception("stream triage failed for %s", acct["id"])
        return None
    labels = streams.normalize_triage(arr, len(events), len(choice_paths))
    groups: dict[str, list[dict[str, Any]]] = {}
    skipped: list[str] = []
    for e, ks in zip(events, labels):
        if not ks:
            skipped.append(e["id"])
            continue
        # Multi-topic spans land in EVERY labelled workspace's batch;
        # each scoped curator extracts only its share (the curation
        # prompt is workspace-aware).
        for k in ks:
            groups.setdefault(choice_paths[k - 1], []).append(e)
    return groups, skipped

async def _curate_into(
    app: web.Application, acct: dict[str, Any], ws: Path,
    events: list[dict[str, Any]],
) -> tuple[bool, str | None]:
    """One curate-then-discard run, scoped to ONE workspace (the
    charter invariant: no cross-workspace curator). Headless and
    OUTSIDE the rail — the messages must not enter the conversation
    log; the wiki pages the agent writes ARE the durable output.
    Registered in the runs registry so the dashboard shows it.

    Occupies one worker seat on the workspace Curate desk so Comms
    shares live-worker limits with /curate.
    """
    from switchbay import comms_review as _cr
    from switchbay.agents import desk_admission as seats
    from switchbay.kernel.desk import DESK_CURATE
    if not ws.is_dir():
        return False, f"target workspace missing: {ws}"
    if any(_cr.is_revoked(str(e.get("comms_key") or "")) for e in events):
        return False, "revoked during handoff"
    if not admin_policy.feature_enabled("comms_streams"):
        return False, admin_policy.feature_error("comms_streams")
    allow = set(streams.live_allowed_workspaces(acct))
    if str(ws) not in allow:
        return False, "workspace is not on this account allowlist"
    pid, model = _daemon_ns._comms_curation_route(ws)
    if not pid:
        return False, "no file-capable curator is available for this workspace"
    if not model:
        model = _daemon_ns._effective_model(pid)
    provider = llmgateway.get(pid)
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    runs: dict[str, dict[str, Any]] = app.setdefault("runs", {})
    runs[run_id] = {
        "run_id": run_id, "provider": pid, "model": model,
        "input_excerpt": f"curate comms: {acct['label']} → {ws.name} ({len(events)} msgs)",
        "started_at": time.time(), "last_chunk_at": time.time(),
        "tool_count": 0, "status": "running",
        "task": asyncio.current_task(),
        "workspace": str(ws), "workspace_name": ws.name,
        "is_background": True,
        "desk": DESK_CURATE,
    }
    gate = None
    sid = None
    acquired = False
    try:
        from switchbay import ce_host
        before = await asyncio.to_thread(ce_host.wiki_work_snapshot, ws)
        if any(_cr.is_revoked(str(e.get("comms_key") or "")) for e in events):
            return False, "revoked during handoff"
        if str(ws) not in set(streams.live_allowed_workspaces(acct)):
            return False, "workspace is not on this account allowlist"
        ws_desc = await asyncio.to_thread(streams.workspace_descriptor, str(ws))
        profile = await asyncio.to_thread(_daemon_ns._curator_profile, ws)
        if any(_cr.is_revoked(str(e.get("comms_key") or "")) for e in events):
            return False, "revoked during handoff"
        domain = seats.desk_domain_id(ws, DESK_CURATE)
        gate = seats.gate_for(domain, workspace=ws)
        gate.retain()
        sid = seats.slot_id(run_id, "comms-curator")
        await gate.acquire(sid, kind="worker")
        acquired = True
        if any(_cr.is_revoked(str(e.get("comms_key") or "")) for e in events):
            return False, "revoked during handoff"
        if not admin_policy.feature_enabled("comms_streams"):
            return False, admin_policy.feature_error("comms_streams")
        if str(ws) not in set(streams.live_allowed_workspaces(acct)):
            return False, "workspace is not on this account allowlist"
        req = llmgateway.ChatRequest(
            messages=[{"role": "user",
                       "content": streams.curation_prompt(
                           acct, events, workspace_desc=ws_desc,
                           profile=profile or None)}],
            model=model,
            workspace=str(ws),
            reasoning_effort=_daemon_ns._effort_for(pid, model, "ladder"),
        )
        if any(_cr.is_revoked(str(e.get("comms_key") or "")) for e in events):
            return False, "revoked during handoff"
        async for ev in provider.chat_stream(req):
            runs[run_id]["last_chunk_at"] = time.time()
            if isinstance(ev, llmgateway.DoneChunk):
                break
        receipt = await asyncio.to_thread(ce_host.wiki_diff_receipt, ws, before)
        landed = int(receipt.get("wiki_pages_landed") or 0)
        changed = list(receipt.get("wiki_pages_changed") or [])
        committed = bool(receipt.get("wiki_committed"))
        if run_id in runs:
            runs[run_id]["wiki_pages_landed"] = landed
            runs[run_id]["wiki_committed"] = committed
        if not committed or (landed <= 0 and not changed):
            return False, "curation produced no wiki commit"
        return True, None
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        log.exception("stream curation failed for %s → %s", acct["id"], ws)
        return False, str(e)
    finally:
        if gate is not None:
            try:
                if acquired and sid:
                    await gate.release_async(sid)
            finally:
                seats.release_domain(gate)
        runs.pop(run_id, None)

async def _run_stream_curation(app: web.Application, acct: dict[str, Any]) -> dict[str, Any]:
    """Curate only approved, non-revoked, allowlisted transit events."""
    from switchbay import comms_review
    raw = (await asyncio.to_thread(streams.pending_events, acct["id"]))[:150]
    allow = set(streams.allowed_workspaces(acct))
    if not allow:
        return {"ok": False,
                "error": "no workspaces allowlisted for this stream — "
                         "tick at least one in Settings"}
    keep: list[dict[str, Any]] = []
    purge: list[str] = []
    skipped: list[str] = []
    for e in raw:
        eid = str(e.get("id") or "")
        key = str(e.get("comms_key") or "")
        ws = str(e.get("approved_workspace") or "")
        if not e.get("approved") or not key or not ws:
            if eid:
                purge.append(eid)
            continue
        if comms_review.is_revoked(key):
            if eid:
                purge.append(eid)
            continue
        if ws not in allow:
            if eid:
                purge.append(eid)
            continue
        item = comms_review.get_item(key)
        if not item or ws not in (item.get("approved_workspaces") or []):
            if eid:
                purge.append(eid)
            continue
        keep.append(e)
    if purge:
        await asyncio.to_thread(streams.consume_transit, acct["id"], purge)
    if not admin_policy.feature_enabled("comms_streams"):
        return {"ok": False, "error": admin_policy.feature_error("comms_streams")}
    if not keep:
        return {"ok": True, "curated": 0, "skipped": 0, "note": "no approved transit"}
    groups: dict[str, list[dict[str, Any]]] = {}
    for e in keep:
        groups.setdefault(str(e["approved_workspace"]), []).append(e)
    errors: list[str] = []
    targets: list[str] = []
    succeeded_ws: set[str] = set()
    for ws_path, evs in groups.items():
        from switchbay import comms_review as _cr
        if any(_cr.is_revoked(str(e.get("comms_key") or "")) for e in evs):
            errors.append("revoked during handoff")
            continue
        ok, err = await _curate_into(app, acct, Path(ws_path), evs)
        if any(_cr.is_revoked(str(e.get("comms_key") or "")) for e in evs):
            errors.append("revoked during handoff")
            for e in evs:
                _cr.set_ingest_state(
                    str(e.get("comms_key") or ""), ws_path,
                    state="error",
                    error=_comms_user_ingest_error("revoked during handoff"),
                )
            continue
        if ok:
            succeeded_ws.add(ws_path)
            targets.append(Path(ws_path).name)
            for e in evs:
                _cr.set_ingest_state(
                    str(e.get("comms_key") or ""), ws_path,
                    state="ingested", error="",
                )
        elif err:
            errors.append(err)
            for e in evs:
                _cr.set_ingest_state(
                    str(e.get("comms_key") or ""), ws_path,
                    state="error",
                    error=_comms_user_ingest_error(err),
                )
    # An event is consumed only when EVERY workspace it was routed to
    # curated successfully — a multi-labelled message whose second
    # target failed stays in transit for the retry (the workspace
    # that already curated it will just dedupe against its own wiki).
    ev_targets: dict[str, set[str]] = {}
    for ws_path, evs in groups.items():
        for e in evs:
            ev_targets.setdefault(e["id"], set()).add(ws_path)
    consumed: list[str] = list(skipped) + [
        eid for eid, tgts in ev_targets.items() if tgts <= succeeded_ws
    ]
    await asyncio.to_thread(streams.consume_transit, acct["id"], consumed)
    await _daemon_ns._broadcast(app, protocol.custom({
        "type": "stream.curated", "account": acct["id"],
        "label": acct["label"],
        "messages": len(consumed) - len(skipped),
        "skipped": len(skipped),
        "workspaces": targets,
    }))
    out: dict[str, Any] = {
        "ok": not errors,
        "curated": len(consumed) - len(skipped),
        "skipped": len(skipped),
        "workspaces": targets,
    }
    if errors:
        out["error"] = "; ".join(errors[:3])
    return out

async def handle_streams_curate(request: web.Request) -> web.Response:
    from switchbay import admin_policy
    if not admin_policy.feature_enabled("comms_streams"):
        return web.json_response(
            {"error": admin_policy.feature_error("comms_streams")}, status=403,
        )
    acct = await asyncio.to_thread(streams.get_account, request.match_info["account_id"])
    if acct is None:
        return web.json_response({"error": "no such account"}, status=404)
    await streams.ingest_approved_updates(acct)
    result = await _run_stream_curation(request.app, acct)
    return web.json_response(result, status=200 if result.get("ok") else 502)
