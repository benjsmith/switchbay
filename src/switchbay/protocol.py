"""JSON message shapes exchanged over the WebSocket.

Single source of truth — the frontend mirrors these in
`frontend/src/ws.ts`.

Two vocabularies share the socket (decided 2026-07-03; see charter):

· **AG-UI lifecycle events** — the agent-run stream speaks the AG-UI
  schema's stable core (`RUN_STARTED`/`RUN_FINISHED`/`RUN_ERROR`,
  `TEXT_MESSAGE_START/CONTENT/END`, `TOOL_CALL_START/ARGS/END` +
  `TOOL_CALL_RESULT`, `STEP_STARTED/FINISHED`). Spec fields are
  camelCase (`threadId`, `runId`, `messageId`, `toolCallId`, `delta`);
  switchbay extras (provider/model/workspace/token counts) ride
  alongside in snake_case so the two layers are visually separable.
  Every event carries `runId` — AG-UI assumes a per-run stream, but
  our WS is a shared broadcast channel, so the frontend routes by run.

· **`CUSTOM` events** — everything switchbay-specific that is NOT
  part of an agent run (hello, nav, selection, permissions, notices,
  file hints) is wrapped `{type: "CUSTOM", name, value}` via
  `custom()`. The frontend unwraps centrally in `ws.ts` so downstream
  handlers see the inner message unchanged — AG-UI spec drift can
  never reach our surfaces.

Deliberately NOT adopted: `STATE_SNAPSHOT`/`STATE_DELTA` (deferred
until shared UI/tab state exists), CopilotKit or any AG-UI frontend
kit. Terminal `term.*` frames stay a separate namespaced channel on
the same socket. Client→server messages (`user_input`,
`selection_set`) are not AG-UI events and stay bare.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal, TypedDict


class TabSpec(TypedDict):
    id: str
    title: str
    kind: str


class Mode(TypedDict, total=False):
    name: str
    tabs: list[TabSpec]


# ── Selection layer (step C) ─────────────────────────────────────────
# Only `page` ships in step C; further kinds (file, rows, range, …)
# arrive as their tabs land.


class SelectionPage(TypedDict):
    kind: Literal["page"]
    id: str
    path: str


class SelectionCsv(TypedDict):
    kind: Literal["csv"]
    path: str


SelectionPayload = SelectionPage | SelectionCsv


class SelectionSet(TypedDict):
    """client → server: user picked a new selection."""

    type: Literal["selection_set"]
    selection: SelectionPayload | None


class SelectionState(TypedDict):
    """server → client: broadcast of the current selection."""

    type: Literal["selection_state"]
    selection: SelectionPayload | None


# ── Hello / rail ─────────────────────────────────────────────────────


class WorkspacesPayload(TypedDict):
    paths: list[str]
    active: str | None


class Hello(TypedDict):
    type: Literal["hello"]
    workspace: str
    default_file: str | None
    mode: Mode
    selection: SelectionPayload | None
    workspaces: WorkspacesPayload


class UserInput(TypedDict, total=False):
    type: Literal["user_input"]
    text: str
    # Optional fan-out count. When >1, the daemon's _dispatch_fanout
    # path runs: planner → N parallel workers → merger. 0 / 1 / unset
    # all mean "ordinary single-agent chat".
    n: int


class Notice(TypedDict, total=False):
    type: Literal["notice"]
    text: str
    kind: str | None


# ── CUSTOM wrapper ───────────────────────────────────────────────────


def custom(value: dict[str, Any]) -> dict[str, Any]:
    """Wrap a switchbay surface message as an AG-UI `CUSTOM` event.
    `value` is the full inner message (its `type` field doubles as the
    CUSTOM `name`); ws.ts unwraps at the dispatch boundary so every
    downstream handler still sees the inner shape."""
    return {"type": "CUSTOM", "name": value["type"], "value": value}


# ── Surface builders (all CUSTOM-wrapped on the wire) ────────────────


def hello(
    workspace: str,
    default_file: str | None,
    mode: dict[str, Any],
    selection: dict[str, Any] | None,
    workspaces: dict[str, Any],
    thread_id: str | None = None,
) -> dict[str, Any]:
    # `thread_id` = the daemon's focused thread, so a connecting client
    # can hydrate the right rail without a /api/threads round-trip.
    # None on a fresh workspace (next turn lazily creates one).
    return custom({
        "type": "hello",
        "workspace": workspace,
        "default_file": default_file,
        "mode": mode,
        "selection": selection,
        "workspaces": workspaces,
        "thread_id": thread_id,
    })


def notice(text: str, kind: str | None = None) -> dict[str, Any]:
    return custom({"type": "notice", "text": text, "kind": kind})


def selection_state(selection: dict[str, Any] | None) -> dict[str, Any]:
    return custom({"type": "selection_state", "selection": selection})


def nav(tab_kind: str, payload: dict[str, Any], label: str) -> dict[str, Any]:
    """Navigation broadcast — the frontend should switch to the first
    tab of `tab_kind` and apply `payload` (selection + tab-specific
    hints). Used by /<verb> slash commands and (later) MCP tool calls
    that resolve to a workspace asset."""
    return custom({
        "type": "nav", "tab_kind": tab_kind, "payload": payload, "label": label,
    })


def files_changed() -> dict[str, Any]:
    """Hint that the workspace file set has shifted (a write, delete,
    duplicate, or external edit). The frontend's file browser bumps
    its refresh on this signal so newly-written files appear without
    a page reload. Cheap; deduped by the receiver if needed."""
    return custom({"type": "files_changed"})


def artifact(
    kind: str, label: str, selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """An AGENT produced or updated a user-facing artifact — a plot,
    a sketch/deck slide, a wiki page. `kind` is the tab kind that
    renders it; `selection`, when present, is a ready-to-apply
    Selection object so the frontend can land on the exact artifact
    (not just the right tab). Zen's pulse badge rides this (charter
    ruling: never auto-switch — the user clicks through); Power
    ignores it today. Only emit from agent tool paths — user-driven
    saves must not pulse."""
    return custom({
        "type": "artifact", "kind": kind, "label": label,
        "selection": selection,
    })


def rail_cleared() -> dict[str, Any]:
    """The rail history for this workspace was wiped on disk. Frontend
    drops its in-memory transcript so the user immediately sees a
    blank rail (instead of stale rows that no longer have a backing
    DB record). Triggered by /clear-rail-history."""
    return custom({"type": "rail_cleared"})


def daemon_shutdown(reason: str = "") -> dict[str, Any]:
    """Sent to every client an instant before the daemon exits on a
    user-requested stop (the Settings "Quit" button or `/quit`). Lets
    each open PWA show an intentional "stopped" overlay and stop
    reconnecting, instead of silently reconnect-looping into a dead
    socket. `reason` is advisory ("user" / "slash")."""
    return custom({"type": "daemon.shutdown", "reason": reason})


def permission_request(
    req_id: str, provider: str, tool: str,
    tool_input: dict[str, Any], pattern: str, run_id: str | None,
    thread_id: str | None = None, origin: str | None = None,
    origin_path: str | None = None,
) -> dict[str, Any]:
    """Inline rail dialog ask: the agent's pre-tool hook (claude-code)
    or sandbox-denial path (codex) wants to run a tool that isn't on
    the static allowlist. Frontend renders an Approve / Approve+remember
    / Deny strip; user click POSTs `/api/permission/decide`.

    `thread_id` scopes the card to its owning rail thread; None means
    the requesting CLI session is not one of ours (bench, scripts,
    background agents) and the card renders in the out-of-thread
    approvals strip, labelled with `origin` (compacted cwd)."""
    return custom({
        "type": "permission_request",
        "req_id": req_id,
        "provider": provider,
        "tool": tool,
        "tool_input": tool_input,
        "pattern": pattern,
        "run_id": run_id,
        "thread_id": thread_id,
        "origin": origin,
        "origin_path": origin_path,
    })


def thread_focused(thread_id: str, kind: str = "structured-agent") -> dict[str, Any]:
    """The daemon's focused thread changed (switcher click, + New
    thread, a `!cmd` spawning a shell thread, or a dispatch that
    lazily created one). Clients move their rail to this thread —
    `kind` tells them which surface to render (transcript vs xterm)
    without a round-trip. Other clients of the same daemon follow in
    lock-step, mirroring how workspace switches broadcast `hello`."""
    return custom({"type": "thread_focused", "thread_id": thread_id, "kind": kind})


def thread_project_changed(thread_id: str, project: str | None) -> dict[str, Any]:
    """A thread's project binding changed (D8: /project verb or the
    ThreadBar picker chip). Clients refetch /api/threads so the chip
    and switcher rows agree; captures already read the binding from
    the DB at write time, so no client-side state is authoritative."""
    return custom({
        "type": "thread.project_changed",
        "thread_id": thread_id,
        "project": project,
    })


def decision_review(entry: dict[str, Any]) -> dict[str, Any]:
    """A heartbeat-drafted charter amendment awaits the user (D9).
    Carries everything the rail card needs — decision text, target
    charter page, and the full proposed page for the preview — so no
    follow-up fetch is needed. Re-offered on reload via
    GET /api/decisions/pending (unlike permission cards, these are
    disk-backed and survive restarts)."""
    return custom({
        "type": "decision.review",
        "id": entry.get("id"),
        "text": entry.get("text"),
        "project": entry.get("project"),
        "created": entry.get("created"),
        "charter_path": entry.get("charter_path"),
        "proposal": entry.get("proposal"),
    })


def decision_review_resolved(dec_id: str, decision: str) -> dict[str, Any]:
    """Companion to decision_review — broadcast after accept/dismiss
    so every connected client settles the card in lock-step."""
    return custom({
        "type": "decision.review_resolved", "id": dec_id, "decision": decision,
    })


def permission_resolved(req_id: str, decision: str) -> dict[str, Any]:
    """Companion to permission_request — broadcast after the user
    clicks so other connected clients (and the originating tab if it
    posted-then-disconnected) can drop the dialog from the rail."""
    return custom({
        "type": "permission_resolved", "req_id": req_id, "decision": decision,
    })


# ── AG-UI agent-run lifecycle events ─────────────────────────────────


def new_message_id() -> str:
    """Fresh AG-UI messageId. One per assistant text segment (a
    segment ends at a tool call or run end) and one per tool-result
    message."""
    return uuid.uuid4().hex


def run_started(
    thread_id: str, run_id: str, provider: str, model: str, workspace: str,
) -> dict[str, Any]:
    # `workspace` lets the rail ignore live events for runs that belong
    # to another workspace (the rail is strictly per-workspace; the
    # Agent Dashboard is the cross-workspace surface). Later frames of
    # a foreign run are dropped by runId (foreignRunsRef).
    return {
        "type": "RUN_STARTED",
        "threadId": thread_id,
        "runId": run_id,
        "provider": provider,
        "model": model,
        "workspace": workspace,
    }


def run_finished(
    thread_id: str,
    run_id: str,
    input_tokens: int | None,
    output_tokens: int | None,
    stop_reason: str | None,
) -> dict[str, Any]:
    return {
        "type": "RUN_FINISHED",
        "threadId": thread_id,
        "runId": run_id,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "stop_reason": stop_reason,
    }


def run_error(
    run_id: str, code: str, message: str, thread_id: str | None = None,
) -> dict[str, Any]:
    # AG-UI RUN_ERROR carries message (+ optional code); threadId/runId
    # ride as extras so the shared-channel frontend can route it.
    msg: dict[str, Any] = {
        "type": "RUN_ERROR",
        "runId": run_id,
        "code": code,
        "message": message,
    }
    if thread_id is not None:
        msg["threadId"] = thread_id
    return msg


def step_started(run_id: str, step_name: str) -> dict[str, Any]:
    """Not emitted yet — lands with the dashboard's "working toward"
    line (Foundation C). Declared now so the schema is complete."""
    return {"type": "STEP_STARTED", "runId": run_id, "stepName": step_name}


def step_finished(run_id: str, step_name: str) -> dict[str, Any]:
    return {"type": "STEP_FINISHED", "runId": run_id, "stepName": step_name}


def text_message_start(
    run_id: str, message_id: str, role: str = "assistant",
) -> dict[str, Any]:
    return {
        "type": "TEXT_MESSAGE_START",
        "runId": run_id,
        "messageId": message_id,
        "role": role,
    }


def text_message_content(
    run_id: str, message_id: str, delta: str,
) -> dict[str, Any]:
    return {
        "type": "TEXT_MESSAGE_CONTENT",
        "runId": run_id,
        "messageId": message_id,
        "delta": delta,
    }


def text_message_end(run_id: str, message_id: str) -> dict[str, Any]:
    return {
        "type": "TEXT_MESSAGE_END",
        "runId": run_id,
        "messageId": message_id,
    }


def reasoning(run_id: str, message_id: str, text: str) -> dict[str, Any]:
    """The model's private chain-of-thought for one assistant segment
    (e.g. Ornith's `reasoning_content`). Delivered whole once the
    segment closes; the frontend renders it as a collapsible block and
    never feeds it back into context."""
    return custom({
        "type": "reasoning",
        "runId": run_id,
        "messageId": message_id,
        "text": text,
    })


def tool_call_start(
    run_id: str,
    tool_call_id: str,
    tool_name: str,
    parent_message_id: str | None = None,
) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "type": "TOOL_CALL_START",
        "runId": run_id,
        "toolCallId": tool_call_id,
        "toolCallName": tool_name,
    }
    if parent_message_id is not None:
        msg["parentMessageId"] = parent_message_id
    return msg


def tool_call_args(run_id: str, tool_call_id: str, delta: str) -> dict[str, Any]:
    """`delta` is a JSON-string fragment of the tool arguments. Our
    providers deliver complete inputs, so today this is emitted once
    with the full `json.dumps(input)` between START and END."""
    return {
        "type": "TOOL_CALL_ARGS",
        "runId": run_id,
        "toolCallId": tool_call_id,
        "delta": delta,
    }


def tool_call_end(run_id: str, tool_call_id: str) -> dict[str, Any]:
    return {
        "type": "TOOL_CALL_END",
        "runId": run_id,
        "toolCallId": tool_call_id,
    }


def tool_call_result(
    run_id: str, tool_call_id: str, message_id: str, content: str, ok: bool,
) -> dict[str, Any]:
    # `ok` is a switchbay extra — AG-UI models failures as content;
    # our rail renders success/failure styling from the flag.
    return {
        "type": "TOOL_CALL_RESULT",
        "runId": run_id,
        "toolCallId": tool_call_id,
        "messageId": message_id,
        "content": content,
        "role": "tool",
        "ok": ok,
    }
