"""One chat turn against the selected provider.

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
from switchbay import ce_tools
from switchbay import command_palettes
from switchbay import conversations
from switchbay import html_decks
from switchbay import llmgateway
from switchbay import localllm
from switchbay import micro_edits
from switchbay import permissions
from switchbay import proposals
from switchbay import protocol
from switchbay import reports
from switchbay import tools
from switchbay import ui_focus
from switchbay.agents import rail_default

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

async def _dispatch_chat(
    app: web.Application,
    ws: web.WebSocketResponse | None,
    text: str,
    *,
    input_excerpt: str | None = None,
    run_id: str | None = None,
    workspace_override: Path | None = None,
    thread_id_override: str | None = None,
    provider_override: str | None = None,
    model_override: str | None = None,
    max_turns: int | None = None,
    extra_system: str | None = None,
    tool_palette: str | None = None,
    command: str | None = None,
    command_template: str | None = None,
    desk_id: str | None = None,
) -> str | None:
    """Run the rail agent against `text`. Multi-turn: streams assistant
    text + tool_use blocks back to every connected client; when the
    model wants a tool, executes it via the tools registry and feeds
    the result back into the next turn. Bounded by _AGENT_MAX_TURNS
    so a misbehaving model can't loop forever.

    `ws` may be None for headless background dispatches (e.g. the
    autopopulate-slides endpoint kicks off a run without a rail
    thread in flight). Early-bail notices route to the WS when
    set, otherwise broadcast to every connected client.

    `workspace_override` / `thread_id_override` bind this dispatch to a
    SPECIFIC workspace + thread instead of the daemon's focused
    globals — the cross-workspace steer path, where the user inputs to a
    run that lives in another workspace. The session resumes by thread,
    and the foreground `app["thread_id"]` is left untouched.

    Returns the run_id once the run is registered, or None on early
    bail (so callers can surface it to the requesting HTTP client).

    `provider_override` / `model_override` pin this dispatch to a
    specific provider+model instead of the workspace default — the CE-
    action path uses it to route heavy curate/ingest grunt work to the
    ladder's worker rung (e.g. the local model) without flipping the
    global default provider. Callers must pass an available+keyed
    provider id (the CE-action resolver checks first and falls back to
    None → default when the rung is unavailable).

    `extra_system` is appended to the system prompt (not the user
    turn) so Jump on a failed background run does not dump steering
    text into the rail transcript.

    `tool_palette` selects a local-model tool subset (``chat`` or
    ``curate``) when no `command` is set. `command` (slash name or
    internal key like ``deck``) picks a command-specific desk;
    `command_template` is the user-command markdown used to infer
    tools. Ignored for cloud providers.
    """
    workspace: Path = workspace_override or app["workspace"]
    # Micro-edit autorouter: short UI-focused edits use the micro-edit
    # policy rung (default trivial) when no explicit override is set.
    micro_meta: dict[str, Any] | None = None
    if provider_override is None and model_override is None:
        # thread id not fully known yet — peek focused for classifier path
        tid_peek = thread_id_override or app.get("thread_id")
        if isinstance(tid_peek, str) or tid_peek is None:
            try:
                if micro_edits.is_micro_edit(workspace, text):
                    resolved = micro_edits.resolve_micro_dispatch(
                        workspace, tid_peek if isinstance(tid_peek, str) else None,
                    )
                    if resolved:
                        provider_override, model_override, mrung = resolved
                        micro_meta = {
                            "rung": mrung,
                            "provider": provider_override,
                            "model": model_override,
                            "original_text": text,
                        }
            except Exception:  # noqa: BLE001
                log.exception("micro-edit classify failed")

    pid = provider_override or _daemon_ns._resolve_default_provider()
    try:
        provider = llmgateway.get(pid)
    except llmgateway.ProviderError as e:
        notice = protocol.notice(f"llm: {e}", kind="chat")
        if ws is not None:
            await ws.send_json(notice)
        else:
            await _daemon_ns._broadcast(app, notice)
        return None

    if not provider.has_key():
        notice = protocol.notice(
            f"no API key configured for {provider.LABEL}. Open Settings (top-right gear) to add one.",
            kind="chat",
        )
        if ws is not None:
            await ws.send_json(notice)
        else:
            await _daemon_ns._broadcast(app, notice)
        return None

    run_id = run_id or f"run-{uuid.uuid4().hex[:8]}"
    model = (
        model_override or _daemon_ns._effective_model(pid)
        or provider.PROVIDER.get("default_model", "?")
    )
    if micro_meta:
        micro_meta["run_id"] = run_id
        notice = protocol.notice(
            f"micro-edit · {micro_meta['rung']} · {pid} · {model}",
            kind="chat",
        )
        if ws is not None:
            await ws.send_json(notice)
        else:
            await _daemon_ns._broadcast(app, notice)
    # Resolve the thread BEFORE announcing the run — AG-UI RUN_STARTED
    # carries `threadId`, so the id must exist first.
    if thread_id_override:
        # Steer path: continue the run's OWN thread; never touch the
        # focused workspace's foreground thread pointer.
        thread_id = thread_id_override
    elif ws is None:
        # Headless background dispatch (curator-profile draft, ingest,
        # plots, pack actions): never inherit the user's focused
        # thread — it may be an interactive-pty (the kind backstop
        # below would silently kill the run), mid-stream (reject-busy),
        # or simply not ours to write a synthetic user turn into. Each
        # background job gets its own thread, same as A2A sends; the
        # dashboard's jump-to-run lands on its transcript.
        thread_id = await asyncio.to_thread(
            conversations.new_thread, workspace, input_excerpt or None,
        )
    else:
        thread_id = app.get("thread_id")
        if not thread_id:
            thread_id = await asyncio.to_thread(conversations.new_thread, workspace)
            app["thread_id"] = thread_id
            app["thread_kind"] = "structured-agent"
    # Kind backstop: chat never dispatches into an `interactive-pty`
    # thread — its surface is the xterm, its "runs" are shells. The
    # composer is hidden client-side on pty threads; this covers other
    # clients / headless / steer callers. Cache-first (glue writers
    # may focus a thread without knowing its kind → DB lookup).
    kind = app.get("thread_kind") if thread_id == app.get("thread_id") else None
    if kind is None:
        kind = await asyncio.to_thread(conversations.thread_kind, workspace, thread_id)
        if thread_id == app.get("thread_id") and kind:
            app["thread_kind"] = kind
    if kind == "interactive-pty":
        notice = protocol.notice(
            "this is a shell thread — type in its terminal, or start a "
            "new thread for chat.",
            kind="chat",
        )
        if ws is not None:
            await ws.send_json(notice)
        else:
            await _daemon_ns._broadcast(app, notice)
        return None
    # Reject-busy guard: one streaming run per thread. A second dispatch
    # would double-resume the thread's provider session mid-stream
    # (claude-code/codex resume ids are single-consumer). Surface a
    # notice instead of corrupting the stream; the user can wait or
    # start a new thread.
    busy = [
        r for r in (app.get("runs") or {}).values()
        if r.get("thread_id") == thread_id and r.get("run_id") != run_id
        and r.get("status") in _daemon_ns._ORCH_BUSY_STATUSES
    ]
    if busy:
        notice = protocol.notice(
            f"thread is busy — {busy[0].get('run_id')} is still streaming. "
            "Wait for it to finish, or start a new thread.",
            kind="chat",
        )
        if ws is not None:
            await ws.send_json(notice)
        else:
            await _daemon_ns._broadcast(app, notice)
        return None
    await _daemon_ns._broadcast(app, protocol.run_started(
        thread_id, run_id, pid, model, str(workspace),
    ))
    # Register this run in the live-runs registry so the Agent
    # Dashboard tab can monitor it. Updates are best-effort: each
    # tool call / chunk bumps `last_chunk_at`, the finally block
    # below removes the entry. The asyncio.Task handle is captured
    # via current_task() so the dashboard's kill button can cancel.
    runs: dict[str, dict[str, Any]] = app.setdefault("runs", {})
    runs[run_id] = {
        "run_id": run_id,
        "provider": pid,
        "model": model,
        # Headless dispatchers (autopopulate-slides, etc.) often want
        # a friendlier label in the dashboard than the raw prompt
        # head. Fall back to the prompt prefix when nothing is
        # supplied, matching the rail's behaviour.
        "input_excerpt": (input_excerpt or text)[:120],
        "started_at": time.time(),
        "last_chunk_at": time.time(),
        "tool_count": 0,
        "status": "running",
        "task": asyncio.current_task(),
        # Which workspace this run belongs to — the Agent Dashboard is
        # cross-workspace, so it labels/groups runs by this and resolves
        # each run's transcript against its OWN workspace DB.
        "workspace": str(workspace),
        "workspace_name": workspace.name,
        # Background runs (no WS) run independently of any rail
        # thread — the dashboard shows them as background.
        "is_background": ws is None,
        "micro_edit": micro_meta,
        "command": command,
        "desk_id": desk_id,
    }
    if desk_id is None and command:
        from switchbay import kernel as sbk
        desk_id = sbk.choose_desk(command=command, text=text)
        runs[run_id]["desk_id"] = desk_id
    if desk_id:
        from switchbay import kernel as sbk
        try:
            sbk.seat(
                workspace, desk_id,
                chief_provider=pid,
                chief_model=model,
                thread_id=thread_id,
                run_id=run_id,
                objective=text,
            )
        except Exception:  # noqa: BLE001
            log.exception("desk seat on chat start failed")
    _daemon_ns._remember_run_workspace(app, run_id, workspace)
    _daemon_ns._remember_run_palette(app, run_id, command, command_template)

    # Provider resume sessions are keyed by the THREAD, not the
    # provider — so rail multi-turn (a new run_id each turn) resumes the
    # same thread, while two workspaces on the same CLI never clobber
    # each other's session.
    sessions: dict[str, str] = app.setdefault("llm_sessions", {})

    # Rail event log (Tier 1): every event lands in the workspace's
    # conversations.db. Working set sent to the provider is the last
    # WORKING_SET_TURNS chat turns; everything else (tool calls,
    # off-rail events) is queryable via the recall_rail tool.
    #
    # Stamp the run with its thread so a later steer can resume the
    # exact thread (the provider session is keyed by thread_id below).
    if run_id in runs:
        runs[run_id]["thread_id"] = thread_id
    _daemon_ns._remember_run_thread(app, run_id, thread_id)
    session_id = sessions.get(thread_id)
    # Await this one: working_set must see the just-typed user turn.
    await _daemon_ns._append_event_wait(app, workspace, thread_id, "user", text, run_id=run_id)
    # Auto-title: the thread's FIRST user turn kicks a background
    # naming pass (small model, fail-soft) so the switcher shows a
    # real label within seconds of creation. Later turns skip it.
    if await asyncio.to_thread(
        conversations.chat_event_count, workspace, thread_id,
    ) == 1:
        asyncio.get_running_loop().create_task(
            _daemon_ns._auto_title_thread(app, workspace, thread_id),
        )
    messages = await asyncio.to_thread(conversations.working_set, workspace, thread_id)

    # Local-model harness (LOCAL MODEL ONLY): append its auto-tunable
    # operating rules to the system prompt, and arm a run-wide loop guard
    # that short-circuits repeated identical tool calls. Ornith is smaller
    # and tends to circle (e.g. ls/search to "find" a skill); other
    # providers are untouched.
    is_local_model = localllm.is_local_provider(pid)
    local_palette = (tool_palette or "chat") if is_local_model else None
    local_rung = None
    cmd_only_tools: list[str] | None = None
    cmd_resolved = None
    if is_local_model:
        _cfg = await asyncio.to_thread(localllm.load_config)
        local_rung = rail_default.resolve_local_rung(
            localllm.ram_gb(),
            model_hint=rail_default.model_hint_from_cfg(_cfg),
        )
        cmd_key = command or (
            tool_palette if tool_palette not in (None, "chat") else None
        )
        if cmd_key:
            cmd_resolved = await asyncio.to_thread(
                command_palettes.resolve,
                workspace, cmd_key,
                rung=local_rung,
                template=command_template,
            )
        if cmd_resolved is not None:
            cmd_only_tools = list(cmd_resolved.tools)
            local_palette = f"cmd:{cmd_resolved.name}"
        do_hygiene = (
            cmd_resolved is not None and cmd_resolved.kind == "curate"
        ) or (cmd_resolved is None and local_palette == "curate")
        if do_hygiene:
            sweep = await asyncio.to_thread(
                ce_tools.mechanical_hygiene, workspace,
            )
            prelude = rail_default.format_sweep_prelude(sweep)
            extra_system = (
                f"{extra_system}\n\n{prelude}" if extra_system else prelude
            )
    if is_local_model:
        system_prompt, tools_for_provider, messages, _pstats = (
            rail_default.assemble_local_prompt(
                palette=local_palette or "chat",
                extra_system=extra_system or "",
                harness=(
                    localllm.harness_body()
                    if localllm.harness_applies_to(pid) else ""
                ),
                messages=messages,
                rung=local_rung,
                only_tools=cmd_only_tools,
            )
        )
        palette_names = {str(t.get("name") or "") for t in tools_for_provider}
        log.info(
            "local prompt rung=%s palette=%s cmd=%s tools=%s tokens~%s "
            "(sys=%s tools=%s msgs=%s trimmed=%s scaffold=%s clipped=%s)",
            _pstats.get("rung"), _pstats.get("palette"),
            command or "",
            _pstats.get("n_tools"), _pstats.get("total"),
            _pstats.get("system"), _pstats.get("tools"),
            _pstats.get("messages"), _pstats.get("trimmed"),
            _pstats.get("force_scaffold"),
            _pstats.get("clipped_tools") or [],
        )
    else:
        tools_for_provider = rail_default.tools_for_provider(local=False)
        palette_names = set(rail_default.ALLOWED_TOOLS)
        system_prompt = rail_default.SYSTEM_PROMPT
        if extra_system:
            system_prompt = f"{system_prompt}\n\n{extra_system}"
    # Live tab focus (Sheet / Table / Plot / Sketch) so agents act on
    # what the user is looking at instead of hunting the wiki.
    try:
        _ui_line = await asyncio.to_thread(ui_focus.combined_prompt_lines, workspace)
        if _ui_line and not is_local_model:
            system_prompt = f"{system_prompt}\n\n{_ui_line}"
        elif _ui_line and is_local_model:
            # Keep one line of focus; don't dump full sheet context.
            short = _ui_line.strip().splitlines()[0][:240]
            system_prompt = f"{system_prompt}\n\n{short}"
    except Exception:  # noqa: BLE001
        pass
    # Exclusion rules ride the hidden system prompt. A missing or
    # unreadable rules file must not stop the turn.
    try:
        from switchbay.federation.exclusion import load as _exclusion_load, prompt_block
        block = prompt_block(_exclusion_load(workspace))
        if block:
            system_prompt = f"{system_prompt}\n\n{block}"
    except Exception:  # noqa: BLE001
        pass
    try:
        from switchbay.federation.session_label import set_current
        set_current(str(thread_id or run_id or "rail"), workspace)
    except Exception:  # noqa: BLE001
        pass
    executed_calls: dict[str, int] = {}
    loop_hits = 0
    wiki_cites: list[str] = []

    final_done: tuple[int | None, int | None, str | None] = (None, None, None)
    usage_in = 0
    usage_out = 0
    # Run-start artifact fence: registry tools may execute in-daemon or in an
    # MCP subprocess. Neither storage handler broadcasts, so scan new reports
    # and slideshows at run-end and open their transient tabs consistently.
    _artifact_fence = time.time()

    # No functional limit — loop detection (below) is what stops a run early.
    # `turns_cap` is only the last-resort safety backstop; callers may raise it
    # further but never below the backstop.
    turns_cap = max(max_turns or 0, _daemon_ns._AGENT_SAFETY_BACKSTOP)
    try:
        for turn in range(turns_cap):
            req = llmgateway.ChatRequest(
                messages=messages,
                model=model,
                system=system_prompt,
                tools=tools_for_provider or None,
                session_id=session_id,
                workspace=str(workspace),
                max_tokens=(
                    1024
                    if is_local_model and local_rung is not None
                    and getattr(local_rung, "force_scaffold", False)
                    else 4096
                ),
                reasoning=(
                    False
                    if is_local_model and local_rung is not None
                    and getattr(local_rung, "force_scaffold", False)
                    else None
                ),
                origin_thread=thread_id,
                # Same loop serves interactive rail chat and micro-edits
                # (the latter arrives with provider/model overridden), so
                # the lane follows which one this turn actually is.
                reasoning_effort=_daemon_ns._effort_for(
                    pid, model, "micro" if micro_meta else "rail",
                    workspace=workspace,
                    rung_effort=(
                        micro_edits.micro_effort(workspace, thread_id)
                        if micro_meta else None
                    ),
                ),
            )
            assistant_blocks: list[dict] = []
            current_text = ""
            reasoning_text = ""

            async def _flush_reasoning() -> None:
                """Emit the accumulated chain-of-thought for this segment
                as a collapsible rail block + persist it (payload only,
                so recall never pulls reasoning into context). Never
                added to assistant_blocks → not replayed to the model."""
                nonlocal reasoning_text
                rzn = reasoning_text.strip()
                reasoning_text = ""
                if not rzn:
                    return
                rid = protocol.new_message_id()
                await _daemon_ns._broadcast(app, protocol.reasoning(run_id, rid, rzn))
                _daemon_ns._append_event(
                    app, workspace, thread_id, "reasoning", rzn[:280],
                    source="assistant", actor="reasoning",
                    payload={"text": rzn}, run_id=run_id,
                )
            # AG-UI message framing: one messageId per assistant text
            # segment. A segment opens on the first text delta and
            # closes at a tool call or end-of-stream — the exact
            # boundaries the persistence flushes below already use.
            msg_id: str | None = None
            stop_reason: str | None = None
            input_tokens: int | None = None
            output_tokens: int | None = None

            async for ev in provider.chat_stream(req):
                if isinstance(ev, llmgateway.TextChunk):
                    if msg_id is None:
                        msg_id = protocol.new_message_id()
                        await _daemon_ns._broadcast(app, protocol.text_message_start(run_id, msg_id))
                    await _daemon_ns._broadcast(app, protocol.text_message_content(run_id, msg_id, ev.text))
                    current_text += ev.text
                    if run_id in runs:
                        runs[run_id]["last_chunk_at"] = time.time()
                        # Show the user what's being typed right now in
                        # the dashboard. Trail-of-the-stream rather
                        # than head — the latest 80 chars give the
                        # user better signal that progress is being
                        # made on prose-heavy turns.
                        runs[run_id]["activity"] = current_text[-120:].lstrip()
                elif isinstance(ev, llmgateway.ReasoningChunk):
                    # Private chain-of-thought — accumulate; flushed as a
                    # collapsible block at the segment boundary. Keep the
                    # dashboard alive so a long think doesn't read as a
                    # stall.
                    reasoning_text += ev.text
                    if run_id in runs:
                        runs[run_id]["last_chunk_at"] = time.time()
                        runs[run_id]["activity"] = "💭 " + reasoning_text[-110:].lstrip()
                elif isinstance(ev, llmgateway.ToolUseChunk):
                    # Thinking that led to this call belongs before it.
                    await _flush_reasoning()
                    if run_id in runs:
                        runs[run_id]["tool_count"] += 1
                        runs[run_id]["last_chunk_at"] = time.time()
                        # Snapshot the tool the agent just kicked off.
                        # Held until a tool_result for this id arrives
                        # (downstream loop), so the dashboard shows
                        # "running Bash …" while a long-running
                        # subprocess executes.
                        runs[run_id]["activity"] = (
                            f"⚙ {ev.name}({_daemon_ns._summarise_input(ev.input)})"
                        )
                        runs[run_id]["current_tool"] = ev.name
                    if msg_id is not None:
                        # Close the open assistant message at the tool
                        # boundary — the next prose gets a fresh id.
                        await _daemon_ns._broadcast(app, protocol.text_message_end(run_id, msg_id))
                        msg_id = None
                    if current_text:
                        assistant_blocks.append({"type": "text", "text": current_text})
                        # Flushing assistant prose ahead of a tool_use:
                        # persist what we have so far, then reset.
                        _daemon_ns._append_event(app,
                            workspace, thread_id, "assistant", current_text,
                            run_id=run_id,
                        )
                        current_text = ""
                    assistant_blocks.append({
                        "type": "tool_use",
                        "id": ev.id,
                        "name": ev.name,
                        "input": ev.input,
                    })
                    # Distinguish ours (the daemon will execute these and
                    # emit a paired tool_result event) from the
                    # provider's own internal tools (e.g. claude-code's
                    # Bash/Read — handled inside the CLI; we only see
                    # the call, not the result).
                    is_ours = ev.name in tools.REGISTRY
                    _daemon_ns._append_event(app,
                        workspace, thread_id, "tool_use",
                        f"{ev.name}({_daemon_ns._summarise_input(ev.input)})",
                        source="rail" if is_ours else f"agent:{pid}",
                        actor=ev.name,
                        payload={"id": ev.id, "name": ev.name, "input": ev.input},
                        ref_id=ev.id, run_id=run_id,
                    )
                    # AG-UI tool-call framing. Our providers deliver the
                    # complete input at once, so START/ARGS/END go out
                    # back-to-back; the RESULT event follows once the
                    # tool actually runs (loop below / provider-internal).
                    await _daemon_ns._broadcast(app, protocol.tool_call_start(run_id, ev.id, ev.name))
                    await _daemon_ns._broadcast(app, protocol.tool_call_args(
                        run_id, ev.id, json.dumps(ev.input or {}),
                    ))
                    await _daemon_ns._broadcast(app, protocol.tool_call_end(run_id, ev.id))
                    # File-affecting tool calls from the provider's own
                    # toolbox (Write/Edit/MultiEdit/NotebookEdit) hit
                    # the disk inside the CLI without going through any
                    # of our handlers — the file browser would never
                    # learn about them otherwise. Surface a hint.
                    if ev.name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
                        await _daemon_ns._broadcast(app, protocol.files_changed())
                        # Wiki edits also need a graph rebuild — schedule
                        # one in the background so the model's next turn
                        # doesn't block on it. A wiki-page write is also
                        # a user-facing artifact (Zen pulse → Editor).
                        try:
                            inp = ev.input or {}
                            fp = str(inp.get("file_path") or inp.get("path") or "")
                            if "/wiki/" in fp or fp.startswith("wiki/"):
                                asyncio.create_task(_daemon_ns._rebuild_graph_async(app))
                            wiki_art = _daemon_ns._wiki_artifact_for_write(workspace, fp)
                            if wiki_art is not None:
                                await _daemon_ns._broadcast(app, wiki_art)
                        except Exception:  # noqa: BLE001
                            log.exception("graph rebuild scheduling failed")
                elif isinstance(ev, llmgateway.DoneChunk):
                    stop_reason = ev.stop_reason
                    input_tokens = ev.input_tokens
                    output_tokens = ev.output_tokens
                    # Capture provider-issued session id so the next
                    # turn on THIS thread can resume it. Keyed by
                    # thread_id (not provider) → rail multi-turn resumes,
                    # cross-workspace runs stay isolated.
                    if ev.session_id:
                        session_id = ev.session_id
                        sessions[thread_id] = ev.session_id

            if stop_reason != "tool_use" and wiki_cites:
                cited = _daemon_ns._with_wiki_cites(current_text, wiki_cites)
                if cited != current_text:
                    extra = cited[len(current_text):]
                    if msg_id is None:
                        msg_id = protocol.new_message_id()
                        await _daemon_ns._broadcast(
                            app, protocol.text_message_start(run_id, msg_id),
                        )
                    await _daemon_ns._broadcast(
                        app, protocol.text_message_content(run_id, msg_id, extra),
                    )
                    current_text = cited
            if stop_reason != "tool_use" and current_text:
                from switchbay.federation.session_label import answer_label, stamp_reply
                stamped = stamp_reply(current_text, answer_label(workspace, []))
                if stamped != current_text:
                    extra = stamped[len(current_text):]
                    if msg_id is None:
                        msg_id = protocol.new_message_id()
                        await _daemon_ns._broadcast(
                            app, protocol.text_message_start(run_id, msg_id),
                        )
                    await _daemon_ns._broadcast(
                        app, protocol.text_message_content(run_id, msg_id, extra),
                    )
                    current_text = stamped
            if msg_id is not None:
                # Stream ended with prose open — close the message.
                await _daemon_ns._broadcast(app, protocol.text_message_end(run_id, msg_id))
                msg_id = None
            # Any trailing chain-of-thought (a turn that reasoned then
            # answered with prose, or reasoned then stopped).
            await _flush_reasoning()
            if current_text:
                assistant_blocks.append({"type": "text", "text": current_text})
                # Persist the assistant's prose so future recall finds
                # it. tool_use / tool_result events are persisted
                # separately (see the ToolUseChunk branch above and
                # the tool-result loop below) so the rail log captures
                # the full agent step.
                _daemon_ns._append_event(app,
                    workspace, thread_id, "assistant", current_text,
                    run_id=run_id,
                )
            final_done = (input_tokens, output_tokens, stop_reason)
            if isinstance(input_tokens, int):
                usage_in += input_tokens
            if isinstance(output_tokens, int):
                usage_out += output_tokens

            if stop_reason != "tool_use":
                # Resolve any provider-internal tool_uses (e.g. claude-code
                # running its own Bash/Read/ToolSearch). We never see a
                # structured tool_result for those — the CLI handles them
                # inline before completing the turn — so the rail cursor
                # would spin forever and the log would be unbalanced
                # without a synthesised completion.
                for block in assistant_blocks:
                    if block.get("type") != "tool_use":
                        continue
                    tname = str(block.get("name", ""))
                    if tname in tools.REGISTRY:
                        # A registry tool in a NON-tool_use stop means a
                        # CLI provider ran it through the MCP bridge —
                        # we saw the call, never a result (HTTP providers
                        # stop with "tool_use" and take the execute loop
                        # below, which emits with the real output).
                        # Announce the artifact optimistically from the
                        # input; a failed tool yields one false pulse.
                        binput = block.get("input")
                        art = _daemon_ns._artifact_for_tool(
                            tname, binput if isinstance(binput, dict) else {}, None,
                        )
                        if art is not None:
                            await _daemon_ns._broadcast(app, art)
                        continue  # result was the MCP bridge's business
                    tid = str(block.get("id", ""))
                    synth = f"(handled internally by {pid})"
                    _daemon_ns._append_event(app,
                        workspace, thread_id, "tool_result", synth,
                        source=f"agent:{pid}", actor=tname, ref_id=tid,
                        payload={"ok": True, "internal": True},
                        run_id=run_id,
                    )
                    await _daemon_ns._broadcast(app, protocol.tool_call_result(
                        run_id, tid, protocol.new_message_id(), synth, True,
                    ))
                break

            # Execute the tools the model requested, feed results back.
            messages.append({"role": "assistant", "content": assistant_blocks})
            tool_results: list[dict] = []
            for block in assistant_blocks:
                if block.get("type") != "tool_use":
                    continue
                tid = str(block.get("id", ""))
                tname = str(block.get("name", ""))
                tinput = block.get("input") or {}
                if not isinstance(tinput, dict):
                    tinput = {}
                # Loop guard (local model only): if this exact call already
                # ran this run, don't re-run it — return a corrective
                # result to break the circle instead of feeding it.
                if is_local_model:
                    ckey = f"{tname}\x00{json.dumps(tinput, sort_keys=True, default=str)}"
                    if executed_calls.get(ckey, 0) >= 1:
                        loop_hits += 1
                        executed_calls[ckey] += 1
                        guard = (
                            f"(loop guard) You already ran {tname} with these "
                            "exact arguments; the result is unchanged. Do NOT "
                            "repeat tool calls. Prefer a different covered "
                            "tool, or load_skill with detail=frontmatter / a "
                            "new section; otherwise answer now with what you "
                            "have."
                        )
                        tool_results.append({
                            "type": "tool_result", "tool_use_id": tid,
                            "content": guard, "is_error": True,
                        })
                        _daemon_ns._append_event(app,
                            workspace, thread_id, "tool_result",
                            "(loop guard) duplicate call suppressed",
                            actor=tname, ref_id=tid,
                            payload={"ok": False, "loop_guard": True},
                            run_id=run_id,
                        )
                        await _daemon_ns._broadcast(app, protocol.tool_call_result(
                            run_id, tid, protocol.new_message_id(),
                            "(loop guard) duplicate call suppressed", False,
                        ))
                        continue
                    executed_calls[ckey] = executed_calls.get(ckey, 0) + 1
                # Enforce this run's tool palette (local) / allowlist.
                if tname not in palette_names:
                    err = f"tool '{tname}' not in this run's tool palette"
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tid,
                        "content": err,
                        "is_error": True,
                    })
                    _daemon_ns._append_event(app,
                        workspace, thread_id, "tool_result", err,
                        actor=tname, ref_id=tid,
                        payload={"ok": False, "error": err},
                        run_id=run_id,
                    )
                    await _daemon_ns._broadcast(app, protocol.tool_call_result(
                        run_id, tid, protocol.new_message_id(), err, False,
                    ))
                    continue
                try:
                    # Off-thread: handlers are sync (file/sqlite work,
                    # and ask_thread does a blocking localhost HTTP
                    # call back into this daemon — on the loop that
                    # would deadlock).
                    if is_local_model and tname == "load_skill":
                        # Progressive: never dump a 26k-token skill
                        # into a small window. Frontmatter / one section.
                        if not tinput.get("section"):
                            det = str(tinput.get("detail") or "frontmatter")
                            if det == "full":
                                tinput = {**tinput, "detail": "frontmatter"}
                    if is_local_model and tname in (
                        "propose_wiki_page", "propose_page_edit",
                    ) and (local_rung is None or local_rung.force_scaffold):
                        tinput = {**tinput, "scaffold": True}
                    if permissions.needs_web_consent(tname, tinput):
                        verdict, reason = await permissions.mediate_protected_call(
                            workspace=workspace, tool=tname, tool_input=tinput,
                            provider=str(pid or "switchbay"),
                            run_id=run_id, thread_id=thread_id,
                            broadcast=lambda msg: _daemon_ns._broadcast(app, msg),
                        )
                        if verdict != "approve":
                            output = {"ok": False, "error": reason}
                        else:
                            output = await asyncio.to_thread(
                                tools.execute, tname, workspace, tinput,
                                consent=permissions.trusted_consent(),
                            )
                    else:
                        output = await asyncio.to_thread(
                            tools.execute, tname, workspace, tinput,
                        )
                    if isinstance(output, dict) and output.get("needs_dialog"):
                        await _daemon_ns._broadcast(app, protocol.custom({
                            "type": "public_write",
                            "mount": str(output.get("mount") or ""),
                        }))
                    # Cap results for every model — a 100-turn curate
                    # that stuffed unbounded JSON into `messages` is a
                    # plausible path to multi-GB RSS.
                    output = _daemon_ns._cap_tool_output(
                        tname, output, local=is_local_model,
                    )
                    for cite in _daemon_ns._wiki_cites_from_tool(tname, output):
                        if tname == "read_wiki_page":
                            if cite in wiki_cites:
                                wiki_cites.remove(cite)
                            wiki_cites.insert(0, cite)
                        elif cite not in wiki_cites:
                            wiki_cites.append(cite)
                    payload = json.dumps(output)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tid,
                        "content": payload,
                    })
                    summary = _daemon_ns._summarise(output)
                    _daemon_ns._append_event(app,
                        workspace, thread_id, "tool_result", summary,
                        actor=tname, ref_id=tid,
                        payload={"ok": True, "output": output},
                        run_id=run_id,
                    )
                    await _daemon_ns._broadcast(app, protocol.tool_call_result(
                        run_id, tid, protocol.new_message_id(), summary, True,
                    ))
                    # Artifact-producing tools (plots, decks, slides)
                    # additionally announce WHAT landed — Zen's pulse
                    # badge jumps to the exact artifact from this.
                    art = _daemon_ns._artifact_for_tool(tname, tinput, output)
                    if art is not None:
                        await _daemon_ns._broadcast(app, art)
                    if tname in (
                        "propose_wiki_page", "propose_page_edit",
                        "propose_charter_edit",
                    ) and isinstance(output, dict) and output.get("ok"):
                        rel = str(output.get("path") or "")
                        if rel:
                            _daemon_ns._schedule_after_wiki_write(app, workspace, rel)
                except Exception as e:  # noqa: BLE001
                    log.exception("tool %s crashed", tname)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tid,
                        "content": f"error: {e}",
                        "is_error": True,
                    })
                    _daemon_ns._append_event(app,
                        workspace, thread_id, "tool_result", f"error: {e}",
                        actor=tname, ref_id=tid,
                        payload={"ok": False, "error": str(e)},
                        run_id=run_id,
                    )
                    await _daemon_ns._broadcast(app, protocol.tool_call_result(
                        run_id, tid, protocol.new_message_id(), str(e), False,
                    ))

            # Circling on repeated no-progress calls → stop the run. This
            # loop guard (not the turn cap) is the real bound on a misbehaving
            # run, and it applies to EVERY model — a low turn cap used to be
            # the only thing stopping a non-local model from looping, which
            # also killed legitimately long tasks. Local models additionally
            # get a background harness-refinement pass (self-optimizing).
            loop_limit = 3 if is_local_model else 5
            if loop_hits >= loop_limit:
                if is_local_model:
                    await _daemon_ns._broadcast(app, protocol.notice(
                        "Local model was looping on repeated tool calls — "
                        "stopped this run. Refining its harness in the "
                        "background so it improves next time.",
                        kind="chat",
                        workspace=str(workspace),
                        run_id=run_id,
                        thread_id=thread_id,
                    ))
                    asyncio.create_task(
                        _daemon_ns._autotune_local_harness(app, workspace, run_id),
                    )
                else:
                    await _daemon_ns._broadcast(app, protocol.notice(
                        "Agent kept repeating the same tool calls without "
                        "progress — stopped this run.",
                        kind="chat",
                        workspace=str(workspace),
                        run_id=run_id,
                        thread_id=thread_id,
                    ))
                break
            messages.append({"role": "user", "content": tool_results})
            if is_local_model and local_rung is not None:
                messages = rail_default.clip_messages_to_budget(
                    system_prompt, tools_for_provider or [],
                    messages, local_rung.prompt_budget,
                )
                log.info(
                    "local prompt after tools tokens~%s (budget=%s, n_msg=%s)",
                    rail_default.prompt_token_breakdown(
                        system_prompt, tools_for_provider or [], messages,
                    ).get("total"),
                    local_rung.prompt_budget, len(messages),
                )
        else:
            # Reached the last-resort safety backstop without the model
            # finishing or the loop guard firing — treat as a runaway and stop.
            # Should be unreachable in a healthy run. Still a real run with
            # persisted turns — report the run_id (the docstring's contract;
            # A2A's message/send reads the reply back by it).
            await _daemon_ns._broadcast(
                app,
                protocol.run_error(
                    run_id, "server",
                    f"agent hit the {turns_cap}-turn safety backstop without "
                    "completing — stopped to avoid a runaway", thread_id,
                ),
            )
            return run_id

        await _daemon_ns._broadcast(app, protocol.run_finished(thread_id, run_id, *final_done))
        # First micro-edit calibration card (non-blocking rail card).
        try:
            mm = (runs.get(run_id) or {}).get("micro_edit")
            if isinstance(mm, dict) and micro_edits.should_show_feedback(
                workspace, thread_id,
            ):
                fid = micro_edits.new_feedback_id()
                micro_edits.store_pending_feedback(
                    fid,
                    workspace=workspace,
                    thread_id=thread_id,
                    original_text=str(mm.get("original_text") or text),
                    rung_used=str(mm.get("rung") or "trivial"),  # type: ignore[arg-type]
                    provider=str(mm.get("provider") or pid),
                    model=str(mm.get("model") or model),
                )
                await _daemon_ns._broadcast(app, protocol.custom({
                    "type": "micro_edit.feedback",
                    "id": fid,
                    "rung_used": mm.get("rung") or "trivial",
                    "provider": mm.get("provider") or pid,
                    "model": mm.get("model") or model,
                    "thread_id": thread_id,
                    "original_text": str(mm.get("original_text") or text)[:280],
                }))
        except Exception:  # noqa: BLE001
            log.exception("micro-edit feedback broadcast failed")
        # Open any rich report this run produced (newest last → focused).
        new_reports = await asyncio.to_thread(
            reports.created_since, workspace, _artifact_fence)
        for meta in new_reports:
            await _daemon_ns._open_report_tab(app, workspace, meta["id"],
                                   meta.get("title") or "Report")
        new_slideshows = await asyncio.to_thread(html_decks.list_decks, workspace)
        for meta in new_slideshows:
            if float(meta.get("updated_at") or 0) <= _artifact_fence:
                continue
            await _daemon_ns._open_html_deck_tab(
                app,
                workspace,
                str(meta["slug"]),
                str(meta.get("title") or meta["slug"]),
            )
        # Vet any page proposals this run staged. propose_* tools run
        # in-daemon for HTTP providers but in the MCP subprocess for
        # claude_code / grok — neither surfaces to a per-tool hook, so
        # scan at run-end (like reports) and vet each fresh, unreviewed one.
        try:
            staged = await asyncio.to_thread(proposals.list_proposals, workspace)
            for p in staged:
                if (p.get("status") == "proposed" and p.get("review") is None
                        and (p.get("created_at") or 0) > _artifact_fence):
                    asyncio.create_task(_daemon_ns._vet_proposal(
                        app, workspace, str(p["id"]), thread_id, run_id))
        except Exception:  # noqa: BLE001
            log.exception("run-end proposal scan failed")
        return run_id
    except asyncio.CancelledError:
        # User-initiated cancel via the Agent Dashboard's kill button.
        # Re-raise after broadcasting so the task actually terminates.
        await _daemon_ns._broadcast(app, protocol.run_error(run_id, "cancelled", "run cancelled", thread_id))
        raise
    except llmgateway.ProviderError as e:
        await _daemon_ns._broadcast(app, protocol.run_error(run_id, e.code, str(e), thread_id))
        # If this looks transient/capacity/billing and another provider is
        # keyed, offer a one-click retry (audit #12).
        try:
            await _daemon_ns._offer_provider_retry(
                app, text, thread_id=thread_id, workspace=workspace,
                failed_pid=pid, err=e,
            )
        except Exception:  # noqa: BLE001
            log.exception("provider-retry offer failed")
    except Exception as e:  # noqa: BLE001
        log.exception("chat stream crashed")
        await _daemon_ns._broadcast(app, protocol.run_error(run_id, "server", str(e), thread_id))
    finally:
        if desk_id:
            from switchbay import kernel as sbk
            try:
                sbk.quiet(
                    workspace, desk_id, run_id=run_id, keep_run=True,
                )
            except Exception:  # noqa: BLE001
                log.exception("desk quiet on chat finish failed")
        # Always deregister so the Dashboard's "Running" panel
        # reflects truth even when the run errored or was cancelled.
        # Stash usage first so Auto N=1 telemetry can record tokens
        # after this run row is gone.
        app.setdefault("run_usage", {})[run_id] = {
            "input_tokens": usage_in or None,
            "output_tokens": usage_out or None,
            "tokens": (usage_in + usage_out) or 0,
        }
        overflow = len(app["run_usage"]) - 256
        if overflow > 0:
            for k in list(app["run_usage"])[:overflow]:
                app["run_usage"].pop(k, None)
        runs = app.get("runs")
        if runs is not None:
            runs.pop(run_id, None)
    # Provider / unexpected errors fall through here after their
    # run_error broadcast — None tells programmatic callers (A2A) the
    # run did not complete.
    return None
