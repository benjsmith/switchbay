"""Drain CE-queued pack-runs into Switchbay rail LLM dispatch.

Curiosity Engine's filebrowser ``POST /api/packs/<pack>/action/<action>``
only writes ``.workbench/pack-runs/<run_id>.json`` with
``status: "queued"`` — it does not seat an LLM agent. Switchbay owns
skill/LLM execution (same path as ``handle_pack_action``). This module
lists those JSON files, validates pack+skill, and fires
``_dispatch_chat`` (or an injectable ``dispatch_fn`` for tests).

Both sides share the workspace, so Switchbay rewrites the same JSON
status fields atomically — no CE PATCH required.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

from . import atomicio, packstore, skillkit

log = logging.getLogger("switchbay.pack_run_drain")

RUNS_REL = Path(".workbench") / "pack-runs"
QUEUED_STATUSES = frozenset({"queued", "accepted"})
# Poll cadence for the background drain loop (3–5s charter window).
POLL_INTERVAL_S = 4.0

DispatchFn = Callable[..., Awaitable[Any]]


def runs_dir(workspace: Path) -> Path:
    return Path(workspace).resolve() / RUNS_REL


def run_path(workspace: Path, run_id: str) -> Path:
    # Basename only — refuse path traversal via run_id.
    safe = Path(str(run_id)).name
    return runs_dir(workspace) / f"{safe}.json"


def build_pack_prompt(pack: str, action: str, rel_path: str) -> str:
    """Same prompt text as ``handle_pack_action`` in daemon.py."""
    skill = f"{pack}-{action}"
    return (
        f"Load the `{skill}` skill with load_skill(\"{skill}\") and follow it "
        f"exactly to handle the file `{rel_path}` in this workspace. The `{pack}` "
        f"pack is active. Route every output to the workspace per the skill — "
        f"`wiki/` pages, `figures/` PNGs, `data/` tables — and finish with a "
        f"one-line summary naming what you wrote."
    )


def list_queued_runs(workspace: Path) -> list[dict[str, Any]]:
    """Read ``.workbench/pack-runs/*.json`` with status queued/accepted."""
    d = runs_dir(workspace)
    if not d.is_dir():
        return []
    out: list[dict[str, Any]] = []
    try:
        paths = sorted(d.glob("*.json"))
    except OSError:
        return []
    for p in paths:
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        status = str(raw.get("status") or "").strip()
        if status not in QUEUED_STATUSES:
            continue
        rid = str(raw.get("run_id") or p.stem).strip()
        if not rid:
            continue
        rec = dict(raw)
        rec["run_id"] = rid
        rec["_path"] = str(p)
        out.append(rec)
    return out


def write_run_status(
    workspace: Path,
    run_id: str,
    status: str,
    **extra: Any,
) -> dict[str, Any] | None:
    """Atomically update a pack-run JSON's status (+ optional fields)."""
    path = run_path(workspace, run_id)
    if not path.is_file():
        return None
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(rec, dict):
        return None
    rec["status"] = status
    for k, v in extra.items():
        if v is None:
            rec.pop(k, None)
        else:
            rec[k] = v
    path.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(path, rec)
    return rec


def _inflight(app: Any) -> set[str]:
    s = app.get("pack_run_inflight")
    if s is None:
        s = set()
        app["pack_run_inflight"] = s
    return s


def _default_dispatch_fn() -> DispatchFn:
    """Lazy import — daemon imports this module at load time."""

    async def _dispatch(app: Any, **kwargs: Any) -> Any:
        from . import daemon as _daemon

        return await _daemon._dispatch_chat(
            app,
            ws=None,
            text=kwargs["text"],
            input_excerpt=kwargs.get("input_excerpt"),
            run_id=kwargs.get("run_id"),
        )

    return _dispatch


def _error_surface(app: Any, run_id: str):
    from . import daemon as _daemon

    return _daemon._make_dispatch_error_surface(app, run_id)


def _validate_run(
    workspace: Path, rec: Mapping[str, Any],
) -> tuple[str, str, str, str] | str:
    """Return (pack, action, rel, skill) or an error note string."""
    pack = str(rec.get("pack") or "").strip()
    action = str(rec.get("action") or "").strip()
    rel = str(rec.get("path") or "").strip()
    if not pack or not action or not rel:
        return "pack, action, and path are required on the run record"
    pack_rec = packstore.get_pack(workspace, pack)
    if pack_rec is None:
        return f"pack not found: {pack}"
    if not pack_rec.get("enabled"):
        return (
            f"pack '{pack}' is not active — activate it in Settings → Packs"
        )
    skill = f"{pack}-{action}"
    if skillkit.get_skill(workspace, skill) is None:
        return f"pack skill not found: {skill}"
    return pack, action, rel, skill


async def drain_once(
    app: Any,
    *,
    dispatch_fn: DispatchFn | None = None,
) -> dict[str, Any]:
    """Seat each queued pack-run as a fire-and-forget rail chat.

    Returns ``{drained, skipped, errors}`` summary lists/counts.
    Deduplicates via ``app['pack_run_inflight']``. On validation failure
    marks the JSON ``failed`` with a ``note``. On successful seat marks
    ``running`` and spawns a background task; when the task finishes the
    JSON becomes ``done`` or ``failed``.
    """
    workspace = Path(app["workspace"])
    dispatch = dispatch_fn or _default_dispatch_fn()
    inflight = _inflight(app)

    drained: list[str] = []
    skipped: list[str] = []
    errors: list[dict[str, str]] = []

    queued = await asyncio.to_thread(list_queued_runs, workspace)
    for rec in queued:
        run_id = str(rec["run_id"])
        if run_id in inflight:
            skipped.append(run_id)
            continue

        # Re-check disk status (another drain / race).
        try:
            path = run_path(workspace, run_id)
            fresh = json.loads(path.read_text(encoding="utf-8"))
            st = str(fresh.get("status") or "")
            if st not in QUEUED_STATUSES:
                skipped.append(run_id)
                continue
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            skipped.append(run_id)
            continue

        validated = _validate_run(workspace, rec)
        if isinstance(validated, str):
            note = validated
            await asyncio.to_thread(
                write_run_status, workspace, run_id, "failed", note=note,
            )
            errors.append({"run_id": run_id, "error": note})
            continue

        pack, action, rel, _skill = validated
        prompt = build_pack_prompt(pack, action, rel)
        excerpt = f"{pack}:{action} {Path(rel).name}"

        inflight.add(run_id)
        try:
            await asyncio.to_thread(
                write_run_status, workspace, run_id, "running",
            )
        except Exception as e:  # noqa: BLE001
            inflight.discard(run_id)
            note = f"failed to mark running: {e}"
            errors.append({"run_id": run_id, "error": note})
            continue

        async def _runner(
            rid: str = run_id,
            text: str = prompt,
            input_excerpt: str = excerpt,
            p: str = pack,
            a: str = action,
            vault: str = rel,
        ) -> None:
            async def _tag_run() -> None:
                await asyncio.sleep(0)
                runs = app.get("runs") or {}
                r = runs.get(rid)
                if r is not None:
                    r["kind"] = f"pack:{p}:{a}"
                    r["vault_path"] = vault

            asyncio.create_task(_tag_run())
            try:
                await dispatch(
                    app,
                    text=text,
                    input_excerpt=input_excerpt,
                    run_id=rid,
                )
            except Exception:  # noqa: BLE001
                log.exception("pack-run drain %s crashed", rid)
                raise

        def _on_done(task: asyncio.Task, rid: str = run_id) -> None:
            inflight.discard(rid)
            try:
                exc = task.exception()
            except (asyncio.CancelledError, asyncio.InvalidStateError):
                try:
                    write_run_status(
                        workspace, rid, "failed",
                        note="dispatch cancelled",
                    )
                except Exception:  # noqa: BLE001
                    pass
                return
            try:
                if exc is None:
                    write_run_status(workspace, rid, "done")
                else:
                    write_run_status(
                        workspace, rid, "failed",
                        note=f"{type(exc).__name__}: {exc}",
                    )
            except Exception:  # noqa: BLE001
                log.exception("pack-run status update failed for %s", rid)
            # Also surface to the rail (same as handle_pack_action).
            try:
                _error_surface(app, rid)(task)
            except Exception:  # noqa: BLE001
                pass

        try:
            task = asyncio.create_task(_runner())
            task.add_done_callback(_on_done)
            drained.append(run_id)
        except Exception as e:  # noqa: BLE001
            inflight.discard(run_id)
            note = f"failed to start dispatch: {e}"
            await asyncio.to_thread(
                write_run_status, workspace, run_id, "failed", note=note,
            )
            errors.append({"run_id": run_id, "error": note})

    return {
        "drained": drained,
        "skipped": skipped,
        "errors": errors,
        "drained_count": len(drained),
        "skipped_count": len(skipped),
        "error_count": len(errors),
    }


async def pack_run_drain_loop(app: Any) -> None:
    """Background: every ~4s, drain queued pack-runs if the dir exists."""
    while True:
        try:
            await asyncio.sleep(POLL_INTERVAL_S)
            ws = Path(app["workspace"])
            if not runs_dir(ws).is_dir():
                continue
            await drain_once(app)
        except asyncio.CancelledError:
            return
        except Exception:  # noqa: BLE001
            log.exception("pack-run drain loop iteration failed")


def kick_drain(app: Any) -> None:
    """Schedule an immediate drain_once on the running loop (best-effort)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def _go() -> None:
        try:
            await drain_once(app)
        except Exception:  # noqa: BLE001
            log.exception("kicked pack-run drain failed")

    loop.create_task(_go())
