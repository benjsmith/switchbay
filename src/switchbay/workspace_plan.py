"""Workspace charter / work-plan / log — plan-assist inside a wiki.

Distinct from ``.curator/log.md`` (CE curator journal) and the rail
event log. These three files live under ``.workbench/plan/``:

  * charter.md — stable goals and invariants (year-scale)
  * work-plan.md — current tasks and next steps
  * workspace-log.md — append-only decisions and progress

The rail agent may edit the work-plan, append the log, and propose
charter changes (those land in Reviews).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from . import atomicio

PLAN_DIR = Path(".workbench") / "plan"

_CHARTER = """# Charter

Stable goals and invariants for this workspace. Year-scale. Edit rarely;
proposed changes go through Reviews.

## Do
- Keep the wiki sourced and linked.
- Prefer small, reversible steps.

## Do not
- Delete sourced wiki pages.
- Mix curator notes (`.curator/log.md`) into this file.

## Goals
- (year goals go here)
"""

_WORK_PLAN = """# Work plan

Current tasks and next steps. The agent updates this as work moves.

## Now
- 

## Next
- 

## Waiting
- 
"""

_LOG = """# Workspace log

Append-only. Decisions, progress, and why. Not the curator log
(`.curator/log.md`) and not the rail transcript.

"""


def plan_root(workspace: Path) -> Path:
    return Path(workspace) / PLAN_DIR


def ensure(workspace: Path) -> Path:
    """Create the three files if missing. Never overwrite."""
    root = plan_root(workspace)
    root.mkdir(parents=True, exist_ok=True)
    seeds = {
        "charter.md": _CHARTER,
        "work-plan.md": _WORK_PLAN,
        "workspace-log.md": _LOG,
    }
    for name, body in seeds.items():
        p = root / name
        if not p.is_file():
            atomicio.write_text_atomic(p, body)
    return root


def read_all(workspace: Path) -> dict[str, str]:
    ensure(workspace)
    root = plan_root(workspace)
    out: dict[str, str] = {}
    for name in ("charter.md", "work-plan.md", "workspace-log.md"):
        try:
            out[name] = (root / name).read_text(encoding="utf-8")
        except OSError:
            out[name] = ""
    return out


def write_work_plan(workspace: Path, text: str) -> None:
    ensure(workspace)
    atomicio.write_text_atomic(plan_root(workspace) / "work-plan.md", text.rstrip() + "\n")


def append_log(workspace: Path, text: str) -> None:
    ensure(workspace)
    p = plan_root(workspace) / "workspace-log.md"
    try:
        cur = p.read_text(encoding="utf-8")
    except OSError:
        cur = _LOG
    stamp = date.today().isoformat()
    block = text.strip()
    if not block:
        return
    if not block.startswith("##"):
        block = f"## {stamp}\n{block}"
    atomicio.write_text_atomic(p, cur.rstrip() + "\n\n" + block + "\n")


# ── Rail tools ──────────────────────────────────────────────────────


def _read_plan(workspace: Path, _payload: dict) -> dict:
    files = read_all(workspace)
    return {"ok": True, "files": files, "dir": str(plan_root(workspace))}


def _write_plan(workspace: Path, payload: dict) -> dict:
    text = str(payload.get("text") or "")
    if not text.strip():
        return {"ok": False, "error": "text is required"}
    write_work_plan(workspace, text)
    return {"ok": True, "path": str(plan_root(workspace) / "work-plan.md")}


def _append_wlog(workspace: Path, payload: dict) -> dict:
    text = str(payload.get("text") or "")
    if not text.strip():
        return {"ok": False, "error": "text is required"}
    append_log(workspace, text)
    return {"ok": True, "path": str(plan_root(workspace) / "workspace-log.md")}


def _propose_charter(workspace: Path, payload: dict) -> dict:
    from . import proposals
    text = str(payload.get("text") or payload.get("body") or "")
    if not text.strip():
        return {"ok": False, "error": "text is required"}
    ensure(workspace)
    e = proposals.add(
        workspace, op="edit", kind="note", title="Charter",
        body=text, path=proposals.CHARTER_REL,
    )
    return {
        "ok": True, "proposal_id": e["id"], "path": e["path"],
        "note": "Charter written provisionally — shows in Reviews. "
        "Reject restores the previous charter.",
    }


def register_tools() -> None:
    from .tools import Tool, register
    register(Tool(
        name="read_workspace_plan",
        description=(
            "Read this workspace's charter.md, work-plan.md, and "
            "workspace-log.md (under .workbench/plan/). Distinct from "
            ".curator/log.md and the rail transcript."
        ),
        input_schema={"type": "object", "properties": {}},
        handler=_read_plan,
    ))
    register(Tool(
        name="update_work_plan",
        description=(
            "Overwrite .workbench/plan/work-plan.md with the current "
            "task list and next steps."
        ),
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        handler=_write_plan,
    ))
    register(Tool(
        name="append_workspace_log",
        description=(
            "Append a dated entry to .workbench/plan/workspace-log.md "
            "(decisions and progress). Not the curator log."
        ),
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        handler=_append_wlog,
    ))
    register(Tool(
        name="propose_charter_edit",
        description=(
            "Propose an edit to .workbench/plan/charter.md (year-scale "
            "goals). Writes provisionally; the change lands in Reviews. "
            "Reject restores the previous charter. Do not silently "
            "overwrite the charter with update_work_plan."
        ),
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        handler=_propose_charter,
    ))
