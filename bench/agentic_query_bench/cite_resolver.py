"""Deterministic citation / provenance pre-pass for agentic_query_bench.

Parses (vault:…), wiki/… paths, and [[wikilinks]] from system text; resolves
against a workspace (vault/ + wiki/). Feeds the judge pack so citation_support
is not free-form plausibility.

Invented provenance (unresolvable cites presented as citations) is reported
for the trajectory GATE — see judgment-charter.json gates.provenance_violation.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

CITE_RESOLVER_VERSION = 5

VAULT_CITE_RE = re.compile(
    r"\(vault:\s*([^)]+?)\s*\)",
    re.IGNORECASE,
)
# wiki/facts/foo.md or `wiki/facts/foo.md`
WIKI_PATH_RE = re.compile(
    r"(?:^|[\s`\"'(\[]|path:)((?:wiki/)?(?:facts|figures|tables|sources|concepts|"
    r"entities|analyses|evidence|notes|todos|projects)/"
    r"[A-Za-z0-9][A-Za-z0-9._\-/]*\.md)",
    re.IGNORECASE | re.MULTILINE,
)
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
# Locus-style lb2-6666:123-456 from raw RAG arms
LOCUS_RE = re.compile(r"\b(lb2-\d+)(?::(\d+)-(\d+))?\b", re.IGNORECASE)
_SPAN_SUFFIX_RE = re.compile(r":(\d+)(?:-(\d+))?$")
_PATH_SHAPED_RE = re.compile(
    r"^[A-Za-z0-9_./\-]+\.[A-Za-z0-9]+(?:\.md)?(?::\d+(?:-\d+)?)?$"
)
_PLACEHOLDER_TARGETS = {"relpath", "example-not-checked-in-stub", "...", "…"}

# Heuristic: line looks like a gap / missing cite, not a positive citation.
_GAP_MARKERS = re.compile(
    r"(?i)\b(missing|not found|no (?:source|citation|page)|unavailable|"
    r"could not (?:find|locate|verify)|gap:|would need)\b"
)

# Fenced ```proposal blocks are DRAFT wiki content (compose_analysis is
# propose-only): wikilinks to not-yet-existing pages inside them are the
# intended product behaviour, not provenance claims — never gate on them
# (review RB5).
_PROPOSAL_FENCE_RE = re.compile(r"```proposal\b.*?(?:```|\Z)", re.IGNORECASE | re.DOTALL)


def _proposal_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _PROPOSAL_FENCE_RE.finditer(text)]


@dataclass
class CiteHit:
    raw: str
    kind: str  # vault | wiki_path | wikilink | locus
    target: str
    resolves: bool
    resolved_path: str | None = None
    quote_match_rate: float | None = None
    presented_as_citation: bool = True
    gate_eligible: bool = True
    failure_class: str | None = None
    hard_provenance_violation: bool = False
    note: str = ""


@dataclass
class CiteResolverReport:
    resolver_version: int = CITE_RESOLVER_VERSION
    cites: list[CiteHit] = field(default_factory=list)
    n_presented: int = 0
    n_resolves: int = 0
    resolve_rate: float = 0.0
    mean_quote_match_rate: float | None = None
    provenance_violation: bool = False
    n_conformance_failures: int = 0
    n_unresolved_semantic_links: int = 0
    n_fabricated_provenance: int = 0
    citation_conformance_rate: float = 1.0
    vault_terminating_rate: float | None = None
    n_placeholder_echoes: int = 0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def _norm_vault_rel(raw: str) -> str:
    s = raw.strip().strip("\"'")
    while s.startswith("vault/"):
        s = s[len("vault/") :]
    return s


@dataclass
class _ExtractedCite:
    kind: str
    raw: str
    target: str
    presented: bool
    start: int
    note: str = ""
    gate_eligible: bool = True


def _split_vault_payload(payload: str) -> list[tuple[str, str]]:
    """Return mechanically identifiable citation targets + annotations.

    RAG context exposes `file:start-end` loci, and models commonly preserve
    them inside the citation DSL.  Comma text is annotation, not filename.
    Semicolon-separated paths are independent citations.
    """
    parts = re.split(r"\s*[;,]\s*", payload.strip())
    expanded: list[str] = []
    for part in parts:
        expanded.extend(
            re.split(
                r"\s+and\s+(?=(?:vault:\s*)?(?:[A-Za-z0-9_./\-]+|\.extracted|:\d))",
                part,
                flags=re.IGNORECASE,
            )
        )

    targets: list[tuple[str, str]] = []
    annotations: list[str] = []
    prior_path: str | None = None
    for part in expanded:
        token = part.strip().strip("\"'")
        token = re.sub(r"^vault:\s*", "", token, flags=re.IGNORECASE)
        token = token.strip()
        if not token:
            continue
        if token.startswith("wiki/"):
            annotations.append(token)
            continue
        if token.startswith(".extracted.") and prior_path:
            token = prior_path + token
        bare, _span = _strip_span(token)
        if token.casefold() in _PLACEHOLDER_TARGETS:
            targets.append((token, "placeholder_echo"))
        elif _PATH_SHAPED_RE.fullmatch(token) or "..." in token or "…" in token:
            targets.append((token, ""))
            prior_path = bare
        else:
            annotations.append(token)

    if not targets and payload.strip():
        token = re.sub(r"^vault:\s*", "", payload.strip(), flags=re.IGNORECASE)
        targets.append((token, "malformed_target"))
    if annotations and targets:
        target, note = targets[-1]
        suffix = "annotation=" + "; ".join(annotations)
        targets[-1] = (target, f"{note}; {suffix}".strip("; "))
    return targets


def _strip_span(target: str) -> tuple[str, str]:
    m = _SPAN_SUFFIX_RE.search(target)
    if not m:
        return target, ""
    return target[: m.start()], f"span={m.group(1)}-{m.group(2) or m.group(1)}"


def _workspace_files(workspace: Path) -> tuple[set[str], dict[str, Path]]:
    """Return (relative posix paths under workspace, stem->wiki path map)."""
    rels: set[str] = set()
    stems: dict[str, Path] = {}
    if not workspace.is_dir():
        return rels, stems
    for p in workspace.rglob("*"):
        if not p.is_file():
            continue
        try:
            rel = p.relative_to(workspace).as_posix()
        except ValueError:
            continue
        rels.add(rel)
        if rel.startswith("wiki/") and rel.endswith(".md"):
            stem = Path(rel).stem
            stems.setdefault(stem, p)
            # also key without type prefix ambiguity: facts/foo
            stems.setdefault(rel[len("wiki/") : -3], p)
    return rels, stems


def _read_text(path: Path, limit: int = 200_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _quote_match(system_text: str, page_text: str, window: int = 40) -> float:
    """Crude support: fraction of content tokens (len>=5) from nearby claims
    that appear in page_text. Not a full NLI — diagnostic only."""
    if not page_text or not system_text:
        return 0.0
    page_cf = page_text.casefold()
    # take alphanumeric tokens from system near length 5+
    toks = re.findall(r"[A-Za-z][A-Za-z0-9\-]{4,}", system_text)
    if not toks:
        return 0.0
    # unique, cap
    seen: list[str] = []
    for t in toks:
        tl = t.casefold()
        if tl not in seen:
            seen.append(tl)
        if len(seen) >= 80:
            break
    hits = sum(1 for t in seen if t in page_cf)
    return hits / max(1, len(seen))


def _line_is_gap(line: str) -> bool:
    return bool(_GAP_MARKERS.search(line))


def _extract_cites_detailed(text: str) -> list[_ExtractedCite]:
    out: list[_ExtractedCite] = []
    lines = text.splitlines()
    line_of: dict[int, str] = {}
    # map char offset -> line for gap detection
    pos = 0
    for line in lines:
        for i in range(pos, pos + len(line) + 1):
            line_of[i] = line
        pos += len(line) + 1

    proposal_spans = _proposal_spans(text)

    def presented_at(match_start: int) -> bool:
        if any(s <= match_start < e for s, e in proposal_spans):
            return False
        line = line_of.get(match_start, "")
        return not _line_is_gap(line)

    vault_spans: list[tuple[int, int]] = []
    for m in VAULT_CITE_RE.finditer(text):
        vault_spans.append((m.start(), m.end()))
        presented = presented_at(m.start())
        for target, note in _split_vault_payload(m.group(1)):
            placeholder = note == "placeholder_echo"
            out.append(_ExtractedCite(
                "vault", m.group(0), _norm_vault_rel(target),
                presented and not placeholder, m.start(), note,
                gate_eligible=not placeholder,
            ))
    for m in WIKI_PATH_RE.finditer(text):
        raw = m.group(1)
        tgt = raw if raw.startswith("wiki/") else f"wiki/{raw}"
        out.append(_ExtractedCite("wiki_path", raw, tgt, presented_at(m.start()), m.start()))
    for m in WIKILINK_RE.finditer(text):
        stem = m.group(1).strip()
        out.append(_ExtractedCite("wikilink", m.group(0), stem, presented_at(m.start()), m.start()))
    for m in LOCUS_RE.finditer(text):
        if any(start <= m.start() < end for start, end in vault_spans):
            continue
        out.append(_ExtractedCite(
            "locus", m.group(0), m.group(1).lower(), presented_at(m.start()), m.start()
        ))
    return out


def extract_cites(text: str) -> list[tuple[str, str, str, bool]]:
    """Return list of (kind, raw, target, presented_as_citation)."""
    return [(c.kind, c.raw, c.target, c.presented) for c in _extract_cites_detailed(text)]


def _resolve_vault(workspace: Path, target: str, rels: set[str]) -> tuple[bool, str | None, Path | None]:
    target, _span = _strip_span(target)
    if "..." in target or "…" in target:
        return _resolve_abbreviated_vault(workspace, target, rels)
    if target.startswith("./"):
        target = target[2:]
    candidates = [target]
    if target.startswith("vault/"):
        candidates.append(target[len("vault/") :])
    else:
        candidates.append(f"vault/{target}")
    for c in candidates:
        if c in rels and c.startswith("vault/"):
            return True, c, workspace / c

    # Timestamped corpus paths are often cited by basename. Permit that only
    # when the basename identifies exactly one logical vault source.
    base = Path(target).name
    matches = [rel for rel in rels if rel.startswith("vault/") and Path(rel).name == base]
    if len(matches) == 1:
        rel = matches[0]
        return True, rel, workspace / rel
    return False, None, None


def _logical_source_key(rel: str) -> str:
    return rel.removesuffix(".extracted.md")


def _resolve_abbreviated_vault(
    workspace: Path, target: str, rels: set[str]
) -> tuple[bool, str | None, Path | None]:
    anchors = [a.casefold() for a in re.split(r"(?:\.{3}|…)+", target) if a]
    matches = [
        rel for rel in rels
        if rel.startswith("vault/") and all(a in rel.casefold() for a in anchors)
    ]
    groups: dict[str, list[str]] = {}
    for rel in matches:
        groups.setdefault(_logical_source_key(rel), []).append(rel)
    if len(groups) != 1:
        return False, None, None
    group = next(iter(groups.values()))
    rel = next((r for r in group if r.endswith(".extracted.md")), group[0])
    return True, rel, workspace / rel


def _resolve_wiki(
    workspace: Path, target: str, rels: set[str], stems: dict[str, Path]
) -> tuple[bool, str | None, Path | None]:
    t = target if target.startswith("wiki/") else f"wiki/{target}"
    if t in rels:
        return True, t, workspace / t
    if not t.endswith(".md"):
        t_md = t + ".md"
        if t_md in rels:
            return True, t_md, workspace / t_md
    # stem lookup
    stem = Path(target).stem if "/" in target or target.endswith(".md") else target
    stem = stem.replace(" ", "-").lower()
    # try exact stem keys
    for key in (stem, target, target.lower()):
        if key in stems:
            p = stems[key]
            rel = p.relative_to(workspace).as_posix()
            return True, rel, p
    # fuzzy: endswith stem.md
    for rel in rels:
        if rel.startswith("wiki/") and rel.endswith(f"/{stem}.md"):
            return True, rel, workspace / rel
    return False, None, None


def _resolve_locus(workspace: Path, lb2_id: str, rels: set[str]) -> tuple[bool, str | None, Path | None]:
    needle = lb2_id.lower()
    for rel in rels:
        if needle in rel.lower() and (rel.startswith("vault/") or "lecturebank" in rel.lower()
                                      or rel.endswith(".txt") or ".extracted." in rel):
            return True, rel, workspace / rel
    # corpus outside workspace: still mark unresolved for workspace-bound gate
    return False, None, None


def resolve_text(
    workspace: Path | str,
    text: str,
    *,
    _inventory: tuple[set[str], dict[str, Path]] | None = None,
) -> CiteResolverReport:
    ws = Path(workspace).expanduser().resolve()
    rels, stems = _inventory if _inventory is not None else _workspace_files(ws)
    hits: list[CiteHit] = []
    seen: set[tuple[str, str]] = set()

    hit_by_key: dict[tuple[str, str], CiteHit] = {}
    for item in _extract_cites_detailed(text):
        kind, raw, target, presented = item.kind, item.raw, item.target, item.presented
        key = (kind, target)
        if key in hit_by_key:
            prior = hit_by_key[key]
            prior.presented_as_citation = prior.presented_as_citation or presented
            # Gate eligibility is intrinsic to the normalized target. A later
            # duplicate cannot turn an ambiguous/placeholder citation into
            # evidence of invention.
            prior.gate_eligible = prior.gate_eligible and item.gate_eligible
            continue
        seen.add(key)
        ok = False
        rpath: str | None = None
        fpath: Path | None = None
        note = item.note
        if kind == "vault":
            ok, rpath, fpath = _resolve_vault(ws, target, rels)
            bare, span_note = _strip_span(target)
            target = bare
            if span_note:
                note = "; ".join(x for x in (note, span_note) if x)
            if ("..." in item.target or "…" in item.target) and ok:
                note = "; ".join(x for x in (note, "abbreviated_unique") if x)
            elif ("..." in item.target or "…" in item.target) and not ok:
                # Ambiguous shorthand is sloppy but not proof of invention;
                # a zero-match abbreviation remains gate-eligible.
                anchors = [a.casefold() for a in re.split(r"(?:\.{3}|…)+", item.target) if a]
                matches = [rel for rel in rels if rel.startswith("vault/") and all(a in rel.casefold() for a in anchors)]
                if matches:
                    item.gate_eligible = False
                    note = "; ".join(x for x in (note, "abbreviated_ambiguous") if x)
        elif kind in ("wiki_path", "wikilink"):
            ok, rpath, fpath = _resolve_wiki(ws, target, rels, stems)
        elif kind == "locus":
            ok, rpath, fpath = _resolve_locus(ws, target, rels)
            if not ok:
                note = "locus id not found under workspace vault/"
        qmr = None
        if ok and fpath is not None:
            qmr = _quote_match(text, _read_text(fpath))
        failure_class: str | None = None
        hard_violation = False
        if presented and item.gate_eligible and not ok:
            if kind == "wiki_path":
                failure_class = "fabricated_provenance"
                hard_violation = True
            elif kind == "vault" and _PATH_SHAPED_RE.fullmatch(item.target):
                # A complete citation-DSL path is an auditable assertion that
                # a source exists. Shorthand, annotations, and malformed
                # locators are conformance failures, not proof of invention.
                failure_class = "fabricated_provenance"
                hard_violation = True
            elif kind == "wikilink":
                failure_class = "unresolved_semantic_link"
            else:
                failure_class = "citation_conformance"
        hits.append(
            CiteHit(
                raw=raw,
                kind=kind,
                target=target,
                resolves=ok,
                resolved_path=rpath,
                quote_match_rate=qmr,
                presented_as_citation=presented,
                gate_eligible=item.gate_eligible,
                failure_class=failure_class,
                hard_provenance_violation=hard_violation,
                note=note,
            )
        )
        hit_by_key[key] = hits[-1]

    # Deduplication can promote a target first mentioned as a gap into a later
    # positive citation. Classify from the final merged state, not the first
    # occurrence's state.
    for hit in hits:
        hit.failure_class = None
        hit.hard_provenance_violation = False
        if not (
            hit.presented_as_citation
            and hit.gate_eligible
            and not hit.resolves
        ):
            continue
        if hit.kind == "wiki_path":
            hit.failure_class = "fabricated_provenance"
            hit.hard_provenance_violation = True
        elif hit.kind == "vault" and _PATH_SHAPED_RE.fullmatch(hit.target):
            hit.failure_class = "fabricated_provenance"
            hit.hard_provenance_violation = True
        elif hit.kind == "wikilink":
            hit.failure_class = "unresolved_semantic_link"
        else:
            hit.failure_class = "citation_conformance"

    presented = [h for h in hits if h.presented_as_citation]
    n_pres = len(presented)
    n_ok = sum(1 for h in presented if h.resolves)
    resolve_rate = (n_ok / n_pres) if n_pres else 1.0  # no cites → no violation
    qmrs = [h.quote_match_rate for h in presented if h.resolves and h.quote_match_rate is not None]
    mean_q = sum(qmrs) / len(qmrs) if qmrs else None
    conformance_failures = [
        h for h in hits
        if h.presented_as_citation and h.gate_eligible and not h.resolves
    ]
    fabricated = [h for h in conformance_failures if h.hard_provenance_violation]
    semantic_links = [
        h for h in conformance_failures
        if h.failure_class == "unresolved_semantic_link"
    ]
    # Headline exclusion is deliberately narrow. A model must assert a fully
    # specified nonexistent provenance path; vague or malformed citation
    # syntax remains visible in citation-conformance scoring.
    violation = bool(fabricated)
    # vault-terminating: vault cites or wiki pages that themselves cite vault
    vault_term = 0
    vault_n = 0
    for h in presented:
        if not h.resolves or not h.resolved_path:
            continue
        vault_n += 1
        if h.kind == "vault" or h.kind == "locus" or h.resolved_path.startswith("vault/"):
            vault_term += 1
        elif h.resolved_path.startswith("wiki/"):
            body = _read_text(ws / h.resolved_path, limit=50_000)
            if VAULT_CITE_RE.search(body) or "sources:" in body[:2000]:
                vault_term += 1
    vt_rate = (vault_term / vault_n) if vault_n else None

    return CiteResolverReport(
        cites=hits,
        n_presented=n_pres,
        n_resolves=n_ok,
        resolve_rate=resolve_rate,
        mean_quote_match_rate=mean_q,
        provenance_violation=violation,
        n_conformance_failures=len(conformance_failures),
        n_unresolved_semantic_links=len(semantic_links),
        n_fabricated_provenance=len(fabricated),
        citation_conformance_rate=(
            n_ok / n_pres if n_pres else 1.0
        ),
        vault_terminating_rate=vt_rate,
        n_placeholder_echoes=sum(1 for h in hits if "placeholder_echo" in h.note),
    )


def resolve_trajectory(
    workspace: Path | str,
    turns: Iterable[dict[str, Any]],
    *,
    answer_key: str = "assistant",
) -> dict[str, Any]:
    """Aggregate cite reports over trajectory turns."""
    per_turn: list[dict[str, Any]] = []
    any_violation = False
    all_presented = 0
    all_ok = 0
    all_conformance_failures = 0
    all_semantic_links = 0
    all_fabricated = 0
    ws = Path(workspace).expanduser().resolve()
    inventory = _workspace_files(ws)
    for t in turns:
        text = t.get(answer_key) or t.get("answer") or t.get("content") or ""
        rep = resolve_text(ws, text, _inventory=inventory)
        if rep.provenance_violation:
            any_violation = True
        all_presented += rep.n_presented
        all_ok += rep.n_resolves
        all_conformance_failures += rep.n_conformance_failures
        all_semantic_links += rep.n_unresolved_semantic_links
        all_fabricated += rep.n_fabricated_provenance
        per_turn.append({"turn_id": t.get("id") or t.get("turn_id"), "report": rep.to_dict()})
    return {
        "resolver_version": CITE_RESOLVER_VERSION,
        "per_turn": per_turn,
        "provenance_violation": any_violation,
        "n_presented": all_presented,
        "n_resolves": all_ok,
        "resolve_rate": (all_ok / all_presented) if all_presented else 1.0,
        "n_conformance_failures": all_conformance_failures,
        "n_unresolved_semantic_links": all_semantic_links,
        "n_fabricated_provenance": all_fabricated,
        "citation_conformance_rate": (
            all_ok / all_presented if all_presented else 1.0
        ),
    }
