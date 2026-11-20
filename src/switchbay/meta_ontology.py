"""Optional workspace meta-ontology.

The file is ``<workspace>/.curator/meta-ontology.yaml``. When it is
absent, callers get nothing and leave prompts, the viewer bundle, and
OKF export alone. When it is present, the same terms drive all three.

A copy of today's graph vocabulary lives at
``examples/meta-ontology.yaml`` in the Switch Bay repo. It is not
loaded on its own.

An edge may name the node types it runs between. Those typed edges
are optional. A file that omits them, and a workspace with no file,
keep the previous behaviour. When they are set, curate prompts
include the endpoints, the viewer draws the edges from wiki
frontmatter, and OKF export records them.
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
_EDGE_KEYS = frozenset({
    "type", "label", "description", "source", "target", "color",
})
# Distinct strokes for typed edges that do not set their own colour.
_EDGE_COLORS = ("#0072b2", "#d55e00", "#cc79a7", "#009e73", "#e69f00", "#56b4e9")
_SKIP_DIR_PARTS = frozenset({"_assets", "_archive", ".git"})
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
    source: tuple[str, ...] = ()
    target: tuple[str, ...] = ()
    color: str | None = None

    @property
    def typed(self) -> bool:
        """True when both ends name node types. Those edges are checked."""
        return bool(self.source and self.target)


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

    def edge_color(self, type_name: str) -> str | None:
        """Stroke for a typed edge. Explicit colour wins; otherwise a stable fallback."""
        typed_i = 0
        want = (type_name or "").strip().lower()
        for edge in self.edges:
            if not edge.typed:
                continue
            if edge.type == want:
                if edge.color:
                    return edge.color
                return _EDGE_COLORS[typed_i % len(_EDGE_COLORS)]
            typed_i += 1
        term = self.edge(want)
        return term.color if term is not None else None

    def to_viewer(self) -> dict[str, Any]:
        """Payload the graph shell reads. Omitted when no file is configured."""
        return {
            "nodes": [_node_public(n) for n in self.nodes],
            "edges": [_edge_viewer(self, e) for e in self.edges],
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
                if e.typed:
                    ends = (
                        f"{', '.join(e.source)} → {', '.join(e.target)}"
                    )
                    lines.append(
                        f"- {shown}, {ends}: On the source page, wikilink "
                        f"the target and list it under {e.type}. "
                        f"{_one_line(e.description)}"
                    )
                else:
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


def apply_to_graph(
    data: dict[str, Any],
    ontology: MetaOntology,
    workspace: Path | None = None,
) -> None:
    """Stamp labels onto a viewer bundle.

    Node ``type`` stays as the bundle has it, except a type this
    ontology names is restored from the wiki file when the viewer
    had bucketed the page as unclassified. Typed edges listed in
    frontmatter are added to ``edges``.
    """
    if workspace is not None:
        _apply_workspace_graph(data, ontology, Path(workspace))
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
    apply_to_graph(data, ont, workspace)
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
    apply_to_graph(data, ont, workspace)
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
        source = _type_names(
            item.get("source"), f"{name}: edges[{i}].source", present="source" in item,
        )
        target = _type_names(
            item.get("target"), f"{name}: edges[{i}].target", present="target" in item,
        )
        if (source is None) != (target is None):
            raise MetaOntologyError(
                f"{name}: edges[{i}] source and target are set together"
            )
        color = item.get("color")
        if color is not None:
            color = str(color).strip()
            if not _COLOR_RE.match(color):
                raise MetaOntologyError(
                    f"{name}: edges[{i}].color must be #rrggbb"
                )
        out.append(EdgeTerm(
            type=type_name,
            label=label or type_name,
            description=description or "",
            source=source or (),
            target=target or (),
            color=color,
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


def _type_names(raw: Any, where: str, *, present: bool) -> tuple[str, ...] | None:
    """Node-type list. ``None`` when the key was omitted."""
    if not present:
        return None
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or not raw:
        raise MetaOntologyError(f"{where} must list at least one node type")
    out: list[str] = []
    for part in raw:
        ident = _ident(part, where, _TYPE_RE)
        if ident:
            out.append(ident)
    if not out:
        raise MetaOntologyError(f"{where} must list at least one node type")
    return tuple(out)


def _number(raw: Any, where: str) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise MetaOntologyError(f"{where} must be a number")
    return float(raw)


def _one_line(text: str) -> str:
    return " ".join(text.split())


EXPORT_DEFAULT_NODES: tuple[NodeTerm, ...] = (
    NodeTerm(
        type="figure",
        label="Figures",
        description=(
            "A plot or diagram. Name the data file in sources. "
            "The caption states what the figure shows and cites that data."
        ),
        folder="figures",
        prefix="fig",
        color="#e17c05",
    ),
    NodeTerm(
        type="table",
        label="Tables",
        description=(
            "An extracted or authored table. Keep the numbers as they "
            "are in the source, and cite the source."
        ),
        folder="tables",
        prefix="tab",
        color="#cc503e",
    ),
)


def for_export(ontology: MetaOntology) -> MetaOntology:
    """Ontology plus figure and table, when the file left them out."""
    missing = tuple(
        node for node in EXPORT_DEFAULT_NODES if ontology.node(node.type) is None
    )
    if not missing:
        return ontology
    return MetaOntology(
        nodes=ontology.nodes + missing,
        edges=ontology.edges,
        schema_keys=ontology.schema_keys,
        path=ontology.path,
    )


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
    out: dict[str, Any] = {
        "type": e.type,
        "label": e.label,
        "description": e.description,
    }
    if e.source:
        out["source"] = list(e.source)
    if e.target:
        out["target"] = list(e.target)
    if e.color:
        out["color"] = e.color
    return out


def _edge_viewer(ontology: MetaOntology, edge: EdgeTerm) -> dict[str, Any]:
    out = _edge_public(edge)
    if edge.typed and "color" not in out:
        color = ontology.edge_color(edge.type)
        if color:
            out["color"] = color
    return out


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


@dataclass(frozen=True)
class TypedEdge:
    """One frontmatter edge whose target page resolved."""

    source_id: str
    target_id: str
    edge_type: str
    source_type: str
    target_type: str


@dataclass(frozen=True)
class TypedEdgeIssue:
    """A typed edge that claim lint should report."""

    path: str
    line: int
    code: str
    message: str


@dataclass(frozen=True)
class _Page:
    id: str
    rel: str
    type: str
    title: str
    fm: dict[str, Any]
    text: str


def parse_frontmatter(text: str) -> dict[str, Any]:
    """Leading frontmatter. Unknown keys are kept.

    List values are either a flow list (``key: [a, b]``) or indented
    ``- item`` lines. A blank key is an empty string.
    """
    if not text.startswith("---"):
        return {}
    rest = text[3:]
    if rest.startswith("\r\n"):
        rest = rest[2:]
    elif rest.startswith("\n"):
        rest = rest[1:]
    else:
        return {}
    end = rest.find("\n---")
    if end < 0:
        return {}
    fm: dict[str, Any] = {}
    lines = rest[:end].splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        if not raw.strip() or raw[0] in " \t":
            i += 1
            continue
        if ":" not in raw:
            i += 1
            continue
        key, _, val = raw.partition(":")
        key = key.strip()
        val = val.strip()
        if val == "":
            items: list[str] = []
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                if not nxt.startswith((" ", "\t")) or not nxt.strip().startswith("-"):
                    break
                item = nxt.strip()[1:].strip().strip("\"'")
                if item:
                    items.append(item)
                j += 1
            if items:
                fm[key] = items
                i = j
                continue
            fm[key] = ""
            i += 1
            continue
        if val.startswith("[") and val.endswith("]"):
            parts = [
                part.strip().strip("\"'")
                for part in val[1:-1].split(",")
                if part.strip().strip("\"'")
            ]
            fm[key] = parts
        else:
            fm[key] = val.strip("\"'")
        i += 1
    return fm


def survey_typed_edges(
    workspace: Path, ontology: MetaOntology,
) -> tuple[tuple[TypedEdge, ...], tuple[TypedEdgeIssue, ...]]:
    """Resolved typed edges, and the problems claim lint prints.

    An edge whose target page exists is returned even when an endpoint
    type does not match, so the viewer can still draw it. The issue
    list carries the mismatch.
    """
    pages = _wiki_pages(Path(workspace), ontology)
    return _typed_from_pages(pages, ontology)


def typed_edge_map(
    workspace: Path, ontology: MetaOntology,
) -> dict[str, list[dict[str, str]]]:
    """Page id → ``[{type, target}, ...]`` for the OKF post-pass."""
    edges, _issues = survey_typed_edges(workspace, ontology)
    out: dict[str, list[dict[str, str]]] = {}
    seen: set[tuple[str, str, str]] = set()
    for edge in edges:
        key = (edge.source_id, edge.edge_type, edge.target_id)
        if key in seen:
            continue
        seen.add(key)
        out.setdefault(edge.source_id, []).append({
            "type": edge.edge_type,
            "target": edge.target_id,
        })
    return out


def _apply_workspace_graph(
    data: dict[str, Any], ontology: MetaOntology, workspace: Path,
) -> None:
    wiki = workspace / "wiki"
    if not wiki.is_dir():
        return
    pages = _wiki_pages(workspace, ontology)
    _restore_declared_types(data, ontology, pages)
    edges, _issues = _typed_from_pages(pages, ontology)
    _merge_typed_edges(data, ontology, pages, edges)
    _surface_edge_lists(data, ontology, pages)


def _wiki_pages(workspace: Path, ontology: MetaOntology) -> list[_Page]:
    wiki = workspace / "wiki"
    if not wiki.is_dir():
        return []
    out: list[_Page] = []
    for path in sorted(wiki.rglob("*.md")):
        if any(
            part in _SKIP_DIR_PARTS or part.startswith(".")
            for part in path.parts
        ):
            continue
        try:
            rel = path.resolve().relative_to(wiki.resolve()).as_posix()
        except ValueError:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        fm = parse_frontmatter(text)
        folder = rel.split("/", 1)[0] if "/" in rel else ""
        title = fm.get("title")
        title_text = title.strip() if isinstance(title, str) else ""
        out.append(_Page(
            id=rel[:-3] if rel.endswith(".md") else rel,
            rel=rel,
            type=_page_type(fm, folder, ontology),
            title=title_text or Path(rel).stem,
            fm=fm,
            text=text,
        ))
    return out


def _page_type(fm: dict[str, Any], folder: str, ontology: MetaOntology) -> str:
    raw = fm.get("type")
    if isinstance(raw, str) and raw.strip():
        return raw.strip().lower()
    for node in ontology.nodes:
        if node.folder and node.folder == folder:
            return node.type
    return ""


def _typed_from_pages(
    pages: list[_Page], ontology: MetaOntology,
) -> tuple[tuple[TypedEdge, ...], tuple[TypedEdgeIssue, ...]]:
    terms = [edge for edge in ontology.edges if edge.typed]
    if not terms:
        return (), ()
    by_id = {page.id.casefold(): page for page in pages}
    by_stem: dict[str, list[_Page]] = {}
    for page in pages:
        by_stem.setdefault(Path(page.id).name.casefold(), []).append(page)
    found: list[TypedEdge] = []
    issues: list[TypedEdgeIssue] = []
    for page in pages:
        for term in terms:
            targets = _target_list(page.fm.get(term.type))
            if not targets:
                continue
            line = _key_line(page.text, term.type)
            if page.type not in term.source:
                shown = page.type or "unset"
                allowed = " or ".join(term.source)
                issues.append(TypedEdgeIssue(
                    page.rel, line, "bad-edge-endpoint",
                    f"{term.type} source type {shown} is not {allowed}.",
                ))
            for raw in targets:
                resolved = _resolve_target(raw, by_id, by_stem)
                if resolved == "missing":
                    issues.append(TypedEdgeIssue(
                        page.rel, line, "missing-edge-target",
                        f"{term.type} target {raw} does not resolve to a page.",
                    ))
                    continue
                if resolved == "ambiguous" or not isinstance(resolved, _Page):
                    issues.append(TypedEdgeIssue(
                        page.rel, line, "ambiguous-edge-target",
                        f"{term.type} target {raw} matches more than one page.",
                    ))
                    continue
                if resolved.type not in term.target:
                    shown = resolved.type or "unset"
                    allowed = " or ".join(term.target)
                    issues.append(TypedEdgeIssue(
                        page.rel, line, "bad-edge-endpoint",
                        f"{term.type} target type {shown} is not {allowed}.",
                    ))
                found.append(TypedEdge(
                    source_id=page.id,
                    target_id=resolved.id,
                    edge_type=term.type,
                    source_type=page.type,
                    target_type=resolved.type,
                ))
    return tuple(found), tuple(issues)


def _target_list(raw: Any) -> list[str]:
    if isinstance(raw, str):
        text = raw.strip()
        return [text] if text else []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    return []


def _normalize_target(raw: str) -> str:
    text = raw.strip().strip("\"'")
    if text.startswith("[[") and text.endswith("]]"):
        text = text[2:-2]
    text = text.split("|", 1)[0].strip()
    text = text.replace("\\", "/")
    if text.lower().startswith("wiki/"):
        text = text[5:]
    if text.lower().endswith(".md"):
        text = text[:-3]
    return text.strip("/")


def _resolve_target(
    raw: str,
    by_id: dict[str, _Page],
    by_stem: dict[str, list[_Page]],
) -> _Page | str:
    key = _normalize_target(raw)
    if not key:
        return "missing"
    hit = by_id.get(key.casefold())
    if hit is not None:
        return hit
    if "/" not in key:
        hits = by_stem.get(key.casefold(), [])
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            return "ambiguous"
    return "missing"


def _key_line(text: str, key: str) -> int:
    if not text.startswith("---"):
        return 1
    end = text.find("\n---", 3)
    head = text[:end] if end >= 0 else text
    prefix = key + ":"
    for i, line in enumerate(head.splitlines(), start=1):
        if line.startswith(prefix):
            return i
    return 1


def _restore_declared_types(
    data: dict[str, Any], ontology: MetaOntology, pages: list[_Page],
) -> None:
    """Use the wiki type when this ontology names it.

    Curiosity Engine's viewer buckets types it does not know, such as
    ``hypothesis``, as ``unclassified``. The file on disk still has the
    declared type.
    """
    want = {
        page.id: page.type
        for page in pages
        if page.type and ontology.node(page.type) is not None
    }
    if not want:
        return

    def take(current: Any, declared: str) -> bool:
        shown = str(current or "").strip().lower()
        return shown in {"", "unclassified", "default"} or shown == declared

    for node in data.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        declared = want.get(str(node.get("id") or ""))
        if declared and take(node.get("type"), declared):
            node["type"] = declared
    page_map = data.get("pages")
    if isinstance(page_map, dict):
        for pid, declared in want.items():
            page = page_map.get(pid)
            if isinstance(page, dict) and take(page.get("type"), declared):
                page["type"] = declared


def _surface_edge_lists(
    data: dict[str, Any], ontology: MetaOntology, pages: list[_Page],
) -> None:
    page_map = data.get("pages")
    if not isinstance(page_map, dict):
        return
    by_id = {page.id: page for page in pages}
    for pid, page in page_map.items():
        src = by_id.get(str(pid))
        if src is None or not isinstance(page, dict):
            continue
        props = page.get("properties")
        if not isinstance(props, dict):
            props = {}
            page["properties"] = props
        for term in ontology.edges:
            if not term.typed or term.type in props:
                continue
            values = _target_list(src.fm.get(term.type))
            if values:
                props[term.type] = values


def _merge_typed_edges(
    data: dict[str, Any],
    ontology: MetaOntology,
    pages: list[_Page],
    edges: tuple[TypedEdge, ...],
) -> None:
    current = data.get("edges")
    if not isinstance(current, list):
        current = []
        data["edges"] = current
    have: set[tuple[str, str, str]] = set()
    for edge in current:
        if not isinstance(edge, dict):
            continue
        kind = str(edge.get("type") or "").strip().lower()
        have.add((_endpoint(edge.get("source")), _endpoint(edge.get("target")), kind))
        term = ontology.edge(kind)
        if term is None:
            continue
        edge["typeLabel"] = term.label
        color = ontology.edge_color(term.type)
        if color and term.typed:
            edge["color"] = color
    nodes = data.get("nodes")
    if not isinstance(nodes, list):
        nodes = []
        data["nodes"] = nodes
    by_node = {
        str(node.get("id")): node
        for node in nodes
        if isinstance(node, dict) and node.get("id")
    }
    by_page = {page.id: page for page in pages}
    for item in edges:
        _ensure_endpoint(nodes, by_node, by_page, item.source_id)
        _ensure_endpoint(nodes, by_node, by_page, item.target_id)
        key = (item.source_id, item.target_id, item.edge_type)
        if key in have:
            continue
        row: dict[str, Any] = {
            "source": item.source_id,
            "target": item.target_id,
            "type": item.edge_type,
        }
        term = ontology.edge(item.edge_type)
        if term is not None:
            row["typeLabel"] = term.label
        color = ontology.edge_color(item.edge_type)
        if color:
            row["color"] = color
        current.append(row)
        have.add(key)
        for pid in (item.source_id, item.target_id):
            node = by_node.get(pid)
            if isinstance(node, dict):
                node["degree"] = int(node.get("degree") or 0) + 1


def _ensure_endpoint(
    nodes: list[Any],
    by_node: dict[str, dict[str, Any]],
    by_page: dict[str, _Page],
    pid: str,
) -> None:
    if pid in by_node:
        return
    page = by_page.get(pid)
    node = {
        "id": pid,
        "path": f"{pid}.md",
        "type": page.type if page and page.type else "unclassified",
        "title": page.title if page else pid,
        "degree": 0,
    }
    nodes.append(node)
    by_node[pid] = node


def _endpoint(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("id") or "")
    return str(value or "")
