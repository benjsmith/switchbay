"""Wave-status file so a VS Code Agent Dashboard can retire a DAG.

Copilot Chat has no session-end hook the extension can subscribe to.
Auto (and other named agents) call ``orchestration_report`` when they
would print ``OBJECTIVE_MET``; the extension file-watches
``.workbench/state/orchestration-report.json``.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from . import atomicio

REL = Path(".workbench") / "state" / "orchestration-report.json"
PHASES = ("running", "done", "failed")


def report_path(workspace: Path) -> Path:
    return Path(workspace) / REL


def write_report(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    phase = str(payload.get("phase") or "").strip().lower()
    if phase not in PHASES:
        return {
            "ok": False,
            "error": "phase must be running, done, or failed",
        }
    detail = str(payload.get("detail") or payload.get("note") or "").strip()
    rec: dict[str, Any] = {
        "at": time.time(),
        "phase": phase,
        "detail": detail,
        "orchestration_id": str(payload.get("orchestration_id") or "").strip(),
        "objective_met": str(payload.get("objective_met") or "").strip().lower(),
    }
    path = report_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(path, rec)
    return {"ok": True, "path": str(REL).replace("\\", "/"), **rec}


def _report(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    return write_report(workspace, payload or {})


def register_tools() -> None:
    from .tools import Tool, register

    register(Tool(
        name="orchestration_report",
        description=(
            "Report this Auto/desk wave to the Agent Dashboard. Call "
            "phase=done with detail='OBJECTIVE_MET: yes' when the requested "
            "wave is complete (even if Chat stays open for Keep curating). "
            "phase=failed if you stopped on an error. phase=running is a "
            "heartbeat while a long desk is still working. Do this before "
            "the OBJECTIVE_MET line."
        ),
        input_schema={
            "type": "object",
            "required": ["phase"],
            "properties": {
                "phase": {
                    "type": "string",
                    "enum": ["running", "done", "failed"],
                },
                "detail": {
                    "type": "string",
                    "description": "Short status, e.g. OBJECTIVE_MET: yes",
                },
                "objective_met": {
                    "type": "string",
                    "enum": ["yes", "no", ""],
                },
                "orchestration_id": {
                    "type": "string",
                    "description": "Optional DAG id from the curate reply.",
                },
            },
        },
        handler=_report,
    ))
