"""Rail WebSocket session.

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
from aiohttp import WSMsgType
from aiohttp import web
from switchbay import commands
from switchbay import html_decks
from switchbay import library
from switchbay import llmgateway
from switchbay import local_models
from switchbay import localllm
from switchbay import protocol
from switchbay import rail
from switchbay import report_packages
from switchbay import selection
from switchbay import slideshow_from_md
from switchbay import tabstore
from switchbay import verbs
from switchbay import worksheets_store
from switchbay.agents import fanout
from switchbay.agents import orchestration_policy
from switchbay.agents import rail_default

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

def _ws_response() -> web.WebSocketResponse:
    """Rail socket. Compression off: aiohttp 3.14 rejects some
    permessage-deflate / PONG sequences ("Received frame with
    non-zero reserved bits", aio-libs/aiohttp#13274), dropping
    ``user_input``. The composer still echoes the slash; the desk
    never seats. Safari and Chromium both hit it.
    """
    return web.WebSocketResponse(heartbeat=30.0, compress=False)

async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    # Defense-in-depth: the _origin_guard middleware already rejected
    # non-loopback Origins, but re-check here so a future routing change
    # that bypasses the middleware can't expose the socket to a
    # drive-by page (WS handshakes carry a browser-set Origin).
    if not _daemon_ns._origin_host_allowed(request):
        return web.json_response(
            {"error": "cross-origin websocket refused"}, status=403,
        )
    ws = _ws_response()
    await ws.prepare(request)
    workspace: Path = request.app["workspace"]
    request.app["ws_clients"].add(ws)

    try:
        await ws.send_json(_daemon_ns._hello_payload(request.app))
        # 6-week local-model refresh nudge (non-blocking).
        try:
            if await asyncio.to_thread(local_models.should_prompt_refresh):
                await ws.send_json(protocol.custom({
                    "type": "local_models.check_prompt",
                    "message": (
                        "You use local models. Check Hugging Face / Ollama "
                        "for newer options that fit this machine? "
                        "(about every 6 weeks)"
                    ),
                    "interval_days": 42,
                }))
        except Exception:  # noqa: BLE001
            pass

        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except json.JSONDecodeError:
                    await ws.send_json(protocol.notice("invalid json from client"))
                    continue

                mtype = data.get("type")
                if mtype == "user_input":
                    raw_text = str(data.get("text", ""))
                    raw_n = data.get("n")
                    fanout_n = 0
                    if isinstance(raw_n, int) and raw_n >= 2:
                        fanout_n = min(raw_n, fanout.MAX_N)
                    raw_pref = data.get("preference")
                    pref: float | None = None
                    if isinstance(raw_pref, (int, float)):
                        pref = orchestration_policy.clamp_preference(raw_pref)
                    parsed = rail.parse(raw_text)
                    kind = parsed.get("kind", "chat")
                    body = parsed.get("body", "")
                    if kind == "chat" and body.strip():
                        if fanout_n >= 2:
                            # Advanced override: explicit fixed-N fan-out.
                            t = asyncio.create_task(
                                _daemon_ns._dispatch_fanout(request.app, ws, body, fanout_n),
                            )
                            t.add_done_callback(_daemon_ns._make_dispatch_error_surface(request.app, ws))
                        # 0. User-defined shortcuts first. If the input
                        #    *is* a rule registration ("when I say X,
                        #    do Y") OR matches a saved trigger, handle
                        #    it before any of the other paths.
                        elif await _daemon_ns._try_rule_dispatch(request.app, ws, body):
                            pass
                        # 1. NL intent: phrases like "show me X" or
                        #    "open Y" route through the verb registry
                        #    when the match is unambiguous, so the user
                        #    doesn't have to type a slash. Falls through
                        #    to chat dispatch when the intent is fuzzy.
                        elif await _daemon_ns._try_intent_dispatch(request.app, ws, body):
                            pass
                        else:
                            # 2. Auto orchestration (may still be one Run).
                            t = asyncio.create_task(
                                _daemon_ns._dispatch_auto(
                                    request.app, ws, body, preference=pref,
                                ),
                            )
                            t.add_done_callback(_daemon_ns._make_dispatch_error_surface(request.app, ws))
                    elif kind == "slash":
                        # Slash commands route through the verb registry:
                        # `/view sales pipeline` finds a match and tells
                        # the frontend to switch tabs. /rule and /rules
                        # are special-cased — they manage user shortcuts
                        # rather than navigating tabs. Unknown slash
                        # names fall through to a logged notice.
                        sname = str(parsed.get("name", ""))
                        sargs = str(parsed.get("args", ""))
                        if sname.lower() == "rule":
                            asyncio.create_task(
                                _daemon_ns._handle_rule_slash(request.app, ws, sargs)
                            )
                            continue
                        if sname.lower() == "rules":
                            asyncio.create_task(
                                _daemon_ns._handle_rules_slash(request.app, ws, sargs)
                            )
                            continue
                        if sname.lower() in (
                            "rescan", "refresh", "reindex",
                            # Aliases — rebuilding the viewer bundle
                            # is functionally identical to a rescan
                            # (cold viewer.sh build via cebridge).
                            # Handling them here keeps the work on
                            # the daemon side; routing to claude-code
                            # makes the agent refuse because
                            # viewer.sh isn't on its bash allowlist.
                            "viewer", "build-viewer", "rebuild-viewer",
                        ):
                            asyncio.create_task(
                                _daemon_ns._handle_rescan(request.app, ws),
                            )
                            continue
                        if sname.lower() in (
                            "clear-rail-history", "clear-history",
                            "clear-rail", "rail-clear", "wipe-rail",
                        ):
                            asyncio.create_task(
                                _daemon_ns._handle_clear_rail(request.app, ws),
                            )
                            continue
                        if sname.lower() in ("quit", "shutdown", "exit"):
                            # Stop the whole daemon. NOT aliased to /stop:
                            # users read "/stop" as "stop the running
                            # agent", so a fat-finger there mustn't kill
                            # the app. Bare /quit asks to confirm.
                            asyncio.create_task(
                                _daemon_ns._handle_quit_slash(request.app, ws, sargs),
                            )
                            continue
                        if sname.lower() in ("start", "restart"):
                            # In-app `make restart`. Refuses on a dev daemon.
                            asyncio.create_task(
                                _daemon_ns._handle_start_slash(request.app, ws),
                            )
                            continue
                        if sname.lower() in ("setup-wiki", "setup", "init-wiki"):
                            # Server-side: the rail agent is sandboxed
                            # shell-less and setup.sh is interactive, so
                            # run it on the daemon (like /viewer → rescan).
                            asyncio.create_task(
                                _daemon_ns._handle_setup_wiki(request.app, ws),
                            )
                            continue
                        if sname.lower() in ("note", "todo", "decision"):
                            # Deterministic capture (D7) — instant
                            # daemon-side write, NO LLM turn. Must win
                            # over the CE-action stage: CE's own /note
                            # command template would otherwise route
                            # these through a chat dispatch.
                            asyncio.create_task(
                                _daemon_ns._handle_capture_slash(
                                    request.app, ws, sname.lower(), sargs,
                                ),
                            )
                            continue
                        if sname.lower() == "project":
                            # Thread→project binding (D8).
                            asyncio.create_task(
                                _daemon_ns._handle_project_slash(request.app, ws, sargs),
                            )
                            continue
                        desk_spec = _daemon_ns._desk_spec(sname.lower())
                        if desk_spec and desk_spec.get("task_kind") in (
                            "projects", "code", "curation", "research",
                        ):
                            # Work / code / curate desks. /work is the
                            # projects desk; /steer is a silent alias.
                            # Not /project (thread binding) and not
                            # /portfolio (Library).
                            slash = str(desk_spec["slash"])
                            verb = _daemon_ns._desk_slash_verb(sargs)
                            reviews_note = (
                                " Reviews stay in the Reviews tab."
                                if desk_spec.get("task_kind") == "curation"
                                else ""
                            )
                            if verb is None and not sargs.strip():
                                resumed = _daemon_ns._maybe_resume_quiet_desk(
                                    request.app, desk_spec,
                                    request.app["workspace"],
                                )
                                if resumed:
                                    await ws.send_json(protocol.notice(
                                        f"Resuming the quiet {slash} desk "
                                        f"(`{resumed}`). Same DAG.",
                                        kind="slash",
                                    ))
                                    continue
                            if verb == "quiet":
                                n = _daemon_ns._quiet_desk(
                                    request.app, desk_spec,
                                    request.app["workspace"],
                                )
                                await ws.send_json(protocol.notice(
                                    f"Quieted the {slash} desk"
                                    + (f" ({n} run" + ("" if n == 1 else "s")
                                       + " stopped)" if n else "")
                                    + f". Dismiss with /{slash} dismiss."
                                    + reviews_note,
                                    kind="slash",
                                ))
                                continue
                            if verb == "dismiss":
                                n = _daemon_ns._dismiss_desk(
                                    request.app, desk_spec,
                                    request.app["workspace"],
                                )
                                await ws.send_json(protocol.notice(
                                    f"Dismissed the {slash} desk"
                                    + (f" ({n} run" + ("" if n == 1 else "s")
                                       + " stopped)" if n else "")
                                    + "."
                                    + reviews_note,
                                    kind="slash",
                                ))
                                continue
                            extra_pid = extra_model = None
                            if desk_spec.get("task_kind") == "curation":
                                extra_pid, extra_model = _daemon_ns._ce_action_provider(
                                    request.app["workspace"],
                                )
                            _daemon_ns._launch_desk(
                                request.app, desk_spec,
                                prompt=sargs.strip(),
                                preference=pref,
                                provider_override=extra_pid,
                                model_override=extra_model,
                            )
                            notice = (
                                f"/{slash} running in the background. "
                                f"Quiet with /{slash} stop; dismiss with "
                                f"/{slash} dismiss."
                            )
                            if extra_pid:
                                try:
                                    extra_label = llmgateway.get(extra_pid).LABEL
                                except llmgateway.ProviderError:
                                    extra_label = extra_pid
                                notice = (
                                    f"/{slash} running in the background on "
                                    f"{extra_label} ({extra_model}). "
                                    "The rail stays free. "
                                    f"Quiet with /{slash} stop; dismiss with "
                                    f"/{slash} dismiss."
                                )
                            await ws.send_json(protocol.notice(
                                notice, kind="chat",
                            ))
                            continue
                        if sname.lower() in ("effort", "reasoning", "think"):
                            # Reasoning effort for the current model.
                            # Handled here rather than forwarded: a
                            # coding CLI's own /effort would be consumed
                            # by this router anyway, and there is no
                            # read-back channel from a one-shot CLI
                            # invocation to keep our picker honest. So
                            # WE own the setting, and the corner control
                            # + this command are the same store.
                            asyncio.create_task(
                                _daemon_ns._handle_effort_slash(request.app, ws, sargs),
                            )
                            continue
                        if sname.lower() == "intro":
                            # Reopen (or focus) the Intro deck tab. Added
                            # here so it wins over any user template; the
                            # tab is closable and seeded once on first
                            # install (see _seed_intro_tab).
                            asyncio.create_task(
                                _daemon_ns._open_intro_tab(request.app, request.app["workspace"]),
                            )
                            await ws.send_json(protocol.notice(
                                "↗ Intro opened in its tab.", kind="slash"))
                            continue
                        if sname.lower() in (
                            "slideshow", "slideshows", "presentation",
                            "presentations",
                            # legacy aliases (avoid Sketch "deck" alone)
                            "html-deck", "html-decks",
                            "slideshow-from-md", "slideshow_from_md",
                        ):
                            # /slideshows [slug] — list or open HTML slideshow
                            # from slideshows/<slug>/.
                            # /slideshow from-md <path.md> [slug] — build from MD
                            ws_path = request.app["workspace"]
                            arg = (sargs or "").strip().split()
                            if arg and arg[0].lower() in (
                                "from-md", "from_md", "md", "build",
                            ):
                                if len(arg) < 2:
                                    await ws.send_json(protocol.notice(
                                        "Usage: `/slideshow from-md "
                                        "<path.md> [slug]` — H1 title, "
                                        "H2 per slide, lists/images/TTS. "
                                        "Optional `--no-media` skips image+voice gen.",
                                        kind="slash",
                                    ))
                                    continue
                                md_rel = arg[1]
                                rest = arg[2:]
                                gen = True
                                use_slug = None
                                for a in rest:
                                    if a in ("--no-media", "--no-gen"):
                                        gen = False
                                    elif not a.startswith("-"):
                                        use_slug = a
                                await ws.send_json(protocol.notice(
                                    f"Building slideshow from `{md_rel}`…",
                                    kind="slash",
                                ))
                                try:
                                    built = await asyncio.to_thread(
                                        slideshow_from_md.build_from_markdown,
                                        ws_path,
                                        md_rel,
                                        slug=use_slug,
                                        generate_media=gen,
                                    )
                                except Exception as e:  # noqa: BLE001
                                    await ws.send_json(protocol.notice(
                                        f"Slideshow build failed: {e}",
                                        kind="error",
                                    ))
                                    continue
                                asyncio.create_task(
                                    _daemon_ns._open_html_deck_tab(
                                        request.app, ws_path,
                                        str(built["slug"]),
                                        str(built.get("title") or built["slug"]),
                                    ),
                                )
                                n = built.get("n_slides", "?")
                                await ws.send_json(protocol.notice(
                                    f"↗ Slideshow “{built.get('title')}” "
                                    f"({n} slides) → `{built.get('path')}`. "
                                    f"Wikilink: {built.get('wikilink')}",
                                    kind="slash",
                                ))
                                continue
                            if not arg:
                                decks = await asyncio.to_thread(
                                    html_decks.list_decks, ws_path)
                                if not decks:
                                    await ws.send_json(protocol.notice(
                                        "No HTML slideshows yet. They live in "
                                        "`slideshows/<slug>/` (outside the wiki). "
                                        "Author MD then `/slideshow from-md notes/deck.md`, "
                                        "or link with `[[slideshow:slug|title]]`.",
                                        kind="slash",
                                    ))
                                else:
                                    lines = ", ".join(
                                        f"`{d['slug']}`" for d in decks[:12]
                                    )
                                    await ws.send_json(protocol.notice(
                                        f"Slideshows: {lines}. Open with "
                                        f"`/slideshow <slug>`; build with "
                                        f"`/slideshow from-md <path.md>`.",
                                        kind="slash",
                                    ))
                            else:
                                slug = arg[0]
                                entry = await asyncio.to_thread(
                                    html_decks.entry_html, ws_path, slug)
                                if entry is None:
                                    await ws.send_json(protocol.notice(
                                        f"No slideshow `{slug}` under slideshows/.",
                                        kind="slash",
                                    ))
                                else:
                                    title = slug
                                    try:
                                        meta_p = html_decks.deck_dir(
                                            ws_path, slug) / "deck.json"
                                        if meta_p.is_file():
                                            meta = json.loads(
                                                meta_p.read_text(encoding="utf-8"))
                                            if isinstance(meta, dict) and meta.get("title"):
                                                title = str(meta["title"])
                                    except (OSError, json.JSONDecodeError, ValueError):
                                        pass
                                    asyncio.create_task(
                                        _daemon_ns._open_html_deck_tab(
                                            request.app, ws_path, slug, title),
                                    )
                                    await ws.send_json(protocol.notice(
                                        f"↗ Slideshow “{title}” opened.", kind="slash"))
                            continue
                        if sname.lower() in ("library", "lib", "portfolio"):
                            ws_path = request.app["workspace"]
                            arg = (sargs or "").strip().split()
                            if arg and arg[0].lower() == "search":
                                q = " ".join(arg[1:]).strip()
                                hits = await asyncio.to_thread(
                                    library.search, ws_path, q, limit=12,
                                )
                                if not hits:
                                    await ws.send_json(protocol.notice(
                                        f"No library hits for “{q}”.",
                                        kind="slash",
                                    ))
                                else:
                                    lines = "; ".join(
                                        f"`{h.get('kind')}:{h.get('slug')}` "
                                        f"{h.get('title')}"
                                        for h in hits[:8]
                                    )
                                    await ws.send_json(protocol.notice(
                                        f"Library: {lines}", kind="slash",
                                    ))
                            else:
                                await asyncio.to_thread(
                                    tabstore.add_library_tab, ws_path)
                                await _daemon_ns._broadcast(
                                    request.app, _daemon_ns._hello_payload(request.app))
                                await _daemon_ns._broadcast(
                                    request.app,
                                    protocol.nav("library", {}, "Library"),
                                )
                                await ws.send_json(protocol.notice(
                                    "↗ Library opened.", kind="slash"))
                            continue
                        if sname.lower() in (
                            "report-doc", "report-package", "durable-report",
                        ):
                            ws_path = request.app["workspace"]
                            arg = (sargs or "").strip().split()
                            if not arg:
                                items = await asyncio.to_thread(
                                    report_packages.list_packages, ws_path)
                                if not items:
                                    await ws.send_json(protocol.notice(
                                        "No durable reports yet "
                                        "(`reports/<slug>/`). Promote an "
                                        "ephemeral Report with "
                                        "`/report-doc promote <id>`.",
                                        kind="slash",
                                    ))
                                else:
                                    lines = ", ".join(
                                        f"`{r['slug']}`" for r in items[:12]
                                    )
                                    await ws.send_json(protocol.notice(
                                        f"Reports: {lines}. "
                                        f"`/report-doc <slug>` opens.",
                                        kind="slash",
                                    ))
                            elif arg[0].lower() == "promote" and len(arg) >= 2:
                                try:
                                    res = await asyncio.to_thread(
                                        report_packages.import_from_ephemeral,
                                        ws_path, arg[1],
                                        slug=arg[2] if len(arg) > 2 else None,
                                    )
                                    await ws.send_json(protocol.notice(
                                        f"Saved to library: {res.get('wikilink')}",
                                        kind="slash",
                                    ))
                                except Exception as e:  # noqa: BLE001
                                    await ws.send_json(protocol.notice(
                                        f"Promote failed: {e}", kind="error",
                                    ))
                            else:
                                slug = arg[0]
                                entry = await asyncio.to_thread(
                                    report_packages.entry_path, ws_path, slug)
                                if entry is None:
                                    await ws.send_json(protocol.notice(
                                        f"No report `{slug}`.", kind="slash",
                                    ))
                                else:
                                    title = slug
                                    asyncio.create_task(
                                        _daemon_ns._open_report_doc_tab(
                                            request.app, ws_path, slug, title),
                                    )
                                    await ws.send_json(protocol.notice(
                                        f"↗ Report “{title}” opened.",
                                        kind="slash",
                                    ))
                            continue
                        if sname.lower() in (
                            "worksheet", "worksheets", "workbook", "workbooks",
                        ):
                            ws_path = request.app["workspace"]
                            arg = (sargs or "").strip().split()
                            if not arg:
                                items = await asyncio.to_thread(
                                    worksheets_store.list_packages, ws_path)
                                if not items:
                                    await ws.send_json(protocol.notice(
                                        "No named worksheets yet. In the Sheet "
                                        "tab use Save as worksheet, or "
                                        "`POST /api/worksheets/save`.",
                                        kind="slash",
                                    ))
                                else:
                                    lines = ", ".join(
                                        f"`{w['slug']}`" for w in items[:12]
                                    )
                                    await ws.send_json(protocol.notice(
                                        f"Worksheets: {lines}. "
                                        f"`/worksheet <slug>` opens.",
                                        kind="slash",
                                    ))
                            else:
                                slug = arg[0]
                                snap = await asyncio.to_thread(
                                    worksheets_store.load_snapshot, ws_path, slug)
                                if snap is None:
                                    await ws.send_json(protocol.notice(
                                        f"No worksheet `{slug}`.", kind="slash",
                                    ))
                                else:
                                    await _daemon_ns._broadcast(request.app, protocol.custom({
                                        "type": "open_worksheet",
                                        "slug": slug,
                                        "title": slug,
                                        "snapshot": snap,
                                    }))
                                    await _daemon_ns._broadcast(
                                        request.app,
                                        protocol.nav("univer", {}, "Sheet"),
                                    )
                                    await ws.send_json(protocol.notice(
                                        f"↗ Worksheet “{slug}” → Sheet.",
                                        kind="slash",
                                    ))
                            continue
                        if sname.lower() in ("walkthrough", "tour", "guide"):
                            # Client-side spotlight tour. Always
                            # re-runnable; first-install auto-start is
                            # client-gated via walkthrough-shown marker.
                            await _daemon_ns._broadcast(
                                request.app,
                                protocol.custom({"type": "open_walkthrough"}),
                            )
                            await ws.send_json(protocol.notice(
                                "↗ Walkthrough started — Next advances, ✕ or Esc exits.",
                                kind="slash",
                            ))
                            continue
                        if sname.lower() in ("micro-edits", "microedits", "micro_edit"):
                            asyncio.create_task(
                                _daemon_ns._handle_micro_edits_slash(
                                    request.app, ws, sargs,
                                ),
                            )
                            continue
                        if sname.lower() == "route":
                            # On-the-fly ladder routing: split a described
                            # complex task into N sub-tasks (the planner
                            # decides N) and fan them across the ladder's
                            # worker/sub-task rungs. Reuses the fan-out
                            # engine; the single ladder is the only routing
                            # config (charter design-first).
                            if not sargs.strip():
                                await ws.send_json(protocol.notice(
                                    "usage: /route <describe the complex task to split + route>",
                                    kind="slash"))
                                continue
                            t = asyncio.create_task(
                                _daemon_ns._dispatch_route(request.app, ws, sargs.strip()))
                            t.add_done_callback(
                                _daemon_ns._make_dispatch_error_surface(request.app, ws))
                            continue
                        # ingest / add-source (curate is a desk slash above).
                        # Worker-rung routing: a hybrid ladder
                        # (normal→local) runs the CE action on the local
                        # model without flipping the global default.
                        cp_pid, cp_model = _daemon_ns._ce_action_provider(
                            request.app["workspace"],
                        )
                        _ce_effective_pid = cp_pid or _daemon_ns._resolve_default_provider()
                        _ce_local = _daemon_ns._provider_is_local(_ce_effective_pid)
                        _lrung = None
                        if _ce_local:
                            _lcfg = await asyncio.to_thread(localllm.load_config)
                            _lrung = rail_default.resolve_local_rung(
                                localllm.ram_gb(),
                                model_hint=rail_default.model_hint_from_cfg(_lcfg),
                            )
                        ce_prompt = _daemon_ns._ce_action_prompt(
                            sname.lower(), sargs, local=_ce_local,
                            local_rung=_lrung,
                        )
                        if ce_prompt is not None:
                            if cp_pid:
                                try:
                                    cp_label = llmgateway.get(cp_pid).LABEL
                                except llmgateway.ProviderError:
                                    cp_label = cp_pid
                                await ws.send_json(protocol.notice(
                                    f"/{sname.lower()} running in the "
                                    f"background on {cp_label} "
                                    f"({cp_model}). The rail stays free. "
                                    f"Stop with /{sname.lower()} stop.",
                                    kind="chat",
                                ))
                            else:
                                await ws.send_json(protocol.notice(
                                    f"/{sname.lower()} running in the "
                                    "background. Stop with "
                                    f"/{sname.lower()} stop.",
                                    kind="chat",
                                ))
                            excerpt = (
                                f"[{sname.lower()} · background] "
                                f"{sargs}"
                            ).strip()
                            t = asyncio.create_task(_daemon_ns._dispatch_chat(
                                request.app, None, ce_prompt,
                                provider_override=cp_pid,
                                model_override=cp_model,
                                input_excerpt=excerpt,
                                command=sname.lower() if _ce_local else None,
                            ))
                            t.add_done_callback(
                                _daemon_ns._make_dispatch_error_surface(request.app, None),
                            )
                            continue
                        verb = verbs.lookup(sname)
                        if verb is not None:
                            asyncio.create_task(
                                _daemon_ns._dispatch_verb(request.app, ws, verb, sargs)
                            )
                            continue
                        # User-defined commands (.workbench/commands/ +
                        # ~/.config/switchbay/commands/): the file body
                        # is a prompt template dispatched as a normal
                        # chat turn. Built-ins above always win.
                        template = await asyncio.to_thread(
                            commands.resolve, request.app["workspace"], sname,
                        )
                        if template is not None:
                            _daemon_ns._log_event(
                                request.app, "slash",
                                f"/{sname} {sargs}".rstrip(),
                                source="rail", actor="user",
                                payload={"parsed": parsed, "user_command": True},
                            )
                            t = asyncio.create_task(_daemon_ns._dispatch_chat(
                                request.app, ws,
                                commands.render(template, sargs),
                                input_excerpt=f"/{sname} {sargs}".rstrip()[:120],
                                command=sname.lower(),
                                command_template=template,
                            ))
                            t.add_done_callback(
                                _daemon_ns._make_dispatch_error_surface(request.app, ws),
                            )
                        else:
                            text = f"/{sname} {sargs}".rstrip()
                            _daemon_ns._log_event(
                                request.app, "slash", text,
                                source="rail", actor="user",
                                payload={"parsed": parsed},
                            )
                            await ws.send_json(
                                protocol.notice(
                                    f"unknown slash command: /{sname} (try /view)",
                                    kind="slash",
                                )
                            )
                    elif kind == "cmd" and body.strip():
                        # `!<command>` from the chat input creates a
                        # fresh shell THREAD and pipes the command into
                        # its PTY (Foundation B). Typing in an existing
                        # shell is the xterm's business; the chat-input
                        # case is explicitly "give me a new shell".
                        await _daemon_ns._dispatch_shell_command(request.app, ws, body)
                    elif kind == "python" and body.strip():
                        # `!py <expr>` spawns a python REPL in the
                        # terminal and writes the expression into it.
                        # Same UX shape as `!cmd` — fresh tab, auto-
                        # focus the panel, command flows in 80 ms
                        # after the shell sources its rc.
                        await _daemon_ns._dispatch_shell_command(
                            request.app, ws, body,
                            argv=["python3", "-i"], name=f"! py",
                        )
                    elif kind == "sql" and body.strip():
                        # `!sql <query>` doesn't spawn a shell — it
                        # routes into the Table tab's SQL editor
                        # via a notice the frontend listens for.
                        await _daemon_ns._broadcast(request.app, protocol.custom({
                            "type": "sql.run",
                            "query": body,
                        }))
                    elif kind == "formula" and body.strip():
                        # `!fn <formula>` (or legacy `!exc`) → pushed
                        # into the active Sheet's formula bar so the
                        # cell selected when the user typed it
                        # receives the formula.
                        await _daemon_ns._broadcast(request.app, protocol.custom({
                            "type": "formula.run",
                            "formula": body,
                        }))
                    else:
                        # !sql / !py / !fn — log the user's decision;
                        # tab-specific dispatch lands when each tab
                        # grows its own !-prefix flow.
                        evkind = {
                            "formula": "exec",
                            "sql": "sql",
                            "python": "exec",
                        }.get(kind, "user")
                        _daemon_ns._log_event(
                            request.app, evkind, body or f"({kind})",
                            source="rail", actor="user",
                            payload={"parsed": parsed},
                        )
                        await ws.send_json(
                            protocol.notice(
                                f"parsed as {kind}: {body!r} (no dispatch wired yet)",
                                kind=kind,
                            )
                        )
                elif mtype == "selection_set":
                    sel = data.get("selection")
                    if sel is not None and not isinstance(sel, dict):
                        await ws.send_json(protocol.notice("selection must be object or null"))
                        continue
                    selection.save(workspace, sel)
                    await _daemon_ns._broadcast(request.app, protocol.selection_state(sel))
                elif mtype == "term.attach":
                    await _daemon_ns._handle_term_attach(request.app, ws, data)
                elif mtype == "term.input":
                    await _daemon_ns._handle_term_input(request.app, data)
                elif mtype == "term.resize":
                    await _daemon_ns._handle_term_resize(request.app, data)
                elif mtype == "term.kill":
                    await _daemon_ns._handle_term_kill(request.app, data)
                else:
                    await ws.send_json(
                        protocol.notice(f"unknown message type: {mtype!r}")
                    )
            elif msg.type == WSMsgType.ERROR:
                log.warning("ws error: %s", ws.exception())
    finally:
        request.app["ws_clients"].discard(ws)

    return ws
