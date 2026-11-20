"""Classification labels and the rule that they follow a citation.

public < internal < confidential < restricted.

A page's label is the highest of its own label and the labels of
everything it cites. Rewriting the prose does not lower it. Lowering
is a separate, recorded act by a person.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import audit, policy

_RANK = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
_CITE = re.compile(
    r"\(\s*(?P<kind>vault|table|figure|graph|capture)\s*:\s*(?P<body>[^)\n]+)\)"
)
_FM = re.compile(r"^classification:\s*(\S+)", re.MULTILINE)


def rank(label: str | None) -> int:
    key = (label or "public").strip().lower()
    if key not in _RANK:
        return _RANK["restricted"]
    return _RANK[key]


def name_for(rank_value: int) -> str:
    for label, value in _RANK.items():
        if value == rank_value:
            return label
    return "restricted"


def highest(*labels: str | None) -> str:
    best = 0
    for label in labels:
        best = max(best, rank(label))
    return name_for(best)


def above(label: str | None, ceiling: str) -> bool:
    return rank(label) > rank(ceiling)


def label_in_text(text: str) -> str:
    match = _FM.search(text or "")
    if not match:
        return "public"
    return match.group(1).strip().lower()


def _frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    if end < 0:
        return ""
    return text[:end]


def page_label(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "public"
    return label_in_text(_frontmatter(text))


def derived(workspace: Path, text: str, *, seen: set[str] | None = None) -> str:
    """Highest label in this text and the files it cites."""
    seen = seen if seen is not None else set()
    own = label_in_text(_frontmatter(text))
    labels = [own]
    for match in _CITE.finditer(text or ""):
        kind = match.group("kind")
        body = match.group("body").strip()
        if kind == "graph":
            labels.append(_graph_label(workspace, body))
            continue
        if kind == "capture":
            labels.append(_capture_label(workspace, body))
            continue
        path = _resolve_file(workspace, body.split("#", 1)[0].strip())
        if path is None:
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        try:
            cited = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        labels.append(derived(workspace, cited, seen=seen))
    return highest(*labels)


def _resolve_file(workspace: Path, rel: str) -> Path | None:
    rel = rel.strip().lstrip("/")
    if ".." in rel.split("/"):
        return None
    for base in (workspace, workspace / "vault", workspace / "wiki"):
        cand = (base / rel).resolve()
        try:
            cand.relative_to(workspace.resolve())
        except ValueError:
            continue
        if cand.is_file():
            return cand
    return None


def _graph_label(workspace: Path, body: str) -> str:
    from .citations import cached_label
    return cached_label(workspace, body) or "public"


def _capture_label(workspace: Path, body: str) -> str:
    from .broker import capture_label
    return capture_label(workspace, body.split("#", 1)[0].strip()) or "confidential"


def refuses(workspace: Path, text: str, ceiling: str) -> str:
    label = derived(workspace, text)
    if above(label, ceiling):
        return f"page is {label}, above the mount ceiling {ceiling}"
    return ""


def declassify(workspace: Path, rel: str, reason: str, *, human_confirmed: bool) -> dict:
    if not human_confirmed:
        audit.record(workspace, "refused_write", why="declassification requires a person", path=rel)
        return {"ok": False, "error": "only a person can declassify a page"}
    if not policy.declassify_allowed():
        audit.record(workspace, "refused_write", why="declassification forbidden", path=rel)
        return {"ok": False, "error": "admin policy forbids declassification"}
    reason = (reason or "").strip()
    if len(reason) < 8:
        return {"ok": False, "error": "a declassification needs a reason"}
    path = workspace / rel if rel.startswith("wiki/") else workspace / "wiki" / rel
    if not path.is_file():
        return {"ok": False, "error": "page not found"}
    text = path.read_text(encoding="utf-8")
    before = label_in_text(_frontmatter(text))
    if text.startswith("---"):
        end = text.find("\n---", 3)
        block = text[4:end]
        rest = text[end + 4:]
        lines = []
        seen = False
        for line in block.splitlines():
            if line.startswith("classification:"):
                lines.append("classification: public")
                seen = True
            elif line.startswith("declassified:"):
                continue
            else:
                lines.append(line)
        if not seen:
            lines.append("classification: public")
        lines.append("declassified: true")
        path.write_text("---\n" + "\n".join(lines) + "\n---" + rest, encoding="utf-8")
    audit.record(
        workspace, "declassify", path=path.relative_to(workspace).as_posix(),
        before=before, after="public", reason=reason,
    )
    return {"ok": True, "path": path.relative_to(workspace).as_posix(), "before": before, "after": "public"}


def blocking_publish_paths(workspace: Path) -> list[dict[str, str]]:
    """Pages and vault files a public share must not include."""
    blocked = []
    for folder in ("wiki", "vault"):
        root = workspace / folder
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in {".md", ".txt", ".yaml", ".yml"}:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            label = derived(workspace, text)
            if above(label, "public"):
                blocked.append({
                    "path": path.relative_to(workspace).as_posix(),
                    "classification": label,
                })
    return blocked
