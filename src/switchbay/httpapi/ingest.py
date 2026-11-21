"""Chat upload, vault upload, and ingest-from-path routes.

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
import hashlib
import json
import logging
import os
import re
import uuid
from aiohttp import web
from switchbay import cebridge
from switchbay import ingest_run_drain
from switchbay import llmgateway

from switchbay.httpapi._ns import _daemon_ns

log = logging.getLogger("switchbay.daemon")

async def handle_chat_upload(request: web.Request) -> web.Response:
    """Stage a user-uploaded file under
    `<workspace>/.workbench/uploads/<sha-prefix>/<filename>` and
    return the stable workspace-relative path. The frontend
    prepends a `[attached: <path>]` reference to the next message
    so the agent can read the file via its native file-reading
    tool. We don't carry the bytes through to the provider's
    attachment API directly — for subscription CLIs (claude_code,
    codex) the path-on-disk is what they consume; HTTP providers
    that take attachments are wired in a follow-up.

    Multipart form upload: field `file` holds the binary content
    + filename. Cap at 25 MB so we don't blow up the
    .workbench/state/ directory."""
    workspace: Path = request.app["workspace"]
    reader = await request.multipart()
    field = None
    while True:
        part = await reader.next()
        if part is None:
            break
        if part.name == "file":
            field = part
            break
    if field is None:
        return web.json_response({"error": "no `file` field"}, status=400)
    raw_filename = (field.filename or "upload.bin").strip()
    # Slug-safe version of the basename.
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_filename) or "upload.bin"
    # Read into memory + size cap. multipart streaming would be
    # nicer but uploads are small and the cap is 25 MB.
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await field.read_chunk(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > 25 * 1024 * 1024:
            return web.json_response({"error": "file too large (>25 MB)"}, status=413)
        chunks.append(chunk)
    payload = b"".join(chunks)
    digest = hashlib.sha1(payload).hexdigest()[:12]
    target_dir = workspace / ".workbench" / "uploads" / digest
    target = target_dir / safe_name

    def _write() -> None:
        target_dir.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)

    await asyncio.to_thread(_write)  # up to 25 MB — off the loop
    rel = str(target.relative_to(workspace))
    log.info("chat upload: %s (%d bytes) → %s", raw_filename, total, rel)
    return web.json_response({
        "ok": True,
        "path": rel,
        "size": total,
        "filename": safe_name,
    })

def _safe_vault_filename(name: str) -> str:
    """Same rules as CE's viewer_server: drop directory components and
    replace anything outside ``[A-Za-z0-9._-]`` with ``_``. Empty and
    dot-leading names are refused."""
    name = Path(name).name
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
    if not name or name.startswith("."):
        raise ValueError("invalid filename")
    return name

def _form_truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}

def _upload_ingest_backend() -> str:
    """Which ingest path /api/upload-vault hands files to.

    ``local_ingest``: CE is installed, so queued runs drain through CE's
    deterministic extraction (no model). ``agent``: no CE, but the default
    model provider is ready, so queued runs drain through the rail ingest
    agent (one run per file). ``none``: neither, so files are only saved.
    """
    if cebridge.ce_scripts_available():
        return "local_ingest"
    # Same check _dispatch_chat makes before it will start a run.
    try:
        ready = llmgateway.get(_daemon_ns._resolve_default_provider()).has_key()
    except Exception:  # noqa: BLE001
        log.exception("upload-vault: provider check failed")
        ready = False
    return "agent" if ready else "none"

def _queue_upload_ingest(workspace: Path, saved: list[tuple[str, int]]) -> dict[str, Any]:
    """Queue one ingest-run per saved file for the active backend.

    Reuses the ingest-run queue CE's own drop-ingest writes, so the
    existing drain loop does the work in one pass."""
    backend = _upload_ingest_backend()
    if backend == "none":
        return {
            "requested": True,
            "backend": "none",
            "queued": False,
            "runs": [],
            "message": (
                "Saved to vault/raw/ but not ingested: no ingest backend is "
                "available. Install Curiosity Engine or set up a model "
                "provider in Settings, then ingest from the drop folder."
            ),
        }
    mode = "staged" if backend == "local_ingest" else "llm"
    runs = []
    for name, size in saved:
        rec = ingest_run_drain.enqueue_run(
            workspace, f"vault/raw/{name}", size=size, mode=mode,
            note="queued by the vault upload dialog",
        )
        runs.append({
            "file": name,
            "run_id": rec["run_id"],
            "vault_path": rec["vault_path"],
        })
    return {"requested": True, "backend": backend, "queued": True, "runs": runs}

async def handle_upload_vault(request: web.Request) -> web.Response:
    """Save uploaded files into ``<workspace>/vault/raw/``, optionally
    queueing ingest.

    Switchbay's copy of CE's ``POST /api/upload-vault`` (viewer_server.py),
    used by the graph sidebar's upload dialog and by CE's own edit.js.
    Multipart form; every part that carries a filename is saved, so
    several ``file`` fields can arrive in one request. Names are
    sanitised with CE's rules and an existing file of the same name is
    replaced, as in CE.

    An ``ingest`` form field (true/false, default false) asks for the
    saved files to be ingested; see ``_upload_ingest_backend``. Returns
    CE's ``{ok, saved: [names]}``, plus ``ingest: {...}`` when ingest
    was requested."""
    if "multipart/form-data" not in (request.headers.get("Content-Type") or ""):
        return web.json_response(
            {"error": "multipart/form-data required"}, status=400,
        )
    workspace: Path = request.app["workspace"]
    raw_dir = workspace / "vault" / "raw"
    try:
        reader = await request.multipart()
    except (ValueError, AssertionError):
        return web.json_response({"error": "not multipart"}, status=400)
    saved: list[str] = []
    sizes: list[tuple[str, int]] = []
    want_ingest = False
    while True:
        part = await reader.next()
        if part is None:
            break
        if not getattr(part, "filename", None):
            if getattr(part, "name", None) == "ingest":
                # Small flag; never buffer an oversized field.
                flag = await part.read_chunk(1024)
                want_ingest = _form_truthy(flag.decode("utf-8", "ignore"))
            # Other plain fields (and nested multiparts) carry no file.
            continue
        try:
            safe = _safe_vault_filename(part.filename)
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = await part.read_chunk(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > _daemon_ns.UPLOAD_VAULT_MAX_BYTES:
                return web.json_response(
                    {"error": "file too large (>50 MB)", "saved": saved},
                    status=413,
                )
            chunks.append(chunk)
        payload = b"".join(chunks)
        target = raw_dir / safe

        def _write(target: Path = target, payload: bytes = payload) -> None:
            raw_dir.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex[:8]}.part")
            tmp.write_bytes(payload)
            os.replace(tmp, target)

        try:
            await asyncio.to_thread(_write)
        except OSError as e:
            log.warning("vault upload: writing %s failed: %s", safe, e)
            return web.json_response(
                {"error": f"could not save {safe}: {e.strerror or e}", "saved": saved},
                status=500,
            )
        if safe in saved:
            sizes = [(n, sz) for n, sz in sizes if n != safe]
        else:
            saved.append(safe)
        sizes.append((safe, total))
        log.info("vault upload: %s (%d bytes) -> vault/raw/%s",
                 part.filename, total, safe)
    if not saved:
        return web.json_response(
            {"error": "no file part with filename"}, status=400,
        )
    body: dict[str, Any] = {"ok": True, "saved": saved}
    if want_ingest:
        info = await asyncio.to_thread(_queue_upload_ingest, workspace, sizes)
        if info.get("queued"):
            ingest_run_drain.kick_drain(request.app)
        body["ingest"] = info
    return web.json_response(body)

async def handle_ingest_from_upload(request: web.Request) -> web.Response:
    """Stage a file under the workspace's `vault/` directory (CE's
    convention for ingested raw materials) and kick a headless
    ingest agent that classifies + writes a CE-shaped wiki page.

    Multipart form: field `file` holds the binary content. The agent
    decides the page's type (`source` for PDF/article-shaped docs,
    `note` for plain text, `figure` for images, etc.) and creates
    `wiki/<type>s/<slug>.md` with appropriate frontmatter — same as
    the manual ingest flow CE skills use.

    Returns `{run_id, vault_path, filename, size}` immediately so the
    Browser can show a spinner + link the user into the Agent
    Dashboard for the live transcript."""
    workspace: Path = request.app["workspace"]
    reader = await request.multipart()
    field = None
    while True:
        part = await reader.next()
        if part is None:
            break
        if part.name == "file":
            field = part
            break
    if field is None:
        return web.json_response({"error": "no `file` field"}, status=400)
    raw_filename = (field.filename or "upload.bin").strip()
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_filename) or "upload.bin"
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await field.read_chunk(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > 50 * 1024 * 1024:  # 50 MB cap for vault ingest
            return web.json_response(
                {"error": "file too large (>50 MB)"}, status=413,
            )
        chunks.append(chunk)
    payload = b"".join(chunks)
    digest = hashlib.sha1(payload).hexdigest()[:12]
    target_dir = workspace / "vault" / digest
    target = target_dir / safe_name

    def _write() -> None:
        target_dir.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)

    await asyncio.to_thread(_write)  # up to 50 MB — off the loop
    rel = str(target.relative_to(workspace))
    log.info("ingest upload: %s (%d bytes) → %s", raw_filename, total, rel)

    # Build the ingest prompt. The agent has Read/Bash/Write via
    # claude-code's tools + our MCP bridge. We tell it the path and
    # let it inspect, classify, and write the resulting wiki page.
    ext = Path(safe_name).suffix.lower().lstrip(".")
    ext_hint = (
        f"The file has extension `.{ext}`." if ext
        else "The file has no extension."
    )
    prompt = (
        f"A file was just dropped into the workspace's vault at "
        f"`{rel}` (size {total} bytes). {ext_hint} Ingest it as a "
        f"CE-shaped wiki page:\n\n"
        f"  1. Read the file (use Read for text/markdown; for PDFs "
        f"or other binaries, try a shell extraction first — e.g. "
        f"`pdftotext` if available, or just describe by filename + "
        f"size when the contents aren't readable).\n"
        f"  2. Classify into one of CE's page types: `source` "
        f"(PDFs, articles, reports — the usual citable artifacts), "
        f"`note` (plain user-authored text), `figure` (images), "
        f"`unclassified` (anything you can't otherwise place).\n"
        f"  3. Slugify the filename to a kebab-case stem (lowercase, "
        f"alphanumeric + hyphens). Write the wiki page using Write "
        f"to `wiki/<type>s/<slug>.md` with frontmatter `type: "
        f"<type>`, `title: \"[<typ>] <human title>\"`, `created` / "
        f"`updated` dates, and `extracted_from: {rel}` so the round-"
        f"trip target is recorded. The bracketed title-prefix follows "
        f"CE convention (`[src]`, `[note]`, `[fig]`).\n"
        f"  4. Body: 2-4 paragraphs of metadata + key takeaways. "
        f"Don't overcommit on prose — readers want the gist + a "
        f"pointer to the original, not a re-summary.\n"
        f"  5. Don't run any other tools after Write. The graph "
        f"rebuilds automatically when the wiki/ tree changes."
    )

    run_id = f"run-{uuid.uuid4().hex[:8]}"

    async def _runner() -> None:
        try:
            await _daemon_ns._dispatch_chat(
                request.app, ws=None, text=prompt,
                input_excerpt=f"ingest {safe_name}",
                run_id=run_id,
                command="ingest",
            )
        except Exception:  # noqa: BLE001
            log.exception("ingest run %s crashed", run_id)

    task = asyncio.create_task(_runner())
    task.add_done_callback(_daemon_ns._make_dispatch_error_surface(request.app, run_id))

    # Tag the run so future surfaces can find it by vault path.
    async def _tag_run() -> None:
        await asyncio.sleep(0)
        runs = request.app.get("runs") or {}
        rec = runs.get(run_id)
        if rec is not None:
            rec["vault_path"] = rel
            rec["kind"] = "ingest-upload"
    asyncio.create_task(_tag_run())

    return web.json_response({
        "ok": True,
        "run_id": run_id,
        "vault_path": rel,
        "filename": safe_name,
        "size": total,
    })

async def handle_ingest_from_path(request: web.Request) -> web.Response:
    """Kick the ingest agent against an already-in-workspace file
    (eg. a CSV the user just saved into `vault/raw/`). Mirrors
    /api/ingest/from-upload but skips the staging step. Body:
    `{path: <workspace-rel-path>}`. Returns `{run_id}` immediately
    so the UI can route into Agents for the live transcript."""
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    rel = str(body.get("path") or "").strip()
    if not rel:
        return web.json_response({"error": "path required"}, status=400)
    candidate = (workspace / rel).resolve()
    if not _daemon_ns._within(workspace, candidate):
        return web.json_response(
            {"error": "path outside workspace"}, status=400,
        )
    if not candidate.is_file():
        return web.json_response({"error": "file not found"}, status=404)
    total = candidate.stat().st_size
    ext = candidate.suffix.lower().lstrip(".")
    ext_hint = (
        f"The file has extension `.{ext}`." if ext
        else "The file has no extension."
    )
    prompt = (
        f"A file in this workspace at `{rel}` needs ingestion "
        f"(size {total} bytes). {ext_hint} Ingest it as a CE-shaped "
        f"wiki page:\n\n"
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
        f"`created` / `updated`, and `extracted_from: {rel}` so the "
        f"round-trip target is recorded. Use the CE bracket-prefix "
        f"convention (`[tab]`, `[src]`, `[note]`, `[fig]`).\n"
        f"  4. Body: for tables, the full markdown table + a one-line "
        f"caption above. For sources, 2-4 paragraphs of metadata + "
        f"key takeaways. Don't write tools after Write — the graph "
        f"rebuilds automatically on wiki/ changes.\n"
        f"  5. If a wiki page with the same slug already exists "
        f"because this file was ingested before, append `-2`, `-3` "
        f"… so the new ingest doesn't clobber the previous one."
    )
    run_id = f"run-{uuid.uuid4().hex[:8]}"

    async def _runner() -> None:
        try:
            await _daemon_ns._dispatch_chat(
                request.app, ws=None, text=prompt,
                input_excerpt=f"ingest {candidate.name}",
                run_id=run_id,
                command="ingest",
            )
        except Exception:  # noqa: BLE001
            log.exception("ingest run %s crashed", run_id)

    task = asyncio.create_task(_runner())
    task.add_done_callback(_daemon_ns._make_dispatch_error_surface(request.app, run_id))

    async def _tag_run() -> None:
        await asyncio.sleep(0)
        runs = request.app.get("runs") or {}
        rec = runs.get(run_id)
        if rec is not None:
            rec["vault_path"] = rel
            rec["kind"] = "ingest-from-path"
    asyncio.create_task(_tag_run())

    return web.json_response({
        "ok": True,
        "run_id": run_id,
        "path": rel,
        "size": total,
    })
