"""Workspace merge, split, and digest routes.

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
import re
import uuid
from aiohttp import web
from switchbay import app_settings
from switchbay import capture
from switchbay import cebridge
from switchbay import conversations
from switchbay import merging
from switchbay import protocol
from switchbay import splitting
from switchbay import workspaces

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

async def handle_workspaces_pick(request: web.Request) -> web.Response:
    """Open the OS folder picker. Returns {path: str|null}; null = cancelled
    or no picker available on this platform."""
    path = await workspaces.pick_folder()
    return web.json_response({"path": path})

async def handle_workspaces_merge(request: web.Request) -> web.Response:
    """D2 merge: build a NEW workspace in the workspaces home from 2+
    registered sources — a deterministic daemon-side pipeline (see
    merging.py; no agent, no scope exception). Body: {sources: [path],
    name}. Returns immediately; completion = rail notice + a
    `workspace.merged` toast with an Open button. Originals stay on
    disk and leave the registry (re-Add any time)."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    raw_sources = body.get("sources")
    if not isinstance(raw_sources, list) or len(raw_sources) < 2:
        return web.json_response(
            {"error": "pick at least two workspaces"}, status=400,
        )
    registered = set(workspaces.load()["paths"])
    sources: list[Path] = []
    for raw in raw_sources:
        s = str(raw).strip()
        if s not in registered:
            return web.json_response(
                {"error": f"not a registered workspace: {s}"}, status=400,
            )
        p = Path(s)
        if not p.is_dir():
            return web.json_response(
                {"error": f"missing on disk: {s}"}, status=400,
            )
        sources.append(p)
    name = re.sub(
        r"[^A-Za-z0-9_.-]+", "-", str(body.get("name") or "").strip(),
    ).strip("-.")
    if not name:
        return web.json_response({"error": "name required"}, status=400)
    target = app_settings.workspaces_home_path() / name
    if target.exists():
        return web.json_response(
            {"error": f"target already exists: {target}"}, status=400,
        )
    last = request.app.get("merge_last")
    if isinstance(last, dict) and last.get("state") == "running":
        return web.json_response(
            {"error": "a merge is already running"}, status=409,
        )
    rec: dict[str, Any] = {
        "state": "running", "step": "starting", "target": str(target),
        "name": name, "error": None,
    }
    request.app["merge_last"] = rec

    def _progress(step: str) -> None:
        rec["step"] = step

    async def _worker() -> None:
        try:
            stats = await merging.merge_workspaces(sources, target, _progress)
            # Graph build via CE's own viewer.sh (its uv env has kuzu —
            # the merge subprocess's rebuild is a no-op in our venv).
            # Best-effort: the workspace is valid without it; opening
            # it can always REBUILD VIEWER.
            _progress("building graph")
            try:
                await cebridge.build(target)
            except Exception:  # noqa: BLE001
                log.exception("post-merge viewer build failed (non-fatal)")
            await asyncio.to_thread(
                workspaces.register, target, False,
            )
            # D2: sources leave the registry; folders stay on disk.
            for src in sources:
                await asyncio.to_thread(workspaces.unregister, src)
            rec.update(state="done", step="done")
            _daemon_ns._log_event(
                request.app, "exec",
                f"workspaces merged → {target} "
                f"(from {', '.join(s.name for s in sources)})",
                source="merge", actor="user",
                payload={
                    "target": str(target),
                    "sources": [str(s) for s in sources],
                    **stats,
                },
            )
            await _daemon_ns._broadcast(request.app, protocol.notice(
                f"merge done → {target} (sources left the registry; "
                f"folders untouched). "
                + (f"\n{stats['output_tail']}" if stats.get("output_tail") else ""),
                kind="chat",
            ))
            await _daemon_ns._broadcast(request.app, protocol.custom({
                "type": "workspace.merged",
                "name": name,
                "path": str(target),
            }))
        except merging.MergeError as e:
            rec.update(state="error", error=str(e))
            await _daemon_ns._broadcast(request.app, protocol.notice(
                f"merge failed (originals untouched): {e}", kind="chat",
            ))
        except Exception as e:  # noqa: BLE001
            log.exception("merge crashed")
            rec.update(state="error", error=str(e))
            await _daemon_ns._broadcast(request.app, protocol.notice(
                f"merge crashed (originals untouched): {e}", kind="chat",
            ))

    asyncio.create_task(_worker())
    return web.json_response({"ok": True, "started": True, "target": str(target)})

async def handle_workspaces_merge_status(request: web.Request) -> web.Response:
    last = request.app.get("merge_last")
    return web.json_response({"last": last if isinstance(last, dict) else None})

async def handle_workspaces_split(request: web.Request) -> web.Response:
    """D4 split: the graph review surface confirmed a selection —
    build a NEW workspace in the workspaces home from the ACTIVE
    workspace's pages. `move` pages are exported then trashed here;
    `copy` pages are exported and kept (the duplicate-to-both
    boundary policy). Body: {name, move: [ref], copy: [ref]}."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    move = [str(r).strip() for r in (body.get("move") or []) if str(r).strip()]
    copy = [str(r).strip() for r in (body.get("copy") or []) if str(r).strip()]
    if not move and not copy:
        return web.json_response({"error": "nothing selected"}, status=400)
    name = re.sub(
        r"[^A-Za-z0-9_.-]+", "-", str(body.get("name") or "").strip(),
    ).strip("-.")
    if not name:
        return web.json_response({"error": "name required"}, status=400)
    workspace: Path = request.app["workspace"]
    target = app_settings.workspaces_home_path() / name
    if target.exists():
        return web.json_response(
            {"error": f"target already exists: {target}"}, status=400,
        )
    last = request.app.get("split_last")
    if isinstance(last, dict) and last.get("state") == "running":
        return web.json_response(
            {"error": "a split is already running"}, status=409,
        )
    rec: dict[str, Any] = {
        "state": "running", "step": "starting", "target": str(target),
        "name": name, "error": None,
    }
    request.app["split_last"] = rec

    def _progress(step: str) -> None:
        rec["step"] = step

    async def _worker() -> None:
        try:
            stats = await splitting.split_workspace(
                workspace, target, move, copy, _progress,
            )
            _progress("building graphs")
            for ws_path in (target, workspace):
                try:
                    await cebridge.build(ws_path)
                except Exception:  # noqa: BLE001
                    log.exception("post-split viewer build failed (non-fatal)")
            await asyncio.to_thread(workspaces.register, target, False)
            rec.update(state="done", step="done")
            _daemon_ns._log_event(
                request.app, "exec",
                f"workspace split → {target} "
                f"({stats['moved']} moved, {stats['copied']} copied)",
                source="split", actor="user",
                payload={"target": str(target), **stats},
            )
            extra = ""
            if stats.get("prune_errors"):
                extra = f" · {len(stats['prune_errors'])} pages couldn't be pruned (see log)"
            if stats.get("missing_figures"):
                extra += f" · {len(stats['missing_figures'])} referenced figures missing"
            await _daemon_ns._broadcast(request.app, protocol.notice(
                f"split done → {target} — {stats['moved']} pages moved "
                f"(recoverable from the Trash), {stats['copied']} copied to "
                f"both sides{extra}. Cross-boundary links stay as red links; "
                f"the split manifest (.curator/splits/) records where each "
                f"page went.",
                kind="chat",
            ))
            await _daemon_ns._broadcast(request.app, protocol.custom({
                "type": "workspace.split",
                "name": name,
                "path": str(target),
            }))
            await _daemon_ns._broadcast(request.app, protocol.files_changed())
            # Async curator link-heal (the split-manifest's purpose):
            # one background agent per side, each scoped to ITS OWN
            # workspace, annotating cross-boundary red links. Fail-soft
            # — a keyless daemon just skips.
            for side, ws_path in (("source", workspace), ("target", target)):
                _dispatch_split_heal(request.app, side, ws_path, name, move)
        except (splitting.SplitError, merging.MergeError) as e:
            rec.update(state="error", error=str(e))
            await _daemon_ns._broadcast(request.app, protocol.notice(
                f"split failed (source untouched): {e}", kind="chat",
            ))
        except Exception as e:  # noqa: BLE001
            log.exception("split crashed")
            rec.update(state="error", error=str(e))
            await _daemon_ns._broadcast(request.app, protocol.notice(
                f"split crashed: {e}", kind="chat",
            ))

    asyncio.create_task(_worker())
    return web.json_response({"ok": True, "started": True, "target": str(target)})

async def handle_workspaces_split_status(request: web.Request) -> web.Response:
    last = request.app.get("split_last")
    return web.json_response({"last": last if isinstance(last, dict) else None})

def _dispatch_split_heal(
    app: web.Application, side: str, ws_path: Path, name: str,
    moved: list[str],
) -> None:
    """Post-split link-heal: a normal workspace-scoped background
    agent (workspace_override binds file access to ONE side) that
    reads the split manifest and annotates cross-boundary wikilinks.
    Judgment lives in the agent — deterministic prose rewriting was
    explicitly rejected."""
    if side == "source":
        gone = ", ".join(moved[:40])
        situation = (
            f"Pages that MOVED AWAY to the '{name}' workspace: {gone}.\n"
            "Wikilinks in the remaining pages that point at those are "
            "now red links."
        )
    else:
        situation = (
            "This workspace was just split OUT of another one. Its "
            "pages may contain wikilinks to pages that STAYED BEHIND "
            "in the source workspace — those are now red links here."
        )
    prompt = (
        f"A workspace split just completed. {situation}\n\n"
        "Read the newest manifest in `.curator/splits/` for the full "
        "moved/copied lists, then Grep `wiki/` for wikilinks "
        "(`[[...]]`) whose target is on the other side of the split.\n"
        "For each such link, use judgment per occurrence:\n"
        "  · usually: append a brief parenthetical after the link, "
        "e.g. `[[page]] (now in the " + name + " workspace)` — keep "
        "the link itself (red links are normal CE practice);\n"
        "  · if the sentence reads fine without it, you may leave it "
        "untouched;\n"
        "  · NEVER delete content or rewrite prose beyond the "
        "annotation.\n"
        "Edit files directly with your file tools. Finish with a "
        "one-paragraph summary of what you annotated (or say nothing "
        "needed it)."
    )
    run_id = f"run-{uuid.uuid4().hex[:8]}"

    async def _runner() -> None:
        try:
            await _daemon_ns._dispatch_chat(
                app, ws=None, text=prompt,
                input_excerpt=f"split link-heal ({side})",
                run_id=run_id,
                workspace_override=ws_path if side == "target" else None,
                thread_id_override=None,
            )
        except Exception:  # noqa: BLE001
            log.exception("split heal (%s) crashed", side)

    task = asyncio.create_task(_runner())
    task.add_done_callback(_daemon_ns._make_dispatch_error_surface(app, run_id))

async def handle_split_proposal(request: web.Request) -> web.Response:
    """The agent-driven split gesture (D4): the rail agent's
    `propose_split` tool posts a page set here; valid refs broadcast
    as a `split.proposal` frame, which pre-highlights the SAME graph
    review surface the manual gesture uses. Nothing is split — the
    user reviews, edits, names, and confirms there."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    pages = [str(p).strip() for p in (body.get("pages") or []) if str(p).strip()]
    if not pages:
        return web.json_response({"error": "pages required"}, status=400)
    workspace: Path = request.app["workspace"]
    bad = await asyncio.to_thread(splitting.validate_refs, workspace, pages)
    good = [p for p in pages if p not in set(bad)]
    if not good:
        return web.json_response(
            {"error": "none of those refs are wiki pages", "invalid": bad},
            status=400,
        )
    await _daemon_ns._broadcast(request.app, protocol.custom({
        "type": "split.proposal",
        "pages": good,
        "reason": str(body.get("reason") or "")[:300],
    }))
    return web.json_response({"ok": True, "shown": len(good), "invalid": bad})

async def handle_digest(request: web.Request) -> web.Response:
    """Away-digest (D5): what happened in this workspace since
    `?since=<unix seconds>` — event counts by kind, the notable tail
    (curation, execs, external edits), and pending charter reviews.
    Deterministic; no LLM."""
    workspace: Path = request.app["workspace"]
    try:
        since = float(request.query.get("since", "0"))
    except ValueError:
        return web.json_response({"error": "bad since"}, status=400)
    evs = await asyncio.to_thread(
        conversations.events_since, workspace, since,
    )
    by_kind: dict[str, int] = {}
    for e in evs:
        by_kind[e["kind"]] = by_kind.get(e["kind"], 0) + 1
    notable_kinds = {"exec", "curation", "file_edit_external"}
    notable = [
        {"kind": e["kind"], "summary": e["summary"][:160], "ts": e["created_at"]}
        for e in evs if e["kind"] in notable_kinds
    ][-8:]
    try:
        decisions = await asyncio.to_thread(capture.list_decisions, workspace)
        pending_reviews = sum(1 for d in decisions if d.get("status") == "proposed")
    except Exception:  # noqa: BLE001
        pending_reviews = 0
    return web.json_response({
        "total": len(evs),
        "by_kind": by_kind,
        "notable": notable,
        "pending_reviews": pending_reviews,
    })
