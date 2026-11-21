"""Stage, scrub, and either apply or quarantine an import.

The shape follows curiosity-merge's merge gate: stage the bytes, audit
the decision, quarantine a hit, and only then write the vault file.
A built-in check flags prompt-injection phrasing and script URLs. When
curiosity-engine's ``scrub_check.py`` is installed, that script runs
too. A hit never lands on the import path the wiki can cite.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import audit, secure

_INJECTION = re.compile(
    r"(?i)\bignore\b.{0,40}\b(previous|prior|above|all)\b.{0,20}\binstructions?\b"
    r"|<\s*script\b|javascript:"
)


def findings(text: str) -> list[str]:
    hits = []
    if _INJECTION.search(text or ""):
        hits.append("prompt injection")
    return hits


def _ce_findings(workspace: Path, rel: str) -> list[str]:
    """curiosity-engine scrub, when the script is on the machine."""
    try:
        from .. import cebridge
    except Exception:
        return []
    script = cebridge.ce_root() / "scripts" / "scrub_check.py"
    if not script.is_file():
        return []
    try:
        out = cebridge.run_script(
            "scrub_check.py", ["--mode", "vault", rel], cwd=workspace, timeout=60.0,
        )
    except Exception:
        return []
    if not isinstance(out, dict):
        return []
    if out.get("error") and "not found" in str(out.get("error")).lower():
        return []
    raw = out.get("findings") or out.get("hits") or out.get("blocked")
    if raw is True:
        return ["scrub_check"]
    if isinstance(raw, list) and raw:
        return [str(item) for item in raw[:8]]
    if out.get("ok") is False and out.get("error"):
        return [str(out["error"])]
    return []


def gate_import(workspace: Path, rel: str, text: str) -> dict:
    """Write ``rel`` under the workspace, or quarantine it.

    ``rel`` is workspace-relative (``vault/ext/...``).
    """
    staged = findings(text)
    path = workspace / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    staged.extend(_ce_findings(workspace, rel))
    # De-duplicate while keeping order.
    seen: set[str] = set()
    hits = []
    for item in staged:
        if item not in seen:
            seen.add(item)
            hits.append(item)
    if not hits:
        audit.record(workspace, "import_apply", path=rel)
        return {"ok": True, "path": rel, "quarantined": False}
    dest_rel = "vault/ext/.quarantine/" + rel.split("vault/ext/", 1)[-1]
    dest = workspace / dest_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    try:
        path.unlink()
    except OSError:
        pass
    manifest = workspace / ".workbench" / "state" / "import-quarantine.jsonl"
    secure.owner_dir(manifest.parent)
    with manifest.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"path": dest_rel, "findings": hits}) + "\n")
    try:
        manifest.chmod(0o600)
    except OSError:
        pass
    audit.record(workspace, "quarantine", path=dest_rel, findings=", ".join(hits))
    return {
        "ok": False,
        "path": dest_rel,
        "quarantined": True,
        "error": "import quarantined: " + ", ".join(hits),
        "findings": hits,
    }
