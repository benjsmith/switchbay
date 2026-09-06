"""Fast wiki-answer path: retrieve, cheap synth, slider-gated kernel check.

Simple questions that the wiki already covers should not wait on a
CLI agent loop or a seated DAG. Search is in-process; synthesis uses
the fastest keyed HTTP model; the strongest model only runs a tiny
OK-or-rewrite pass, and Economy skips that pass when the synthesizer
is already a flash/luna-class model. Analysis pages are proposed in
the background after the answer is on the rail.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any

from .. import conversations, llmgateway, protocol, tools
from ..kernel.hire import (
    CHECK_CONFIRM, CHECK_REVISE, CHECK_SKIP,
    pick_fast_model, pick_kernel_model, strong_check_mode,
)

log = logging.getLogger("switchbay.agents.fast_lookup")

HIT_MIN_SCORE = 8
MAX_PAGES = 4
MAX_PAGE_CHARS = 6000
SYNTH_MAX_TOKENS = 2048
CONFIRM_MAX_TOKENS = 400
REVISE_MAX_TOKENS = 1200

_STOP = frozenset({
    "a", "an", "the", "and", "or", "for", "that", "this", "with", "from",
    "what", "who", "when", "where", "why", "how", "does", "did", "are",
    "was", "were", "do", "we", "i", "know", "about", "tell", "me", "please",
    "wiki", "page", "into", "your", "our", "can", "you", "explain",
    "define", "is", "it", "of", "in", "on", "to", "my",
})

SYNTH_SYSTEM = (
    "Answer from the retrieved wiki excerpts only. Cite pages as "
    "[[wikilink]] when you use them. If the excerpts do not contain "
    "the answer, say so in one sentence. Be concise. No preamble."
)

CONFIRM_SYSTEM = (
    "Check the draft against the retrieved wiki excerpts. If it is "
    "faithful and has no obvious errors, reply with exactly OK. If it "
    "contains a clear error, contradiction, or missing citation, reply "
    "with REWRITE on the first line and the corrected answer after."
)

REVISE_SYSTEM = (
    "Check the draft against the retrieved wiki excerpts. Reply OK if "
    "it is already a faithful, complete, concise answer. Otherwise "
    "reply REWRITE on the first line, then an improved answer still "
    "grounded in the excerpts, with [[wikilink]] citations. Keep it "
    "short — a few more tokens than the draft, not a new essay."
)


def search_query(text: str) -> str:
    terms = [
        t for t in re.findall(r"[A-Za-z][\w+.-]{1,}", text or "")
        if t.casefold() not in _STOP
    ]
    return " ".join(terms) or (text or "").strip()


def retrieve(workspace: Path, text: str, *, limit: int = 8) -> list[dict[str, Any]]:
    """In-process wiki search + top-page reads. Milliseconds, not a model."""
    query = search_query(text)
    if not query:
        return []
    try:
        raw = tools.execute("search_wiki", workspace, {"query": query, "limit": limit})
    except Exception:  # noqa: BLE001
        log.exception("fast_lookup search_wiki failed")
        return []
    if not isinstance(raw, dict):
        return []
    results = raw.get("results") or []
    if not isinstance(results, list):
        return []
    hits: list[dict[str, Any]] = []
    for row in results:
        if not isinstance(row, dict):
            continue
        score = int(row.get("score") or 0)
        if score < HIT_MIN_SCORE:
            continue
        page = str(row.get("page") or "").strip()
        if not page:
            continue
        try:
            body = tools.execute("read_wiki_page", workspace, {"page": page})
        except Exception:  # noqa: BLE001
            body = None
        content = ""
        if isinstance(body, dict) and not body.get("error"):
            content = str(body.get("content") or "")[:MAX_PAGE_CHARS]
        hits.append({
            "page": page,
            "title": str(row.get("title") or Path(page).stem),
            "score": score,
            "snippet": str(row.get("snippet") or ""),
            "wikilink": str(row.get("wikilink") or ""),
            "content": content,
        })
        if len(hits) >= MAX_PAGES:
            break
    return hits


def format_excerpts(hits: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for h in hits:
        cite = h.get("wikilink") or f"[[{h.get('page')}]]"
        body = (h.get("content") or h.get("snippet") or "").strip()
        parts.append(f"### {cite}\n{body}")
    return "\n\n".join(parts)


def apply_check(draft: str, check_text: str) -> str:
    """Keep the draft on OK; otherwise take the rewrite."""
    draft = (draft or "").strip()
    t = (check_text or "").strip()
    if not t:
        return draft
    first, _, rest = t.partition("\n")
    head = first.strip().casefold().strip(".!")
    if head in {"ok", "okay", "pass", "yes"} or head.startswith("ok ") or head == "ok":
        return draft
    if head.startswith("rewrite") or head.startswith("revised"):
        body = rest.strip()
        return body or draft
    if len(t) > max(80, int(len(draft) * 0.4)):
        return t
    return draft


def _cheapest_effort(provider_id: str, model: str | None, *, richer: bool = False) -> str | None:
    try:
        opts = llmgateway.reasoning_options(provider_id, model)
    except Exception:  # noqa: BLE001
        return None
    if not opts:
        return None
    ids = [str(o.get("id") or "") for o in opts if o.get("id")]
    if not ids:
        return None
    if not richer:
        for prefer in ("off", "none", "minimal", "low"):
            if prefer in ids:
                return prefer
        return ids[0]
    for prefer in ("low", "minimal", "medium"):
        if prefer in ids:
            return prefer
    return ids[min(1, len(ids) - 1)]


async def _complete(
    provider: Any,
    *,
    model: str | None,
    system: str,
    user: str,
    max_tokens: int,
    effort: str | None,
    workspace: Path,
    reasoning: bool | None = False,
    on_text: Any | None = None,
) -> tuple[str, int | None, int | None]:
    req = llmgateway.ChatRequest(
        messages=[{"role": "user", "content": user}],
        model=model,
        system=system,
        max_tokens=max_tokens,
        tools=None,
        reasoning=reasoning,
        reasoning_effort=effort,
        workspace=str(workspace),
    )
    parts: list[str] = []
    in_tok: int | None = None
    out_tok: int | None = None
    async for ev in provider.chat_stream(req):
        if isinstance(ev, llmgateway.TextChunk):
            parts.append(ev.text)
            if on_text is not None:
                await on_text(ev.text)
        elif isinstance(ev, llmgateway.DoneChunk):
            in_tok = ev.input_tokens
            out_tok = ev.output_tokens
            break
    return "".join(parts).strip(), in_tok, out_tok


async def _broadcast(app: Any, message: dict[str, Any]) -> None:
    clients = app.get("ws_clients") or set()
    for client in list(clients):
        try:
            await client.send_json(message)
        except Exception:  # noqa: BLE001
            pass


async def _retire_run(runs: dict[str, dict[str, Any]], run_id: str, delay: float) -> None:
    try:
        await asyncio.sleep(delay)
    finally:
        runs.pop(run_id, None)


def _analysis_title(text: str) -> str:
    q = search_query(text) or (text or "").strip()
    q = re.sub(r"\s+", " ", q).strip(" ?.")
    if len(q) > 72:
        q = q[:72].rsplit(" ", 1)[0]
    return f"What we know: {q or 'lookup'}"


def _analysis_body(title: str, answer: str, hits: list[dict[str, Any]]) -> str:
    sources = []
    seen: set[str] = set()
    for h in hits:
        page = str(h.get("page") or "").strip()
        if page and page not in seen:
            seen.add(page)
            sources.append(page)
    src = ", ".join(sources)
    return (
        f"---\nkind: analysis\ntitle: {title}\n"
        f"sources: [{src}]\n---\n\n"
        f"# {title}\n\n{answer.strip()}\n"
    )


def propose_analysis(workspace: Path, text: str, answer: str, hits: list[dict[str, Any]]) -> None:
    """Stage an analysis page in Reviews. Does not block the rail answer."""
    if not (answer or "").strip() or not hits:
        return
    from .. import proposals
    title = _analysis_title(text)
    try:
        dest = proposals.target_path(workspace, "analysis", title)
        if dest.is_file():
            return
    except Exception:  # noqa: BLE001
        dest = None
    body = _analysis_body(title, answer, hits)
    try:
        tools.execute("propose_wiki_page", workspace, {
            "kind": "analysis",
            "title": title,
            "body": body,
        })
    except Exception:  # noqa: BLE001
        log.exception("fast_lookup analysis propose failed")


def notice_for(synth: tuple[str, str | None], mode: str) -> str:
    pid, model = synth
    label = f"{pid}/{model or 'default'}"
    if mode == CHECK_SKIP:
        return f"Auto: wiki lookup — {label} (pass-through)."
    if mode == CHECK_CONFIRM:
        return f"Auto: wiki lookup — {label}, tiny kernel check."
    return f"Auto: wiki lookup — {label}, kernel pass to tighten the answer."


async def dispatch(
    app: Any,
    ws: Any,
    text: str,
    *,
    workspace: Path,
    hits: list[dict[str, Any]],
    preference: float,
    thread_id_override: str | None = None,
    input_excerpt: str | None = None,
    available: list[tuple[str, str | None]] | None = None,
    denied: list[str] | None = None,
) -> str | None:
    """Retrieve-already-done lookup: synth, optional kernel check, stream."""
    synth = pick_fast_model(
        workspace=workspace, available=available, denied=denied,
    )
    if synth is None:
        return None
    pid, model = synth
    try:
        provider = llmgateway.get(pid)
    except llmgateway.ProviderError:
        return None
    if not provider.has_key():
        return None

    kernel = pick_kernel_model(
        workspace=workspace, available=available, denied=denied,
    )
    mode = strong_check_mode(preference, synth=synth, kernel=kernel)

    if thread_id_override:
        thread_id = thread_id_override
    elif ws is None:
        thread_id = await asyncio.to_thread(
            conversations.new_thread, workspace, input_excerpt or None,
        )
    else:
        thread_id = app.get("thread_id")
        if not thread_id:
            thread_id = await asyncio.to_thread(conversations.new_thread, workspace)
            app["thread_id"] = thread_id
            app["thread_kind"] = "structured-agent"

    kind = app.get("thread_kind") if thread_id == app.get("thread_id") else None
    if kind == "interactive-pty":
        await _broadcast(app, protocol.notice(
            "this is a shell thread — type in its terminal, or start a "
            "new thread for chat.",
            kind="chat",
        ))
        return None

    busy = [
        r for r in (app.get("runs") or {}).values()
        if r.get("thread_id") == thread_id
        and r.get("status") in (
            "running", "planning", "merging", "verifying",
            "expanding", "synthesizing", "waiting_limits",
        )
    ]
    if busy:
        msg = protocol.notice(
            f"thread is busy — {busy[0].get('run_id')} is still streaming. "
            "Wait for it to finish, or start a new thread.",
            kind="chat",
        )
        await _broadcast(app, msg)
        return None

    run_id = f"run-{uuid.uuid4().hex[:8]}"
    runs: dict[str, dict[str, Any]] = app.setdefault("runs", {})
    runs[run_id] = {
        "run_id": run_id,
        "provider": pid,
        "model": model or provider.PROVIDER.get("default_model", "?"),
        "input_excerpt": (input_excerpt or text)[:120],
        "started_at": time.time(),
        "last_chunk_at": time.time(),
        "tool_count": 0,
        "status": "running",
        "task": asyncio.current_task(),
        "workspace": str(workspace),
        "workspace_name": workspace.name,
        "is_background": ws is None,
        "thread_id": thread_id,
        "orchestration_strategy": "fast_lookup",
        "fanout_n": 1,
        "preference": preference,
        "activity": "wiki lookup",
    }
    run_ws: dict[str, str] = app.setdefault("run_ws", {})
    run_ws[run_id] = str(workspace)
    run_thread: dict[str, str] = app.setdefault("run_thread", {})
    run_thread[run_id] = thread_id

    excerpts = format_excerpts(hits)
    user_blob = (
        f"Question:\n{text.strip()}\n\n"
        f"Retrieved wiki excerpts:\n{excerpts}"
    )
    synth_effort = _cheapest_effort(pid, model, richer=False)
    in_tok = 0
    out_tok = 0
    answer = ""
    error: str | None = None
    msg_id: str | None = None

    try:
        await _broadcast(app, protocol.run_started(
            thread_id, run_id, pid, str(model or ""), str(workspace),
        ))
        await asyncio.to_thread(
            conversations.append_event, workspace, thread_id, "user", text,
            run_id=run_id,
        )
        stream_live = mode == CHECK_SKIP
        if stream_live:
            msg_id = protocol.new_message_id()
            await _broadcast(app, protocol.text_message_start(run_id, msg_id))

            async def _on_text(delta: str) -> None:
                if run_id in runs:
                    runs[run_id]["last_chunk_at"] = time.time()
                    runs[run_id]["activity"] = delta[-120:].lstrip()
                await _broadcast(
                    app, protocol.text_message_content(run_id, msg_id, delta),
                )

            draft, s_in, s_out = await _complete(
                provider, model=model, system=SYNTH_SYSTEM, user=user_blob,
                max_tokens=SYNTH_MAX_TOKENS, effort=synth_effort,
                workspace=workspace, reasoning=False, on_text=_on_text,
            )
        else:
            draft, s_in, s_out = await _complete(
                provider, model=model, system=SYNTH_SYSTEM, user=user_blob,
                max_tokens=SYNTH_MAX_TOKENS, effort=synth_effort,
                workspace=workspace, reasoning=False,
            )
        in_tok += int(s_in or 0)
        out_tok += int(s_out or 0)
        answer = draft
        if mode != CHECK_SKIP and kernel is not None and draft:
            kpid, kmodel = kernel
            try:
                kprov = llmgateway.get(kpid)
            except llmgateway.ProviderError:
                kprov = None
            if kprov is not None and kprov.has_key():
                richer = mode == CHECK_REVISE
                check_user = (
                    f"Question:\n{text.strip()}\n\n"
                    f"Draft answer:\n{draft}\n\n"
                    f"Retrieved wiki excerpts:\n{excerpts}"
                )
                sys = REVISE_SYSTEM if richer else CONFIRM_SYSTEM
                cap = REVISE_MAX_TOKENS if richer else CONFIRM_MAX_TOKENS
                check_text, c_in, c_out = await _complete(
                    kprov, model=kmodel, system=sys, user=check_user,
                    max_tokens=cap,
                    effort=_cheapest_effort(kpid, kmodel, richer=richer),
                    workspace=workspace, reasoning=False,
                )
                in_tok += int(c_in or 0)
                out_tok += int(c_out or 0)
                answer = apply_check(draft, check_text)

        if not answer:
            answer = (
                "I searched the wiki and did not get a usable synthesis. "
                "Try asking with more specific terms, or run a research desk."
            )
        if stream_live:
            if not draft and msg_id is not None:
                await _broadcast(
                    app, protocol.text_message_content(run_id, msg_id, answer),
                )
            if msg_id is not None:
                await _broadcast(app, protocol.text_message_end(run_id, msg_id))
        else:
            msg_id = protocol.new_message_id()
            await _broadcast(app, protocol.text_message_start(run_id, msg_id))
            await _broadcast(app, protocol.text_message_content(run_id, msg_id, answer))
            await _broadcast(app, protocol.text_message_end(run_id, msg_id))
        await asyncio.to_thread(
            conversations.append_event, workspace, thread_id, "assistant",
            answer, run_id=run_id, payload={"text": answer[:24_000]},
        )
    except asyncio.CancelledError:
        error = "cancelled"
        await _broadcast(app, protocol.run_error(
            run_id, "cancelled", "lookup cancelled", thread_id,
        ))
        raise
    except Exception as e:  # noqa: BLE001
        error = str(e)
        log.exception("fast_lookup dispatch failed")
        await _broadcast(app, protocol.run_error(run_id, "server", error, thread_id))
    else:
        if error is None:
            await _broadcast(app, protocol.run_finished(
                thread_id, run_id, in_tok or None, out_tok or None, "end_turn",
            ))
            try:
                loop = asyncio.get_running_loop()
                loop.run_in_executor(
                    None, propose_analysis, workspace, text, answer, hits,
                )
            except Exception:  # noqa: BLE001
                log.exception("fast_lookup background analysis schedule failed")
        return None if error else run_id
    finally:
        if run_id in runs:
            st = "cancelled" if error == "cancelled" else ("error" if error else "done")
            runs[run_id]["status"] = st
            runs[run_id]["last_chunk_at"] = time.time()
            runs[run_id]["finished_at"] = time.time()
            usage = app.setdefault("run_usage", {})
            usage[run_id] = {
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "tokens": in_tok + out_tok,
            }
            asyncio.create_task(_retire_run(runs, run_id, delay=8.0))
