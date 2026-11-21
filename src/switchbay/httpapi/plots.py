"""Plot, sketch, and gallery commands.

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
import time
import uuid
from aiohttp import web
from switchbay import atomicio
from switchbay import plot_gallery
from switchbay import plots
from switchbay import protocol
from switchbay import sketches
from switchbay import ui_focus

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

async def handle_plot_command(request: web.Request) -> web.Response:
    """Agent → Plot tab.

    Body:
      {op: "show", id: "<plot_id>", wait_ack?: true}
      {op: "update", id?, name?, spec, wait_ack?: true}
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "body must be an object"}, status=400)
    ws = _daemon_ns._workspace_from_request(request, body)
    if isinstance(ws, web.Response):
        return ws
    op = str(body.get("op") or "").strip()
    wait_ack = bool(body.get("wait_ack"))

    if op == "show":
        pid = str(body.get("id") or "").strip()
        if not pid:
            focus = await asyncio.to_thread(ui_focus.load, ws, "plot")
            pid = str((focus or {}).get("id") or "").strip()
        if not pid:
            return web.json_response(
                {"error": "no plot id — pass id or focus a plot card"}, status=400)
        rec = await asyncio.to_thread(plots.get_plot, ws, pid)
        if not rec:
            return web.json_response({"error": f"unknown plot id {pid!r}"}, status=404)
        name = str(rec.get("name") or pid)
        command_id = uuid.uuid4().hex if wait_ack else None
        fut = _daemon_ns._register_ui_ack(request.app, command_id) if command_id else None
        await _daemon_ns._broadcast(request.app, protocol.custom({
            "type": "plot.show",
            "id": pid,
            "name": name,
            "command_id": command_id,
            "workspace": str(ws),
        }))
        await asyncio.to_thread(ui_focus.save, ws, "plot", {
            "id": pid, "name": name,
        })
        await _daemon_ns._broadcast(request.app, protocol.notice(
            f"Opened Plot · {name}", kind="chat"))
        if not wait_ack or fut is None or command_id is None:
            return web.json_response({
                "ok": True, "op": "show", "id": pid, "name": name,
                "workspace": str(ws),
            })
        ack = await _daemon_ns._wait_ui_ack(request.app, command_id, fut)
        if ack.get("timeout") or not ack.get("ok"):
            return web.json_response({
                "ok": False,
                "error": ack.get("error") or "Plot show failed",
                "command_id": command_id,
                "id": pid,
                "workspace": str(ws),
            }, status=504 if ack.get("timeout") else 422)
        return web.json_response({
            "ok": True, "op": "show", "id": pid, "name": name,
            "applied": True, "command_id": command_id, "workspace": str(ws),
        })

    if op == "update":
        spec = body.get("spec")
        if not isinstance(spec, dict):
            return web.json_response({"error": "`spec` object is required"}, status=400)
        pid = str(body.get("id") or "").strip() or None
        if not pid:
            focus = await asyncio.to_thread(ui_focus.load, ws, "plot")
            pid = str((focus or {}).get("id") or "").strip() or None
        name = str(body.get("name") or "").strip()
        if not name and pid:
            existing = await asyncio.to_thread(plots.get_plot, ws, pid)
            name = str((existing or {}).get("name") or pid)
        if not name:
            name = "Untitled plot"
        try:
            rec = await asyncio.to_thread(
                plots.save_plot, ws,
                name=name, spec=spec, plot_id=pid,
            )
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        command_id = uuid.uuid4().hex if wait_ack else None
        fut = _daemon_ns._register_ui_ack(request.app, command_id) if command_id else None
        await _daemon_ns._broadcast(request.app, protocol.files_changed())
        await _daemon_ns._broadcast(request.app, protocol.custom({
            "type": "plot.show",
            "id": rec["id"],
            "name": rec["name"],
            "command_id": command_id,
            "workspace": str(ws),
        }))
        await asyncio.to_thread(ui_focus.save, ws, "plot", {
            "id": rec["id"], "name": rec["name"],
        })
        if not wait_ack or fut is None or command_id is None:
            return web.json_response({
                "ok": True,
                "op": "update",
                "id": rec["id"],
                "name": rec["name"],
                "workspace": str(ws),
                "durable": True,
                "note": "Plot saved and shown in the Plot tab.",
            })
        ack = await _daemon_ns._wait_ui_ack(request.app, command_id, fut)
        if ack.get("timeout") or not ack.get("ok"):
            # Spec is already durable on disk; still report show failure.
            return web.json_response({
                "ok": False,
                "error": (
                    ack.get("error")
                    or "Plot saved on disk but Plot tab did not confirm show"
                ),
                "command_id": command_id,
                "id": rec["id"],
                "name": rec["name"],
                "durable": True,
                "workspace": str(ws),
            }, status=504 if ack.get("timeout") else 422)
        return web.json_response({
            "ok": True,
            "op": "update",
            "id": rec["id"],
            "name": rec["name"],
            "workspace": str(ws),
            "applied": True,
            "durable": True,
            "command_id": command_id,
            "note": "Plot saved and shown in the Plot tab.",
        })

    return web.json_response(
        {"error": f"unknown op {op!r}; expected show|update"}, status=400)

async def handle_sketch_command(request: web.Request) -> web.Response:
    """Agent → Sketch tab.

    Body:
      {op: "show", sketch_id?: str, slide_index?: int, wait_ack?: true}
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "body must be an object"}, status=400)
    ws = _daemon_ns._workspace_from_request(request, body)
    if isinstance(ws, web.Response):
        return ws
    op = str(body.get("op") or "").strip()
    if op != "show":
        return web.json_response(
            {"error": f"unknown op {op!r}; expected show"}, status=400)

    sid = str(body.get("sketch_id") or body.get("id") or "").strip()
    slide_index = body.get("slide_index")
    if not sid:
        focus = await asyncio.to_thread(ui_focus.load, ws, "sketch")
        sid = str((focus or {}).get("sketch_id") or "").strip()
    if not sid and slide_index is None:
        return web.json_response({
            "error": "pass sketch_id or slide_index (or focus a slide first)",
        }, status=400)

    name = ""
    if sid:
        rec = await asyncio.to_thread(sketches.get_sketch, ws, sid)
        name = str((rec or {}).get("name") or sid)

    wait_ack = bool(body.get("wait_ack"))
    command_id = uuid.uuid4().hex if wait_ack else None
    fut = _daemon_ns._register_ui_ack(request.app, command_id) if command_id else None
    await _daemon_ns._broadcast(request.app, protocol.custom({
        "type": "sketch.show",
        "sketch_id": sid or None,
        "slide_index": slide_index if isinstance(slide_index, int) else None,
        "name": name or None,
        "command_id": command_id,
        "workspace": str(ws),
    }))
    if sid:
        await asyncio.to_thread(ui_focus.save, ws, "sketch", {
            "sketch_id": sid, "name": name,
            "slide_index": slide_index if isinstance(slide_index, int) else None,
        })
    if not wait_ack or fut is None or command_id is None:
        return web.json_response({
            "ok": True,
            "op": "show",
            "sketch_id": sid or None,
            "slide_index": slide_index,
            "name": name or None,
            "workspace": str(ws),
        })
    ack = await _daemon_ns._wait_ui_ack(request.app, command_id, fut)
    if ack.get("timeout") or not ack.get("ok"):
        return web.json_response({
            "ok": False,
            "error": ack.get("error") or "Sketch show failed",
            "command_id": command_id,
            "sketch_id": sid or None,
            "workspace": str(ws),
        }, status=504 if ack.get("timeout") else 422)
    return web.json_response({
        "ok": True,
        "op": "show",
        "sketch_id": sid or None,
        "slide_index": slide_index,
        "name": name or None,
        "applied": True,
        "command_id": command_id,
        "workspace": str(ws),
    })

async def handle_sheet_save_csv(request: web.Request) -> web.Response:
    """Write a CSV file under `<workspace>/<dir>/<name>.csv`.

    Body: `{name, values, dir?}`. `dir` defaults to `vault/tables`
    and is restricted to paths inside the workspace. Values get
    RFC-4180-style quoted: any cell with a comma, quote, or newline
    is wrapped in double quotes with internal quotes doubled.
    Refuses to overwrite an existing file — the client surfaces
    the name collision so the user can rename.
    """
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    name = str(body.get("name") or "").strip()
    values = body.get("values")
    dest_dir = str(body.get("dir") or "vault/tables").strip().strip("/")
    if not name:
        return web.json_response({"error": "name required"}, status=400)
    if not isinstance(values, list):
        return web.json_response({"error": "values must be a list"}, status=400)
    # Resolve + containment-check the destination directory. Block
    # path-traversal by confirming the resolved path stays inside
    # the workspace root.
    ws_resolved = workspace.resolve()
    target_dir = (workspace / dest_dir).resolve()
    if not _daemon_ns._within(workspace, target_dir):
        return web.json_response(
            {"error": "dir outside workspace"}, status=400,
        )
    # Slugify the user-supplied filename; drop any leading dots so
    # path-traversal can't happen via leading "../".
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.")
    if not safe:
        return web.json_response({"error": "name has no safe characters"}, status=400)
    if not safe.lower().endswith(".csv"):
        safe = f"{safe}.csv"
    target = target_dir / safe
    rel_dir = target_dir.relative_to(ws_resolved).as_posix()
    if target.exists():
        return web.json_response(
            {"error": f"file exists: {rel_dir}/{safe}"}, status=409,
        )
    # Build CSV bytes.
    import csv
    import io
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    for row in values:
        if not isinstance(row, list):
            continue
        writer.writerow(["" if v is None else v for v in row])

    def _write() -> None:
        target_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(buf.getvalue(), encoding="utf-8")

    await asyncio.to_thread(_write)
    rel = str(target.relative_to(workspace.resolve()).as_posix())
    log.info("sheet csv saved: %s (%d rows)", rel, len(values))
    # Broadcast so the file browser refreshes.
    await _daemon_ns._broadcast(request.app, protocol.files_changed())
    return web.json_response({"ok": True, "path": rel})

async def handle_plots_list(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]

    def _build() -> tuple[list[str], dict[str, Any]]:
        created = plot_gallery.backfill_figure_docs(workspace)
        return created, plot_gallery.gallery(workspace)

    created, data = await asyncio.to_thread(_build)
    if created:
        await _daemon_ns._broadcast(request.app, protocol.files_changed())
    return web.json_response(data)

async def handle_plot_thumb(request: web.Request) -> web.Response:
    """Small cached PNG for a generated plot. Not the full-size asset."""
    workspace: Path = request.app["workspace"]
    plot_id = request.match_info.get("plot_id", "").strip()
    png = await asyncio.to_thread(plot_gallery.thumbnail_bytes, workspace, plot_id)
    if not png:
        return web.json_response({"error": "not found"}, status=404)
    return web.Response(
        body=png,
        content_type="image/png",
        headers={
            "Cache-Control": "private, max-age=60",
            "X-Content-Type-Options": "nosniff",
        },
    )

async def handle_plot_figure(request: web.Request) -> web.Response:
    """Figure page written for a generated plot."""
    workspace: Path = request.app["workspace"]
    plot_id = request.query.get("id", "").strip()
    if not plot_id:
        return web.json_response({"error": "id required"}, status=400)
    doc = await asyncio.to_thread(plot_gallery.figure_doc_for_plot, workspace, plot_id)
    if doc is None:
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response(doc)

async def handle_plot_get(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    plot_id = request.query.get("id", "").strip()
    if not plot_id:
        return web.json_response({"error": "id required"}, status=400)
    try:
        plot = plots.get_plot(workspace, plot_id)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    if plot is None:
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response({"plot": plot})

async def handle_plot_post(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    name = str(body.get("name") or "").strip()
    spec = body.get("spec")
    plot_id = body.get("id")
    if not isinstance(spec, dict):
        return web.json_response({"error": "spec must be an object"}, status=400)
    try:
        record = plots.save_plot(
            workspace, name=name, spec=spec,
            plot_id=plot_id if isinstance(plot_id, str) and plot_id else None,
        )
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({"plot": record})

async def handle_plot_delete(request: web.Request) -> web.Response:
    workspace: Path = request.app["workspace"]
    plot_id = request.query.get("id", "").strip()
    if not plot_id:
        return web.json_response({"error": "id required"}, status=400)
    try:
        ok = plots.delete_plot(workspace, plot_id)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({"ok": ok})

async def handle_plots_from_table(request: web.Request) -> web.Response:
    """Kick an agent run that authors 2-4 informative Vega-Lite plots
    from a table payload. The table arrives inlined as `values` (a 2D
    array, first row = headers); `origin` is a human-readable
    breadcrumb (e.g., "[tab] Table p.16 — Table VII…") that the
    prompt threads into plot names so the result is traceable back to
    the source. Returns the run_id so the caller can show a spinner /
    link to the live transcript."""
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    values = body.get("values")
    origin = str(body.get("origin") or "").strip() or "table"
    if not isinstance(values, list) or not values:
        return web.json_response({"error": "values must be a non-empty 2D array"}, status=400)
    # Trim to a reasonable preview window — the agent shouldn't see
    # 50000 rows inline. It can re-query if the user wants the full
    # range, but for plot brainstorming the head is enough.
    headers = [str(c).strip() for c in values[0]]
    preview_rows: list[list[Any]] = []
    for row in values[1:51]:
        if isinstance(row, list):
            preview_rows.append(row[: len(headers)])
    tsv_preview = "\n".join(
        ["\t".join(headers)]
        + ["\t".join("" if c is None else str(c) for c in r) for r in preview_rows[:20]]
    )
    total_rows = max(0, len(values) - 1)
    prompt = (
        f"Author 2-4 informative Vega-Lite plots that surface the most "
        f"interesting patterns in this table.\n\n"
        f"Origin: `{origin}` ({total_rows} data rows, {len(headers)} columns).\n\n"
        f"First 20 rows (tab-separated, with header row):\n"
        f"```tsv\n{tsv_preview}\n```\n\n"
        f"Required for every plot — these are not optional, plots that "
        f"miss them render blank or unlabelled in the Plot tab:\n"
        f"  1. Inline data in `spec.data.values: [...]` — an array of "
        f"objects keyed by header name. Never reference external CSV "
        f"paths or named datasets.\n"
        f"  2. A `spec.description` field with ONE plain-prose sentence "
        f"explaining what the chart shows. This becomes the figure "
        f"legend under the plot tile — write it for someone scanning "
        f"the gallery who hasn't read the table. Don't put the legend "
        f"in your chat response; put it in spec.description so it "
        f"travels with the plot.\n"
        f"  3. A `spec.title` string with a concise descriptor that "
        f"names the variables (e.g. \"Test MAE vs training-set size\"). "
        f"Include the origin label in the title where it adds context.\n"
        f"  4. A `mark` and an `encoding` block — verify the spec "
        f"would actually render a visible mark before calling "
        f"save_plot. A bar/scatter/line/point spec with no `encoding` "
        f"renders an empty canvas.\n"
        f"  5. Pass `origin=\"{origin}\"` to every save_plot call. "
        f"This breadcrumb lets the Plot tab recognise that this "
        f"table has already been plotted — clicking ↗ Plot a second "
        f"time will then just open the existing plots instead of "
        f"re-running you. Skip this and the user will get duplicate "
        f"plots every time they click.\n\n"
        f"Tile sizing (optional): if a plot really needs more room "
        f"(many categories, wide faceted layout, long time-series), "
        f"set `spec.usermeta.tile` to claim more grid cells:\n"
        f"    \"usermeta\": {{ \"tile\": {{ \"size\": \"wide\" }} }}    // 2 cols\n"
        f"    \"usermeta\": {{ \"tile\": {{ \"size\": \"tall\" }} }}    // 2 rows\n"
        f"    \"usermeta\": {{ \"tile\": {{ \"size\": \"large\" }} }}   // 2x2\n"
        f"    \"usermeta\": {{ \"tile\": {{ \"size\": \"full\" }} }}    // full row\n"
        f"Or pass `cols` / `rows` explicitly (1-4 / 1-3). Default "
        f"is 1x1 — use the hint sparingly; most plots fit one cell.\n\n"
        f"Chart-shape guidance:\n"
        f"  · scatter for two numeric columns, bar for "
        f"category-vs-numeric, line for time-series, faceted "
        f"small-multiples when a third dimension helps the story.\n"
        f"  · Skip columns that are all-same or all-empty — they're "
        f"axis noise.\n"
        f"  · Cap your data array at the full table; if the table is "
        f">500 rows, aggregate or sample first via inline transform.\n\n"
        f"After saving, do NOT write a long explanation in chat — the "
        f"`description` field on each spec already carries the legend. "
        f"A one-line summary referencing the plot names is enough."
    )
    run_id = f"run-{uuid.uuid4().hex[:8]}"

    async def _runner() -> None:
        try:
            await _daemon_ns._dispatch_chat(
                request.app, ws=None, text=prompt,
                input_excerpt=f"plots from {origin}",
                run_id=run_id,
                command="plot",
            )
        except Exception:  # noqa: BLE001
            log.exception("plots-from-table run %s crashed", run_id)

    asyncio.create_task(_runner())
    return web.json_response({"run_id": run_id, "origin": origin})

async def handle_plot_save_as_figure(request: web.Request) -> web.Response:
    """Promote a plot into a CE-shaped figure doc.

    Writes `<ws>/wiki/figures/_assets/<slug>.png` from the
    base64-encoded PNG the frontend rendered via vega-embed, and
    creates `<ws>/wiki/figures/<slug>.md` with frontmatter pointing
    at that asset. Re-saving an existing plot overwrites the PNG
    but keeps the figure doc's body intact so the user can layer
    annotations on top.
    """
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    plot_id = str(body.get("id") or "").strip()
    png_b64 = body.get("png_b64")
    if not plot_id:
        return web.json_response({"error": "id required"}, status=400)
    if not isinstance(png_b64, str) or not png_b64:
        return web.json_response({"error": "png_b64 required"}, status=400)
    plot = plots.get_plot(workspace, plot_id)
    if plot is None:
        return web.json_response({"error": "plot not found"}, status=404)
    name = plot.get("name") or plot_id
    import base64 as _b64
    raw = png_b64.strip()
    if raw.startswith("data:"):
        comma = raw.find(",")
        if comma == -1:
            return web.json_response({"error": "malformed data URL"}, status=400)
        raw = raw[comma + 1:]
    try:
        png_bytes = _b64.b64decode(raw, validate=False)
    except (ValueError, _b64.binascii.Error) as e:
        return web.json_response({"error": f"invalid base64: {e}"}, status=400)
    figures_dir = workspace / "wiki" / "figures"
    assets_dir = figures_dir / "_assets"
    slug = plots._slugify(str(name))  # type: ignore[attr-defined]
    if not slug:
        slug = plot_id
    asset_name = f"{slug}.png"
    asset_path = assets_dir / asset_name
    figure_path = figures_dir / f"{slug}.md"
    today = time.strftime("%Y-%m-%d", time.gmtime())

    def _write_figure() -> bool:
        # All filesystem work off the event loop (mkdir + PNG write +
        # frontmatter read/rewrite); returns whether the doc pre-existed.
        figures_dir.mkdir(parents=True, exist_ok=True)
        assets_dir.mkdir(parents=True, exist_ok=True)
        asset_path.write_bytes(png_bytes)
        if figure_path.exists():
            # Don't clobber a hand-edited body — bump `updated:` and
            # fill in missing caption/provenance if the stub is still
            # the auto-promoted placeholder.
            try:
                text = figure_path.read_text(encoding="utf-8")
                if text.startswith("---\n"):
                    end = text.find("\n---\n", 4)
                    if end != -1:
                        head = text[4:end]
                        rest = text[end + 5:]
                        new_head_lines: list[str] = []
                        bumped = False
                        for line in head.splitlines():
                            if line.startswith("updated:"):
                                new_head_lines.append(f"updated: {today}")
                                bumped = True
                            else:
                                new_head_lines.append(line)
                        if not bumped:
                            new_head_lines.append(f"updated: {today}")
                        atomicio.write_text_atomic(
                            figure_path,
                            "---\n" + "\n".join(new_head_lines) + "\n---\n" + rest,
                        )
            except OSError:
                pass
            return True
        body_md = plots.figure_page_markdown(
            plot, asset_name=asset_name, today=today,
        )
        atomicio.write_text_atomic(figure_path, body_md)
        return False

    existed = await asyncio.to_thread(_write_figure)
    # Wire [[wikilinks]] from caption/provenance, rebuild kuzu + viewer
    # so the wiki browser and graph pick the figure up without curate.
    fig_rel = f"wiki/figures/{slug}.md"
    try:
        asyncio.create_task(_daemon_ns._after_wiki_write(request.app, workspace, fig_rel))
    except Exception:  # noqa: BLE001
        log.exception("graph rebuild scheduling failed (plot save-as-figure)")
    return web.json_response({
        "ok": True,
        "asset_path": f"wiki/figures/_assets/{asset_name}",
        "figure_path": f"wiki/figures/{slug}.md",
        "created": not existed,
    })
