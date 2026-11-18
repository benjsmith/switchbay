"""Apply the workspace meta-ontology to a Curiosity Engine OKF export.

CE ``okf_export.py`` stays the exporter. This module runs after it,
and only when ``.curator/meta-ontology.yaml`` is present. Concept
``type`` is left as CE wrote it (that is what round-trips). The
configured label and curation text are added as ``x_ce_type_label``
and ``x_ce_type_description``. The same terms are written to
``x_ce_ontology.yaml`` in the export directory.

With no config file, ``finalize_after_ce`` returns without reading
or writing the export.

Figure and table pages are labelled even when the workspace file
does not list those types. A type the file does define keeps the
file's text. ``extracted-table`` uses the table term.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from . import meta_ontology
from .meta_ontology import MetaOntology

_OUT_FLAGS = frozenset({"--out", "--output", "-o", "--dest", "--dir"})
_RESULT_KEYS = ("out", "output", "path", "dest", "directory")
_SKIP_NAMES = frozenset({"index.md", "log.md"})
_FM_KEY_RE = re.compile(r"^([A-Za-z0-9_]+)\s*:(.*)$")
_TYPE_ALIAS = {
    "extracted-table": "table",
    "extracted_table": "table",
}


def finalize_after_ce(
    workspace: Path,
    args: list[str] | None,
    result: dict[str, Any] | None,
) -> None:
    """Annotate an export directory. No-op when the ontology file is absent."""
    ont, err = meta_ontology.load_result(workspace)
    if err or ont is None:
        return
    dest = export_dir(args, result)
    if dest is None or not dest.is_dir():
        return
    count = apply_to_export_tree(dest, ont)
    if isinstance(result, dict):
        result["meta_ontology"] = {
            "concepts": count,
            "sidecar": "x_ce_ontology.yaml",
        }


def export_dir(args: list[str] | None, result: Any) -> Path | None:
    """Output directory named by the CE invocation, if we can see one."""
    argv = [str(a) for a in (args or [])]
    for i, arg in enumerate(argv):
        if arg in _OUT_FLAGS and i + 1 < len(argv):
            return Path(argv[i + 1]).expanduser()
        for flag in ("--out", "--output", "--dest", "--dir"):
            prefix = flag + "="
            if arg.startswith(prefix) and arg[len(prefix):].strip():
                return Path(arg.split("=", 1)[1]).expanduser()
    if isinstance(result, dict):
        for key in _RESULT_KEYS:
            val = result.get(key)
            if isinstance(val, str) and val.strip():
                path = Path(val).expanduser()
                if path.is_dir():
                    return path
    return None


def apply_to_export_tree(root: Path, ontology: MetaOntology) -> int:
    """Rewrite concept frontmatter in ``root`` and write the sidecar.

    Returns how many concept files gained a type label.
    """
    ontology = meta_ontology.for_export(ontology)
    count = 0
    for path in sorted(root.rglob("*.md")):
        if path.name in _SKIP_NAMES:
            continue
        try:
            original = path.read_text(encoding="utf-8")
        except OSError:
            continue
        updated = annotate_concept(original, ontology)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            count += 1
    sidecar = root / "x_ce_ontology.yaml"
    sidecar.write_text(
        yaml.safe_dump(
            ontology.to_export(), sort_keys=False, allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return count


def annotate_concept(text: str, ontology: MetaOntology) -> str:
    """Add x_ce type fields when the concept type is in the ontology."""
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    if end < 0:
        return text
    head = text[4:end]
    body = text[end + 5:]
    type_name = _frontmatter_type(head)
    if not type_name:
        return text
    node = ontology.node(type_name)
    if node is None:
        node = ontology.node(_TYPE_ALIAS.get(type_name, ""))
    if node is None:
        return text
    lines = head.splitlines()
    lines = _set_key(lines, "x_ce_type_label", node.label)
    lines = _set_key(lines, "x_ce_type_description", _one_line(node.description))
    new_head = "\n".join(lines)
    return f"---\n{new_head}\n---\n{body}"


def _frontmatter_type(head: str) -> str:
    for raw in head.splitlines():
        match = _FM_KEY_RE.match(raw)
        if not match or match.group(1) != "type":
            continue
        return match.group(2).strip().strip("'\"").lower()
    return ""


def _set_key(lines: list[str], key: str, value: str) -> list[str]:
    rendered = f"{key}: {_yaml_scalar(value)}"
    for i, raw in enumerate(lines):
        match = _FM_KEY_RE.match(raw)
        if match and match.group(1) == key:
            lines[i] = rendered
            return lines
    lines.append(rendered)
    return lines


def _yaml_scalar(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _./#-]*", value) and ":" not in value:
        return value
    return json.dumps(value, ensure_ascii=False)


def _one_line(text: str) -> str:
    return " ".join(text.split())
