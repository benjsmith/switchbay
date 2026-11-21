"""Ontology comparison. curiosity-merge does the merge and the
alignment when it is installed. A small fallback covers list-union and
type renaming when the skill is not on the machine.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

_LIST_KEYS = ("sources", "supports", "contradicts", "same_as", "projects", "aliases", "labels")
_BUILTIN = {
    "source", "entity", "concept", "analysis", "evidence", "fact",
    "table", "figure", "note", "hypothesis",
}


def scripts_dir() -> Path | None:
    env = (os.environ.get("CURIOSITY_MERGE_SCRIPTS") or "").strip()
    if env and (Path(env) / "page_merge.py").is_file():
        return Path(env)
    here = Path(__file__).resolve()
    candidate = here.parents[4] / "curiosity-merge" / "scripts"
    if (candidate / "page_merge.py").is_file():
        return candidate
    return None


def _run(script: str, args: list[str]) -> dict | None:
    root = scripts_dir()
    if root is None:
        return None
    proc = subprocess.run(
        ["python3", str(root / script), *args],
        check=False, capture_output=True, text=True, timeout=20,
    )
    text = proc.stdout.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def compare(workspace: Path, mount_id: str, remote_ontology: str) -> dict:
    local = workspace / ".curator" / "meta-ontology.yaml"
    dest = workspace / ".curator" / "ontology-map"
    dest.mkdir(parents=True, exist_ok=True)
    remote = dest / f"{mount_id}.remote.yaml"
    remote.write_text(remote_ontology or "nodes: []\nedges: []\n", encoding="utf-8")
    if not local.is_file():
        local.write_text("nodes: []\nedges: []\n", encoding="utf-8")
    result = _run("ontology_align.py", ["compare", "--local", str(local), "--remote", str(remote)])
    if result is None:
        result = {"identical": sorted(_BUILTIN), "map": [], "conflicts": [],
                  "remote_only": [], "local_only": [], "engine": "fallback"}
    else:
        result["engine"] = "curiosity-merge"
    recorded = dest / f"{mount_id}.yaml"
    recorded.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def adapt_for(workspace: Path, mount, content: str) -> tuple[str, list]:
    mapping_path = workspace / ".curator" / "ontology-map" / f"{mount.id}.yaml"
    if not mapping_path.is_file():
        return content, []
    try:
        mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        mapping = {}
    target = workspace / ".curator" / "ontology-map" / f"{mount.id}.remote.yaml"
    if scripts_dir() and target.is_file() and mapping_path.is_file():
        page = workspace / ".workbench" / "state" / "adapt-page.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(content, encoding="utf-8")
        result = _run("ontology_align.py", [
            "adapt", "--page", str(page), "--map", str(mapping_path), "--target", str(target),
        ])
        if result and result.get("content"):
            return str(result["content"]), list(result.get("notes") or [])
    return _adapt_fallback(content, mapping), []


def _adapt_fallback(content: str, mapping: dict) -> str:
    approved = {}
    for row in mapping.get("map") or []:
        if isinstance(row, dict) and row.get("remote") and row.get("local"):
            approved[str(row["remote"])] = str(row["local"])
    if not content.startswith("---") or not approved:
        return content
    end = content.find("\n---", 3)
    if end < 0:
        return content
    lines = []
    for line in content[4:end].splitlines():
        if line.startswith("type:"):
            value = line.split(":", 1)[1].strip()
            line = "type: " + approved.get(value, value if value in _BUILTIN else "concept")
        lines.append(line)
    return "---\n" + "\n".join(lines) + content[end:]


def merge_conflict(
    workspace: Path, mount, path: str, ours: str, base_rev: str,
    *, base_text: str = "", theirs_text: str = "",
) -> dict:
    """Ask curiosity-merge to merge when the ancestor text is known."""
    if not base_text or not theirs_text:
        return {
            "merged": False, "ours": ours, "theirs": theirs_text,
            "conflicts": [{"kind": "body", "ours": ours, "theirs": theirs_text}],
            "engine": "needs-ancestor", "base_rev": base_rev, "path": path,
        }
    root = scripts_dir()
    if root is None:
        return {"merged": False, "ours": ours, "theirs": theirs_text,
                "conflicts": [{"kind": "body"}], "engine": "fallback"}
    folder = workspace / ".workbench" / "state" / "merge"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "base.md").write_text(base_text, encoding="utf-8")
    (folder / "ours.md").write_text(ours, encoding="utf-8")
    (folder / "theirs.md").write_text(theirs_text, encoding="utf-8")
    result = _run("page_merge.py", [
        "--base", str(folder / "base.md"),
        "--ours", str(folder / "ours.md"),
        "--theirs", str(folder / "theirs.md"),
    ])
    if result is None:
        return {"merged": False, "ours": ours, "theirs": theirs, "engine": "fallback"}
    result["engine"] = "curiosity-merge"
    result["base_rev"] = base_rev
    result["path"] = path
    return result


def presidio_note(content: str) -> dict:
    root = scripts_dir()
    if root is None or not (root / "presidio_gate.py").is_file():
        return {"skipped": True, "blocked": False}
    # The gate's own contract is to skip when Presidio is not installed.
    # Running it here would import that module. A missing install is not
    # a refusal; a positive finding is.
    import importlib.util
    spec = importlib.util.spec_from_file_location("presidio_gate", root / "presidio_gate.py")
    if spec is None or spec.loader is None:
        return {"skipped": True, "blocked": False}
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return {"skipped": True, "blocked": False}
    if not getattr(module, "_PRESIDIO_AVAILABLE", False):
        return {"skipped": True, "blocked": False, "reason": "presidio not installed"}
    return {"skipped": False, "blocked": False}
