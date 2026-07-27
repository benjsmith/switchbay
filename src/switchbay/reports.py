"""Rich HTML report artifacts — a capable model's answer as a document.

When a question yields an analysis / comparison / structured answer, a
strong model calls the `create_report` tool with a self-contained HTML
page; it lands in a **Report tab** (sandboxed iframe) and the chat reply
carries just a one-line summary + a link to the tab. The local model is
never offered this tool — it can't produce artifact-quality HTML.

Storage is machine-local (statedir), regenerable, never on a sync
service — same rationale as fan-out run output. Each report is
`<state>/reports/<id>.html` plus `<id>.json` (title, summary, created).
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from . import statedir


def reports_dir(workspace: Path) -> Path:
    return statedir.workspace_state_dir(workspace) / "reports"


def _html_path(workspace: Path, report_id: str) -> Path:
    return reports_dir(workspace) / f"{report_id}.html"


def _meta_path(workspace: Path, report_id: str) -> Path:
    return reports_dir(workspace) / f"{report_id}.json"


def save(workspace: Path, *, title: str, summary: str, html: str) -> dict[str, Any]:
    """Persist a report; return its meta ({id, title, summary, created})."""
    rid = f"report-{uuid.uuid4().hex[:10]}"
    d = reports_dir(workspace)
    d.mkdir(parents=True, exist_ok=True)
    (_html_path(workspace, rid)).write_text(html, encoding="utf-8")
    meta = {
        "id": rid,
        "title": (title or "Report").strip()[:120],
        "summary": (summary or "").strip()[:400],
        "created_at": time.time(),
    }
    _meta_path(workspace, rid).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def html_of(workspace: Path, report_id: str) -> str | None:
    # Guard against path traversal: ids are our own `report-<hex>`.
    if not report_id.startswith("report-") or "/" in report_id or ".." in report_id:
        return None
    p = _html_path(workspace, report_id)
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return None


def meta_of(workspace: Path, report_id: str) -> dict[str, Any] | None:
    try:
        return json.loads(_meta_path(workspace, report_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def created_since(workspace: Path, ts: float) -> list[dict[str, Any]]:
    """Report metas created strictly after `ts`, oldest→newest. Lets a
    dispatch open whatever a capable model produced this run, whether the
    tool ran in-daemon (HTTP providers) or in the MCP subprocess (CLI
    providers like claude_code) — neither path can broadcast, so the
    dispatch scans at run-end instead."""
    out: list[dict[str, Any]] = []
    d = reports_dir(workspace)
    if not d.is_dir():
        return out
    for meta in sorted(d.glob("*.json")):
        try:
            m = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(m, dict) and (m.get("created_at") or 0) > ts:
            out.append(m)
    out.sort(key=lambda m: m.get("created_at") or 0)
    return out
