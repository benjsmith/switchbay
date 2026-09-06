"""Pre-ingest staging so curiosity-engine indexes usable text.

CE ``local_ingest.py`` copy-mode wants a *directory* (a bare file path
errors ``not a directory``). It UTF-8-decodes HTML/JSON/text and caps
the extract at 200 KiB from the *start* of the file. That cap is a CE
index-cost bound; we do not change CE.

Large HTML/XML/JSON often spends that prefix on schema, hidden XBRL
blocks, or a huge leading array (SEC iXBRL, publisher HTML, JATS/NXML,
GEO/API dumps). Staging writes visible/readable text so the prefix CE
indexes is content. Originals stay put.

This is not an iXBRL (or JATS) fact extractor — a future CE upgrade
can replace the conversion. Domain-agnostic: papers, dumps, filings.
"""

from __future__ import annotations

import csv
import hashlib
import html.parser
import json
import os
import re
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from typing import Any

# Stay under CE DEFAULT_MAX_EXTRACT_BYTES (200 KiB) after our header.
MAX_READABLE_BYTES = 180 * 1024
# Investigator/verifier prompt budget — smaller than the ingest cap.
MAX_READ_SOURCE_CHARS = 48_000
MAX_SOURCE_BYTES = 40 * 1024 * 1024
CE_DEFAULT_EXTS = {
    ".md", ".txt", ".rst", ".html", ".htm", ".json", ".yaml", ".yml",
    ".org", ".pdf", ".csv", ".xlsx", ".pptx",
}
MARKUP_EXTS = {".html", ".htm", ".xhtml", ".xml", ".xbrl", ".nxml", ".sgml"}
JSON_EXTS = {".json", ".jsonl"}
CSV_EXTS = {".csv"}
STAGE_REL = ".orchestrator/cache/ingest-stage"

_PRIORITY_HEADING = re.compile(
    r"\b("
    r"abstract|synopsis|highlights|summary|"
    r"introduction|background|"
    r"methods?|materials and methods|experimental|"
    r"results?|findings|"
    r"discussion|conclusion|conclusions|"
    r"references|bibliography|"
    r"financial statements?|consolidated statements?|"
    r"management.?s discussion|md&a|"
    r"risk factors|"
    r"data availability|supplementary|appendix|"
    r"acknowledg"
    r")\b",
    re.I,
)
_NOISE_LINE = re.compile(
    r"xmlns:|http://www\.w3\.org/2001/XMLSchema|http://www\.xbrl\.org/"
    r"|http://xbrl\.sec\.gov/|iso4217:|:xsd:",
    re.I,
)
_XML_INLINE = {
    "p", "div", "span", "body", "html", "td", "th", "tr", "table",
    "sec", "text", "paragraph", "title-group", "front", "article",
    "back", "caption", "label", "italic", "bold", "underline",
    "ext-link", "xref", "named-content", "section", "head", "floats-wrap",
    "contrib-group", "contrib", "name", "xml",
}


def _within(root: Path, candidate: Path) -> bool:
    try:
        root = root.resolve()
        candidate = candidate.resolve()
    except (OSError, ValueError):
        return False
    return candidate == root or root in candidate.parents


def resolve_workspace_path(workspace: Path, raw: str) -> Path | None:
    """Resolve ``raw`` under ``workspace``. None if missing or escape."""
    if not raw or "\x00" in raw:
        return None
    ws = Path(workspace).resolve()
    p = Path(raw)
    if not p.is_absolute():
        p = ws / raw
    try:
        resolved = p.resolve()
    except (OSError, ValueError):
        return None
    if not _within(ws, resolved):
        return None
    return resolved


def rel_to_workspace(workspace: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(Path(workspace).resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _clip_text(text: str, max_bytes: int) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    cut = raw[:max_bytes].decode("utf-8", errors="ignore")
    return cut.rsplit("\n", 1)[0] if "\n" in cut else cut


def _ws(s: str) -> str:
    return re.sub(r"[ \t]+", " ", s).strip()


def _is_noise(text: str) -> bool:
    s = text.strip()
    if not s:
        return True
    if _NOISE_LINE.search(s) and len(s) < 400:
        return True
    if s.lower().startswith("xmlns"):
        return True
    return False


class _VisibleHTML(html.parser.HTMLParser):
    _SKIP = {
        "script", "style", "noscript", "template",
        "ix:header", "ix:hidden", "ix:references", "ix:resources",
        "xbrli:context", "xbrli:unit",
    }
    _BLOCK = {
        "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
        "section", "article", "blockquote", "pre",
    }
    _HEADING = {"h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self, *, skip_hidden: bool = True) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_hidden = skip_hidden
        self.skip = 0
        self.parts: list[tuple[str, str]] = []
        self._buf: list[str] = []
        self._row: list[str] = []
        self._in_td = False
        self._td_buf: list[str] = []
        self._title: list[str] = []
        self._in_title = False

    def _local(self, tag: str) -> str:
        return tag.lower().strip()

    def _should_skip(self, tag: str, attrs: list[tuple[str, str | None]]) -> bool:
        t = self._local(tag)
        if t in self._SKIP or t.endswith(":header") or t.endswith(":hidden"):
            return True
        if t.endswith(":references") or t.endswith(":resources"):
            return True
        if not self.skip_hidden:
            return False
        ad = {k.lower(): (v or "") for k, v in attrs}
        if "hidden" in ad or ad.get("aria-hidden") == "true":
            return True
        style = ad.get("style", "").lower().replace(" ", "")
        if "display:none" in style or "visibility:hidden" in style:
            return True
        return False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = self._local(tag)
        if self.skip:
            self.skip += 1
            return
        if self._should_skip(tag, attrs):
            self.skip = 1
            return
        if t == "title":
            self._in_title = True
            return
        if t == "br":
            self._buf.append("\n")
            return
        if t in self._HEADING:
            self._flush_p()
            return
        if t in ("td", "th"):
            self._in_td = True
            self._td_buf = []
            return
        if t == "tr":
            self._row = []

    def handle_endtag(self, tag: str) -> None:
        t = self._local(tag)
        if self.skip:
            self.skip = max(0, self.skip - 1)
            return
        if t == "title":
            self._in_title = False
            return
        if t in self._HEADING:
            text = _ws("".join(self._buf))
            self._buf.clear()
            if text and not _is_noise(text):
                self.parts.append(("heading", text))
            return
        if t in ("td", "th"):
            self._in_td = False
            self._row.append(_ws("".join(self._td_buf)))
            self._td_buf = []
            return
        if t == "tr":
            if any(self._row):
                self.parts.append(("table", "| " + " | ".join(self._row) + " |"))
            self._row = []
            return
        if t in self._BLOCK:
            self._flush_p()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.skip:
            return
        if self._local(tag) == "br":
            self._buf.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        if self._in_title:
            self._title.append(data)
            return
        if self._in_td:
            self._td_buf.append(data)
            return
        self._buf.append(data)

    def _flush_p(self) -> None:
        text = _ws("".join(self._buf))
        self._buf.clear()
        if text and not _is_noise(text):
            self.parts.append(("p", text))

    def finish(self) -> tuple[str, list[tuple[str, str]]]:
        self._flush_p()
        title = _ws("".join(self._title))
        return title, self.parts


def _pack_sections(sections: list[tuple[str, str]], max_bytes: int) -> str:
    if not sections:
        return ""
    if len(sections) == 1:
        h, b = sections[0]
        body = f"## {h}\n{b}" if h else b
        return _clip_text(body, max_bytes)
    outline_items = [h for h, _ in sections if h]
    outline = "\n".join(f"- {h}" for h in outline_items)
    include_outline = len(outline_items) > 3
    overhead = (len(outline.encode("utf-8")) + 40) if include_outline else 0
    budget = max(1024, max_bytes - overhead)
    scores: list[float] = []
    for i, (h, b) in enumerate(sections):
        s = 0.0
        if i == 0:
            s += 8.0
        if h and _PRIORITY_HEADING.search(h):
            s += 6.0
        s += min(3.0, len(b) / 8000)
        scores.append(s)
    order = sorted(range(len(sections)), key=lambda i: -scores[i])
    def _priority(i: int, h: str) -> bool:
        return i == 0 or bool(h and _PRIORITY_HEADING.search(h))

    allot = [0] * len(sections)
    used = 0
    for i in order:
        h, b = sections[i]
        need_min = 200 if _priority(i, h) else 80
        avail = budget - used
        if avail < need_min and used > 0:
            continue
        take = min(len(b.encode("utf-8")), max(0, avail))
        if take <= 0:
            continue
        allot[i] = take
        used += take + len((h or "").encode("utf-8")) + 8
    parts: list[str] = []
    remaining = max_bytes
    if include_outline:
        block = _clip_text("## Document outline\n" + outline, max(256, remaining // 5))
        parts.append(block)
        remaining -= len(block.encode("utf-8"))
    for want_priority in (True, False):
        for i, (h, b) in enumerate(sections):
            if allot[i] <= 0:
                continue
            if _priority(i, h) != want_priority:
                continue
            block = f"## {h}\n{b}" if h else b
            take = _clip_text(block, min(allot[i] + 80, remaining))
            if not take.strip():
                continue
            parts.append(take)
            remaining -= len(take.encode("utf-8"))
            if remaining < 256:
                break
        if remaining < 256:
            break
    return _clip_text("\n\n".join(parts), max_bytes)


def readable_html(raw: bytes, max_bytes: int = MAX_READABLE_BYTES) -> str:
    def _run(*, skip_hidden: bool) -> tuple[str, list[tuple[str, str]]]:
        parser = _VisibleHTML(skip_hidden=skip_hidden)
        try:
            parser.feed(raw.decode("utf-8", errors="replace"))
            parser.close()
        except Exception:  # noqa: BLE001
            pass
        return parser.finish()

    title, parts = _run(skip_hidden=True)
    body_len = sum(len(t) for _, t in parts)
    if body_len < 200 and len(raw) > 5000:
        title, parts = _run(skip_hidden=False)
    sections: list[tuple[str, list[str]]] = []
    cur_h = title
    cur_b: list[str] = []
    for kind, text in parts:
        if kind == "heading":
            if cur_b or cur_h:
                sections.append((cur_h, cur_b))
            cur_h = text
            cur_b = []
        else:
            cur_b.append(text)
    if cur_b or cur_h:
        sections.append((cur_h, cur_b))
    packed = [(h, "\n".join(b).strip()) for h, b in sections]
    return _pack_sections(packed, max_bytes)


def readable_xml(raw: bytes, max_bytes: int = MAX_READABLE_BYTES) -> str:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return readable_html(raw, max_bytes)
    parts: list[str] = []

    def walk(el: ET.Element) -> None:
        local = el.tag.split("}")[-1].split(":")[-1]
        text = (el.text or "").strip()
        kids = list(el)
        if not kids and text:
            if local.lower() in _XML_INLINE or len(local) <= 1:
                parts.append(text)
            else:
                parts.append(f"{local}: {text}")
        else:
            if text and not _is_noise(text):
                if local.lower() not in _XML_INLINE:
                    parts.append(f"{local}: {text}")
                else:
                    parts.append(text)
            for child in kids:
                walk(child)
        tail = (el.tail or "").strip()
        if tail and not _is_noise(tail):
            parts.append(tail)

    walk(root)
    return _clip_text("\n".join(p for p in parts if p), max_bytes)


def _shrink_json(obj: Any, *, max_list: int = 20, max_tail: int = 8) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for i, (k, v) in enumerate(obj.items()):
            if i >= 80:
                out["_omitted_keys"] = len(obj) - 80
                break
            out[str(k)] = _shrink_json(v, max_list=max_list, max_tail=max_tail)
        return out
    if isinstance(obj, list):
        n = len(obj)
        if n <= max_list + max_tail:
            return [
                _shrink_json(x, max_list=max_list, max_tail=max_tail) for x in obj
            ]
        head = [_shrink_json(x, max_list=8, max_tail=2) for x in obj[:max_list]]
        tail = [_shrink_json(x, max_list=8, max_tail=2) for x in obj[-max_tail:]]
        marker = {
            "_omitted": n - max_list - max_tail,
            "_note": "middle of array omitted",
        }
        return head + [marker] + tail
    if isinstance(obj, str) and len(obj) > 4000:
        return obj[:4000] + "…"
    return obj


def readable_json(raw: bytes, max_bytes: int = MAX_READABLE_BYTES) -> str:
    text = raw.decode("utf-8", errors="replace")
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        if raw[:1] in (b"{", b"[") or b"\n{" in raw[:4000]:
            # jsonl: keep first/last lines
            lines = text.splitlines()
            if len(lines) > 40:
                keep = (
                    lines[:20]
                    + [json.dumps({"_omitted_lines": len(lines) - 30})]
                    + lines[-10:]
                )
                text = "\n".join(keep)
        return _clip_text(text, max_bytes)
    dumped = json.dumps(
        _shrink_json(obj), indent=2, ensure_ascii=False, default=str,
    )
    return _clip_text(dumped, max_bytes)


def readable_csv(raw: bytes, max_bytes: int = MAX_READABLE_BYTES) -> str:
    text = raw.decode("utf-8", errors="replace")
    if len(text.encode("utf-8")) <= max_bytes:
        return text
    try:
        rows = list(csv.reader(StringIO(text)))
    except csv.Error:
        return _clip_text(text, max_bytes)
    if not rows:
        return ""
    header, body = rows[0], rows[1:]
    head_n, tail_n = 80, 20
    if len(body) <= head_n + tail_n:
        chosen = body
        note = ""
    else:
        omitted = len(body) - head_n - tail_n
        chosen = (
            body[:head_n]
            + [[f"... {omitted} rows omitted ..."]]
            + body[-tail_n:]
        )
        note = f"# csv sampled {head_n}+{tail_n} of {len(body)} data rows\n"
    buf = StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(chosen)
    return _clip_text(note + buf.getvalue(), max_bytes)


def convert_bytes(data: bytes, suffix: str, max_bytes: int = MAX_READABLE_BYTES) -> tuple[str, str]:
    """Return (text, conversion_kind)."""
    ext = suffix.lower()
    if ext in {".html", ".htm", ".xhtml"}:
        return readable_html(data, max_bytes), "html-visible"
    if ext in {".xml", ".xbrl", ".nxml", ".sgml"}:
        return readable_xml(data, max_bytes), "xml-text"
    if ext == ".json":
        return readable_json(data, max_bytes), "json-compact"
    if ext == ".jsonl":
        return readable_json(data, max_bytes), "jsonl-sample"
    if ext == ".csv":
        return readable_csv(data, max_bytes), "csv-sample"
    try:
        return _clip_text(data.decode("utf-8", errors="replace"), max_bytes), "utf8"
    except Exception:  # noqa: BLE001
        return "", "empty"


def needs_conversion(path: Path, size: int | None = None) -> bool:
    ext = path.suffix.lower()
    if ext in MARKUP_EXTS:
        return True
    n = size if size is not None else (path.stat().st_size if path.is_file() else 0)
    if ext in JSON_EXTS and n > MAX_READABLE_BYTES:
        return True
    if ext in CSV_EXTS and n > MAX_READABLE_BYTES:
        return True
    if ext not in CE_DEFAULT_EXTS and ext in JSON_EXTS | MARKUP_EXTS | CSV_EXTS:
        return True
    return False


def _safe_stem(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-")
    return (s or "doc")[:80]


def _read_capped(path: Path) -> bytes:
    n = min(path.stat().st_size, MAX_SOURCE_BYTES)
    with path.open("rb") as f:
        return f.read(n)


def _header(original_rel: str, kind: str) -> str:
    return (
        "# switchbay-readable\n"
        f"# original: {original_rel}\n"
        f"# conversion: {kind}\n"
        "# Original file is unchanged. This is the indexed body.\n\n"
    )


def readable_for_path(
    workspace: Path,
    path: Path,
    *,
    max_bytes: int = MAX_READABLE_BYTES,
) -> dict[str, Any]:
    """Convert one file to readable text (no staging). Path must exist."""
    rel = rel_to_workspace(workspace, path)
    if not path.is_file():
        return {"error": f"not a file: {rel}"}
    ext = path.suffix.lower()
    data = _read_capped(path)
    if needs_conversion(path, len(data)):
        text, kind = convert_bytes(data, ext, max_bytes)
    else:
        if ext in {".pdf", ".xlsx", ".pptx"} or b"\x00" in data[:1024]:
            return {
                "error": "binary file; ingest with ce_ingest rather than read_source",
                "path": rel,
            }
        text, kind = convert_bytes(data, ext, max_bytes)
    truncated = path.stat().st_size > MAX_SOURCE_BYTES or len(
        text.encode("utf-8"),
    ) >= max_bytes
    return {
        "path": rel,
        "content": text,
        "conversion": kind,
        "truncated": truncated,
        "bytes": path.stat().st_size,
    }


def _iter_source_files(root: Path, *, limit: int = 500) -> list[Path]:
    if root.is_file():
        return [root]
    out: list[Path] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.is_symlink():
            continue
        if p.name.startswith("."):
            continue
        if p.name.endswith(".extracted.md"):
            continue
        parts = set(p.parts)
        if "__pycache__" in parts or "node_modules" in parts:
            continue
        if "ingest-stage" in p.parts:
            continue
        out.append(p)
        if len(out) >= limit:
            break
    return out


def _stage_id(workspace: Path, source: Path) -> str:
    rel = rel_to_workspace(workspace, source)
    digest = hashlib.sha256(rel.encode("utf-8")).hexdigest()[:12]
    return f"{_safe_stem(source.stem)}-{digest}"


def _place_copy(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return
    try:
        os.link(src, dest)
    except OSError:
        shutil.copy2(src, dest)


def _unique_name(used: set[str], path: Path, suffix: str) -> str:
    base = f"{_safe_stem(path.stem)}{suffix}"
    if base not in used:
        used.add(base)
        return base
    parent = _safe_stem(path.parent.name)
    base = f"{parent}-{_safe_stem(path.stem)}{suffix}"
    n = 2
    name = base
    while name in used:
        name = f"{_safe_stem(path.stem)}-{n}{suffix}"
        n += 1
    used.add(name)
    return name


@dataclass
class IngestPrep:
    ce_args: list[str] = field(default_factory=list)
    original: str | None = None
    staged: bool = False
    converted: list[dict[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    error: str | None = None

    def as_meta(self) -> dict[str, Any]:
        return {
            "staged": self.staged,
            "original": self.original,
            "converted": self.converted,
            "notes": self.notes,
            "ce_args": list(self.ce_args),
        }


def _dir_needs_stage(files: list[Path]) -> bool:
    for p in files:
        if needs_conversion(p):
            return True
        if p.suffix.lower() not in CE_DEFAULT_EXTS:
            # XML etc. would be skipped by CE's default extension filter.
            if p.suffix.lower() in MARKUP_EXTS | JSON_EXTS | CSV_EXTS:
                return True
    return False


def prepare(workspace: Path, path: str) -> IngestPrep:
    """Build CE ``local_ingest.py`` args for a workspace file or directory.

    Empty ``path`` uses ``vault/raw/`` (drop-folder) unless those files
    need conversion, in which case we stage and copy-ingest instead of
    moving the originals.
    """
    ws = Path(workspace).resolve()
    raw = (path or "").strip()
    if raw in {".", str(ws)}:
        return IngestPrep(error="pass a file or subdirectory, not the workspace root")

    if not raw:
        drop = ws / "vault" / "raw"
        if drop.is_dir():
            files = _iter_source_files(drop)
            if files and _dir_needs_stage(files):
                return _stage_sources(ws, drop, files, original_rel="vault/raw")
        return IngestPrep(notes=["drop-folder vault/raw/"])

    resolved = resolve_workspace_path(ws, raw)
    if resolved is None:
        return IngestPrep(error=f"path escapes workspace or is invalid: {raw}")
    if not resolved.exists():
        return IngestPrep(error=f"not found: {rel_to_workspace(ws, resolved)}")
    if resolved == ws:
        return IngestPrep(error="pass a file or subdirectory, not the workspace root")

    orig_rel = rel_to_workspace(ws, resolved)
    if resolved.is_file():
        if needs_conversion(resolved) or resolved.suffix.lower() not in CE_DEFAULT_EXTS:
            staged = _stage_sources(ws, resolved, [resolved], original_rel=orig_rel)
            if staged.error:
                return staged
            if len(staged.converted) == 1:
                out_rel = staged.converted[0]["staged"]
                staged.ce_args = ["--file", out_rel]
            return staged
        return IngestPrep(
            ce_args=["--file", orig_rel],
            original=orig_rel,
            notes=["single file; CE --file"],
        )

    files = _iter_source_files(resolved)
    if not files:
        return IngestPrep(
            ce_args=[orig_rel],
            original=orig_rel,
            notes=["directory empty or no ingestible files"],
        )
    if not _dir_needs_stage(files):
        return IngestPrep(
            ce_args=[orig_rel],
            original=orig_rel,
            notes=["directory passed through; no readable conversion needed"],
        )
    return _stage_sources(ws, resolved, files, original_rel=orig_rel)


def _stage_sources(
    ws: Path,
    source: Path,
    files: list[Path],
    *,
    original_rel: str,
) -> IngestPrep:
    sid = _stage_id(ws, source)
    stage_root = ws / STAGE_REL
    dest_dir = stage_root / sid
    dest_dir.mkdir(parents=True, exist_ok=True)
    used: set[str] = set()
    converted: list[dict[str, str]] = []
    notes: list[str] = []
    for src in files:
        rel = rel_to_workspace(ws, src)
        try:
            size = src.stat().st_size
        except OSError as e:
            notes.append(f"skip {rel}: {e}")
            continue
        if needs_conversion(src, size):
            data = _read_capped(src)
            text, kind = convert_bytes(data, src.suffix, MAX_READABLE_BYTES)
            if len(text.strip()) < 40 and size > 5000 and src.suffix.lower() in MARKUP_EXTS:
                text, kind = convert_bytes(data, ".html", MAX_READABLE_BYTES)
            name = _unique_name(used, src, ".txt")
            out = dest_dir / name
            out.write_text(_header(rel, kind) + text, encoding="utf-8")
            converted.append({
                "original": rel, "staged": f"{STAGE_REL}/{sid}/{name}",
                "kind": kind,
            })
            continue
        ext = src.suffix.lower()
        if ext not in CE_DEFAULT_EXTS:
            notes.append(f"skip {rel}: extension {ext} not ingestible")
            continue
        name = _unique_name(used, src, ext or ".bin")
        _place_copy(src, dest_dir / name)
        converted.append({
            "original": rel, "staged": f"{STAGE_REL}/{sid}/{name}",
            "kind": "copy",
        })
    if not converted:
        return IngestPrep(
            error="no ingestible files after staging",
            original=original_rel,
            notes=notes,
        )
    stage_rel = f"{STAGE_REL}/{sid}"
    notes.append(
        "CE indexes staged readable text (visible HTML/XML, compacted "
        "JSON/CSV). Originals are unchanged. A tagged-fact extractor "
        "(e.g. iXBRL) is a future CE upgrade, not this staging step."
    )
    ce_args = [stage_rel]
    if source.is_file() and len(converted) == 1:
        ce_args = ["--file", converted[0]["staged"]]
    return IngestPrep(
        ce_args=ce_args,
        original=original_rel,
        staged=True,
        converted=converted,
        notes=notes,
    )


def read_source(workspace: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Tool handler: read a workspace source as readable text."""
    raw = str(payload.get("path") or payload.get("source_path") or "").strip()
    if not raw:
        return {"error": "path is required"}
    resolved = resolve_workspace_path(workspace, raw)
    if resolved is None:
        return {"error": f"path escapes workspace or is invalid: {raw}"}
    if not resolved.exists():
        return {"error": f"not found: {raw}"}
    if resolved.is_dir():
        return {"error": "path is a directory; pass a file"}
    result = readable_for_path(
        workspace, resolved, max_bytes=MAX_READABLE_BYTES,
    )
    if result.get("error"):
        return result
    content = str(result.get("content") or "")
    truncated = bool(result.get("truncated"))
    if len(content) > MAX_READ_SOURCE_CHARS:
        content = content[:MAX_READ_SOURCE_CHARS]
        truncated = True
    result["content"] = content
    result["truncated"] = truncated
    return result


_PDF_BODY_RE = re.compile(
    r"%PDF-\d|FlateDecode|/Filter\s*/FlateDecode",
    re.I,
)
_DOUBLED_STEM_RE = re.compile(
    r"^([a-z][a-z0-9]*)-(\d{4})-\1-\2-(.+)$",
)


def extracted_body_is_raw_pdf(text: str) -> bool:
    """True when an ``.extracted.md`` body is truncated PDF bytes, not prose.

    Historic ``local_ingest`` UTF-8-decoded PDFs and capped them at 40 KiB.
    Current CE writes a pypdf placeholder on failure; this still catches
    leftover vault files and an agent Write of a fetched PDF.
    """
    body = text or ""
    if body.startswith("---"):
        rest = body[3:]
        end = rest.find("\n---")
        if end >= 0:
            body = rest[end + 4:]
    marker = "<!-- BEGIN FETCHED CONTENT"
    i = body.find(marker)
    if i >= 0:
        body = body[i:]
        nl = body.find("\n")
        if nl >= 0:
            body = body[nl + 1:]
    head = body.lstrip()[:800]
    return bool(_PDF_BODY_RE.search(head))


def dedupe_citation_stem(stem: str) -> str:
    """``waleffe-2024-waleffe-2024-topic`` → ``waleffe-2024-topic``.

    CE ``citation_stem`` prepends author-year onto a filename topic that
    already starts with author-year (common for arXiv drops).
    """
    s = (stem or "").strip()
    m = _DOUBLED_STEM_RE.match(s)
    if not m:
        return s
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def flag_raw_pdf_extractions(workspace: Path, ingest_out: dict[str, Any]) -> list[str]:
    """Return vault-relative extracted.md paths whose body is raw PDF."""
    ws = Path(workspace)
    hits: list[str] = []
    rows = ingest_out.get("results")
    paths: list[str] = []
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                p = str(row.get("extracted") or row.get("extracted_path") or "")
                if p:
                    paths.append(p)
    for key in ("extracted", "extracted_path"):
        p = str(ingest_out.get(key) or "")
        if p:
            paths.append(p)
    for raw in paths:
        cand = Path(raw)
        if not cand.is_absolute():
            cand = ws / raw
        try:
            cand = cand.resolve()
        except OSError:
            continue
        if not str(cand).startswith(str(ws.resolve())):
            continue
        if not cand.name.endswith(".extracted.md") or not cand.is_file():
            continue
        try:
            text = cand.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if extracted_body_is_raw_pdf(text):
            try:
                rel = str(cand.relative_to(ws))
            except ValueError:
                rel = str(cand)
            hits.append(rel)
    return hits
