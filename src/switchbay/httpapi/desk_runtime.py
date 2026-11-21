"""Desk seating, quiet, dismiss, and curate launch.

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
from aiohttp import web
from switchbay import localllm
from switchbay import rail
from switchbay.agents import orchestration
from switchbay.agents import rail_default

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

def _desk_spec(sname: str) -> dict[str, Any] | None:
    """Slash name → standing-desk spec. None if not a desk slash."""
    n = (sname or "").strip().lower()
    if n in ("work", "working", "steer", "steering"):
        return {
            "desk_id": "projects",
            "command": "work",
            "cancel": ("work", "steer"),
            "task_kind": "projects",
            "slash": "work",
            "staff": _daemon_ns._WORK_STAFF,
        }
    if n in ("code", "coding"):
        return {
            "desk_id": "code",
            "command": "code",
            "cancel": ("code",),
            "task_kind": "code",
            "slash": "code",
            "staff": _daemon_ns._CODE_STAFF,
        }
    if n in ("curate", "curator"):
        return {
            "desk_id": "curate",
            "command": "curate",
            "cancel": ("curate",),
            "task_kind": "curation",
            "slash": "curate",
            "staff": _daemon_ns._CURATE_STAFF,
        }
    if n in ("deck", "slideshow-author"):
        return {
            "desk_id": "deck",
            "command": "deck",
            "cancel": ("deck",),
            "task_kind": "deck",
            "slash": None,
            "staff": _daemon_ns._DECK_STAFF,
        }
    if n == "research":
        return {
            "desk_id": "research",
            "command": "research",
            "cancel": ("research",),
            "task_kind": "research",
            "slash": "research",
            "staff": _daemon_ns._RESEARCH_STAFF,
        }
    if n == "auto":
        return {
            "desk_id": "auto",
            "command": None,
            "cancel": (),
            "task_kind": "auto",
            "slash": None,
            "staff": "Continue the standing Auto desk from the last roster.",
        }
    return None

def _desk_spec_from_id(desk_id: str) -> dict[str, Any] | None:
    did = (desk_id or "").strip().lower()
    if did in ("projects", "work", "steer"):
        return _desk_spec("work")
    if did in ("code", "coding"):
        return _desk_spec("code")
    if did in ("curate", "curator"):
        return _desk_spec("curate")
    if did in ("deck", "slideshow"):
        return _desk_spec("deck")
    if did == "research":
        return _desk_spec("research")
    if did == "auto":
        return _desk_spec("auto")
    return None

def _desk_slash_verb(sargs: str) -> str | None:
    """First token of ``/work <args>``: quiet, dismiss, or a brief."""
    head = (sargs or "").strip().split(None, 1)
    if not head:
        return None
    w = head[0].lower()
    if w in _daemon_ns._DESK_STOP_WORDS:
        return "quiet"
    if w in _daemon_ns._DESK_DISMISS_WORDS:
        return "dismiss"
    return None

def _quiet_desk(app: web.Application, spec: dict[str, Any], workspace: Path) -> int:
    """Stop the live wave; the DAG stays standing (quiet) until Start."""
    from switchbay import kernel as sbk
    rec = None
    try:
        rec = sbk.get(workspace, str(spec["desk_id"]))
    except Exception:  # noqa: BLE001
        rec = None
    cancel = spec.get("cancel") or ()
    n = (
        _daemon_ns._cancel_ce_runs(
            app, tuple(cancel), workspace=workspace, settle="quiet",
        ) if cancel else 0
    )
    rid = rec.run_id if rec is not None else None
    if rid:
        n += _daemon_ns._cancel_run_ids(app, {rid})
    if _cancel_desk_launch(app, workspace, str(spec["desk_id"])):
        n += 1
    try:
        sbk.quiet(workspace, str(spec["desk_id"]), keep_run=True)
    except Exception:  # noqa: BLE001
        log.exception("desk quiet failed")
    return n

def _dismiss_desk(app: web.Application, spec: dict[str, Any], workspace: Path) -> int:
    """Tear the chief and DAG down. Explicit dismiss only."""
    from switchbay import kernel as sbk
    rec = None
    try:
        rec = sbk.get(workspace, str(spec["desk_id"]))
        sbk.dismiss(workspace, str(spec["desk_id"]))
    except Exception:  # noqa: BLE001
        log.exception("desk dismiss failed")
    cancel = spec.get("cancel") or ()
    n = (
        _daemon_ns._cancel_ce_runs(
            app, tuple(cancel), workspace=workspace, settle="cancelled",
        ) if cancel else 0
    )
    rid = rec.run_id if rec is not None else None
    if rid:
        n += _daemon_ns._cancel_run_ids(app, {rid}, dismiss=True)
    if _cancel_desk_launch(app, workspace, str(spec["desk_id"])):
        n += 1
    return n

def _stop_desk(app: web.Application, spec: dict[str, Any], workspace: Path) -> int:
    """Any ``/<desk> stop`` quiets the DAG; dismiss is separate."""
    return _quiet_desk(app, spec, workspace)

def _maybe_resume_quiet_desk(
    app: web.Application, spec: dict[str, Any], workspace: Path,
) -> str | None:
    """Resume a frozen DAG. Returns the run id, or None to launch new."""
    from switchbay import kernel as sbk
    rec = sbk.get(workspace, str(spec["desk_id"]))
    if rec is None or rec.state != sbk.STATE_QUIET or not rec.run_id:
        return None
    try:
        from switchbay import schedules as _sched
        for item in _sched.list_items(workspace):
            if str(item.get("desk_id") or "") != rec.desk_id:
                continue
            until = item.get("until_at")
            try:
                until_f = float(until) if until is not None else None
            except (TypeError, ValueError):
                until_f = None
            if until_f is not None and time.time() >= until_f:
                return None
    except Exception:  # noqa: BLE001
        pass
    ck = orchestration.load_checkpoint(workspace, rec.run_id)
    st = (ck or {}).get("status") if isinstance(ck, dict) else None
    phase = str((st or {}).get("phase") or "")
    if phase not in ("quiet", "interrupted", "running"):
        return None
    until = None
    if isinstance(st, dict):
        until = st.get("curate_until")
    plan = (ck or {}).get("plan") if isinstance(ck, dict) else None
    if until is None and plan is not None:
        dec = getattr(plan, "decision", None)
        if isinstance(dec, dict):
            until = dec.get("curate_until")
    try:
        until_f = float(until) if until is not None else None
    except (TypeError, ValueError):
        until_f = None
    if until_f is not None and time.time() >= until_f:
        return None
    oid = rec.run_id
    sbk.set_working(workspace, rec.desk_id, run_id=oid)
    t = asyncio.create_task(
        _daemon_ns._resume_orchestration(app, oid, workspace=workspace),
    )
    t.add_done_callback(_daemon_ns._make_dispatch_error_surface(app, oid))
    return oid

def _curate_constrained(*, local: bool, text: str = "") -> bool:
    """Local short curate stays a single session. Cloud always host-waves.

    Duration/continuous local still uses host package waves (one worker).
    Mode aliases belong in the prime payload; they are not a reason to
    skip the desk.
    """
    if not local:
        return False
    from switchbay.agents.orchestration import parse_duration_window
    repeat, _until = parse_duration_window(text)
    return not repeat

def _parse_schedule_prompt(
    prompt: str,
) -> tuple[str, dict[str, Any] | None, str]:
    """Classify a schedule prompt: desk fire, skip control, or Auto.

    ``skip`` is ``/curate stop`` / ``/work dismiss`` — those are not
    fires. Deck/Auto have no public slash, so ``/deck`` stays Auto.
    """
    parsed = rail.parse(prompt)
    if parsed.get("kind") != "slash":
        return "auto", None, prompt
    spec = _desk_spec(str(parsed.get("name") or ""))
    if not spec or not spec.get("slash"):
        return "auto", None, prompt
    sargs = str(parsed.get("args") or "")
    if _desk_slash_verb(sargs) in ("quiet", "dismiss"):
        return "skip", spec, sargs
    return "desk", spec, sargs

def _schedule_desk_launch(prompt: str) -> tuple[dict[str, Any] | None, str]:
    """Schedule prompt → (desk spec, args) when it should fire a desk."""
    kind, spec, sargs = _parse_schedule_prompt(prompt)
    if kind == "desk":
        return spec, sargs
    return None, prompt

def _desk_launch_key(workspace: Path, desk_id: str) -> tuple[str, str]:
    return (str(workspace), str(desk_id))

def _track_desk_launch(
    app: web.Application, workspace: Path, desk_id: str, task: asyncio.Task,
) -> None:
    launches: dict[tuple[str, str], asyncio.Task] = app.setdefault(
        "desk_launches", {},
    )
    key = _desk_launch_key(workspace, desk_id)
    old = launches.get(key)
    if old is not None and old is not task and not old.done():
        old.cancel()
    launches[key] = task

def _cancel_desk_launch(
    app: web.Application, workspace: Path, desk_id: str,
) -> bool:
    launches: dict[tuple[str, str], asyncio.Task] = app.get("desk_launches") or {}
    task = launches.pop(_desk_launch_key(workspace, desk_id), None)
    if task is None or task.done():
        return False
    task.cancel()
    return True

def _seat_desk_now(
    workspace: Path,
    spec: dict[str, Any],
    prompt: str,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> None:
    """Stand the desk before dispatch so the dashboard is not empty.

    Keep a live ``run_id`` — ``seat()`` would otherwise clear it and
    Stop/Start would lose the wave that is already running.
    """
    from switchbay import kernel as sbk
    did = str(spec["desk_id"])
    pid = provider or _daemon_ns._resolve_default_provider()
    mdl = model or (_daemon_ns._effective_model(pid) if pid else None)
    obj = (prompt or "").strip() or str(spec.get("staff") or did)
    keep_run = None
    try:
        rec = sbk.get(workspace, did)
        if rec is not None and rec.state == sbk.STATE_WORKING and rec.run_id:
            keep_run = rec.run_id
    except Exception:  # noqa: BLE001
        keep_run = None
    try:
        sbk.seat(
            workspace, did,
            chief_provider=str(pid or "unknown"),
            chief_model=mdl,
            objective=obj[:2000],
            run_id=keep_run,
        )
    except Exception:  # noqa: BLE001
        log.exception("desk seat on launch failed")

async def _curate_extra_system(
    workspace: Path, args: str, *, local: bool, local_rung: Any = None,
) -> str:
    """Profile + Reviews feedback + Phase 1 prime. Off the WS loop."""
    cap = _daemon_ns._CURATOR_PROFILE_CAP_TOKENS
    if local_rung is not None:
        cap = max(400, int(getattr(local_rung, "extra_system_chars", 0) or 0) // 4)
    elif local:
        cap = 400
    prof = await asyncio.to_thread(_daemon_ns._curator_profile, workspace, cap)
    extra = _daemon_ns._curator_profile_system(prof)
    fb = await asyncio.to_thread(_daemon_ns._review_feedback_system, workspace)
    if fb:
        extra = (extra + "\n\n" + fb).strip()
    prime = await asyncio.to_thread(
        _daemon_ns._curate_wave_prime_system, workspace, args, local=local,
    )
    if prime:
        extra = (extra + "\n\n" + prime).strip()
    from switchbay import meta_ontology
    ont = await asyncio.to_thread(
        meta_ontology.curation_system,
        workspace,
        cap_chars=cap * _daemon_ns._CHARS_PER_TOKEN_EST,
    )
    if ont:
        extra = (extra + "\n\n" + ont).strip()
    return extra

async def _run_curate_desk(
    app: web.Application,
    args: str,
    *,
    preference: float | None = None,
    workspace: Path,
    workspace_override: Path | None = None,
    provider_override: str | None = None,
    model_override: str | None = None,
    lock_provider: bool = False,
) -> str | None:
    """Build the CE prompt off-loop, then dispatch the Curate desk."""
    pid = provider_override
    model = model_override
    if not pid:
        pid, model = _daemon_ns._ce_action_provider(workspace)
    effective = pid or _daemon_ns._resolve_default_provider()
    is_local = _daemon_ns._provider_is_local(effective)
    lrung = None
    if is_local:
        lcfg = await asyncio.to_thread(localllm.load_config)
        lrung = rail_default.resolve_local_rung(
            localllm.ram_gb(),
            model_hint=rail_default.model_hint_from_cfg(lcfg),
        )
    ce_prompt = _daemon_ns._ce_action_prompt(
        "curate", args, local=is_local, local_rung=lrung,
    ) or _daemon_ns._CURATE_STAFF
    extra = await _curate_extra_system(
        workspace, args, local=is_local, local_rung=lrung,
    )
    from switchbay import kernel as sbk
    rec = sbk.get(workspace, sbk.DESK_CURATE)
    if rec is None or rec.state == sbk.STATE_DISMISSED:
        return None
    excerpt = f"[curate · background] {args}".strip()
    return await _daemon_ns._dispatch_auto(
        app, None, ce_prompt,
        preference=preference,
        workspace_override=workspace_override,
        provider_override=pid,
        model_override=model,
        input_excerpt=excerpt,
        extra_system=extra or None,
        command="curate",
        task_kind="curation",
        constrained=_curate_constrained(local=is_local, text=args),
        lock_provider=lock_provider,
    )

async def _run_desk(
    app: web.Application,
    spec: dict[str, Any],
    *,
    prompt: str,
    workspace: Path,
    preference: float | None = None,
    provider_override: str | None = None,
    model_override: str | None = None,
    lock_provider: bool = False,
) -> str | None:
    ws_path = Path(workspace)
    me = asyncio.current_task()
    if me is not None:
        _track_desk_launch(app, ws_path, str(spec["desk_id"]), me)
    # Pin the captured vault. Comparing to the focused workspace and
    # passing None lets a mid-preflight workspace switch steal the run.
    override = ws_path
    kind = spec.get("task_kind")
    rid: str | None = None
    try:
        from switchbay import kernel as sbk
        rec = sbk.get(ws_path, str(spec["desk_id"]))
        if rec is not None and rec.state == sbk.STATE_DISMISSED:
            return None
        if kind == "curation":
            rid = await _run_curate_desk(
                app, prompt,
                preference=preference,
                workspace=Path(workspace),
                workspace_override=override,
                provider_override=provider_override,
                model_override=model_override,
                lock_provider=lock_provider,
            )
        else:
            staff = not (prompt or "").strip()
            text = (prompt or "").strip() or str(spec["staff"])
            cmd = spec.get("command")
            excerpt = (
                f"[{cmd} · background] {prompt}"
                if cmd else
                f"[desk · background] {prompt}"
            ).strip()
            rid = await _daemon_ns._dispatch_auto(
                app, None, text,
                preference=preference,
                workspace_override=override,
                provider_override=provider_override,
                model_override=model_override,
                lock_provider=lock_provider,
                input_excerpt=excerpt,
                command=cmd,
                task_kind=kind,
                family_staff=staff and kind in {"projects", "code"},
            )
    finally:
        launches: dict[tuple[str, str], asyncio.Task] = app.get("desk_launches") or {}
        key = _desk_launch_key(ws_path, str(spec["desk_id"]))
        if launches.get(key) is me:
            launches.pop(key, None)
        # Only tear down a placeholder seat (working, no run yet).
        # A started wave is quieted by `_finish_desk`; Stop uses keep_run.
        if not rid:
            from switchbay import kernel as sbk
            try:
                rec = sbk.get(ws_path, str(spec["desk_id"]))
                if (
                    rec is not None
                    and rec.state == sbk.STATE_WORKING
                    and not rec.run_id
                ):
                    sbk.quiet(ws_path, rec.desk_id)
            except Exception:  # noqa: BLE001
                pass
    return rid

def _launch_desk(
    app: web.Application,
    spec: dict[str, Any],
    *,
    prompt: str,
    workspace: Path | None = None,
    preference: float | None = None,
    provider_override: str | None = None,
    model_override: str | None = None,
    lock_provider: bool = False,
) -> None:
    focused = Path(app["workspace"])
    ws_path = Path(workspace) if workspace is not None else focused
    _seat_desk_now(
        ws_path, spec, prompt,
        provider=provider_override,
        model=model_override,
    )
    t = asyncio.create_task(_run_desk(
        app, spec,
        prompt=prompt,
        workspace=ws_path,
        preference=preference,
        provider_override=provider_override,
        model_override=model_override,
        lock_provider=lock_provider,
    ))
    _track_desk_launch(app, ws_path, str(spec["desk_id"]), t)
    t.add_done_callback(_daemon_ns._make_dispatch_error_surface(app, None))
