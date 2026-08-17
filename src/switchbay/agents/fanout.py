"""Fan-out orchestration: planner → N parallel workers → merger.

Triggered when the user dials the rail's +/- counter to N≥2 and
submits a prompt. The dispatch path (`_dispatch_fanout` in
daemon.py) calls into this module:

  1. plan(text, n)     — single LLM turn that returns N task
                          descriptions with optional difficulty
                          ratings (trivial / normal / hard).
  2. run_workers(...)  — spawns N concurrent worker tasks. Each
                          gets its own run_id so the Agent
                          Dashboard's Running panel shows live
                          progress per worker. State streams to
                          all WS clients via the same agent_*
                          message shapes a single-agent run uses.
  3. merge(results)    — concat-with-headers (default; spec's
                          fallback merger). Returns one final
                          assistant string for the rail.

Per-worker output is also written to disk at
`<state-root>/workspaces/<ws>/runs/<parent_run_id>/worker-<i>.md` plus
a `summary.md` with the merged result, so the run survives restarts.
This is transient/regenerable, so it lives in the machine-local state
root (see `statedir`), never on a cloud-sync service.

"Subprocess workers" in the spec means OS-level isolation: the
subscription-backed providers (claude_code, codex) already run in
a subprocess, so workers using those providers get the
crash-isolation property natively. HTTP providers (Anthropic,
OpenAI, Gemini, Ollama) don't — they inherit asyncio task
isolation only. That's a real gap when an HTTP request crashes the
asyncio loop in a way `gather` can't recover from, but it covers
the common case (parallelism + per-worker results) and we can
revisit if it bites.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from .. import (
    conversations, llmgateway, modestore, protocol, routing_status, statedir,
)

log = logging.getLogger("switchbay.agents.fanout")

# Cap N to keep both the planner LLM and the workers manageable.
# 8 parallel workers is enough for any reasonable map-reduce; past
# that we'd hit provider rate limits and the merger output would be
# too long to be useful as one rail message anyway.
MAX_N = 8


async def _retire_run(
    runs: dict[str, dict[str, Any]], run_id: str, delay: float,
) -> None:
    """Sleep `delay` seconds then remove `run_id` from the registry.
    Used to let completed worker rows linger so the Agent Dashboard's
    poll loop catches them before they disappear."""
    try:
        await asyncio.sleep(delay)
    finally:
        runs.pop(run_id, None)

# How long to wait for a single worker before timing it out and
# returning a stub result. Workers that exceed this still get their
# own run_id in the dashboard so the user can manually kill them.
WORKER_TIMEOUT_SEC = 180.0


PLANNER_SYSTEM = (
    "You are a planner. Given a user request and a target number of "
    "parallel sub-tasks N, return EXACTLY N JSON objects describing "
    "tasks that, when run independently, cover the request. Each task "
    "is its own self-contained instruction — workers won't see each "
    "other or the original request. Make tasks meaningfully different "
    "(different angle, different data slice, different sub-question), "
    "not paraphrases of the same prompt.\n\n"
    "Output format: a JSON array of objects, each with:\n"
    "  description: string  — full instruction the worker will receive\n"
    "  difficulty:  \"trivial\" | \"normal\" | \"hard\"  — rough cost hint\n"
    "Output ONLY the JSON array. No prose, no code fence, no preamble."
)


WORKER_SYSTEM_PREFIX = (
    "You are one of several parallel workers running a sub-task of a "
    "larger user request. Other workers are handling sibling tasks; "
    "they are not visible to you and you should not coordinate with "
    "them. Answer your specific task only, concisely."
)


async def plan(
    text: str, n: int, *, provider: Any, model: str | None, workspace: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run the planner LLM. Returns `(tasks, meta)` where `tasks` is a
    list of `{description, difficulty}` dicts of length exactly `n` and
    `meta` records the planner's provider/model + token usage (for the
    hybrid-split experiment's cost ledger; token fields are None when
    the provider doesn't report usage). Falls back to N copies of the
    original request when the planner output isn't parseable — better
    to silently degrade to "run the same prompt N times" than surface a
    planner error to the user, since the workers can still do useful
    work."""
    n = max(2, min(MAX_N, int(n)))
    meta: dict[str, Any] = {
        "provider": getattr(provider, "ID", "?"),
        "model": model or getattr(provider, "DEFAULT_MODEL", None),
        "input_tokens": None,
        "output_tokens": None,
    }
    prompt = (
        f"User request:\n\n{text.strip()}\n\n"
        f"Number of parallel sub-tasks to produce: N = {n}.\n"
        f"Output the JSON array now."
    )
    req = llmgateway.ChatRequest(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        system=PLANNER_SYSTEM,
        max_tokens=2048,
        reasoning_effort=routing_status.effort_for(
            getattr(provider, "ID", ""), model, "ladder",
            rung_effort=modestore.rung_effort(workspace, "hard")),
        workspace=str(workspace),
    )
    accumulated = ""
    try:
        async for ev in provider.chat_stream(req):
            if isinstance(ev, llmgateway.TextChunk):
                accumulated += ev.text
            if isinstance(ev, llmgateway.DoneChunk):
                meta["input_tokens"] = ev.input_tokens
                meta["output_tokens"] = ev.output_tokens
                break
    except Exception:  # noqa: BLE001
        log.exception("planner crashed; falling back to identical tasks")
        return _fallback_tasks(text, n), meta

    tasks = _parse_planner_output(accumulated, n)
    if tasks is None:
        log.warning("planner output didn't parse; falling back. raw=%r",
                    accumulated[:200])
        return _fallback_tasks(text, n), meta
    return tasks, meta


def _parse_planner_output(raw: str, n: int) -> list[dict[str, Any]] | None:
    s = raw.strip()
    # Tolerate accidental code fences.
    if s.startswith("```"):
        first_nl = s.find("\n")
        if first_nl != -1:
            s = s[first_nl + 1:]
        if s.endswith("```"):
            s = s[: -3]
        s = s.strip()
    try:
        parsed = json.loads(s)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list):
        return None
    out: list[dict[str, Any]] = []
    for item in parsed[:n]:
        if not isinstance(item, dict):
            continue
        desc = item.get("description")
        if not isinstance(desc, str) or not desc.strip():
            continue
        difficulty = str(item.get("difficulty") or "normal").lower()
        if difficulty not in ("trivial", "normal", "hard"):
            difficulty = "normal"
        out.append({"description": desc.strip(), "difficulty": difficulty})
    if len(out) < n:
        return None
    return out


def _fallback_tasks(text: str, n: int) -> list[dict[str, Any]]:
    """When planning fails, fan out the *same* prompt to N workers.
    Useful as a sampling sanity-check: the user gets N independent
    answers to compare. Not as good as a real plan but better than
    erroring out."""
    return [
        {
            "description": text.strip(),
            "difficulty": "normal",
        } for _ in range(n)
    ]


async def run_worker(
    *,
    task: dict[str, Any],
    worker_index: int,
    provider: Any,
    model: str | None,
    workspace: Path,
    parent_run_id: str,
    thread_id: str,
    app: Any,
    ws: Any,
    runs_dir: Path,
) -> dict[str, Any]:
    """One worker. Streams AG-UI TEXT_MESSAGE events via WS so the
    Agent Dashboard's Running panel shows live per-worker progress;
    writes final output to runs_dir/worker-<i>.md. Returns a result
    record `{worker_index, task, output, run_id, ok, error?}`.
    Workers belong to the parent dispatch's thread — `thread_id`
    stamps their lifecycle events (AG-UI RUN_STARTED requires it)."""
    run_id = f"{parent_run_id}-w{worker_index}"
    runs: dict[str, dict[str, Any]] = app.setdefault("runs", {})
    runs[run_id] = {
        "run_id": run_id,
        "provider": getattr(provider, "ID", "?"),
        "model": model or getattr(provider, "DEFAULT_MODEL", "?"),
        "input_excerpt": task["description"][:120],
        "started_at": time.time(),
        "last_chunk_at": time.time(),
        "tool_count": 0,
        "status": "running",
        "task": asyncio.current_task(),
        "parent_run_id": parent_run_id,
        "thread_id": thread_id,
        "worker_index": worker_index,
        "workspace": str(workspace),
        "workspace_name": workspace.name,
    }
    # Cross-workspace transcript resolution (Agent Dashboard) — keep the
    # run→ws map in sync for workers too. Mirrors daemon._remember_run_workspace
    # (kept inline to avoid a daemon import from this worker module).
    _run_ws: dict[str, str] = app.setdefault("run_ws", {})
    _run_ws[run_id] = str(workspace)
    _overflow = len(_run_ws) - 256
    if _overflow > 0:
        for _k in list(_run_ws)[:_overflow]:
            _run_ws.pop(_k, None)
    # Bump the parent's running-counter so the dashboard's parent row
    # can show "fan-out · 3 of 4 running" without polling each worker.
    parent_rec = runs.get(parent_run_id)
    if parent_rec is not None:
        parent_rec["workers_running"] = int(parent_rec.get("workers_running", 0)) + 1
    pid = getattr(provider, "ID", "?")
    await _broadcast(app, protocol.run_started(
        thread_id, run_id, pid, runs[run_id]["model"], str(workspace),
    ))
    # The worker's task description IS its step — gives cross-thread
    # dashboards a "working toward" line per worker.
    step_name = str(task.get("description") or "")[:80]
    if run_id in runs:
        runs[run_id]["step"] = step_name
    await _broadcast(app, protocol.step_started(run_id, step_name))

    req = llmgateway.ChatRequest(
        messages=[{"role": "user", "content": task["description"]}],
        model=model,
        system=WORKER_SYSTEM_PREFIX,
        max_tokens=4096,
        reasoning_effort=routing_status.effort_for(
            getattr(provider, "ID", ""), model, "ladder",
            rung_effort=modestore.rung_effort(
                workspace, str(task.get("difficulty") or "normal"))),
        workspace=str(workspace),
    )

    text_parts: list[str] = []
    error: str | None = None
    in_tok: int | None = None
    out_tok: int | None = None
    # Workers stream plain prose (no tools) — one AG-UI message per
    # worker, opened on the first delta, closed when the stream ends.
    msg_id: str | None = None
    try:
        async for ev in provider.chat_stream(req):
            if isinstance(ev, llmgateway.TextChunk):
                text_parts.append(ev.text)
                if msg_id is None:
                    msg_id = protocol.new_message_id()
                    await _broadcast(app, protocol.text_message_start(run_id, msg_id))
                await _broadcast(app, protocol.text_message_content(run_id, msg_id, ev.text))
                if run_id in runs:
                    runs[run_id]["last_chunk_at"] = time.time()
            elif isinstance(ev, llmgateway.DoneChunk):
                in_tok = ev.input_tokens
                out_tok = ev.output_tokens
                break
        if msg_id is not None:
            await _broadcast(app, protocol.text_message_end(run_id, msg_id))
            msg_id = None
    except asyncio.CancelledError:
        await _broadcast(app, protocol.run_error(run_id, "cancelled", "worker cancelled", thread_id))
        raise
    except Exception as e:  # noqa: BLE001
        error = str(e)
        log.exception("worker %d crashed", worker_index)
        await _broadcast(app, protocol.run_error(run_id, "server", error, thread_id))
    finally:
        # Flag the worker as finished but linger it in the registry
        # for a few polling cycles so the dashboard's 2-second poll
        # doesn't miss fast workers entirely (the visual rationale
        # for fan-out is "see N parallel workers" — losing them
        # before the user can see them defeats the point).
        if run_id in runs:
            runs[run_id]["status"] = "error" if error else "done"
            runs[run_id]["last_chunk_at"] = time.time()
            runs[run_id]["finished_at"] = time.time()
            asyncio.create_task(_retire_run(runs, run_id, delay=8.0))
        parent_rec = runs.get(parent_run_id)
        if parent_rec is not None:
            parent_rec["workers_running"] = max(
                0, int(parent_rec.get("workers_running", 0)) - 1,
            )

    output = "".join(text_parts).strip()
    worker_pid = getattr(provider, "ID", "?")
    worker_model = model or getattr(provider, "DEFAULT_MODEL", None)
    # Persist worker output for re-opening / debugging.
    runs_dir.mkdir(parents=True, exist_ok=True)
    worker_path = runs_dir / f"worker-{worker_index}.md"
    tok_note = ""
    if in_tok is not None or out_tok is not None:
        tok_note = f"  ·  _tokens: in {in_tok or 0} / out {out_tok or 0}_"
    body = (
        f"# Worker {worker_index}: {task['description'][:80]}\n\n"
        f"_difficulty: {task.get('difficulty', 'normal')}_  ·  "
        f"_{worker_pid}/{worker_model}_  ·  "
        f"_run_id: {run_id}_{tok_note}\n\n"
        f"---\n\n{output if output else '(no output)'}\n"
    )
    if error:
        body += f"\n\n---\n\n**Error:** {error}\n"
    try:
        worker_path.write_text(body, encoding="utf-8")
    except OSError:
        log.exception("failed to write worker output")

    if not error:
        await _broadcast(app, protocol.step_finished(run_id, step_name))
        await _broadcast(app, protocol.run_finished(
            thread_id, run_id, in_tok, out_tok, "end_turn"))

    return {
        "worker_index": worker_index,
        "task": task,
        "output": output,
        "run_id": run_id,
        "ok": error is None,
        "error": error,
        "provider": worker_pid,
        "model": worker_model,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
    }


async def run_workers(
    tasks: list[dict[str, Any]],
    *,
    provider: Any, model: str | None, workspace: Path,
    parent_run_id: str, thread_id: str, app: Any, ws: Any,
) -> list[dict[str, Any]]:
    """Spawn one task per item in `tasks`, run them concurrently,
    return ordered results. Each task gets its own run_id so the
    dashboard tracks them independently. Worker timeout caps long
    runs at WORKER_TIMEOUT_SEC.

    Per-worker provider+model selection: if mode.json declares a
    `model_ladder`, each task's `difficulty` is looked up to pick a
    specific (provider, model) for that worker; missing rungs fall
    back to the dispatch-level (provider, model) supplied by the
    caller. Provider lookup failures (typo'd id, missing key) also
    fall back rather than failing the worker — gives the user a
    visible result they can debug."""
    runs_dir = statedir.runs_dir(workspace, parent_run_id)

    def _resolve_for(task: dict[str, Any]) -> tuple[Any, str | None]:
        """Pick the (provider obj, model) for this single worker."""
        diff = str(task.get("difficulty") or "normal")
        rung_pid, rung_model = modestore.resolve_for_difficulty(workspace, diff)
        if rung_pid is None:
            return provider, model
        try:
            p = llmgateway.get(rung_pid)
        except llmgateway.ProviderError as e:
            log.warning(
                "ladder rung %s -> provider %s unavailable (%s); "
                "falling back to dispatch default",
                diff, rung_pid, e,
            )
            return provider, model
        if not p.has_key():
            log.warning(
                "ladder rung %s -> provider %s has no key; "
                "falling back to dispatch default",
                diff, rung_pid,
            )
            return provider, model
        return p, rung_model

    async def _bounded(t, i):
        """Wrap one worker so any failure mode (timeout, SDK
        exception, broadcast error, ladder lookup raise) lands as
        a normalised `{ok: False, error}` record instead of
        propagating. Without this, asyncio.gather(return_exceptions=
        False) would cancel every sibling worker the moment one
        raised — exactly the failure mode the user reported."""
        run_id = f"{parent_run_id}-w{i}"
        try:
            worker_provider, worker_model = _resolve_for(t)
        except Exception as e:  # noqa: BLE001
            log.exception("worker %d: provider resolution crashed", i)
            return {
                "worker_index": i, "task": t, "output": "",
                "run_id": run_id, "ok": False,
                "error": f"provider resolution failed: {type(e).__name__}: {e}",
            }
        try:
            return await asyncio.wait_for(
                run_worker(
                    task=t, worker_index=i,
                    provider=worker_provider, model=worker_model,
                    workspace=workspace,
                    parent_run_id=parent_run_id, thread_id=thread_id,
                    app=app, ws=ws,
                    runs_dir=runs_dir,
                ),
                timeout=WORKER_TIMEOUT_SEC,
            )
        except asyncio.TimeoutError:
            # run_worker catches its own broad excepts and returns a
            # normal record, so the timeout is the only "expected"
            # outer signal. We still drop the registry entry + emit
            # a RUN_ERROR so the dashboard reflects truth.
            runs: dict[str, dict[str, Any]] = app.setdefault("runs", {})
            runs.pop(run_id, None)
            try:
                await _broadcast(app, protocol.run_error(
                    run_id, "timeout",
                    f"timed out after {WORKER_TIMEOUT_SEC:.0f}s", thread_id,
                ))
            except Exception:  # noqa: BLE001
                pass
            return {
                "worker_index": i, "task": t, "output": "",
                "run_id": run_id, "ok": False,
                "error": f"timed out after {WORKER_TIMEOUT_SEC:.0f}s",
            }
        except asyncio.CancelledError:
            # User-driven cancel via the Dashboard's kill button.
            # Re-raise so the cancellation propagates the right
            # way — gather will record it via return_exceptions
            # without aborting the siblings.
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("worker %d: unexpected crash escaped run_worker", i)
            runs: dict[str, dict[str, Any]] = app.setdefault("runs", {})
            runs.pop(run_id, None)
            try:
                await _broadcast(app, protocol.run_error(
                    run_id, "server", f"{type(e).__name__}: {e}", thread_id,
                ))
            except Exception:  # noqa: BLE001
                pass
            return {
                "worker_index": i, "task": t, "output": "",
                "run_id": run_id, "ok": False,
                "error": f"{type(e).__name__}: {e}",
            }

    coros = [_bounded(t, i) for i, t in enumerate(tasks)]
    # `return_exceptions=True` so a CancelledError from one worker
    # (or any other still-escaping raise) doesn't cancel its
    # siblings. _bounded already normalises everything else to a
    # failure-record return; this is the last belt.
    raw = await asyncio.gather(*coros, return_exceptions=True)
    results: list[dict[str, Any]] = []
    for i, r in enumerate(raw):
        if isinstance(r, BaseException):
            # Should only be CancelledError given _bounded's catches.
            # Convert into the same record shape so merge() / the
            # dashboard see a consistent type.
            run_id = f"{parent_run_id}-w{i}"
            results.append({
                "worker_index": i, "task": tasks[i], "output": "",
                "run_id": run_id, "ok": False,
                "error": f"{type(r).__name__}: {r}",
            })
        else:
            results.append(r)
    return results


def merge(text: str, results: list[dict[str, Any]]) -> str:
    """Default merger: concat-with-headers. Each worker's output is a
    section under its task description. Failed workers surface their
    error inline rather than being silently dropped — the user wants
    to know which slices didn't get an answer."""
    lines: list[str] = [
        f"_Fan-out across {len(results)} workers for: {text.strip()[:120]}_",
        "",
    ]
    for r in results:
        task = r.get("task") or {}
        idx = r.get("worker_index", 0)
        desc = str(task.get("description") or "(no description)")
        lines.append(f"### Worker {idx + 1}: {desc[:80]}")
        if r.get("ok"):
            output = (r.get("output") or "").strip()
            if not output:
                lines.append("_(no output)_")
            else:
                lines.append(output)
        else:
            lines.append(f"_Worker failed: {r.get('error') or 'unknown error'}_")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


async def _broadcast(app: Any, message: dict[str, Any]) -> None:
    """Mirror daemon._broadcast — we can't import it directly without
    creating a cycle, so fan out manually through the same WS set."""
    clients = app.get("ws_clients") or set()
    for client in list(clients):
        try:
            await client.send_json(message)
        except Exception:  # noqa: BLE001
            pass


def write_summary(
    workspace: Path, parent_run_id: str, *,
    text: str, tasks: list[dict[str, Any]], merged: str,
    planner_meta: dict[str, Any] | None = None,
    results: list[dict[str, Any]] | None = None,
) -> None:
    """Write a sibling summary.md with the merged result + plan, so
    the file ops left bar can show the whole run as a real artifact.

    When `planner_meta` / `results` are supplied, also write a **token
    ledger** — planner + per-worker provider/model + prompt/completion
    tokens, with totals. This is the single artifact the hybrid-split
    experiment reads to compare vendor-only vs strong-planner/local-
    worker runs (see work-plan.md SESSION HANDOFF)."""
    runs_dir = statedir.runs_dir(workspace, parent_run_id)
    runs_dir.mkdir(parents=True, exist_ok=True)
    plan_lines = [
        f"## Plan ({len(tasks)} workers)",
        "",
    ]
    for i, t in enumerate(tasks):
        plan_lines.append(
            f"{i + 1}. **{t.get('difficulty', 'normal')}** — {t.get('description', '')}"
        )
    ledger = _token_ledger(planner_meta, results)
    body = (
        f"# Fan-out run {parent_run_id}\n\n"
        f"_Original request:_ {text}\n\n"
        f"---\n\n"
        + "\n".join(plan_lines)
        + ledger
        + "\n\n---\n\n## Merged result\n\n"
        + merged
    )
    try:
        (runs_dir / "summary.md").write_text(body, encoding="utf-8")
    except OSError:
        log.exception("failed to write fan-out summary")


def _token_ledger(
    planner_meta: dict[str, Any] | None,
    results: list[dict[str, Any]] | None,
) -> str:
    """Render a markdown token-cost table for the run. Empty string
    when nothing to report (keeps pre-instrumentation callers clean)."""
    if not planner_meta and not results:
        return ""
    rows: list[tuple[str, str, Any, Any]] = []
    tot_in = 0
    tot_out = 0

    def _row(label: str, meta: dict[str, Any]) -> None:
        nonlocal tot_in, tot_out
        it = meta.get("input_tokens")
        ot = meta.get("output_tokens")
        who = f"{meta.get('provider', '?')}/{meta.get('model', '?')}"
        rows.append((label, who, it, ot))
        if isinstance(it, int):
            tot_in += it
        if isinstance(ot, int):
            tot_out += ot

    if planner_meta:
        _row("planner", planner_meta)
    for r in results or []:
        if not isinstance(r, dict):
            continue
        _row(f"worker {r.get('worker_index', 0)}", r)

    lines = [
        "\n\n---\n\n## Token ledger",
        "",
        "| leg | provider/model | prompt | completion |",
        "| --- | --- | ---: | ---: |",
    ]
    for label, who, it, ot in rows:
        lines.append(
            f"| {label} | {who} | {it if it is not None else '—'} "
            f"| {ot if ot is not None else '—'} |"
        )
    lines.append(f"| **total** | | **{tot_in}** | **{tot_out}** |")
    return "\n".join(lines)


def append_to_rail_log(
    workspace: Path, thread_id: str, *, parent_run_id: str, merged: str,
) -> None:
    """Persist the merged final into the thread's rail log so future
    recall_rail finds it. Keyed to the parent run_id so the dashboard
    transcript expander shows the merger result alongside the planner
    + worker rows."""
    conversations.append_event(
        workspace, thread_id, "assistant", merged,
        run_id=parent_run_id,
    )
