"""Single-report fetch and proposal decision routes.

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
from aiohttp import web
from switchbay import llmgateway
from switchbay import orchestrator_fs
from switchbay import proposals
from switchbay import protocol
from switchbay import report_html
from switchbay import reports

from switchbay.httpapi._ns import _daemon_ns

async def handle_report_get(request: web.Request) -> web.Response:
    """Serve a report's self-contained HTML (rendered in a sandboxed
    iframe by the Report tab). Machine-local; 404 if unknown."""
    workspace: Path = request.app["workspace"]
    report_id = request.match_info.get("report_id", "")
    html = await asyncio.to_thread(reports.html_of, workspace, report_id)
    if html is None:
        return web.json_response({"error": "no such report"}, status=404)
    return _daemon_ns._untrusted_html_response(report_html.linkify_report_html(html))

async def handle_proposals_pending(request: web.Request) -> web.Response:
    """Open (proposed) page proposals — disk-backed, survive restarts."""
    workspace: Path = request.app["workspace"]
    entries = await asyncio.to_thread(proposals.list_proposals, workspace)
    return web.json_response(
        {"proposals": [e for e in entries if e.get("status") == "proposed"]})

def _proposal_preview_html(entry: dict[str, Any]) -> str:
    """Render a staged page + the reviewer's annotations as a single-
    column HTML report (patterned on the curation-quality artifact, no
    side-by-side). Self-contained for the sandboxed Report tab."""
    import html as _html
    v = entry.get("review") or {}
    verdict = str(v.get("verdict") or "review").lower()
    vclass = {"accept": "accept", "edit": "edit"}.get(verdict, "reject")
    issues = "".join(
        f"<li>{_html.escape(str(i))}</li>" for i in (v.get("issues") or []))
    one = _html.escape(str(v.get("one_line") or ""))
    body = _html.escape(entry.get("body") or "")
    kind = _html.escape(str(entry.get("kind") or "page"))
    title = _html.escape(str(entry.get("title") or entry.get("path") or "Proposal"))
    path = _html.escape(str(entry.get("path") or ""))
    op = _html.escape(str(entry.get("op") or "create"))
    conf = v.get("confidence")
    conf_s = f"{conf:.2f}" if isinstance(conf, (int, float)) else "—"
    ann = (f'<div class="ann"><div class="ann-head">Reviewer · '
           f'<span class="v v--{vclass}">{_html.escape(verdict)}</span> '
           f'<span class="conf">conf {conf_s}</span></div>'
           f'<p class="one">{one}</p>'
           + (f"<ul>{issues}</ul>" if issues else "")
           + "</div>") if v else ""
    return f"""<!doctype html><meta charset="utf-8">
<title>{title}</title>
<style>
:root{{--bg:#eceff1;--surface:#fff;--ink:#14181b;--muted:#5c656d;--line:#d5dbdf;
--accent:#0a6a68;--edit:#a6711a;--reject:#b0323f;--accept:#2e7b4c;
--mono:ui-monospace,"SF Mono",Menlo,monospace;--serif:"Iowan Old Style",Georgia,serif;
--sans:system-ui,-apple-system,"Segoe UI",sans-serif;}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0d1013;--surface:#161b1e;--ink:#e6eaec;
--muted:#9aa3ab;--line:#293037;--accent:#4cccc0;--edit:#dcae5b;--reject:#e57a89;--accept:#69c08d;}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);
font-family:var(--sans);line-height:1.55}}
.wrap{{max-width:820px;margin:0 auto;padding:40px 28px 72px}}
.eyebrow{{font-family:var(--mono);font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--accent);margin-bottom:10px}}
h1{{font-family:var(--serif);font-weight:600;font-size:32px;line-height:1.1;margin:0 0 8px;text-wrap:balance}}
.path{{font-family:var(--mono);font-size:12.5px;color:var(--muted);margin-bottom:24px}}
.ann{{background:var(--surface);border:1px solid var(--line);border-left:3px solid var(--edit);
border-radius:10px;padding:16px 20px;margin:0 0 22px}}
.ann-head{{font-family:var(--mono);font-size:12px;letter-spacing:.04em;color:var(--muted);text-transform:uppercase;margin-bottom:8px}}
.v{{padding:2px 9px;border-radius:999px;font-weight:600}}
.v--edit{{background:color-mix(in srgb,var(--edit) 17%,transparent);color:var(--edit)}}
.v--reject{{background:color-mix(in srgb,var(--reject) 15%,transparent);color:var(--reject)}}
.v--accept{{background:color-mix(in srgb,var(--accept) 16%,transparent);color:var(--accept)}}
.conf{{opacity:.7}}.one{{font-size:15px;margin:6px 0 10px}}
.ann ul{{margin:0;padding-left:20px}}.ann li{{font-size:13.5px;color:var(--muted);margin-bottom:6px}}
.doc-label{{font-family:var(--mono);font-size:12px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);margin:0 0 8px}}
pre.doc{{background:var(--surface);border:1px solid var(--line);border-radius:10px;
padding:18px 20px;font-family:var(--mono);font-size:13px;line-height:1.55;
white-space:pre-wrap;word-break:break-word;overflow-x:auto}}
</style>
<div class="wrap">
<div class="eyebrow">proposed {kind} · {op}</div>
<h1>{title}</h1>
<div class="path">{path}</div>
{ann}
<p class="doc-label">Proposed page</p>
<pre class="doc">{body}</pre>
</div>"""

async def handle_proposal_preview(request: web.Request) -> web.Response:
    """Render a proposal + its reviewer annotations into a temporary
    Report tab (single-column artifact) for the user to inspect before
    deciding. Reuses the create_report / Report-tab plumbing."""
    workspace: Path = request.app["workspace"]
    pid = request.match_info.get("proposal_id", "")
    entry = await asyncio.to_thread(proposals.get, workspace, pid)
    if entry is None:
        return web.json_response({"error": "no such proposal"}, status=404)
    html = _proposal_preview_html(entry)
    meta = await asyncio.to_thread(
        reports.save, workspace,
        title=f"Review · {entry.get('title') or entry.get('path')}",
        summary="Proposed page + reviewer annotations", html=html)
    await _daemon_ns._open_report_tab(request.app, workspace, meta["id"], meta["title"])
    return web.json_response({"ok": True, "report_id": meta["id"]})

async def handle_proposal_decide(request: web.Request) -> web.Response:
    """Accept (write the page) or dismiss a staged proposal."""
    workspace: Path = request.app["workspace"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    pid = str(body.get("id") or "")
    decision = str(body.get("decision") or "").lower()
    comments = str(body.get("comments") or "").strip()
    new_body = body.get("body")
    if isinstance(new_body, str) and new_body.strip():
        await asyncio.to_thread(
            proposals.update, workspace, pid, body=new_body.strip())
    if comments or decision in ("comment", "save"):
        if decision in ("comment", "save"):
            e = await asyncio.to_thread(
                proposals.comment_and_keep, workspace, pid, comments)
            if e is None:
                return web.json_response({"error": "unknown proposal"}, status=404)
            rel = str(e.get("path") or "")
            if rel.startswith("wiki/") or rel == proposals.CHARTER_REL:
                asyncio.create_task(
                    _daemon_ns._after_wiki_write(request.app, workspace, rel))
            await _daemon_ns._broadcast(request.app, protocol.custom({
                "type": "page_proposal_resolved", "id": pid,
                "decision": "accept",
            }))
            return web.json_response({"ok": True, "status": e.get("status")})
        e = await asyncio.to_thread(
            proposals.apply_comments, workspace, pid, comments)
        if e is None:
            return web.json_response({"error": "unknown proposal"}, status=404)
    if decision == "accept":
        e = await asyncio.to_thread(proposals.accept, workspace, pid)
    elif decision in ("dismiss", "reject"):
        e = await asyncio.to_thread(proposals.dismiss, workspace, pid)
    else:
        return web.json_response({"error": "decision must be accept|dismiss|comment"}, status=400)
    if e is None:
        return web.json_response({"error": "unknown or already-resolved proposal"}, status=404)
    if decision == "accept" and e.get("status") == "accepted":
        await _daemon_ns._after_wiki_write(
            request.app, workspace, str(e.get("path") or ""),
        )
    elif decision in ("dismiss", "reject"):
        try:
            orchestrator_fs.forget_landed(workspace, str(e.get("path") or ""))
        except Exception:  # noqa: BLE001
            pass
    await _daemon_ns._broadcast(request.app, protocol.custom({
        "type": "page_proposal_resolved", "id": pid, "decision": decision}))
    return web.json_response({"ok": True, "status": e.get("status"), "path": e.get("path")})

async def handle_provider_retry_decide(request: web.Request) -> web.Response:
    """Accept a provider-retry offer (audit #12): re-dispatch the failed
    input on the chosen provider, or dismiss the card. `{id, provider?}`
    — provider present = retry, absent = dismiss."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    rid = str(body.get("id") or "")
    provider = str(body.get("provider") or "").strip()
    pending = request.app.get("provider_retries") or {}
    rec = pending.pop(rid, None)
    if rec is None:
        return web.json_response({"error": "unknown or already-used retry"}, status=404)
    if provider:
        if provider not in llmgateway.PROVIDERS:
            return web.json_response({"error": "unknown provider"}, status=400)
        ws_path = Path(rec["workspace"])
        t = asyncio.create_task(_daemon_ns._dispatch_chat(
            request.app, None, rec["text"],
            workspace_override=ws_path,
            thread_id_override=rec.get("thread_id") or None,
            provider_override=provider,
        ))
        t.add_done_callback(_daemon_ns._make_dispatch_error_surface(request.app, rid))
    await _daemon_ns._broadcast(request.app, protocol.custom({
        "type": "provider_retry_resolved", "id": rid,
        "provider": provider or None,
    }))
    return web.json_response({"ok": True, "retried": bool(provider)})
