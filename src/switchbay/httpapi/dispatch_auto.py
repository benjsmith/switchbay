"""Auto orchestration dispatch for one rail turn.

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
import logging
import time
import uuid
from aiohttp import web
from switchbay import conversations
from switchbay import llmgateway
from switchbay import protocol
from switchbay.agents import fanout
from switchbay.agents import orchestration
from switchbay.agents import orchestration_policy

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

async def _dispatch_auto(
    app: web.Application, ws: web.WebSocketResponse | None, text: str,
    *, preference: float | None = None,
    workspace_override: Path | None = None,
    thread_id_override: str | None = None,
    provider_override: str | None = None,
    model_override: str | None = None,
    input_excerpt: str | None = None,
    extra_system: str | None = None,
    command: str | None = None,
    task_kind: str | None = None,
    constrained: bool = False,
    lock_provider: bool = False,
    family_staff: bool = False,
) -> str | None:
    """Default chat path: Auto orchestration.

    Null hypothesis is a single ordinary Run (`_dispatch_chat`). Simple
    wiki/factual questions take ``fast_lookup`` (in-process search + a
    cheap HTTP synthesizer, with a slider-gated kernel check) instead
    of a CLI agent loop. Extra workers / verify / expansion only fire
    when the conservative policy says the task structure, uncertainty,
    or preference justifies them.

    ``workspace_override`` runs Auto in another vault (scheduler) without
    stealing the focused rail thread.
    """
    workspace: Path = workspace_override or app["workspace"]
    headless = ws is None or workspace_override is not None
    from switchbay import kernel as sbk
    if not task_kind and sbk.looks_like_deck(text):
        task_kind = "deck"
        command = command or "deck"
    pref = (
        orchestration_policy.clamp_preference(preference)
        if preference is not None
        else orchestration_policy.get_preference()
    )
    features = orchestration_policy.extract_features(
        text,
        preference=pref,
        provider_diversity=_daemon_ns._keyed_provider_count(),
    )
    features = orchestration_policy.apply_task_context(
        features, task_kind=task_kind, constrained=constrained,
    )
    try:
        state = orchestration_policy.load_state(workspace)
    except Exception:  # noqa: BLE001
        state = None
    decision = orchestration_policy.decide(features, state=state)
    if task_kind:
        decision.reason = f"{task_kind}: {decision.reason}"
    if lock_provider and provider_override:
        pid = provider_override
        model = model_override or _daemon_ns._effective_model(pid)
    else:
        pid, model = _daemon_ns._auto_roster_pair(
            workspace,
            hint_pid=provider_override or _daemon_ns._resolve_default_provider(),
            hint_model=model_override,
            preference=pref,
        )
    local_pid = (
        pid in orchestration_policy.LOCAL_PROVIDER_IDS
        or orchestration_policy.provider_category(pid) == "local"
    )
    # Provider-backed /curate is always the CE curator node so it can
    # dispatch Phase 2 workers. Local short curate stays a single
    # session (constrained=True). Duration/continuous local still host-
    # waves, one worker at a time — do not skip duration machinery.
    ce_provider_wave = task_kind == "curation" and not constrained
    projects_desk_wave = task_kind in {"projects", "code"}
    deck_wave = task_kind == "deck"
    research_desk_wave = task_kind == "research"
    desk_id = sbk.choose_desk(
        task_kind=task_kind,
        command=command,
        text=text,
        strategy=decision.strategy,
        n_investigators=int(decision.n_investigators or 1),
        include_verify=bool(decision.include_verify),
        lookup=bool(features.lookup),
        research=bool(features.research),
        code=bool(features.code),
    )
    if desk_id == sbk.DESK_AUTO and not task_kind:
        task_kind = "auto"
    plain_single = (
        decision.strategy == "single"
        and not decision.include_verify
        and not decision.include_execute
        and decision.n_investigators <= 1
    )
    if (
        decision.strategy == "fast_lookup"
        and not ce_provider_wave
        and not projects_desk_wave
        and task_kind not in {"curation", "projects", "code", "deck", "auto", "research"}
    ):
        from switchbay.agents import fast_lookup as fast_lookup_mod
        from switchbay.kernel.hire import pick_fast_model, pick_kernel_model, strong_check_mode
        hits = await asyncio.to_thread(fast_lookup_mod.retrieve, workspace, text)
        synth = pick_fast_model(workspace=workspace)
        if hits and synth is not None:
            kernel = pick_kernel_model(workspace=workspace)
            mode = strong_check_mode(pref, synth=synth, kernel=kernel)
            await _daemon_ns._chat_notice(
                app, ws,
                f"{fast_lookup_mod.notice_for(synth, mode)} {decision.reason}",
                kind="chat", workspace=str(workspace),
            )
            t0 = time.time()
            run_id = await fast_lookup_mod.dispatch(
                app, ws, text,
                workspace=workspace,
                hits=hits,
                preference=pref,
                thread_id_override=thread_id_override,
                input_excerpt=input_excerpt,
            )
            if run_id:
                usage = (app.get("run_usage") or {}).pop(run_id, {}) or {}
                tok_in = usage.get("input_tokens") if isinstance(usage.get("input_tokens"), int) else 0
                tok_out = usage.get("output_tokens") if isinstance(usage.get("output_tokens"), int) else 0
                orchestration_policy.record_outcome({
                    "orchestration_id": run_id,
                    "strategy": "fast_lookup",
                    "arm_id": "fast_lookup",
                    "explored": bool(decision.explored),
                    "preference": pref,
                    "features": features.to_dict(),
                    "bucket": features.bucket(),
                    "initial_nodes": 1,
                    "final_nodes": 1,
                    "dag_depth": 1,
                    "max_concurrency": 1,
                    "tokens": int(usage.get("tokens") or (tok_in + tok_out) or 0),
                    "input_tokens": tok_in or None,
                    "output_tokens": tok_out or None,
                    "latency_s": time.time() - t0,
                    "completed": True,
                    "decision_reason": decision.reason,
                }, workspace)
                return run_id
        # Empty wiki / no HTTP synth: ordinary chat, never a DAG.
        plain_single = True
    if (
        plain_single and not ce_provider_wave
        and not projects_desk_wave and not deck_wave
        and not research_desk_wave
        and not bool(features.web_ingest)
    ):
        await _daemon_ns._chat_notice(
            app, ws,
            f"Auto: single run — {decision.reason}.",
            kind="chat", workspace=str(workspace),
        )
        t0 = time.time()
        run_id = await _daemon_ns._dispatch_chat(
            app, ws, text, workspace_override=workspace_override,
            thread_id_override=thread_id_override,
            provider_override=pid,
            model_override=model,
            input_excerpt=input_excerpt,
            extra_system=extra_system,
            command=command,
            desk_id=desk_id,
        )
        if run_id:
            usage = (app.get("run_usage") or {}).pop(run_id, {}) or {}
            tok_in = usage.get("input_tokens") if isinstance(usage.get("input_tokens"), int) else 0
            tok_out = usage.get("output_tokens") if isinstance(usage.get("output_tokens"), int) else 0
            orchestration_policy.record_outcome({
                "orchestration_id": run_id,
                "strategy": "single",
                "arm_id": "single",
                "explored": bool(decision.explored),
                "preference": pref,
                "features": features.to_dict(),
                "bucket": features.bucket(),
                "initial_nodes": 1,
                "final_nodes": 1,
                "dag_depth": 1,
                "max_concurrency": 1,
                "tokens": int(usage.get("tokens") or (tok_in + tok_out) or 0),
                "input_tokens": tok_in or None,
                "output_tokens": tok_out or None,
                "latency_s": time.time() - t0,
                "completed": True,
                "decision_reason": decision.reason,
            }, workspace)
        return run_id

    try:
        provider = llmgateway.get(pid)
    except llmgateway.ProviderError as e:
        await _daemon_ns._chat_notice(app, ws, f"llm: {e}", kind="chat")
        return None
    if not provider.has_key():
        await _daemon_ns._chat_notice(
            app, ws,
            f"no API key configured for {provider.LABEL}. Open Settings to add one.",
            kind="chat",
        )
        return None

    parent_run_id = f"run-{uuid.uuid4().hex[:8]}"
    model = model or provider.PROVIDER.get("default_model")
    n = decision.n_investigators
    runs: dict[str, dict[str, Any]] = app.setdefault("runs", {})
    runs[parent_run_id] = {
        "run_id": parent_run_id,
        "provider": pid,
        "model": model,
        "input_excerpt": input_excerpt or f"[auto {decision.strategy}] {text[:100]}",
        "started_at": time.time(),
        "last_chunk_at": time.time(),
        "tool_count": 0,
        "status": "planning",
        "task": asyncio.current_task(),
        "workspace": str(workspace),
        "workspace_name": workspace.name,
        "fanout_n": n,
        "workers_total": n,
        "workers_running": 0,
        "orchestration_id": parent_run_id,
        "orchestration_strategy": decision.strategy,
        "preference": pref,
        "decision_reason": decision.reason,
        "independence": decision.independence,
        "command": command,
        "task_kind": task_kind,
        "desk_id": desk_id,
    }
    _daemon_ns._remember_run_workspace(app, parent_run_id, workspace)

    if headless:
        thread_id = thread_id_override or await asyncio.to_thread(
            conversations.new_thread, workspace,
        )
    else:
        thread_id = app.get("thread_id")
        if not thread_id:
            thread_id = await asyncio.to_thread(conversations.new_thread, workspace)
            app["thread_id"] = thread_id
            app["thread_kind"] = "structured-agent"
        if app.get("thread_kind") == "interactive-pty":
            runs.pop(parent_run_id, None)
            await _daemon_ns._chat_notice(
                app, ws,
                "this is a shell thread — start a new thread for chat.",
                kind="chat",
            )
            return None
        busy = [
            r for r in runs.values()
            if r.get("thread_id") == thread_id
            and r.get("run_id") != parent_run_id
            and r.get("status") in _daemon_ns._ORCH_BUSY_STATUSES
        ]
        if busy:
            runs.pop(parent_run_id, None)
            await _daemon_ns._chat_notice(
                app, ws,
                f"thread is busy — {busy[0].get('run_id')} is still streaming. "
                "Wait for it to finish, or start a new thread.",
                kind="chat",
            )
            return None
    runs[parent_run_id]["thread_id"] = thread_id
    _daemon_ns._remember_run_thread(app, parent_run_id, thread_id)
    _daemon_ns._append_event(app, workspace, thread_id, "user", text, run_id=parent_run_id)
    await _daemon_ns._broadcast(app, protocol.run_started(
        thread_id, parent_run_id, pid, str(model), str(workspace),
    ))

    try:
        await _daemon_ns._chat_notice(
            app, ws, f"Auto: {decision.reason}.", kind="chat",
            workspace=str(workspace),
            run_id=parent_run_id,
            thread_id=thread_id,
        )
        await _daemon_ns._broadcast(app, protocol.step_started(parent_run_id, "planning"))
        if parent_run_id in runs:
            runs[parent_run_id]["step"] = "planning"

        # Deterministic decomposition: a planner LLM would serialize the
        # DAG and correlate every worker's prior. Explicit n≥2 fan-out
        # still uses fanout.plan. Extra allocation slots go to the
        # verifier so it is not the same model as investigator 0.
        tasks_list = orchestration_policy.decompose_tasks(text, n, features)
        planner_meta = {
            "provider": None, "model": None,
            "input_tokens": None, "output_tokens": None,
            "decomposition": "deterministic",
        }
        allocations = orchestration_policy.allocate_models(
            len(tasks_list) + (1 if decision.include_verify else 0),
            independence=decision.independence,
            preference=pref,
            default_provider=pid,
            default_model=model,
            workspace=workspace,
            bucket=features.bucket(),
        )
        from switchbay.agents import orchestration_health as orch_health
        skipped = orch_health.skip_notes()
        roster = orchestration_policy.format_allocation_notice(
            allocations,
            rail_provider=pid,
            rail_model=str(model) if model else None,
            skipped=skipped or None,
        )
        if roster:
            await _daemon_ns._chat_notice(
                app, ws, roster, kind="chat",
                workspace=str(workspace),
                run_id=parent_run_id,
                thread_id=thread_id,
            )
        hints = orchestration_policy.method_hints_for(
            len(tasks_list), decision.independence, features,
        )
        curator_provider = curator_model = curator_harness = None
        project_hires: list[dict] | None = None
        research_hires: list[dict] | None = None
        if str(task_kind or "") == "curation":
            from switchbay.agents.rail_default import ALLOWED_TOOLS as _CHIEF_TOOLS
            hire = sbk.decide_hire(
                sbk.HireRequest(
                    package_id=sbk.CURATOR_ID,
                    justification="curate desk",
                    needed_tools=list(sbk.get_package(sbk.CURATOR_ID).tools
                                      if sbk.get_package(sbk.CURATOR_ID) else []),
                    kind="specialist",
                    desk_prior=True,
                ),
                preference=pref,
                chief=(pid, model),
                org=[],
                workspace=workspace,
                chief_tools=list(_CHIEF_TOOLS),
                pi_available=sbk.pi_available(),
            )
            if hire.accepted:
                curator_provider = hire.provider
                curator_model = hire.model
                curator_harness = hire.harness
            sbk.seat(
                workspace, sbk.DESK_CURATE,
                chief_provider=pid,
                chief_model=model,
                thread_id=thread_id,
                run_id=parent_run_id,
                objective=text,
                org=[{
                    "package": sbk.CURATOR_ID,
                    "provider": curator_provider or pid,
                    "model": curator_model or model,
                    "harness": curator_harness or "rail",
                    "reports_to": "chief",
                }],
            )
        elif str(task_kind or "") == "deck":
            from switchbay.agents.rail_default import ALLOWED_TOOLS as _CHIEF_TOOLS
            pkg = sbk.get_package(sbk.SLIDESHOW_ID)
            hire = sbk.decide_hire(
                sbk.HireRequest(
                    package_id=sbk.SLIDESHOW_ID,
                    justification="deck desk",
                    needed_tools=list(pkg.tools if pkg else []),
                    kind="specialist",
                    desk_prior=True,
                ),
                preference=pref,
                chief=(pid, model),
                org=[],
                workspace=workspace,
                chief_tools=list(_CHIEF_TOOLS),
                pi_available=sbk.pi_available(),
            )
            if hire.accepted:
                curator_provider = hire.provider
                curator_model = hire.model
                curator_harness = hire.harness
            sbk.seat(
                workspace, sbk.DESK_DECK,
                chief_provider=pid,
                chief_model=model,
                thread_id=thread_id,
                run_id=parent_run_id,
                objective=text,
                org=[{
                    "package": sbk.SLIDESHOW_ID,
                    "provider": curator_provider or pid,
                    "model": curator_model or model,
                    "harness": curator_harness or "rail",
                    "reports_to": "chief",
                }],
            )
        elif str(task_kind or "") == "research":
            from switchbay.agents.rail_default import ALLOWED_TOOLS as _CHIEF_TOOLS
            pkg = sbk.get_package(sbk.RESEARCH_ID)
            hire = sbk.decide_hire(
                sbk.HireRequest(
                    package_id=sbk.RESEARCH_ID,
                    justification="research desk",
                    needed_tools=list(pkg.tools if pkg else []),
                    needed_skills=list(pkg.needed_skills if pkg else []),
                    kind="specialist",
                    desk_prior=True,
                ),
                preference=pref,
                chief=(pid, model),
                org=[],
                workspace=workspace,
                chief_tools=list(_CHIEF_TOOLS),
                pi_available=sbk.pi_available(),
            )
            if hire.accepted:
                curator_provider = hire.provider
                curator_model = hire.model
                curator_harness = hire.harness
            research_hires = [hire.to_dict()] if hire.accepted else None
            sbk.seat(
                workspace, sbk.DESK_RESEARCH,
                chief_provider=pid,
                chief_model=model,
                thread_id=thread_id,
                run_id=parent_run_id,
                objective=text,
                org=[{
                    "package": sbk.RESEARCH_ID,
                    "provider": curator_provider or pid,
                    "model": curator_model or model,
                    "harness": curator_harness or "rail",
                    "reports_to": "chief",
                }],
            )
        elif desk_id == sbk.DESK_AUTO:
            from switchbay.agents.rail_default import ALLOWED_TOOLS as _CHIEF_TOOLS
            auto_hires = sbk.pick_auto_hires(
                text,
                preference=pref,
                chief=(pid, model),
                workspace=workspace,
                chief_tools=list(_CHIEF_TOOLS),
                pi_available=sbk.pi_available(),
                research=bool(features.research and features.web_ingest),
                web_ingest=bool(features.web_ingest),
            )
            if auto_hires:
                research_hires = [d.to_dict() for d in auto_hires]
            sbk.seat(
                workspace, sbk.DESK_AUTO,
                chief_provider=pid,
                chief_model=model,
                thread_id=thread_id,
                run_id=parent_run_id,
                objective=text,
                org=[{
                    "package": d.package_id,
                    "provider": d.provider or pid,
                    "model": d.model or model,
                    "harness": d.harness or "rail",
                    "reports_to": "chief",
                } for d in auto_hires],
            )
        elif str(task_kind or "") in {"projects", "code"}:
            from switchbay import kernel as sbk
            from switchbay.agents.rail_default import ALLOWED_TOOLS as _CHIEF_TOOLS
            from switchbay.kernel.packages import CODING_FAMILY, PROJECTS_DESK_NOTE, PROJECTS_FAMILY
            note = PROJECTS_DESK_NOTE if task_kind == "projects" else (
                "Code desk: hire explore / plan / edit / review as distinct "
                "write-authorities. Do not hire a 'frontend' persona."
            )
            extra_system = "\n\n".join(
                p for p in (extra_system or "", note) if p
            ) or None
            family = PROJECTS_FAMILY if task_kind == "projects" else CODING_FAMILY
            desk_id = sbk.DESK_PROJECTS if task_kind == "projects" else sbk.DESK_CODE
            decisions = sbk.pick_family_hires(
                text,
                preference=pref,
                chief=(pid, model),
                workspace=workspace,
                chief_tools=list(_CHIEF_TOOLS),
                pi_available=sbk.pi_available(),
                desk_prior=True,
                family=family,
                staff_desk=family_staff,
            )
            project_hires = [d.to_dict() for d in decisions]
            sbk.seat(
                workspace, desk_id,
                chief_provider=pid,
                chief_model=model,
                thread_id=thread_id,
                run_id=parent_run_id,
                objective=text,
                org=[{
                    "package": d.package_id,
                    "provider": d.provider or pid,
                    "model": d.model or model,
                    "harness": d.harness or "rail",
                    "reports_to": "chief",
                } for d in decisions],
            )
        plan = orchestration.plan_from_decision(
            text, decision, tasks_list,
            orchestration_id=parent_run_id,
            allocations=allocations,
            method_hints=hints,
            task_kind=task_kind,
            curator_provider=curator_provider,
            curator_model=curator_model,
            curator_harness=curator_harness,
            project_hires=project_hires,
            research_hires=research_hires,
            workspace=workspace,
        )
        plan.features = features.to_dict()
        if extra_system:
            plan.extra_system = extra_system
        if local_pid:
            b = plan.bounds
            plan.bounds = orchestration.OrchestrationBounds(
                max_nodes=b.max_nodes,
                max_depth=b.max_depth,
                max_concurrency=1,
                max_expansions=b.max_expansions,
                worker_timeout_sec=b.worker_timeout_sec,
                wall_clock_sec=b.wall_clock_sec,
            ).clamp()
        if parent_run_id in runs:
            runs[parent_run_id]["planner_provider"] = planner_meta.get("provider")
            runs[parent_run_id]["planner_model"] = planner_meta.get("model")
            runs[parent_run_id]["planner_input_tokens"] = planner_meta.get("input_tokens")
            runs[parent_run_id]["planner_output_tokens"] = planner_meta.get("output_tokens")
            runs[parent_run_id]["status"] = "running"
        await _daemon_ns._broadcast(app, protocol.step_finished(parent_run_id, "planning"))

        result = await orchestration.execute(
            plan,
            app=app, workspace=workspace, thread_id=thread_id,
            parent_run_id=parent_run_id, default_provider=provider,
            default_model=model, ws=ws,
        )
        window_ended = str(
            (result.telemetry or {}).get("stop_reason") or "",
        ) == "curate window ended"
        _daemon_ns._finish_desk(
            workspace, task_kind, parent_run_id,
            cancelled=result.cancelled or window_ended,
        )
        if result.cancelled:
            if parent_run_id in runs:
                runs[parent_run_id]["status"] = "cancelled"
                runs[parent_run_id]["user_cancel"] = True
            await _daemon_ns._broadcast(app, protocol.run_error(
                parent_run_id, "cancelled", "orchestration cancelled", thread_id,
            ))
            await _daemon_ns._chat_notice(
                app, ws, _daemon_ns._desk_stopped_notice(task_kind), kind="slash",
                workspace=str(workspace),
            )
        else:
            merged = result.output
            if not merged:
                merged = "_Auto orchestration produced no output._\n"
            await _daemon_ns._stream_parent_reply(
                app, parent_run_id=parent_run_id, thread_id=thread_id, text=merged,
            )
            fanout.append_to_rail_log(
                workspace, thread_id, parent_run_id=parent_run_id, merged=merged,
            )
            fanout.write_summary(
                workspace, parent_run_id,
                text=text, tasks=tasks_list, merged=merged,
                planner_meta=planner_meta, results=result.results,
            )
            if parent_run_id in runs and result.telemetry:
                runs[parent_run_id]["expansions"] = result.telemetry.get("targeted_expansions")
                runs[parent_run_id]["verification_conflicts"] = result.telemetry.get(
                    "verification_conflicts",
                )
                runs[parent_run_id]["tokens"] = result.telemetry.get("tokens")
            await _daemon_ns._broadcast(app, protocol.run_finished(
                thread_id, parent_run_id,
                result.telemetry.get("input_tokens"),
                result.telemetry.get("output_tokens"),
                "end_turn",
            ))
    except asyncio.CancelledError:
        if parent_run_id in runs:
            runs[parent_run_id]["status"] = "cancelled"
            runs[parent_run_id]["user_cancel"] = True
        _daemon_ns._finish_desk(workspace, task_kind, parent_run_id, cancelled=True)
        await _daemon_ns._broadcast(app, protocol.run_error(
            parent_run_id, "cancelled", "orchestration cancelled", thread_id,
        ))
        raise
    except llmgateway.ProviderError as e:
        _daemon_ns._finish_desk(workspace, task_kind, parent_run_id, cancelled=False)
        await _daemon_ns._broadcast(app, protocol.run_error(parent_run_id, e.code, str(e), thread_id))
    except Exception as e:  # noqa: BLE001
        log.exception("auto orchestration crashed; falling back to single run")
        _daemon_ns._finish_desk(workspace, task_kind, parent_run_id, cancelled=False)
        await _daemon_ns._broadcast(app, protocol.run_error(
            parent_run_id, "server", str(e), thread_id,
        ))
        runs.pop(parent_run_id, None)
        try:
            await _daemon_ns._dispatch_chat(
                app, ws, text,
                workspace_override=workspace_override,
                thread_id_override=thread_id_override,
                provider_override=provider_override,
                model_override=model_override,
                input_excerpt=input_excerpt,
                extra_system=extra_system,
                command=command,
            )
        except Exception:  # noqa: BLE001
            log.exception("single-run fallback also failed")
    finally:
        rec = runs.get(parent_run_id)
        if rec and rec.get("status") == "cancelled":
            async def _drop_cancelled(rid: str = parent_run_id) -> None:
                await asyncio.sleep(8)
                (app.get("runs") or {}).pop(rid, None)
            asyncio.create_task(_drop_cancelled())
        else:
            runs.pop(parent_run_id, None)
    return parent_run_id
