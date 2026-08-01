"""Deterministic mutation-contract auditor for the CE QUERY product pilot.

The complete product is not read-only. An ordinary QUERY turn may append to
``.curator/log.md``; an accepted crystallization may additionally add exactly
one ``wiki/analyses/<slug>.md`` and make one wiki git commit. Every other
filesystem change is a hard product failure.

This module decides that verdict deterministically from two per-turn workspace
snapshots. Snapshot hashes/diffs are authoritative — never shell-pattern
containment (charter "Mutation adjudication" rule). The auditor answers *what*
changed and *whether the contract allows it*; a permitted wiki git commit is
validated separately (HEAD moved by exactly one commit), so this content
auditor deliberately excludes ``.git`` internals — otherwise a legitimate
commit's object churn would read as a mass mutation.

No model calls. Pure functions over path→hash manifests, plus thin filesystem
wrappers.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

CURATOR_LOG = ".curator/log.md"
ANALYSES_PREFIX = "wiki/analyses/"

# Read-side caches the shipped CE tooling writes while answering (per the prereg
# mutation-adjudication ladder: a code-audited read-cache is amended into the
# contract, not scored as a forbidden mutation). uv writes an interpreter cache
# under .curator/uv-cache/ when the model runs the CE scripts via `uv run`.
CE_READ_CACHE_PREFIXES: tuple[str, ...] = (".curator/uv-cache/", ".curator/.uv-cache/")

Mode = Literal["ordinary", "crystallization"]


def _skip(path: Path, root: Path) -> bool:
    """Exclude VCS internals and Python caches from the content manifest.

    Unlike ``query_orchestrator._tree_hash`` we skip *any* ``.git`` component
    (root- or nested-, e.g. ``wiki/.git``) because a permitted wiki commit is
    adjudicated by a dedicated git check, not by content diff.
    """
    parts = path.relative_to(root).parts
    if ".git" in parts or "__pycache__" in parts:
        return True
    if path.suffix == ".pyc":
        return True
    return False


def content_manifest(root: Path) -> dict[str, str]:
    """Map every content file under ``root`` to its sha256 (POSIX rel paths)."""
    root = Path(root)
    out: dict[str, str] = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        if _skip(path, root):
            continue
        rel = path.relative_to(root).as_posix()
        out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def stat_manifest(root: Path) -> dict[str, str]:
    """Fast ``(size, mtime_ns)`` manifest — for the per-turn product diff over a
    ~3.8 GB / 100k-file snapshot where sha256-ing everything is impractical.

    A content-preserving rewrite that bumps mtime reads as "modified" (a
    conservative false-positive the auditor is happy to surface). Same skip
    rules and same shape as :func:`content_manifest`, so it plugs straight into
    :func:`classify_changes`; the append-only ``.curator/log.md`` check still
    reads that one file's bytes.
    """
    root = Path(root)
    out: dict[str, str] = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        if _skip(path, root):
            continue
        try:
            st = path.stat()
        except OSError:
            continue
        out[path.relative_to(root).as_posix()] = f"{st.st_size}:{st.st_mtime_ns}"
    return out


def is_append_only(before: bytes | None, after: bytes | None) -> bool:
    """True iff ``after`` is ``before`` with content only appended.

    A missing ``before`` (log created this turn) counts as append-from-empty.
    A missing ``after`` (deletion) is never append-only.
    """
    if after is None:
        return False
    if before is None:
        return True
    return after.startswith(before)


@dataclass
class MutationVerdict:
    allowed: bool
    mode: str
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    allowed_changes: list[dict[str, str]] = field(default_factory=list)
    violations: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "mode": self.mode,
            "added": self.added,
            "removed": self.removed,
            "modified": self.modified,
            "allowed_changes": self.allowed_changes,
            "violations": self.violations,
        }


def _under_cache(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path.startswith(pfx) for pfx in prefixes)


def classify_changes(
    before: dict[str, str],
    after: dict[str, str],
    *,
    mode: Mode = "ordinary",
    log_is_append_only: bool = True,
    read_cache_paths: frozenset[str] = frozenset(),
    read_cache_prefixes: tuple[str, ...] = (),
) -> MutationVerdict:
    """Adjudicate a content diff against the frozen mutation contract.

    Args:
        before / after: path→sha256 content manifests bracketing one user turn.
        mode: ``crystallization`` additionally permits exactly one new
            ``wiki/analyses/<slug>.md``; ``ordinary`` permits no wiki writes.
        log_is_append_only: whether ``.curator/log.md`` changed append-only
            (caller computes this from the two file bodies via
            :func:`is_append_only`).
        read_cache_paths: preflight-frozen read-side cache paths whose
            add/modify is tolerated.
    """
    before_keys = set(before)
    after_keys = set(after)
    added = sorted(after_keys - before_keys)
    removed = sorted(before_keys - after_keys)
    modified = sorted(k for k in before_keys & after_keys if before[k] != after[k])

    allowed_changes: list[dict[str, str]] = []
    violations: list[dict[str, str]] = []

    # Deletions are never permitted (contract forbids modifying/removing
    # history) — except read-cache eviction under a frozen cache prefix.
    for p in removed:
        if _under_cache(p, read_cache_prefixes):
            allowed_changes.append({"path": p, "op": "delete", "reason": "read-cache eviction"})
        else:
            violations.append({"path": p, "op": "delete", "reason": "deletion forbidden"})

    for p in modified:
        if p == CURATOR_LOG:
            if log_is_append_only:
                allowed_changes.append(
                    {"path": p, "op": "append", "reason": "append-only curator log"}
                )
            else:
                violations.append(
                    {"path": p, "op": "modify", "reason": "curator log not append-only"}
                )
        elif p in read_cache_paths or _under_cache(p, read_cache_prefixes):
            allowed_changes.append(
                {"path": p, "op": "modify", "reason": "frozen read-cache metadata"}
            )
        else:
            violations.append(
                {"path": p, "op": "modify", "reason": "out-of-contract file modified"}
            )

    analyses_added: list[str] = []
    for p in added:
        if p == CURATOR_LOG:
            if log_is_append_only:
                allowed_changes.append(
                    {"path": p, "op": "create", "reason": "curator log created (append-only)"}
                )
            else:
                violations.append(
                    {"path": p, "op": "create", "reason": "curator log not append-only"}
                )
        elif p in read_cache_paths or _under_cache(p, read_cache_prefixes):
            allowed_changes.append(
                {"path": p, "op": "create", "reason": "frozen read-cache metadata"}
            )
        elif p.startswith(ANALYSES_PREFIX) and p.endswith(".md"):
            analyses_added.append(p)
        else:
            violations.append(
                {"path": p, "op": "create", "reason": "out-of-contract file created"}
            )

    if mode == "crystallization":
        if len(analyses_added) == 1:
            allowed_changes.append(
                {"path": analyses_added[0], "op": "create", "reason": "crystallization analysis page"}
            )
        elif len(analyses_added) > 1:
            for p in analyses_added:
                violations.append(
                    {"path": p, "op": "create", "reason": "more than one analysis page created"}
                )
        # zero analyses added in crystallization mode is fine (offer declined).
    else:
        for p in analyses_added:
            violations.append(
                {"path": p, "op": "create", "reason": "wiki write outside crystallization"}
            )

    return MutationVerdict(
        allowed=not violations,
        mode=mode,
        added=added,
        removed=removed,
        modified=modified,
        allowed_changes=allowed_changes,
        violations=violations,
    )


def _read_bytes(root: Path, rel: str) -> bytes | None:
    path = Path(root) / rel
    if not path.is_file():
        return None
    return path.read_bytes()


def audit_dirs(
    before_root: Path,
    after_root: Path,
    *,
    mode: Mode = "ordinary",
    read_cache_paths: frozenset[str] = frozenset(),
    read_cache_prefixes: tuple[str, ...] = (),
) -> MutationVerdict:
    """Build content manifests for two snapshot directories and adjudicate.

    ``before_root`` is a retained pre-turn copy; ``after_root`` is the live
    post-turn snapshot. The append-only flag for ``.curator/log.md`` is derived
    from the two file bodies.
    """
    before = content_manifest(before_root)
    after = content_manifest(after_root)
    log_append_ok = is_append_only(
        _read_bytes(before_root, CURATOR_LOG),
        _read_bytes(after_root, CURATOR_LOG),
    )
    return classify_changes(
        before,
        after,
        mode=mode,
        log_is_append_only=log_append_ok,
        read_cache_paths=read_cache_paths,
        read_cache_prefixes=read_cache_prefixes,
    )
