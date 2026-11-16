"""Paragraph-level claim lint.

    python -m switchbay.claim_lint WORKSPACE

Every claim paragraph on a fact, evidence, hypothesis, or assumption
page must contain a ``(vault:...)``, ``(table:...)``, or ``[[wikilink]]``
citation. Notes and todos are skipped. A figure page needs a
``sources`` list. A case page needs the five sections in
``case_page.REQUIRED_SECTIONS``.

``confidence``, ``uncertainty``, and ``role`` are checked when a page
sets them. A meta-ontology file can add keys and can mark further
types with ``claims: true`` or ``false``. With no file, those three
keys and the four page types above are the whole check.

Exit status is 1 when any violation is printed, 0 otherwise.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import case_page, meta_ontology
from .meta_ontology import SchemaKey

DEFAULT_CLAIM_TYPES = frozenset({"fact", "evidence", "hypothesis", "assumption"})
EXEMPT_TYPES = frozenset({"note", "todo"})
CLAIM_ROLES = frozenset({"assumption", "hypothesis"})

BUILTIN_SCHEMA: tuple[SchemaKey, ...] = (
    SchemaKey(
        key="confidence",
        description="A number from 0 to 1.",
        minimum=0.0,
        maximum=1.0,
    ),
    SchemaKey(
        key="uncertainty",
        description="attested, inferred, or unattested.",
        values=("attested", "inferred", "unattested"),
    ),
    SchemaKey(
        key="role",
        description="What the page is doing beyond its type.",
    ),
)

_CITE_RE = re.compile(
    r"\(\s*vault:[^)\n]+\)"
    r"|\(\s*table:[^)\n]+\)"
    r"|\[\[[^\]\n]+\]\]"
)
_LIST_RE = re.compile(r"^(?:[-*+]|\d+\.)\s+")
_WORD_RE = re.compile(r"[A-Za-z]{3,}")


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    code: str
    message: str

    def format(self) -> str:
        return f"{self.path}:{self.line}: {self.code}: {self.message}"


def lint_path(path: Path) -> list[Violation]:
    """Lint a workspace, a wiki directory, or one markdown file."""
    target = Path(path)
    if target.is_file():
        workspace = _workspace_for(target)
        return _lint_file(target, target, workspace)
    workspace = target
    wiki = target / "wiki" if (target / "wiki").is_dir() else target
    violations: list[Violation] = []
    ont, err = meta_ontology.load_result(workspace)
    if err:
        config = meta_ontology.config_path(workspace)
        violations.append(Violation(
            str(config), 1, "bad-meta-ontology", err,
        ))
    if not wiki.is_dir():
        return violations
    for md in sorted(wiki.rglob("*.md")):
        violations.extend(_lint_file(md, wiki, workspace, ont=ont))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m switchbay.claim_lint")
    parser.add_argument(
        "path",
        type=Path,
        help="Workspace, wiki directory, or one markdown file.",
    )
    args = parser.parse_args(argv)
    violations = lint_path(args.path)
    for item in violations:
        print(item.format())
    return 1 if violations else 0


def _lint_file(
    path: Path,
    root: Path,
    workspace: Path,
    *,
    ont: meta_ontology.MetaOntology | None = None,
) -> list[Violation]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [Violation(str(path), 1, "unreadable", str(exc))]
    if ont is None and (workspace / ".curator" / "meta-ontology.yaml").is_file():
        ont, _err = meta_ontology.load_result(workspace)
    fm, body, body_line = _read_frontmatter(text)
    page_type = str(fm.get("type") or "").strip().lower()
    role = str(fm.get("role") or "").strip().lower()
    try:
        rel = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        rel = path.as_posix()
    out: list[Violation] = []
    out.extend(_schema_violations(fm, rel, _schema_for(workspace, ont)))
    if page_type == "figure" and not _has_sources(fm):
        out.append(Violation(
            rel, 1, "figure-without-sources",
            "A figure page needs a sources list naming its data.",
        ))
    if page_type == "case" or role == "case":
        for section in case_page.missing_sections(body):
            out.append(Violation(
                rel, 1, "missing-section",
                f"Case page is missing the section {section}.",
            ))
    if page_type in EXEMPT_TYPES:
        return out
    claim_bearing = (
        page_type in _claim_types(ont)
        or role in CLAIM_ROLES
    )
    if not claim_bearing:
        return out
    paragraphs = _claim_paragraphs(body, body_line)
    if not _CITE_RE.search(body):
        out.append(Violation(
            rel, body_line, "missing-page-citation",
            "This page states claims and has no citation.",
        ))
    for line, paragraph in paragraphs:
        if _is_claim(paragraph) and not _CITE_RE.search(paragraph):
            snippet = " ".join(paragraph.split())
            if len(snippet) > 80:
                snippet = snippet[:77] + "..."
            out.append(Violation(
                rel, line, "missing-citation",
                f"Claim paragraph has no citation: {snippet}",
            ))
    return out


def _claim_types(ont: meta_ontology.MetaOntology | None) -> set[str]:
    types = set(DEFAULT_CLAIM_TYPES)
    if ont is not None:
        for node in ont.nodes:
            if node.claims is True:
                types.add(node.type)
            elif node.claims is False:
                types.discard(node.type)
    return types - set(EXEMPT_TYPES)


def _schema_for(
    workspace: Path, ont: meta_ontology.MetaOntology | None,
) -> list[SchemaKey]:
    if ont is None:
        ont, _err = meta_ontology.load_result(workspace)
    by_key = {item.key: item for item in BUILTIN_SCHEMA}
    ordered: list[SchemaKey] = []
    seen: set[str] = set()
    if ont is not None:
        for item in ont.schema_keys:
            by_key[item.key] = item
    for item in BUILTIN_SCHEMA:
        ordered.append(by_key[item.key])
        seen.add(item.key)
    if ont is not None:
        for item in ont.schema_keys:
            if item.key not in seen:
                ordered.append(item)
                seen.add(item.key)
    return ordered


def _schema_violations(
    fm: dict[str, Any], rel: str, keys: list[SchemaKey],
) -> list[Violation]:
    out: list[Violation] = []
    for spec in keys:
        if spec.key not in fm:
            continue
        raw = fm.get(spec.key)
        if raw is None:
            continue
        if isinstance(raw, list):
            parts = [str(item).strip().strip("\"'") for item in raw]
            parts = [part for part in parts if part]
            if not parts:
                continue
            text = parts[0] if len(parts) == 1 else ", ".join(parts)
        else:
            text = str(raw).strip().strip("\"'")
            if not text:
                continue
        if spec.values and text not in spec.values:
            allowed = ", ".join(spec.values)
            out.append(Violation(
                rel, 1, "bad-schema-key",
                f"{spec.key} must be one of: {allowed}.",
            ))
            continue
        if spec.minimum is None and spec.maximum is None:
            continue
        try:
            number = float(text)
        except ValueError:
            out.append(Violation(
                rel, 1, "bad-schema-key",
                f"{spec.key} must be a number.",
            ))
            continue
        if spec.minimum is not None and number < spec.minimum:
            out.append(Violation(
                rel, 1, "bad-schema-key",
                f"{spec.key} must be at least {spec.minimum}.",
            ))
        elif spec.maximum is not None and number > spec.maximum:
            out.append(Violation(
                rel, 1, "bad-schema-key",
                f"{spec.key} must be at most {spec.maximum}.",
            ))
    return out


def _has_sources(fm: dict[str, Any]) -> bool:
    raw = fm.get("sources")
    if isinstance(raw, list):
        return any(str(item).strip() for item in raw)
    if isinstance(raw, str):
        text = raw.strip()
        return bool(text) and text not in {"[]", '""', "''"}
    return False


def _claim_paragraphs(body: str, body_line: int) -> list[tuple[int, str]]:
    paragraphs: list[tuple[int, str]] = []
    buf: list[str] = []
    start = body_line
    in_fence = False

    def flush(next_start: int) -> None:
        nonlocal buf, start
        text = "\n".join(buf).strip()
        buf = []
        if text:
            paragraphs.append((start, text))
        start = next_start

    lines = body.splitlines()
    for offset, line in enumerate(lines):
        file_line = body_line + offset
        stripped = line.strip()
        if stripped.startswith("```"):
            if buf:
                flush(file_line)
            in_fence = not in_fence
            start = file_line + 1
            continue
        if in_fence:
            continue
        if not stripped or stripped.startswith("#"):
            if buf:
                flush(file_line + 1)
            else:
                start = file_line + 1
            continue
        if _LIST_RE.match(stripped) and buf:
            flush(file_line)
        if not buf:
            start = file_line
        buf.append(line)
    if buf:
        flush(body_line + len(lines))
    return paragraphs


def _is_claim(text: str) -> bool:
    residual = _CITE_RE.sub(" ", text)
    residual = re.sub(r"[#>*_`\[\]()]", " ", residual)
    return _WORD_RE.search(residual) is not None


def _read_frontmatter(text: str) -> tuple[dict[str, Any], str, int]:
    if not text.startswith("---\n"):
        return {}, text, 1
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text, 1
    head = text[4:end]
    body = text[end + 5:]
    body_line = text[: end + 5].count("\n") + 1
    fm: dict[str, Any] = {}
    cur_key: str | None = None
    cur_list: list[str] | None = None
    for raw in head.splitlines():
        if raw.startswith("  - ") and cur_list is not None:
            cur_list.append(raw[4:].strip().strip("\"'"))
            continue
        if ":" in raw and not raw.startswith(" "):
            cur_key, _, val = raw.partition(":")
            cur_key = cur_key.strip()
            val = val.strip()
            if val.startswith("[") and val.endswith("]"):
                items = [
                    part.strip().strip("\"'")
                    for part in val[1:-1].split(",")
                ]
                fm[cur_key] = [part for part in items if part]
                cur_list = None
            elif val == "":
                cur_list = []
                fm[cur_key] = cur_list
            else:
                fm[cur_key] = val.strip("\"'")
                cur_list = None
    return fm, body, body_line


def _workspace_for(path: Path) -> Path:
    """Walk up to a directory that holds .curator or wiki, else the parent."""
    current = path.parent
    for parent in (current, *current.parents):
        if (parent / "wiki").is_dir() or (parent / ".curator").is_dir():
            return parent
    return current


if __name__ == "__main__":
    sys.exit(main())
