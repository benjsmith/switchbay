"""Page access is delegated to the catalog that already owns the item.

Switchbay does not run a permission server. A page may record
``source_ref``. A ``deny:`` reference is refused. A ``readonly:``
reference can be read and not written. A ``workiq:`` reference is
asked of the configured Work IQ source, and a ``uc:``, ``unity:``, or
``unity-catalog:`` reference is asked of the configured Unity Catalog
source. Both calls use the HTTP MCP transport. A reference that names
no configured source is refused. A reference with no catalog prefix
uses the whole-graph right.

``same_as`` neighbours travel on the search ``also`` list. A neighbour
the caller cannot read is dropped.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_UNITY = {"uc", "unity", "unity-catalog"}


@dataclass(frozen=True)
class Decision:
    read: bool
    write: bool
    system: str
    export: bool = True


class SourceChecker:
    """Ask the owning catalog. ``workspace`` selects the configured source."""

    def check(self, source_ref: str, *, write: bool = False, workspace: Path | None = None) -> Decision:
        ref = (source_ref or "").strip()
        if not ref:
            return Decision(True, True, "whole-graph")
        if ref.startswith("deny:"):
            return Decision(False, False, "source", False)
        if ref.startswith("readonly:"):
            return Decision(True, False, "source")
        kind, rest = _split(ref)
        if kind == "workiq":
            return _catalog(workspace, "workiq", ref, write=write)
        if kind in _UNITY:
            return _catalog(workspace, "unity-catalog", ref if rest else ref, write=write)
        return Decision(True, True, "whole-graph")


def _split(ref: str) -> tuple[str, str]:
    kind, _, rest = ref.partition(":")
    return kind.strip().lower(), rest.strip()


def _catalog(workspace: Path | None, kind: str, source_ref: str, *, write: bool) -> Decision:
    if workspace is None:
        return Decision(False, False, kind, False)
    from .adapters import HttpMcpTransport, access_arguments
    from .mounts import load
    from . import oauth
    source = next((item for item in load(workspace).sources if item.kind == kind), None)
    if source is None or not str(source.url).startswith(("http://", "https://")):
        return Decision(False, False, kind, False)
    tool, arguments = access_arguments(kind, source_ref, write=write)
    token = oauth.load_token(source.id)
    try:
        result = HttpMcpTransport(source.url, token).call(tool, arguments)
    except Exception:
        return Decision(False, False, kind, False)
    return _decision_from(kind, result, write=write)


def _closed(read: bool, write: bool, system: str, result: dict | None = None) -> Decision:
    """Export follows read unless the catalog sets ``export`` itself."""
    export = read
    if isinstance(result, dict) and "export" in result:
        export = bool(result["export"])
    return Decision(read, write, system, bool(export and read))


def _decision_from(kind: str, result: dict, *, write: bool) -> Decision:
    if not isinstance(result, dict):
        return Decision(False, False, kind, False)
    if result.get("policy_outcome") == "denied" or result.get("error") in ("policy_denied", "denied"):
        return Decision(False, False, kind, False)
    if "read" in result or "write" in result or "export" in result:
        can_read = bool(result.get("read", True))
        can_write = bool(result.get("write", False))
        return _closed(can_read, can_write, kind, result)
    privileges = result.get("privileges") or result.get("permissions") or []
    if isinstance(privileges, str):
        privileges = [privileges]
    names = {str(item).upper().replace(" ", "_") for item in privileges}
    if not names and result.get("error"):
        return Decision(False, False, kind, False)
    can_write = bool(names & {"MODIFY", "ALL_PRIVILEGES", "OWNERSHIP", "WRITE"})
    can_read = can_write or bool(names & {"SELECT", "USE_CATALOG", "USE_SCHEMA", "READ", "BROWSE"})
    if not names:
        can_read = result.get("policy_outcome") != "denied" and not result.get("error")
        can_write = False
    return _closed(bool(can_read), bool(can_write), kind, result)


_CHECKER = SourceChecker()


def checker() -> SourceChecker:
    return _CHECKER


def allows_read(source_ref: str, workspace: Path | None = None) -> bool:
    return _CHECKER.check(source_ref, workspace=workspace).read


def allows_export(source_ref: str, workspace: Path | None = None) -> bool:
    """Whether a reference may leave the workspace in a file export.

    ``deny:``, a catalog ``export: false``, a failed read, a missing
    source, and a transport error all refuse. ``readonly:`` may be
    exported: the catalog granted read.
    """
    decision = _CHECKER.check(source_ref, workspace=workspace)
    return bool(decision.read and decision.export)


def allows_write(source_ref: str, workspace: Path | None = None) -> bool:
    decision = _CHECKER.check(source_ref, write=True, workspace=workspace)
    if (source_ref or "").strip().startswith("readonly:"):
        return False
    return decision.write and decision.read


def filter_rows(rows: list[dict], workspace: Path | None = None) -> list[dict]:
    kept = []
    for row in rows:
        ref = str(row.get("source_ref") or "")
        if ref and not allows_read(ref, workspace):
            continue
        also = []
        for extra in row.get("also") or []:
            extra_ref = str(extra.get("source_ref") or "")
            if extra_ref and not allows_read(extra_ref, workspace):
                continue
            also.append(extra)
        if "also" in row:
            row = {**row, "also": also}
        kept.append(row)
    return kept


def page_source_ref(workspace: Path, rel: str) -> str:
    path = workspace / rel if rel.startswith("wiki/") else workspace / "wiki" / rel
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    if end < 0:
        return ""
    for line in text[4:end].splitlines():
        if line.startswith("source_ref:"):
            return line.split(":", 1)[1].strip()
    return ""


def may_edit_page(workspace: Path, rel: str) -> tuple[bool, str]:
    ref = page_source_ref(workspace, rel)
    if ref and not allows_write(ref, workspace):
        return False, "the source system does not grant edit on this page"
    return True, ""
