"""Host glue around CE scripts: wiki git, evolve_guard, wave prime.

Not a planner. Calls curiosity-engine scripts/shell the skill already
documents, with Switch Bay path/JSON constraints MCP needs.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from . import cebridge
from .ce_protocol import CURATE_MODE_ALIASES, CURATE_WORKER_ROLES

_UNSAFE_MSG = re.compile(r"[;&|`$<>\n\r]|\$\(")
_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")


def _wiki_git(workspace: Path, *git_args: str, timeout: float = 60.0) -> dict[str, Any]:
    wiki = Path(workspace) / "wiki"
    if not wiki.is_dir():
        return {"ok": False, "error": "no wiki/ directory"}
    git_dir = wiki / ".git"
    if not git_dir.exists():
        return {"ok": False, "error": "wiki/ is not a git repository"}
    try:
        proc = subprocess.run(
            ["git", "-C", str(wiki), *git_args],
            capture_output=True, text=True, timeout=timeout,
            cwd=str(workspace),
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "error": f"git -C wiki failed: {e}"}
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        return {
            "ok": False,
            "error": err or out or f"git exited {proc.returncode}",
            "stdout": out[-2000:],
        }
    return {"ok": True, "stdout": out[-2000:], "stderr": err[-800:]}


def wiki_commit(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    msg = str(payload.get("message") or "").strip()
    if not msg:
        return {"ok": False, "error": "message is required"}
    if _UNSAFE_MSG.search(msg):
        return {"ok": False, "error": "commit message has shell metacharacters"}
    if len(msg) > 200:
        msg = msg[:197] + "..."
    added = _wiki_git(workspace, "add", "-A")
    if not added.get("ok"):
        return added
    committed = _wiki_git(workspace, "commit", "-m", msg)
    if not committed.get("ok"):
        err = str(committed.get("error") or "")
        if "nothing to commit" in err.lower() or "no changes added" in err.lower():
            return {"ok": True, "committed": False, "note": "nothing to commit"}
        return committed
    return {"ok": True, "committed": True, "stdout": committed.get("stdout")}


def evolve_guard(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    verb = str(payload.get("verb") or "snapshot").strip()
    if verb not in ("snapshot", "check", "hash"):
        return {"ok": False, "error": f"unknown evolve_guard verb {verb!r}"}
    snap = str(payload.get("path") or ".curator/.guard.snapshot").strip()
    if snap.startswith("/") or ".." in Path(snap).parts:
        return {"ok": False, "error": "snapshot path must stay in the workspace"}
    (Path(workspace) / ".curator").mkdir(parents=True, exist_ok=True)
    args = [verb] if verb == "hash" else [verb, snap]
    return cebridge.run_sh("evolve_guard.sh", args, cwd=workspace, timeout=60.0)


def wave_prime(workspace: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Mechanical CURATE Phase 1: guard snapshot, scan, epoch, pick-mode."""
    from . import ce_tools

    payload = payload or {}
    wanted = str(payload.get("mode") or payload.get("wave_mode") or "").strip().lower()
    override = CURATE_MODE_ALIASES.get(wanted, wanted if wanted else "")
    steps: dict[str, Any] = {}
    steps["guard"] = evolve_guard(workspace, {"verb": "snapshot"})
    try:
        steps["scan"] = ce_tools._ce_scan(workspace, {"verb": "all"})
    except Exception as exc:  # noqa: BLE001
        steps["scan"] = {"ok": False, "error": str(exc)[:200]}
    steps["epoch"] = ce_tools._ce_epoch_summary(workspace, {})
    picked = ce_tools._ce_planner(workspace, {"verb": "pick-mode"})
    steps["planner"] = picked
    mode = ""
    reason = ""
    if isinstance(picked, dict):
        mode = str(picked.get("mode") or "")
        reason = str(picked.get("reason") or "")
        if not mode and isinstance(picked.get("stdout"), str):
            try:
                body = json.loads(picked["stdout"])
                if isinstance(body, dict):
                    mode = str(body.get("mode") or "")
                    reason = str(body.get("reason") or reason)
                    picked = {**picked, **body}
            except json.JSONDecodeError:
                pass
    if override and override != "sweep":
        reason = (
            f"user override {wanted!r} → {override}"
            + (f"; planner had {mode}" if mode and mode != override else "")
        )
        mode = override
    return {
        "ok": bool(mode) or override == "sweep",
        "mode": mode or override,
        "reason": reason,
        "planner": picked if isinstance(picked, dict) else {"raw": picked},
        "steps": {
            k: _slim_step(v) for k, v in steps.items()
        },
        "instruction": (
            f"This wave's mode is {mode or override or 'unknown'}. "
            "Execute SKILL.md Phase 2 for that mode with ce_* tools. "
            "Do not pick a different mode without logging why."
        ),
    }


def _slim_step(out: Any) -> dict[str, Any]:
    if not isinstance(out, dict):
        return {"preview": str(out)[:400]}
    err = out.get("error")
    slim = {"ok": not err, "error": (str(err)[:200] if err else None)}
    for key in ("mode", "reason", "queue_depths", "stdout"):
        if key in out:
            val = out[key]
            slim[key] = val if not isinstance(val, str) else val[:600]
    return slim


def _prompts_path(workspace: Path) -> Path | None:
    ws = Path(workspace) / ".curator" / "prompts.md"
    if ws.is_file():
        return ws
    bundled = cebridge.ce_root() / "template" / "prompts.md"
    if bundled.is_file():
        return bundled
    return None


def extract_prompt_section(text: str, role: str) -> str | None:
    want = (role or "").strip().lower()
    if not want or not text:
        return None
    lines = text.splitlines()
    start: int | None = None
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if not m:
            continue
        heading = m.group(1).strip().lower()
        name = heading.split("(", 1)[0].strip()
        if name == want or heading.startswith(want):
            start = i
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if _HEADING_RE.match(lines[j]):
            end = j
            break
    return "\n".join(lines[start:end]).strip()


def fill_placeholders(template: str, mapping: dict[str, str]) -> str:
    out = template
    for key, val in mapping.items():
        token = key if key.startswith("<") else f"<{key}>"
        out = out.replace(token, val)
    return out


def dispatch_worker(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    role = str(payload.get("role") or "").strip()
    if not role:
        return {"ok": False, "error": "role is required",
                "roles": sorted(CURATE_WORKER_ROLES)}
    path = _prompts_path(workspace)
    if path is None:
        return {"ok": False, "error": "no .curator/prompts.md (run CE setup)"}
    try:
        body = path.read_text(encoding="utf-8")
    except OSError as e:
        return {"ok": False, "error": str(e)}
    section = extract_prompt_section(body, role)
    if not section:
        return {
            "ok": False,
            "error": f"no prompts.md section for {role!r}",
            "roles": sorted(CURATE_WORKER_ROLES),
        }
    mapping: dict[str, str] = {}
    raw_sub = payload.get("substitutions")
    if isinstance(raw_sub, dict):
        mapping = {str(k): str(v) for k, v in raw_sub.items()}
    elif isinstance(raw_sub, str) and raw_sub.strip():
        try:
            parsed = json.loads(raw_sub)
        except json.JSONDecodeError as e:
            return {"ok": False, "error": f"substitutions JSON: {e}"}
        if isinstance(parsed, dict):
            mapping = {str(k): str(v) for k, v in parsed.items()}
    brief = str(payload.get("brief") or "").strip()
    filled = fill_placeholders(section, mapping)
    if brief:
        filled = filled.rstrip() + "\n\nOrchestrator brief:\n" + brief
    agent = CURATE_WORKER_ROLES.get(role, "Curator")
    plugin = os.environ.get("CSWY_PROFILE", "").strip().lower() in (
        "vscode", "plugin",
    )
    result: dict[str, Any] = {
        "ok": True,
        "role": role,
        "agent": agent,
        "prompt": filled,
        "source": str(path),
    }
    if plugin:
        result["note"] = (
            f"VS Code: spawn Copilot custom agent {agent} with this prompt. "
            "MCP has no model; do not expect this tool to complete the worker."
        )
        return result
    result["note"] = (
        "PWA host completes this as a fresh-context child run when a "
        "non-local provider is keyed. Local hosts run the prompt "
        "in-session (CE single-session fallback)."
    )
    return result


def write_temp(workspace: Path, name: str, text: str) -> Path:
    folder = Path(workspace) / ".curator"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(text if isinstance(text, str) else json.dumps(text), encoding="utf-8")
    return path
