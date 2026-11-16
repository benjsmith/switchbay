"""Optional workspace meta-ontology.

The file is ``<workspace>/.curator/meta-ontology.yaml``. When it is
absent, callers get nothing and leave prompts, the viewer bundle, and
OKF export alone. When it is present, the same terms drive all three.

A copy of today's graph vocabulary lives at
``examples/meta-ontology.yaml`` in the Switch Bay repo. It is not
loaded on its own.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

CONFIG_REL = Path(".curator") / "meta-ontology.yaml"
_TYPE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

_TOP_KEYS = frozenset({"version", "nodes", "edges", "schema_keys"})
_NODE_KEYS = frozenset({
    "type", "label", "folder", "prefix", "color", "claims", "description",
})
_EDGE_KEYS = frozenset({"type", "label", "description"})
_SCHEMA_KEYS = frozenset({
    "key", "description", "applies_to", "values", "minimum", "maximum",
})


class MetaOntologyError(ValueError):
    """The config file is present and not usable."""


@dataclass(frozen=True)
class NodeTerm:
    type: str
    label: str
    description: str
    folder: str | None = None
    prefix: str | None = None
    color: str | None = None
    claims: bool | None = None


@dataclass(frozen=True)
class EdgeTerm:
    type: str
    label: str
    description: str


@dataclass(frozen=True)
class SchemaKey:
    key: str
    description: str
    applies_to: tuple[str, ...] = ()
    values: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None


@dataclass(frozen=True)
class MetaOntology:
    nodes: tuple[NodeTerm, ...]
    edges: tuple[EdgeTerm, ...]
    schema_keys: tuple[SchemaKey, ...]
    path: Path | None = None

    def node(self, type_name: str) -> NodeTerm | None:
        want = (type_name or "").strip().lower()
        for n in self.nodes:
            if n.type == want:
                return n
        return None

    def edge(self, type_name: str) -> EdgeTerm | None:
        want = (type_name or "").strip().lower()
        for e in self.edges:
            if e.type == want:
                return e
        return None

    def to_viewer(self) -> dict[str, Any]:
        """Payload the graph shell reads. Omitted when no file is configured."""
        return {
            "nodes": [_node_public(n) for n in self.nodes],
            "edges": [_edge_public(e) for e in self.edges],
            "schemaKeys": [_schema_public(k) for k in self.schema_keys],
        }

    def to_export(self) -> dict[str, Any]:
        """Same terms, in the YAML shape of the config file."""
        return {
            "version": 1,
            "nodes": [_node_public(n) for n in self.nodes],
            "edges": [_edge_public(e) for e in self.edges],
            "schema_keys": [
                {
                    "key": k.key,
                    "description": k.description,
                    "applies_to": list(k.applies_to),
                    "values": list(k.values),
                    **({} if k.minimum is None else {"minimum": k.minimum}),
                    **({} if k.maximum is None else {"maximum": k.maximum}),
                }
                for k in self.schema_keys
            ],
        }

    def curation_text(self) -> str:
        lines = [
            "Workspace meta-ontology. Curate each term as written here.",
        ]
        if self.nodes:
            lines.append("Node types:")
            for n in self.nodes:
                bits = [n.type]
                if n.label != n.type:
                    bits.append(f"label {n.label}")
                if n.folder:
                    bits.append(f"folder wiki/{n.folder}/")
                if n.prefix:
                    bits.append(f"title prefix [{n.prefix}]")
                lines.append(f"- {', '.join(bits)}: {_one_line(n.description)}")
        if self.edges:
            lines.append("Edge types:")
            for e in self.edges:
                shown = e.type if e.label == e.type else f"{e.type} (label {e.label})"
                lines.append(f"- {shown}: {_one_line(e.description)}")
        if self.schema_keys:
            lines.append("Frontmatter keys:")
            for k in self.schema_keys:
                extra = ""
                if k.values:
                    extra += " values " + ", ".join(k.values) + "."
                if k.minimum is not None or k.maximum is not None:
                    extra += f" range {k.minimum} to {k.maximum}."
                if k.applies_to:
                    extra += " applies to " + ", ".join(k.applies_to) + "."
                lines.append(
                    f"- {k.key}: {_one_line(k.description)}{extra}"
                )
        return "\n".join(lines)


def config_path(workspace: Path) -> Path:
    return Path(workspace) / CONFIG_REL


def load_file(path: Path) -> MetaOntology:
    """Parse one file. Raises MetaOntologyError when the file is unusable."""
    return _parse(Path(path))


def load_result(workspace: Path) -> tuple[MetaOntology | None, str | None]:
    """``(None, None)`` when the file is absent.

    A present but broken file returns ``(None, message)`` so a graph
    request can keep serving today's bundle.
    """
    path = config_path(workspace)
    try:
        st = path.stat()
    except OSError:
        _CACHE.pop(str(path), None)
        return None, None
    if not path.is_file():
        return None, None
    key = str(path)
    hit = _CACHE.get(key)
    stamp = (st.st_mtime_ns, st.st_size)
    if hit and hit[0] == stamp:
        return hit[1], hit[2]
    try:
        ont = _parse(path)
    except MetaOntologyError as exc:
        _CACHE[key] = (stamp, None, str(exc))
        return None, str(exc)
    _CACHE[key] = (stamp, ont, None)
    return ont, None


def load(workspace: Path) -> MetaOntology | None:
    """The ontology, or None when the file is absent.

    Raises MetaOntologyError when the file is present and broken.
    """
    ont, err = load_result(workspace)
    if err:
        raise MetaOntologyError(err)
    return ont


def curation_system(workspace: Path, *, cap_chars: int = 8000) -> str:
    """System text for a curate prompt. Empty when no file is configured."""
    ont, err = load_result(workspace)
    if err:
        return (
            "Workspace meta-ontology failed to load "
            f"({err}). Do not invent types until it is fixed."
        )
    if ont is None:
        return ""
    text = ont.curation_text()
    if cap_chars > 0 and len(text) > cap_chars:
        return text[:cap_chars].rstrip() + "\n…"
    return text


def apply_to_graph(data: dict[str, Any], ontology: MetaOntology) -> None:
    """Stamp labels onto a viewer bundle. Does not change ``type``."""
    data["metaOntology"] = ontology.to_viewer()
    colors = {n.type: n.color for n in ontology.nodes if n.color}
    if colors:
        palette = data.get("palette")
        if not isinstance(palette, dict):
            palette = {}
            data["palette"] = palette
        for key, color in colors.items():
            palette[key] = color
            folder = ontology.node(key)
            if folder and folder.folder:
                palette[folder.folder] = color
    by_node = {n.type: n for n in ontology.nodes}
    by_edge = {e.type: e for e in ontology.edges}

    def stamp_node(obj: Any) -> None:
        if not isinstance(obj, dict):
            return
        term = by_node.get(str(obj.get("type") or "").strip().lower())
        if term is not None:
            obj["typeLabel"] = term.label

    for node in data.get("nodes") or []:
        stamp_node(node)
    pages = data.get("pages")
    if isinstance(pages, dict):
        for page in pages.values():
            stamp_node(page)
    for edge in data.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        term = by_edge.get(str(edge.get("type") or "").strip().lower())
        if term is not None:
            edge["typeLabel"] = term.label


def apply_to_graph_if_configured(workspace: Path, data: dict[str, Any]) -> bool:
    """Apply the file when it loads. No-op (and no new keys) when absent."""
    ont, err = load_result(workspace)
    if err:
        if err not in _LOGGED_ERRORS:
            _LOGGED_ERRORS.add(err)
            log.warning("meta-ontology: %s", err)
        return False
    if ont is None:
        return False
    apply_to_graph(data, ont)
    return True


def patch_graph_json(payload: bytes, workspace: Path) -> bytes:
    """Return ``payload`` unchanged when no ontology file is configured."""
    ont, err = load_result(workspace)
    if ont is None or err:
        return payload
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return payload
    if not isinstance(data, dict):
        return payload
    apply_to_graph(data, ont)
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


_CACHE: dict[str, tuple[tuple[int, int], MetaOntology | None, str | None]] = {}
_LOGGED_ERRORS: set[str] = set()


def _parse(path: Path) -> MetaOntology:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MetaOntologyError(f"{path}: {exc}") from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise MetaOntologyError(f"{path.name}: {exc}") from exc
    if not isinstance(raw, dict):
        raise MetaOntologyError(f"{path.name}: the top level must be a mapping")
    unknown = set(raw) - _TOP_KEYS
    if unknown:
        raise MetaOntologyError(
            f"{path.name}: unknown keys {sorted(unknown)}"
        )
    if raw.get("version", 1) != 1:
        raise MetaOntologyError(f"{path.name}: version must be 1")
    nodes = tuple(_parse_nodes(raw.get("nodes") or [], path.name))
    edges = tuple(_parse_edges(raw.get("edges") or [], path.name))
    keys = tuple(_parse_schema_keys(raw.get("schema_keys") or [], path.name))
    if not nodes and not edges and not keys:
        raise MetaOntologyError(
            f"{path.name}: list at least one node, edge, or schema key"
        )
    return MetaOntology(nodes=nodes, edges=edges, schema_keys=keys, path=path)


def _parse_nodes(raw: Any, name: str) -> list[NodeTerm]:
    rows = _as_list(raw, f"{name}: nodes")
    out: list[NodeTerm] = []
    seen: set[str] = set()
    for i, row in enumerate(rows, start=1):
        item = _as_map(row, f"{name}: nodes[{i}]")
        _reject_unknown(item, _NODE_KEYS, f"{name}: nodes[{i}]")
        type_name = _ident(item.get("type"), f"{name}: nodes[{i}].type", _TYPE_RE)
        if type_name in seen:
            raise MetaOntologyError(f"{name}: duplicate node type {type_name}")
        seen.add(type_name)
        label = _text(item.get("label"), f"{name}: nodes[{i}].label", required=False)
        description = _text(
            item.get("description"), f"{name}: nodes[{i}].description", required=True,
        )
        folder = _ident(
            item.get("folder"), f"{name}: nodes[{i}].folder", _TYPE_RE, required=False,
        )
        prefix = _ident(
            item.get("prefix"), f"{name}: nodes[{i}].prefix", _TYPE_RE, required=False,
        )
        color = item.get("color")
        if color is not None:
            color = str(color).strip()
            if not _COLOR_RE.match(color):
                raise MetaOntologyError(
                    f"{name}: nodes[{i}].color must be #rrggbb"
                )
        claims = item.get("claims")
        if claims is not None and not isinstance(claims, bool):
            raise MetaOntologyError(f"{name}: nodes[{i}].claims must be true or false")
        out.append(NodeTerm(
            type=type_name,
            label=label or type_name,
            description=description or "",
            folder=folder,
            prefix=prefix,
            color=color,
            claims=claims if isinstance(claims, bool) else None,
        ))
    return out


def _parse_edges(raw: Any, name: str) -> list[EdgeTerm]:
    rows = _as_list(raw, f"{name}: edges")
    out: list[EdgeTerm] = []
    seen: set[str] = set()
    for i, row in enumerate(rows, start=1):
        item = _as_map(row, f"{name}: edges[{i}]")
        _reject_unknown(item, _EDGE_KEYS, f"{name}: edges[{i}]")
        type_name = _ident(item.get("type"), f"{name}: edges[{i}].type", _TYPE_RE)
        if type_name in seen:
            raise MetaOntologyError(f"{name}: duplicate edge type {type_name}")
        seen.add(type_name)
        label = _text(item.get("label"), f"{name}: edges[{i}].label", required=False)
        description = _text(
            item.get("description"), f"{name}: edges[{i}].description", required=True,
        )
        out.append(EdgeTerm(
            type=type_name,
            label=label or type_name,
            description=description or "",
        ))
    return out


def _parse_schema_keys(raw: Any, name: str) -> list[SchemaKey]:
    rows = _as_list(raw, f"{name}: schema_keys")
    out: list[SchemaKey] = []
    seen: set[str] = set()
    for i, row in enumerate(rows, start=1):
        item = _as_map(row, f"{name}: schema_keys[{i}]")
        _reject_unknown(item, _SCHEMA_KEYS, f"{name}: schema_keys[{i}]")
        key = _ident(item.get("key"), f"{name}: schema_keys[{i}].key", _KEY_RE)
        if key in seen:
            raise MetaOntologyError(f"{name}: duplicate schema key {key}")
        seen.add(key)
        description = _text(
            item.get("description"),
            f"{name}: schema_keys[{i}].description",
            required=True,
        )
        applies = tuple(
            part.lower()
            for part in _str_list(
                item.get("applies_to"), f"{name}: schema_keys[{i}].applies_to",
            )
        )
        values = tuple(_str_list(
            item.get("values"), f"{name}: schema_keys[{i}].values",
        ))
        minimum = _number(item.get("minimum"), f"{name}: schema_keys[{i}].minimum")
        maximum = _number(item.get("maximum"), f"{name}: schema_keys[{i}].maximum")
        out.append(SchemaKey(
            key=key,
            description=description or "",
            applies_to=applies,
            values=values,
            minimum=minimum,
            maximum=maximum,
        ))
    return out


def _as_list(raw: Any, where: str) -> list[Any]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise MetaOntologyError(f"{where} must be a list")
    return raw


def _as_map(raw: Any, where: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise MetaOntologyError(f"{where} must be a mapping")
    return raw


def _reject_unknown(item: dict[str, Any], allowed: frozenset[str], where: str) -> None:
    unknown = set(item) - allowed
    if unknown:
        raise MetaOntologyError(f"{where}: unknown keys {sorted(unknown)}")


def _ident(
    raw: Any, where: str, pattern: re.Pattern[str], *, required: bool = True,
) -> str | None:
    if raw is None or raw == "":
        if required:
            raise MetaOntologyError(f"{where} is required")
        return None
    text = str(raw).strip().lower()
    if not pattern.match(text):
        raise MetaOntologyError(f"{where} must match {pattern.pattern}")
    return text


def _text(raw: Any, where: str, *, required: bool) -> str | None:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        if required:
            raise MetaOntologyError(f"{where} is required")
        return None
    if not isinstance(raw, str):
        raise MetaOntologyError(f"{where} must be a string")
    return raw.strip()


def _str_list(raw: Any, where: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(x, str) and x.strip() for x in raw):
        raise MetaOntologyError(f"{where} must be a list of strings")
    return [x.strip() for x in raw]


def _number(raw: Any, where: str) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise MetaOntologyError(f"{where} must be a number")
    return float(raw)


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _node_public(n: NodeTerm) -> dict[str, Any]:
    out: dict[str, Any] = {
        "type": n.type,
        "label": n.label,
        "description": n.description,
    }
    if n.folder:
        out["folder"] = n.folder
    if n.prefix:
        out["prefix"] = n.prefix
    if n.color:
        out["color"] = n.color
    if n.claims is not None:
        out["claims"] = n.claims
    return out


def _edge_public(e: EdgeTerm) -> dict[str, Any]:
    return {"type": e.type, "label": e.label, "description": e.description}


def _schema_public(k: SchemaKey) -> dict[str, Any]:
    out: dict[str, Any] = {
        "key": k.key,
        "description": k.description,
        "appliesTo": list(k.applies_to),
        "values": list(k.values),
    }
    if k.minimum is not None:
        out["minimum"] = k.minimum
    if k.maximum is not None:
        out["maximum"] = k.maximum
    return out
