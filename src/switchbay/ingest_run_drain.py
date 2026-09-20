"""Drain CE-queued ingest-runs into local_ingest (or Switchbay rail LLM).

Curiosity Engine's drop-ingest
(``POST /api/ingest/from-upload`` / ``from-path``) only stages under
``vault/raw/`` and writes ``.workbench/ingest-runs/<run_id>.json`` with
``status: "queued"`` — it does not run ``local_ingest`` or seat an LLM.
Switchbay owns deterministic CE ingest + skill/LLM execution (same
pattern as ``pack_run_drain`` / ADR-006).

Default path: deterministic ``local_ingest`` (via ``ce_tools._ce_ingest``)
for normal vault sources. Escalate to ``_dispatch_chat`` only when the
run metadata opts in (``mode`` / ``drain`` ∈ {llm,rail,agent,dispatch}
or ``prefer_rail`` / ``use_llm`` truthy).

Both sides share the workspace, so Switchbay rewrites the same JSON
status fields atomically — no CE PATCH required.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

from . import atomicio, ingest_prep

log = logging.getLogger("switchbay.ingest_run_drain")

RUNS_REL = Path(".workbench") / "ingest-runs"
QUEUED_STATUSES = frozenset({"queued", "accepted"})
POLL_INTERVAL_S = 4.0
_RAIL_MODES = frozenset({"llm", "rail", "agent", "dispatch"})

DispatchFn = Callable[..., Awaitable[Any]]
LocalIngestFn = Callable[[Path, str, Mapping[str, Any]], dict[str, Any]]


def runs_dir(workspace: Path) -> Path:
    return Path(workspace).resolve() / RUNS_REL


def run_path(workspace: Path, run_id: str) -> Path:
    # Basename only — refuse path traversal via run_id.
    safe = Path(str(run_id)).name
    return runs_dir(workspace) / f"{safe}.json"


def wants_rail(rec: Mapping[str, Any]) -> bool:
    """True only when run metadata explicitly opts into LLM/rail drain."""
    mode = str(rec.get("mode") or "").strip().lower()
    if mode in _RAIL_MODES:
        return True
    drain = str(rec.get("drain") or "").strip().lower()
    if drain in _RAIL_MODES:
        return True
    for key in ("prefer_rail", "use_llm", "llm"):
        v = rec.get(key)
        if v is True:
            return True
        if isinstance(v, str) and v.strip().lower() in {"1", "true", "yes"}:
            return True
    return False


def build_ingest_prompt(vault_path: str, *, size: int | None = None) -> str:
    """Same shape as ``handle_ingest_from_path`` in daemon.py."""
    name = Path(vault_path).name
    ext = Path(vault_path).suffix.lower().lstrip(".")
    ext_hint = (
        f"The file has extension `.{ext}`." if ext
        else "The file has no extension."
    )
    size_hint = f" (size {size} bytes)" if size is not None else ""
    return (
        f"A file in this workspace at `{vault_path}` needs ingestion"
        f"{size_hint}. {ext_hint} Ingest it as a CE-shaped wiki page:\n\n"
        f"  1. Read the file (Read for text; for CSV/TSV produce a "
        f"clean markdown table in the body; for PDFs try `pdftotext` "
        f"first; for binaries you can't read, describe by filename + "
        f"size).\n"
        f"  2. Classify into a CE page type: `source` (PDFs, articles, "
        f"citable artifacts), `table` (CSV/TSV data; the title prefix "
        f"becomes `[tab]` and the body is the markdown table), "
        f"`note` (plain prose), `figure` (images), `unclassified` "
        f"as a last resort.\n"
        f"  3. Slugify the filename's stem to kebab-case. Write the "
        f"page with Write to `wiki/<type>s/<slug>.md` with frontmatter "
        f"`type: <type>`, `title: \"[<typ>] <human title>\"`, "
        f"`created` / `updated`, and `extracted_from: {vault_path}` so "
        f"the round-trip target is recorded. Use the CE bracket-prefix "
        f"convention (`[tab]`, `[src]`, `[note]`, `[fig]`).\n"
        f"  4. Body: for tables, the full markdown table + a one-line "
        f"caption above. For sources, 2-4 paragraphs of metadata + "
        f"key takeaways. Don't write tools after Write — the graph "
        f"rebuilds automatically on wiki/ changes.\n"
        f"  5. If a wiki page with the same slug already exists "
        f"because this file was ingested before, append `-2`, `-3` "
        f"… so the new ingest doesn't clobber the previous one.\n"
        f"(filename hint: `{name}`)"
    )


def list_queued_runs(workspace: Path) -> list[dict[str, Any]]:
    """Read ``.workbench/ingest-runs/*.json`` with status queued/accepted."""
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
    """Atomically update an ingest-run JSON's status (+ optional fields)."""
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


def resolve_run_vault_path(
    workspace: Path, rec: Mapping[str, Any],
) -> tuple[str, Path] | str:
    """Return ``(rel, resolved)`` or an error note (refuse escape)."""
    raw = str(
        rec.get("vault_path") or rec.get("path") or ""
    ).strip()
    if not raw:
        return "vault_path is required on the ingest-run record"
    if "\x00" in raw:
        return "invalid vault_path"
    # Refuse absolute paths and ``..`` components before resolve so
    # ``vault/raw/../../etc/passwd`` cannot normalize into-workspace.
    candidate = Path(raw)
    if candidate.is_absolute():
        return f"vault_path escapes workspace or is invalid: {raw}"
    if any(part == ".." for part in candidate.parts):
        return f"vault_path escapes workspace or is invalid: {raw}"
    resolved = ingest_prep.resolve_workspace_path(workspace, raw)
    if resolved is None:
        return f"vault_path escapes workspace or is invalid: {raw}"
    try:
        rel = resolved.relative_to(Path(workspace).resolve()).as_posix()
    except ValueError:
        return f"vault_path escapes workspace: {raw}"
    return rel, resolved


def _inflight(app: Any) -> set[str]:
    s = app.get("ingest_run_inflight")
    if s is None:
        s = set()
        app["ingest_run_inflight"] = s
    return s


def _default_dispatch_fn() -> DispatchFn:
    async def _dispatch(app: Any, **kwargs: Any) -> Any:
        from . import daemon as _daemon

        return await _daemon._dispatch_chat(
            app,
            ws=None,
            text=kwargs["text"],
            input_excerpt=kwargs.get("input_excerpt"),
            run_id=kwargs.get("run_id"),
            command=kwargs.get("command", "ingest"),
        )

    return _dispatch


def _default_local_ingest_fn() -> LocalIngestFn:
    def _local(
        workspace: Path, vault_path: str, _rec: Mapping[str, Any],
    ) -> dict[str, Any]:
        from . import ce_tools

        return ce_tools._ce_ingest(workspace, {"path": vault_path})

    return _local


def _error_surface(app: Any, run_id: str):
    from . import daemon as _daemon

    return _daemon._make_dispatch_error_surface(app, run_id)


def _local_ok(result: Mapping[str, Any]) -> tuple[bool, str | None]:
    """Interpret ce_tools / local_ingest JSON as success or failure note."""
    if not isinstance(result, Mapping):
        return False, "local_ingest returned non-object"
    err = result.get("error")
    if err:
        return False, str(err)
    # Summary shape from local_ingest.main: ok count + results list.
    if "ok" in result and isinstance(result.get("ok"), int):
        considered = int(result.get("considered") or 0)
        ok_n = int(result["ok"])
        if considered == 0:
            return False, "local_ingest considered 0 files"
        if ok_n <= 0:
            return False, "local_ingest ok=0"
        return True, None
    # Tool / prep may return ok: True without counts.
    if result.get("ok") is True:
        return True, None
    if result.get("ok") is False:
        return False, str(result.get("reason") or "local_ingest ok=false")
    # Unknown success-shaped payload — treat as done if no error.
    return True, None


async def drain_once(
    app: Any,
    *,
    dispatch_fn: DispatchFn | None = None,
    local_ingest_fn: LocalIngestFn | None = None,
) -> dict[str, Any]:
    """Process each queued ingest-run (local first, rail if metadata says).

    Returns ``{drained, skipped, errors, …}``. Deduplicates via
    ``app['ingest_run_inflight']``.
    """
    workspace = Path(app["workspace"])
    dispatch = dispatch_fn or _default_dispatch_fn()
    local_fn = local_ingest_fn or _default_local_ingest_fn()
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

        validated = resolve_run_vault_path(workspace, rec)
        if isinstance(validated, str):
            note = validated
            await asyncio.to_thread(
                write_run_status, workspace, run_id, "failed", note=note,
            )
            errors.append({"run_id": run_id, "error": note})
            continue

        rel, resolved = validated
        if not resolved.is_file():
            note = f"staged file not found: {rel}"
            await asyncio.to_thread(
                write_run_status, workspace, run_id, "failed", note=note,
            )
            errors.append({"run_id": run_id, "error": note})
            continue

        use_rail = wants_rail(rec)
        size = rec.get("size")
        try:
            size_i = int(size) if size is not None else resolved.stat().st_size
        except (TypeError, ValueError, OSError):
            size_i = None

        inflight.add(run_id)
        try:
            await asyncio.to_thread(
                write_run_status,
                workspace,
                run_id,
                "running",
                drain_via="rail" if use_rail else "local_ingest",
            )
        except Exception as e:  # noqa: BLE001
            inflight.discard(run_id)
            note = f"failed to mark running: {e}"
            errors.append({"run_id": run_id, "error": note})
            continue

        if use_rail:
            prompt = build_ingest_prompt(rel, size=size_i)
            excerpt = f"ingest {Path(rel).name}"

            async def _runner(
                rid: str = run_id,
                text: str = prompt,
                input_excerpt: str = excerpt,
                vault: str = rel,
            ) -> None:
                async def _tag_run() -> None:
                    await asyncio.sleep(0)
                    runs = app.get("runs") or {}
                    r = runs.get(rid)
                    if r is not None:
                        r["kind"] = "ingest-upload"
                        r["vault_path"] = vault

                asyncio.create_task(_tag_run())
                try:
                    await dispatch(
                        app,
                        text=text,
                        input_excerpt=input_excerpt,
                        run_id=rid,
                        command="ingest",
                    )
                except Exception:  # noqa: BLE001
                    log.exception("ingest-run rail drain %s crashed", rid)
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
                    log.exception(
                        "ingest-run status update failed for %s", rid,
                    )
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
            continue

        # Deterministic local_ingest path.
        async def _local_runner(
            rid: str = run_id,
            vault: str = rel,
            record: Mapping[str, Any] = rec,
        ) -> None:
            try:
                result = await asyncio.to_thread(
                    local_fn, workspace, vault, record,
                )
            except Exception as e:  # noqa: BLE001
                log.exception("ingest-run local drain %s crashed", rid)
                raise RuntimeError(f"{type(e).__name__}: {e}") from e
            ok, note = _local_ok(result if isinstance(result, dict) else {})
            if not ok:
                raise RuntimeError(note or "local_ingest failed")
            # Stash a compact summary on the run record before done.
            summary: dict[str, Any] = {}
            if isinstance(result, dict):
                for k in (
                    "ok", "failed", "considered", "file", "mode",
                    "multimodal_pending",
                ):
                    if k in result:
                        summary[k] = result[k]
            if summary:
                await asyncio.to_thread(
                    write_run_status,
                    workspace,
                    rid,
                    "running",
                    local_ingest=summary,
                )

        def _on_local_done(task: asyncio.Task, rid: str = run_id) -> None:
            inflight.discard(rid)
            try:
                exc = task.exception()
            except (asyncio.CancelledError, asyncio.InvalidStateError):
                try:
                    write_run_status(
                        workspace, rid, "failed",
                        note="local_ingest cancelled",
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
                log.exception(
                    "ingest-run status update failed for %s", rid,
                )

        try:
            task = asyncio.create_task(_local_runner())
            task.add_done_callback(_on_local_done)
            drained.append(run_id)
        except Exception as e:  # noqa: BLE001
            inflight.discard(run_id)
            note = f"failed to start local_ingest: {e}"
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


async def ingest_run_drain_loop(app: Any) -> None:
    """Background: every ~4s, drain queued ingest-runs if the dir exists."""
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
            log.exception("ingest-run drain loop iteration failed")


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
            log.exception("kicked ingest-run drain failed")

    loop.create_task(_go())
