"""Paragraph-level claim lint.

    python -m switchbay.claim_lint WORKSPACE

Every claim paragraph on a fact, evidence, hypothesis, or assumption
page must contain a ``(vault:...)``, ``(table:...)``, ``(figure:...)``,
or ``[[wikilink]]`` citation, and that citation has to resolve. A vault
citation needs the file. A table citation needs the table page, or a
CSV or parquet file when the citation names one. A figure citation
needs the figure page or image. A wikilink needs the page. ``#anchor``
needs that heading. ``#row=`` or ``#id=`` needs that row, and
``#column=`` needs that column. Notes and todos are skipped. A figure
page needs a ``sources`` list. A case page needs the five sections in
``case_page.REQUIRED_SECTIONS``.

``confidence``, ``uncertainty``, and ``role`` are checked when a page
sets them. A blank value is reported as blank. A meta-ontology file
can add keys and can mark further types with ``claims: true`` or
``false``. With no file, those three keys and the four page types
above are the whole check.

A typed edge (an edge that names source and target node types) is
checked when a page lists targets under that edge's frontmatter key.
The target page has to exist, and the source and target page types
have to match the edge. Edges that omit endpoints, and workspaces
with no meta-ontology file, are not checked this way.

Exit status is 1 when any violation is printed, 0 otherwise.
"""

from __future__ import annotations

import argparse
import csv
import io
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
    r"\(\s*(?P<kind>vault|table|figure)\s*:\s*(?P<body>[^)\n]*?)\)"
    r"|\[\[(?P<link>[^\]\n]+)\]\]"
)
_LIST_RE = re.compile(r"^(?:[-*+]|\d+\.)\s+")
_WORD_RE = re.compile(r"[A-Za-z]{3,}")
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
_ANCHOR_RE = re.compile(
    r"\{#([A-Za-z0-9_-]+)\}|<a\s+[^>]*\bid=[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")
_DATA_SUFFIXES = {".csv", ".tsv", ".tab", ".parquet"}
_ID_HEADERS = {"id", "series", "name", "key"}
_AMBIGUOUS = object()


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
        violations = _lint_file(
            target, target, workspace, index=_Index(workspace),
        )
        try:
            only = target.resolve().relative_to((workspace / "wiki").resolve()).as_posix()
        except ValueError:
            only = target.name
        violations.extend(_typed_edge_violations(workspace, only_path=only))
        return violations
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
    index = _Index(workspace)
    for md in sorted(wiki.rglob("*.md")):
        violations.extend(_lint_file(md, wiki, workspace, ont=ont, index=index))
    violations.extend(_typed_edge_violations(workspace, ont))
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
    index: _Index | None = None,
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
    if index is None:
        index = _Index(workspace)
    out.extend(_unresolved_citations(
        body, body_line, rel, paragraphs, index,
    ))
    for line, paragraph in paragraphs:
        if _is_claim(paragraph) and not _CITE_RE.search(paragraph):
            out.append(Violation(
                rel, line, "missing-citation",
                f"Claim paragraph has no citation: {_snippet(paragraph)}",
            ))
    return out


def _typed_edge_violations(
    workspace: Path,
    ont: meta_ontology.MetaOntology | None = None,
    *,
    only_path: str | None = None,
) -> list[Violation]:
    """Validate edges that declare source and target node types."""
    if ont is None:
        ont, err = meta_ontology.load_result(workspace)
        if err or ont is None:
            return []
    if not any(edge.typed for edge in ont.edges):
        return []
    _edges, issues = meta_ontology.survey_typed_edges(workspace, ont)
    out: list[Violation] = []
    for issue in issues:
        if only_path is not None and issue.path != only_path:
            continue
        out.append(Violation(issue.path, issue.line, issue.code, issue.message))
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
        if _is_blank(raw):
            out.append(Violation(
                rel, 1, "bad-schema-key",
                f"{spec.key} is blank.",
            ))
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

    def close_blank() -> None:
        nonlocal cur_list
        if (
            cur_key
            and cur_list is not None
            and fm.get(cur_key) is cur_list
            and not cur_list
        ):
            fm[cur_key] = ""
        cur_list = None

    for raw in head.splitlines():
        if raw.startswith("  - ") and cur_list is not None:
            cur_list.append(raw[4:].strip().strip("\"'"))
            continue
        if ":" in raw and not raw.startswith(" "):
            close_blank()
            cur_key, _, val = raw.partition(":")
            cur_key = cur_key.strip()
            val = val.strip()
            if val.startswith("[") and val.endswith("]"):
                items = [
                    part.strip().strip("\"'")
                    for part in val[1:-1].split(",")
                ]
                fm[cur_key] = [part for part in items if part]
            elif val == "":
                cur_list = []
                fm[cur_key] = cur_list
            else:
                fm[cur_key] = val.strip("\"'")
    close_blank()
    return fm, body, body_line


def _is_blank(raw: Any) -> bool:
    if raw is None:
        return True
    if isinstance(raw, str):
        return not raw.strip().strip("\"'")
    if isinstance(raw, list):
        return not any(str(item).strip().strip("\"'") for item in raw)
    return False


def _snippet(text: str) -> str:
    snippet = " ".join(text.split())
    if len(snippet) > 80:
        return snippet[:77] + "..."
    return snippet


@dataclass(frozen=True)
class _Locators:
    anchor: str | None = None
    row: str | None = None
    column: str | None = None
    ident: str | None = None

    def any(self) -> bool:
        return bool(self.anchor or self.row or self.column or self.ident)


@dataclass(frozen=True)
class _Cite:
    raw: str
    kind: str
    target: str
    loc: _Locators
    line: int


@dataclass(frozen=True)
class _Table:
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


def _unresolved_citations(
    body: str,
    body_line: int,
    rel: str,
    paragraphs: list[tuple[int, str]],
    index: _Index,
) -> list[Violation]:
    spans = _fence_spans(body)
    out: list[Violation] = []
    for cite in _iter_cites(body, body_line, spans):
        problem = index.problem(cite)
        if not problem:
            continue
        claim = _claim_for(paragraphs, cite.line, cite.raw, body)
        out.append(Violation(
            rel, cite.line, "unresolved-citation",
            f"Citation {cite.raw} {problem}. Claim: {_snippet(claim)}",
        ))
    return out


def _fence_spans(body: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    offset = 0
    open_at: int | None = None
    for line in body.splitlines(keepends=True):
        if line.strip().startswith("```"):
            if open_at is None:
                open_at = offset
            else:
                spans.append((open_at, offset + len(line)))
                open_at = None
        offset += len(line)
    if open_at is not None:
        spans.append((open_at, len(body)))
    return spans


def _in_span(pos: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= pos < end for start, end in spans)


def _iter_cites(
    body: str, body_line: int, spans: list[tuple[int, int]],
) -> list[_Cite]:
    found: list[_Cite] = []
    for match in _CITE_RE.finditer(body):
        if _in_span(match.start(), spans):
            continue
        line = body_line + body.count("\n", 0, match.start())
        if match.group("link") is not None:
            target, loc = _split_target(match.group("link").split("|", 1)[0])
            kind = "figure" if _is_figure_ref(target) else "page"
        else:
            kind = (match.group("kind") or "").lower()
            target, loc = _split_target(match.group("body") or "")
        raw = " ".join(match.group(0).split())
        found.append(_Cite(raw=raw, kind=kind, target=target, loc=loc, line=line))
    return found


def _split_target(raw: str) -> tuple[str, _Locators]:
    text = (raw or "").strip()
    path, _, frag = text.partition("#")
    return path.strip(), _parse_locators(frag)


def _parse_locators(frag: str) -> _Locators:
    frag = frag.strip()
    if not frag:
        return _Locators()
    parts = [part.strip() for part in re.split(r"[&,]", frag) if part.strip()]
    if not any("=" in part for part in parts):
        return _Locators(anchor=frag)
    anchor: str | None = None
    row: str | None = None
    column: str | None = None
    ident: str | None = None
    for part in parts:
        if "=" not in part:
            anchor = anchor or part
            continue
        key, _, val = part.partition("=")
        key = key.strip().lower()
        val = val.strip()
        if key in {"column", "col"}:
            column = val
        elif key == "row":
            row = val
        elif key == "id":
            ident = val
        elif key in {"anchor", "heading"}:
            anchor = val
        else:
            anchor = anchor or part
    return _Locators(anchor=anchor, row=row, column=column, ident=ident)


def _is_figure_ref(target: str) -> bool:
    path = target.replace("\\", "/").lower()
    if path.startswith("figures/") or "/figures/" in f"/{path}":
        return True
    return Path(path).suffix in _IMAGE_SUFFIXES


def _claim_for(
    paragraphs: list[tuple[int, str]], line: int, raw: str, body: str,
) -> str:
    found = ""
    for start, text in paragraphs:
        if start <= line and raw in " ".join(text.split()):
            found = text
    if found:
        return found
    for text in body.splitlines():
        if raw in " ".join(text.split()):
            return text
    return raw


def _cell_norm(value: str) -> str:
    text = re.sub(r"[*_`]", "", value or "")
    return " ".join(text.split()).casefold()


def _slug(text: str) -> str:
    text = _cell_norm(text).replace("'", "")
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    return re.sub(r"-{2,}", "-", text).strip("-")


def _join_missing(parts: list[str]) -> str:
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + ", and " + parts[-1]


class _Index:
    """Files and wiki pages a citation can point at."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.pages: list[tuple[str, Path]] = []
        self.by_stem: dict[str, list[Path]] = {}
        self._text: dict[Path, str] = {}
        self._meta: dict[Path, tuple[str, str]] = {}
        self._built = False

    def problem(self, cite: _Cite) -> str:
        if cite.kind == "vault":
            found = self.find_file(cite.target)
            noun = "file"
        elif cite.kind == "table":
            found = self.find_table(cite.target)
            noun = "table"
        elif cite.kind == "figure":
            found = self.find_figure(cite.target)
            noun = "figure"
        else:
            found = self.find_page(cite.target)
            noun = "page"
        if found is _AMBIGUOUS:
            return f"matches more than one {noun}"
        if not isinstance(found, Path):
            name = cite.target or noun
            return f"is missing {noun} {name}"
        missing = self._locator_missing(found, cite.loc)
        if not missing:
            return ""
        return "is missing " + _join_missing(missing)

    def find_file(self, target: str) -> Path | object | None:
        rel = _clean_rel(target)
        if rel is None:
            return None
        ordered = []
        if not rel.startswith("vault/"):
            ordered.append(f"vault/{rel}")
        ordered.append(rel)
        for cand in ordered:
            path = self._safe(cand)
            if path is not None and path.is_file():
                return path
        if "/" in rel:
            return None
        root = self.workspace / "vault"
        if not root.is_dir():
            return None
        matches = []
        for path in root.rglob(Path(rel).name):
            if not path.is_file():
                continue
            try:
                path.resolve().relative_to(self.workspace)
            except ValueError:
                continue
            matches.append(path)
        return _one(matches)

    def find_page(self, target: str) -> Path | object | None:
        rel = _page_rel(target)
        if not rel:
            return None
        exact = [path for key, path in self._ensure() if key.casefold() == rel.casefold()]
        if "/" in rel:
            return _one(exact)
        hit = _one(exact)
        if hit is not None:
            return hit
        stemmed = self.by_stem.get(_stem_key(rel), [])
        hit = _one(stemmed)
        if hit is not None:
            return hit
        want = rel.casefold()
        titled = [
            path for path in self._page_paths()
            if self._title(path).casefold() == want
        ]
        return _one(titled)

    def find_table(self, target: str) -> Path | object | None:
        if _data_suffix(target):
            return self.find_file(target)
        rel = _page_rel(target)
        if not rel:
            return None
        exact = [path for key, path in self._ensure() if key.casefold() == rel.casefold()]
        tables = [path for path in exact if self._is_table_page(path)]
        if "/" in rel:
            return _one(tables)
        hit = _one(tables)
        if hit is not None:
            return hit
        stemmed = [
            path for path in self.by_stem.get(_stem_key(rel), [])
            if self._is_table_page(path)
        ]
        return _one(stemmed)

    def find_figure(self, target: str) -> Path | object | None:
        rel = _clean_rel(target)
        if rel is None:
            return None
        page_rel = _page_rel(_strip_image(rel))
        pages = [
            path for key, path in self._ensure()
            if key.casefold() == page_rel.casefold() and self._is_figure_page(path)
        ]
        if "/" not in page_rel:
            pages = pages or [
                path for path in self.by_stem.get(_stem_key(page_rel), [])
                if self._is_figure_page(path)
            ]
        hit = _one(pages)
        if hit is not None:
            return hit
        return _one(self._figure_files(rel))

    def _locator_missing(self, path: Path, loc: _Locators) -> list[str]:
        if not loc.any():
            return []
        missing: list[str] = []
        if loc.anchor and not self._has_anchor(path, loc.anchor):
            missing.append(f"anchor {loc.anchor}")
        needed: list[tuple[str, str]] = []
        if loc.column:
            needed.append(("column", f"column {loc.column}"))
        if loc.ident:
            needed.append(("id", f"row {loc.ident}"))
        if loc.row:
            needed.append(("row", f"row {loc.row}"))
        if not needed:
            return missing
        tables = self._tables(path)
        if any(_table_satisfies(table, loc) for table in tables):
            return missing
        for key, label in needed:
            if not any(_table_has(table, loc, key) for table in tables):
                missing.append(label)
        if not any(item.startswith("row ") or item.startswith("column ") for item in missing):
            if needed:
                missing.append("row and column in the same table")
        return missing

    def _ensure(self) -> list[tuple[str, Path]]:
        if self._built:
            return self.pages
        self._built = True
        wiki = self.workspace / "wiki"
        if not wiki.is_dir():
            return self.pages
        for path in sorted(wiki.rglob("*.md")):
            if not path.is_file():
                continue
            try:
                key = path.relative_to(wiki).as_posix()[:-3]
            except ValueError:
                continue
            self.pages.append((key, path))
            self.by_stem.setdefault(path.stem.casefold(), []).append(path)
        return self.pages

    def _page_paths(self) -> list[Path]:
        return [path for _, path in self._ensure()]

    def _safe(self, rel: str) -> Path | None:
        rel = rel.strip().replace("\\", "/")
        while rel.startswith("./"):
            rel = rel[2:]
        if not rel or rel.startswith("/") or "\x00" in rel:
            return None
        parts = [part for part in rel.split("/") if part not in {"", "."}]
        if any(part == ".." for part in parts):
            return None
        target = (self.workspace / "/".join(parts)).resolve()
        try:
            target.relative_to(self.workspace)
        except ValueError:
            return None
        return target

    def _text_of(self, path: Path) -> str:
        cached = self._text.get(path)
        if cached is not None:
            return cached
        try:
            data = path.read_bytes()
        except OSError:
            self._text[path] = ""
            return ""
        if data.startswith(b"PAR1") or b"\x00" in data[:1024]:
            self._text[path] = ""
            return ""
        text = data.decode("utf-8", errors="replace")
        self._text[path] = text
        return text

    def _meta_of(self, path: Path) -> tuple[str, str]:
        cached = self._meta.get(path)
        if cached is not None:
            return cached
        text = self._text_of(path)
        title = ""
        page_type = ""
        if text.startswith("---"):
            end = text.find("\n---", 3)
            head = text[3:end] if end >= 0 else text[:800]
            for raw in head.splitlines():
                if raw.lower().startswith("title:"):
                    title = raw.split(":", 1)[1].strip().strip("\"'")
                elif raw.lower().startswith("type:"):
                    page_type = raw.split(":", 1)[1].strip().strip("\"'").lower()
        self._meta[path] = (title, page_type)
        return self._meta[path]

    def _title(self, path: Path) -> str:
        return self._meta_of(path)[0]

    def _page_type(self, path: Path) -> str:
        return self._meta_of(path)[1]

    def _is_table_page(self, path: Path) -> bool:
        if self._page_type(path) in {"table", "extracted-table", "extracted_table"}:
            return True
        return "tables" in self._wiki_folders(path)

    def _is_figure_page(self, path: Path) -> bool:
        if self._page_type(path) == "figure":
            return True
        return "figures" in self._wiki_folders(path)

    def _wiki_folders(self, path: Path) -> tuple[str, ...]:
        try:
            rel = path.resolve().relative_to(self.workspace / "wiki")
        except ValueError:
            return ()
        return rel.parts[:-1]

    def _figure_files(self, rel: str) -> list[Path]:
        names = [rel]
        bare = Path(rel).name
        if "/" not in rel:
            names = [
                f"wiki/figures/{bare}",
                f"wiki/figures/_assets/{bare}",
                f"figures/{bare}",
                f"figures/_assets/{bare}",
                bare,
            ]
        else:
            if not rel.startswith("wiki/"):
                names.append(f"wiki/{rel}")
        found: list[Path] = []
        seen: set[str] = set()
        for name in names:
            candidates = [name]
            if not Path(name).suffix:
                candidates.extend(name + suffix for suffix in _IMAGE_SUFFIXES)
            for cand in candidates:
                path = self._safe(cand)
                if path is None or not path.is_file():
                    continue
                key = str(path)
                if key not in seen:
                    seen.add(key)
                    found.append(path)
        return found

    def _has_anchor(self, path: Path, anchor: str) -> bool:
        anchors = _anchors(self._text_of(path))
        want = _cell_norm(anchor)
        return want in anchors or _slug(anchor) in anchors

    def _tables(self, path: Path) -> list[_Table]:
        if path.suffix.lower() == ".parquet" or _magic_parquet(path):
            columns = _parquet_columns(path) or []
            return [_Table(tuple(columns), ())]
        text = self._text_of(path)
        tables = _markdown_tables(text)
        if path.suffix.lower() in {".csv", ".tsv", ".tab"}:
            tables.extend(_csv_tables(text, path))
        return tables


def _one(paths: list[Path]) -> Path | object | None:
    uniq: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        uniq.append(path)
    if not uniq:
        return None
    if len(uniq) == 1:
        return uniq[0]
    return _AMBIGUOUS


def _clean_rel(target: str) -> str | None:
    rel = (target or "").strip().replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    if not rel or rel.startswith("/") or "\x00" in rel:
        return None
    if any(part == ".." for part in rel.split("/")):
        return None
    return rel


def _page_rel(target: str) -> str:
    rel = _clean_rel(target) or ""
    if rel.lower().startswith("wiki/"):
        rel = rel[5:]
    if rel.lower().endswith(".md"):
        rel = rel[:-3]
    return rel.strip("/")


def _stem_key(name: str) -> str:
    base = _page_rel(name).rsplit("/", 1)[-1]
    return base.casefold().replace(" ", "-")


def _strip_image(rel: str) -> str:
    lower = rel.lower()
    for suffix in _IMAGE_SUFFIXES:
        if lower.endswith(suffix):
            return rel[:-len(suffix)]
    return rel


def _data_suffix(target: str) -> bool:
    return Path(target.strip()).suffix.lower() in _DATA_SUFFIXES


def _magic_parquet(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(4) == b"PAR1"
    except OSError:
        return False


def _anchors(text: str) -> set[str]:
    found: set[str] = set()
    for match in _HEADING_RE.finditer(text or ""):
        title = match.group(1).strip()
        found.add(_cell_norm(title))
        found.add(_slug(title))
    for match in _ANCHOR_RE.finditer(text or ""):
        token = match.group(1) or match.group(2) or ""
        found.add(token.strip().casefold())
        found.add(_slug(token))
    return {item for item in found if item}


def _markdown_tables(text: str) -> list[_Table]:
    tables: list[_Table] = []
    block: list[str] = []

    def flush() -> None:
        nonlocal block
        parsed = _parse_markdown_table(block)
        if parsed is not None:
            tables.append(parsed)
        block = []

    for line in (text or "").splitlines():
        if line.strip().startswith("|"):
            block.append(line)
        elif block:
            flush()
    if block:
        flush()
    return tables


def _parse_markdown_table(lines: list[str]) -> _Table | None:
    rows = [_split_md_row(line) for line in lines]
    rows = [row for row in rows if any(row)]
    if len(rows) < 2 or not _is_separator(rows[1]):
        return None
    headers = rows[0]
    body = tuple(tuple(row) for row in rows[2:])
    return _Table(tuple(headers), body)


def _split_md_row(line: str) -> list[str]:
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    return [cell.strip() for cell in text.split("|")]


def _is_separator(cells: list[str]) -> bool:
    seen = False
    for cell in cells:
        compact = cell.replace(" ", "")
        if not compact:
            continue
        seen = True
        if not re.fullmatch(r":?-{3,}:?", compact):
            return False
    return seen


def _csv_tables(text: str, path: Path) -> list[_Table]:
    delim = "\t" if path.suffix.lower() in {".tsv", ".tab"} else ","
    try:
        rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    except csv.Error:
        return []
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    if not rows:
        return []
    headers = tuple(cell.strip() for cell in rows[0])
    body = tuple(tuple(cell.strip() for cell in row) for row in rows[1:])
    return [_Table(headers, body)]


def _id_index(headers: tuple[str, ...]) -> int:
    for index, header in enumerate(headers):
        if _cell_norm(header) in _ID_HEADERS:
            return index
    return 0


def _table_has(table: _Table, loc: _Locators, key: str) -> bool:
    if key == "column":
        want = _cell_norm(loc.column or "")
        return any(_cell_norm(header) == want for header in table.headers)
    if key == "id":
        index = _id_index(table.headers)
        want = _cell_norm(loc.ident or "")
        return any(
            index < len(row) and _cell_norm(row[index]) == want
            for row in table.rows
        )
    if key == "row":
        want = _cell_norm(loc.row or "")
        return any(any(_cell_norm(cell) == want for cell in row) for row in table.rows)
    return False


def _table_satisfies(table: _Table, loc: _Locators) -> bool:
    if loc.column and not _table_has(table, loc, "column"):
        return False
    if loc.ident and not _table_has(table, loc, "id"):
        return False
    if loc.row and not _table_has(table, loc, "row"):
        return False
    return bool(loc.column or loc.ident or loc.row)


def _parquet_columns(path: Path) -> list[str] | None:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if handle.read(4) != b"PAR1" or size < 12:
                return None
            handle.seek(size - 8)
            tail = handle.read(8)
            if len(tail) != 8 or tail[4:] != b"PAR1":
                return None
            footer_len = int.from_bytes(tail[:4], "little")
            if footer_len <= 0 or footer_len > size - 8:
                return None
            handle.seek(size - 8 - footer_len)
            footer = handle.read(footer_len)
        return _parse_parquet_footer(footer)
    except (OSError, ValueError, IndexError, UnicodeError):
        return None


def _parse_parquet_footer(footer: bytes) -> list[str]:
    pos = 0
    last_id = 0
    names: list[str] | None = None
    while pos < len(footer):
        header = footer[pos]
        pos += 1
        field_type = header & 0x0F
        delta = header >> 4
        if field_type == 0:
            break
        if delta == 0:
            field_id, pos = _varint(footer, pos)
            field_id = _zigzag(field_id)
        else:
            field_id = last_id + delta
        last_id = field_id
        if field_id == 2 and field_type == 9:
            names, pos = _read_schema_columns(footer, pos)
        else:
            pos = _skip_thrift(footer, pos, field_type)
    if names is None:
        raise ValueError("parquet schema missing")
    return names


def _read_schema_columns(buf: bytes, pos: int) -> tuple[list[str], int]:
    if pos >= len(buf):
        raise ValueError("truncated list")
    marker = buf[pos]
    pos += 1
    if marker == 0:
        return [], pos
    size = marker >> 4
    elem = marker & 0x0F
    if size == 15:
        size, pos = _varint(buf, pos)
    if elem != 12:
        for _ in range(size):
            pos = _skip_thrift(buf, pos, elem)
        return [], pos
    names: list[str] = []
    for _ in range(size):
        name, has_type, pos = _read_schema_element(buf, pos)
        if has_type and name:
            names.append(name)
    return names, pos


def _read_schema_element(buf: bytes, pos: int) -> tuple[str | None, bool, int]:
    name: str | None = None
    has_type = False
    last_id = 0
    while pos < len(buf):
        header = buf[pos]
        pos += 1
        field_type = header & 0x0F
        delta = header >> 4
        if field_type == 0:
            return name, has_type, pos
        if delta == 0:
            field_id, pos = _varint(buf, pos)
            field_id = _zigzag(field_id)
        else:
            field_id = last_id + delta
        last_id = field_id
        if field_id == 4 and field_type == 8:
            length, pos = _varint(buf, pos)
            name = buf[pos:pos + length].decode("utf-8", "replace")
            pos += length
            continue
        if field_id == 1 and field_type == 5:
            _, pos = _varint(buf, pos)
            has_type = True
            continue
        pos = _skip_thrift(buf, pos, field_type)
    raise ValueError("truncated schema element")


def _skip_thrift(buf: bytes, pos: int, field_type: int) -> int:
    if field_type in {1, 2}:
        return pos
    if field_type == 3:
        return pos + 1
    if field_type in {4, 5, 6}:
        _, pos = _varint(buf, pos)
        return pos
    if field_type == 7:
        return pos + 8
    if field_type == 8:
        length, pos = _varint(buf, pos)
        return pos + length
    if field_type in {9, 10}:
        return _skip_list(buf, pos)
    if field_type == 11:
        return _skip_map(buf, pos)
    if field_type == 12:
        return _skip_struct(buf, pos)
    raise ValueError(f"unknown thrift type {field_type}")


def _skip_struct(buf: bytes, pos: int) -> int:
    last_id = 0
    while pos < len(buf):
        header = buf[pos]
        pos += 1
        field_type = header & 0x0F
        if field_type == 0:
            return pos
        delta = header >> 4
        if delta == 0:
            field_id, pos = _varint(buf, pos)
            last_id = _zigzag(field_id)
        else:
            last_id = last_id + delta
        pos = _skip_thrift(buf, pos, field_type)
    raise ValueError("truncated struct")


def _skip_list(buf: bytes, pos: int) -> int:
    if pos >= len(buf):
        raise ValueError("truncated list")
    marker = buf[pos]
    pos += 1
    if marker == 0:
        return pos
    size = marker >> 4
    elem = marker & 0x0F
    if size == 15:
        size, pos = _varint(buf, pos)
    for _ in range(size):
        pos = _skip_thrift(buf, pos, elem)
    return pos


def _skip_map(buf: bytes, pos: int) -> int:
    if pos >= len(buf):
        raise ValueError("truncated map")
    marker = buf[pos]
    pos += 1
    if marker == 0:
        return pos
    size = marker >> 4
    key_type = marker & 0x0F
    if size == 15:
        size, pos = _varint(buf, pos)
    if pos >= len(buf):
        raise ValueError("truncated map")
    value_type = buf[pos]
    pos += 1
    for _ in range(size):
        pos = _skip_thrift(buf, pos, key_type)
        pos = _skip_thrift(buf, pos, value_type)
    return pos


def _varint(buf: bytes, pos: int) -> tuple[int, int]:
    shift = 0
    value = 0
    while pos < len(buf) and shift <= 70:
        byte = buf[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, pos
        shift += 7
    raise ValueError("truncated varint")


def _zigzag(value: int) -> int:
    return (value >> 1) ^ -(value & 1)


def _workspace_for(path: Path) -> Path:
    """Walk up to a directory that holds .curator or wiki, else the parent."""
    current = path.parent
    for parent in (current, *current.parents):
        if (parent / "wiki").is_dir() or (parent / ".curator").is_dir():
            return parent
    return current


if __name__ == "__main__":
    sys.exit(main())
