"""Host glue around CE scripts: wiki git, evolve_guard, wave prime.

Not a planner. Calls curiosity-engine scripts/shell the skill already
documents, with Switch Bay path/JSON constraints MCP needs.
"""

from __future__ import annotations

import hashlib
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


def wiki_head(workspace: Path) -> dict[str, Any]:
    out = _wiki_git(workspace, "rev-parse", "HEAD")
    if not out.get("ok"):
        return out
    return {"ok": True, "sha": str(out.get("stdout") or "").strip(), "committed": True}


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


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            while True:
                chunk = fh.read(65536)
                if not chunk:
                    break
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def _tree_entries(
    root: Path,
    *,
    rel_to: Path,
    suffixes: tuple[str, ...] | None = None,
    content_hash: bool = False,
) -> list[tuple]:
    out: list[tuple] = []
    if not root.is_dir():
        return out
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if ".git" in p.parts:
            continue
        if suffixes and p.suffix.lower() not in suffixes:
            continue
        try:
            rel = p.relative_to(rel_to).as_posix()
            st = p.stat()
        except OSError:
            continue
        size = int(st.st_size)
        mtime = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))
        if content_hash:
            out.append((rel, size, mtime, _file_sha256(p)))
        else:
            out.append((rel, size, mtime))
    out.sort()
    return out


def wiki_work_snapshot(workspace: Path) -> dict[str, Any]:
    """HEAD + porcelain + wiki markdown inventory. No CE subprocess."""
    ws = Path(workspace)
    head = wiki_head(ws)
    sha = str(head.get("sha") or "") if head.get("ok") else ""
    status = _wiki_git(ws, "status", "--porcelain")
    porcelain = str(status.get("stdout") or "") if status.get("ok") else ""
    pages = _tree_entries(
        ws / "wiki", rel_to=ws, suffixes=(".md",), content_hash=True,
    )
    return {"sha": sha, "porcelain": porcelain, "pages": pages}


def work_availability_fingerprint(workspace: Path, *, planner: bool = False) -> str:
    """Deterministic source/wiki/queue fingerprint for idle Curate.

    File inventory only by default (cheap, no LLM, no evolve_guard).
    ``planner=True`` adds pick-mode when a no-LLM planner check is wanted.
    """
    ws = Path(workspace)
    snap = wiki_work_snapshot(ws)
    vault = _tree_entries(ws / "vault", rel_to=ws)
    curator_root = ws / ".curator"
    curator: list[tuple[str, int, int]] = []
    if curator_root.is_dir():
        for p in curator_root.rglob("*"):
            if not p.is_file():
                continue
            # Guard snapshots change on wave_prime; they are not work.
            if p.name.startswith(".guard") or p.suffix == ".snapshot":
                continue
            try:
                rel = p.relative_to(ws).as_posix()
                st = p.stat()
            except OSError:
                continue
            curator.append((rel, int(st.st_size), int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))))
        curator.sort()
    payload: dict[str, Any] = {
        "sha": snap.get("sha") or "",
        "porcelain": snap.get("porcelain") or "",
        "pages": snap.get("pages") or [],
        "vault": vault,
        "curator": curator,
    }
    if planner:
        mode = ""
        queues: Any = None
        try:
            from . import ce_tools
            picked = ce_tools._ce_planner(ws, {"verb": "pick-mode"})
            if isinstance(picked, dict):
                mode = str(picked.get("mode") or "")
                if not mode and isinstance(picked.get("stdout"), str):
                    try:
                        body = json.loads(picked["stdout"])
                        if isinstance(body, dict):
                            mode = str(body.get("mode") or "")
                    except json.JSONDecodeError:
                        pass
            scanned = ce_tools._ce_scan(ws, {"verb": "all"})
            if isinstance(scanned, dict):
                queues = scanned.get("queue_depths")
        except Exception:  # noqa: BLE001
            mode = ""
            queues = None
        payload["planner_mode"] = mode
        payload["queue_depths"] = queues
    blob = json.dumps(payload, default=str, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _page_content_key(row: Any) -> tuple[str, Any] | None:
    """Identity for receipt comparison: content hash, not mtime."""
    if not isinstance(row, (list, tuple)) or not row:
        return None
    rel = str(row[0]).replace("\\", "/")
    if len(row) >= 4 and row[3]:
        return rel, ("sha", str(row[3]))
    if len(row) >= 3:
        return rel, ("sz", int(row[1]))
    return rel, ()


def wiki_diff_receipt(workspace: Path, before: dict[str, Any] | None) -> dict[str, Any]:
    """Actual wiki page/commit *content* diff since ``before``.

    mtime-only rewrites and empty commits are not productive work.
    Same-size edits with a preserved mtime still count.
    """
    ws = Path(workspace)
    after = wiki_work_snapshot(ws)
    before = before if isinstance(before, dict) else {}

    def _map(pages: Any) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for row in pages or []:
            parsed = _page_content_key(row)
            if parsed is None:
                continue
            rel, key = parsed
            out[rel] = key
        return out

    before_pages = _map(before.get("pages"))
    after_pages = _map(after.get("pages"))
    changed = sorted(
        set(after_pages) - set(before_pages)
        | {
            k for k in after_pages
            if k in before_pages and after_pages[k] != before_pages[k]
        }
    )
    removed = sorted(set(before_pages) - set(after_pages))
    sha_before = str(before.get("sha") or "")
    sha_after = str(after.get("sha") or "")
    diff = ""
    if sha_before and sha_after and sha_before != sha_after:
        out = _wiki_git(ws, "diff", "--stat", sha_before, sha_after)
        if out.get("ok"):
            diff = str(out.get("stdout") or "")
    if not diff and (changed or removed or (after.get("porcelain") or "") != (before.get("porcelain") or "")):
        out = _wiki_git(ws, "diff", "--stat")
        if out.get("ok"):
            diff = str(out.get("stdout") or "")
        if not diff:
            names = _wiki_git(ws, "diff", "--name-only")
            if names.get("ok"):
                diff = str(names.get("stdout") or "")
    landed = len(changed)
    committed = bool(sha_before and sha_after and sha_before != sha_after)
    return {
        "wiki_head_before": sha_before,
        "wiki_head_after": sha_after,
        "wiki_pages_changed": changed,
        "wiki_pages_removed": removed,
        "wiki_commit_diff": diff[:4000],
        "wiki_pages_landed": landed,
        "wiki_committed": committed,
        "wiki_snapshot": after,
    }


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
    # Unknown tokens are briefs ("for 10 mins"), not pick-mode names.
    override = CURATE_MODE_ALIASES.get(wanted, "")
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
        "launched": False,
    }
    if plugin:
        result["note"] = (
            f"VS Code: spawn Copilot custom agent {agent} with this prompt. "
            "MCP has no model; this tool does not launch a worker."
        )
        return result
    result["note"] = (
        "Filled prompt only — this tool does not spawn a child. "
        "On the rail, the host intercepts ce_dispatch_worker and may "
        "launch a fresh-context child. Pi has no launch bridge; use the "
        "prompt in-session or skip."
    )
    return result


def write_temp(workspace: Path, name: str, text: str) -> Path:
    folder = Path(workspace) / ".curator"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(text if isinstance(text, str) else json.dumps(text), encoding="utf-8")
    return path
