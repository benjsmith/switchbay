"""Orchestration-local evidence blackboard.

Transient claims + provenance for one orchestration. Distinct from
durable wiki/graph knowledge: workers write *candidate* findings here;
a verifier classifies them; a synthesizer reduces them; only the
existing propose → reviewer path may promote anything into the wiki.

Append-oriented: existing records are never mutated in place. Persisted
with the run artifacts under the machine-local state root.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from .. import atomicio

VERDICTS = (
    "supported",
    "contradicted",
    "insufficient",
    "inconsistent",
    "redundant",
    "candidate",
)

ProvenanceKind = Literal[
    "wiki", "vault", "file", "graph", "tool", "external", "compute", "unknown",
]


@dataclass
class EvidenceItem:
    source: str
    locator: str = ""
    excerpt_or_fact: str = ""
    kind: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Any) -> EvidenceItem:
        if not isinstance(raw, dict):
            return cls(source=str(raw)[:240])
        kind = str(raw.get("kind") or "unknown")
        if kind not in ("wiki", "vault", "file", "graph", "tool", "external", "compute", "unknown"):
            kind = "unknown"
        return cls(
            source=str(raw.get("source") or "")[:500],
            locator=str(raw.get("locator") or "")[:500],
            excerpt_or_fact=str(raw.get("excerpt_or_fact") or raw.get("excerpt") or "")[:4000],
            kind=kind,
        )


@dataclass
class Finding:
    claim: str
    evidence: list[EvidenceItem] = field(default_factory=list)
    confidence: float = 0.0
    assumptions: list[str] = field(default_factory=list)
    contradicts: list[str] = field(default_factory=list)
    finding_id: str = ""
    node_id: str = ""
    verdict: str = "candidate"
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.finding_id:
            self.finding_id = f"f-{uuid.uuid4().hex[:10]}"
        try:
            c = float(self.confidence)
        except (TypeError, ValueError):
            c = 0.0
        self.confidence = max(0.0, min(1.0, c))
        if self.verdict not in VERDICTS:
            self.verdict = "candidate"

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "node_id": self.node_id,
            "claim": self.claim,
            "evidence": [e.to_dict() for e in self.evidence],
            "confidence": self.confidence,
            "assumptions": list(self.assumptions),
            "contradicts": list(self.contradicts),
            "verdict": self.verdict,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, raw: Any, *, node_id: str = "") -> Finding:
        if not isinstance(raw, dict):
            return cls(claim=str(raw)[:4000], node_id=node_id)
        ev = raw.get("evidence") or []
        items = [EvidenceItem.from_dict(x) for x in ev] if isinstance(ev, list) else []
        assumptions = raw.get("assumptions") or []
        contradicts = raw.get("contradicts") or []
        return cls(
            claim=str(raw.get("claim") or "")[:4000],
            evidence=items,
            confidence=raw.get("confidence") or 0.0,
            assumptions=[str(a)[:500] for a in assumptions] if isinstance(assumptions, list) else [],
            contradicts=[str(a)[:500] for a in contradicts] if isinstance(contradicts, list) else [],
            finding_id=str(raw.get("finding_id") or ""),
            node_id=str(raw.get("node_id") or node_id),
            verdict=str(raw.get("verdict") or "candidate"),
            notes=str(raw.get("notes") or "")[:2000],
        )


@dataclass
class VerificationRecord:
    node_id: str
    classifications: list[dict[str, Any]]
    confidence: float = 0.0
    unresolved: list[str] = field(default_factory=list)
    conflicts: int = 0
    unsupported: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Any) -> VerificationRecord:
        if not isinstance(raw, dict):
            return cls(node_id="", classifications=[])
        classif = raw.get("classifications") or []
        if not isinstance(classif, list):
            classif = []
        try:
            conf = float(raw.get("confidence") or 0.0)
        except (TypeError, ValueError):
            conf = 0.0
        unresolved = raw.get("unresolved") or []
        return cls(
            node_id=str(raw.get("node_id") or ""),
            classifications=[c for c in classif if isinstance(c, dict)],
            confidence=max(0.0, min(1.0, conf)),
            unresolved=[str(u)[:500] for u in unresolved] if isinstance(unresolved, list) else [],
            conflicts=int(raw.get("conflicts") or 0),
            unsupported=int(raw.get("unsupported") or 0),
        )


class Blackboard:
    """Append-only, orchestration-local store of findings + verifications."""

    def __init__(self, orchestration_id: str) -> None:
        self.orchestration_id = orchestration_id
        self.findings: list[Finding] = []
        self.verifications: list[VerificationRecord] = []
        self.replaced_nodes: set[str] = set()
        self.created_at = time.time()

    def mark_replaced(self, node_ids: list[str] | None) -> None:
        """After a reducer runs, its inputs are no longer frontier."""
        for nid in node_ids or []:
            if nid:
                self.replaced_nodes.add(str(nid))

    def append_finding(self, finding: Finding) -> Finding:
        if not finding.finding_id:
            finding.finding_id = f"f-{uuid.uuid4().hex[:10]}"
        self.findings.append(finding)
        return finding

    def append_findings(self, items: list[Finding]) -> None:
        for f in items:
            self.append_finding(f)

    def append_verification(self, rec: VerificationRecord) -> VerificationRecord:
        self.verifications.append(rec)
        # Apply classifications onto matching findings by copying a
        # classified *view* — the original candidate stays, a classified
        # sibling is appended so history is reconstructable.
        by_id = {f.finding_id: f for f in self.findings}
        for row in rec.classifications:
            fid = str(row.get("finding_id") or row.get("claim_id") or "")
            verdict = str(row.get("verdict") or "")
            if verdict not in VERDICTS or verdict == "candidate":
                continue
            src = by_id.get(fid)
            if src is None:
                continue
            classified = Finding(
                claim=src.claim,
                evidence=list(src.evidence),
                confidence=src.confidence,
                assumptions=list(src.assumptions),
                contradicts=list(src.contradicts),
                finding_id=f"{src.finding_id}-v",
                node_id=rec.node_id,
                verdict=verdict,
                notes=str(row.get("notes") or "")[:2000],
            )
            self.findings.append(classified)
        return rec

    def candidates(self) -> list[Finding]:
        return [f for f in self.findings if f.verdict == "candidate"]

    def latest_verification(self) -> VerificationRecord | None:
        return self.verifications[-1] if self.verifications else None

    def conflict_count(self) -> int:
        if self.verifications:
            return int(self.verifications[-1].conflicts)
        claims = [f.claim.strip().lower() for f in self.candidates() if f.claim.strip()]
        return max(0, len(claims) - len(set(claims)))

    def unsupported_count(self) -> int:
        if self.verifications:
            return int(self.verifications[-1].unsupported)
        return sum(1 for f in self.candidates() if not f.evidence)

    def source_paths(self) -> set[str]:
        return {e.source for f in self.findings for e in f.evidence if e.source}

    def unique_source_count(self) -> int:
        return len(self.source_paths())

    @staticmethod
    def _stem(finding_id: str) -> str:
        fid = finding_id or ""
        return fid[:-2] if fid.endswith("-v") else fid

    def unclassified_candidates(self) -> list[Finding]:
        """Candidates with no classified sibling — the verifier's worklist."""
        classified = {
            self._stem(f.finding_id) for f in self.findings if f.verdict != "candidate"
        }
        classified.update(
            self._stem(f.finding_id) for f in self.findings if f.finding_id.endswith("-v")
        )
        out: list[Finding] = []
        seen: set[str] = set()
        for f in self.findings:
            if f.verdict != "candidate":
                continue
            stem = self._stem(f.finding_id)
            if stem in classified or stem in seen:
                continue
            seen.add(stem)
            out.append(f)
        return out

    def synthesis_view(self, findings: list[Finding] | None = None) -> list[Finding]:
        """One row per claim: classified copy wins; minority verdicts kept.

        Avoids sending both a candidate and its later classification, which
        doubles the synthesizer's context without adding information.
        """
        src = findings if findings is not None else self.findings
        if self.replaced_nodes:
            src = [f for f in src if f.node_id not in self.replaced_nodes]
        groups: dict[str, list[Finding]] = {}
        order: list[str] = []
        for f in src:
            stem = self._stem(f.finding_id)
            if stem not in groups:
                order.append(stem)
                groups[stem] = []
            groups[stem].append(f)
        out: list[Finding] = []
        for stem in order:
            group = groups[stem]
            classified = [f for f in group if f.verdict != "candidate"]
            out.append(classified[-1] if classified else group[-1])
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "orchestration_id": self.orchestration_id,
            "created_at": self.created_at,
            "findings": [f.to_dict() for f in self.findings],
            "verifications": [v.to_dict() for v in self.verifications],
            "replaced_nodes": sorted(self.replaced_nodes),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_dict(cls, raw: Any) -> Blackboard:
        if not isinstance(raw, dict):
            return cls(orchestration_id="unknown")
        bb = cls(str(raw.get("orchestration_id") or "unknown"))
        try:
            bb.created_at = float(raw.get("created_at") or bb.created_at)
        except (TypeError, ValueError):
            pass
        for item in raw.get("findings") or []:
            bb.findings.append(Finding.from_dict(item))
        for item in raw.get("verifications") or []:
            bb.verifications.append(VerificationRecord.from_dict(item))
        replaced = raw.get("replaced_nodes") or []
        if isinstance(replaced, list):
            bb.replaced_nodes = {str(x) for x in replaced if x}
        return bb

    def persist(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomicio.write_json_atomic(path, self.to_dict())

    @classmethod
    def load(cls, path: Path, orchestration_id: str) -> Blackboard:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls(orchestration_id)
        bb = cls.from_dict(data)
        if not bb.orchestration_id:
            bb.orchestration_id = orchestration_id
        return bb

    def compact_for_prompt(
        self,
        *,
        include_candidates: bool = True,
        role: str = "",
        from_nodes: list[str] | None = None,
        max_chars: int = 12_000,
    ) -> str:
        """Minimum sufficient typed payload for a downstream node.

        Never concatenates worker transcripts. Role views drop information
        that would only correlate or bloat the next decision:

        * verify — unclassified candidates (minus hierarchically
          replaced nodes); prior unresolved items, not previous verdicts.
        * synthesize — one classified row per claim; minority
          (contradicted / inconsistent / insufficient) preserved.
        * reduce — findings from the named sibling nodes only.
        """
        findings = self.findings
        if from_nodes is not None:
            allowed = set(from_nodes)
            findings = [f for f in findings if f.node_id in allowed]

        role = (role or "").strip().lower()
        excerpt_lim = 500
        ev_lim = 4
        if role == "verify":
            # Worklist = still-unclassified candidates whose source node
            # has not been hierarchically replaced. Expansion must still
            # see claims the first verifier missed.
            findings = [
                f for f in self.unclassified_candidates()
                if f.node_id not in self.replaced_nodes
            ]
            excerpt_lim, ev_lim = 400, 4
        elif role == "synthesize":
            findings = self.synthesis_view(findings)
            excerpt_lim, ev_lim = 400, 4
        elif role == "reduce":
            findings = [f for f in findings if f.verdict == "candidate"]
            excerpt_lim, ev_lim = 350, 3
        elif not include_candidates:
            findings = [f for f in findings if f.verdict != "candidate"]

        def _row(f: Finding, ex: int, evn: int) -> dict[str, Any]:
            row: dict[str, Any] = {
                "finding_id": f.finding_id,
                "node_id": f.node_id,
                "claim": f.claim[:800],
                "evidence": [
                    {
                        "source": e.source,
                        "locator": e.locator,
                        "excerpt_or_fact": (e.excerpt_or_fact or "")[:ex],
                        "kind": e.kind,
                    }
                    for e in f.evidence[:evn]
                ],
                "confidence": f.confidence,
                "verdict": f.verdict,
                "contradicts": f.contradicts[:6],
            }
            if role != "synthesize":
                row["assumptions"] = f.assumptions[:4]
                row["notes"] = (f.notes or "")[:400]
            elif f.notes:
                row["notes"] = f.notes[:400]
            return row

        def _payload(ex: int, evn: int, rows_in: list[Finding]) -> dict[str, Any]:
            body: dict[str, Any] = {"findings": [_row(f, ex, evn) for f in rows_in]}
            last = self.latest_verification()
            if role == "verify":
                if last is not None:
                    body["prior_unresolved"] = last.unresolved[:8]
                    body["prior_conflicts"] = last.conflicts
                    body["prior_unsupported"] = last.unsupported
            elif role == "synthesize":
                if last is not None:
                    body["verification_summary"] = {
                        "confidence": last.confidence,
                        "conflicts": last.conflicts,
                        "unsupported": last.unsupported,
                        "unresolved": last.unresolved[:8],
                    }
            elif role == "reduce":
                pass
            else:
                body["verifications"] = [v.to_dict() for v in self.verifications[-2:]]
            return body

        rows = list(findings)
        payload = _payload(excerpt_lim, ev_lim, rows)
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if len(text) <= max_chars:
            return text
        # Compress without dropping minority / unresolved signal: shrink
        # excerpts first, then drop oldest high-confidence supported rows.
        payload = _payload(220, 2, rows)
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if len(text) <= max_chars:
            return text
        keep: list[Finding] = []
        dropped: list[Finding] = []
        for f in rows:
            if f.verdict in ("contradicted", "inconsistent", "insufficient") or f.contradicts:
                keep.append(f)
            elif f.verdict == "supported" and f.confidence >= 0.75:
                dropped.append(f)
            else:
                keep.append(f)
        if dropped:
            keep.extend(dropped[-(max(2, len(dropped) // 3)):])
        payload = _payload(180, 2, keep)
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if len(text) > max_chars:
            text = text[: max_chars - 20] + "\n…[clipped]\n"
        return text


def _strip_fence(raw: str) -> str:
    s = (raw or "").strip()
    if s.startswith("```"):
        first_nl = s.find("\n")
        if first_nl != -1:
            s = s[first_nl + 1:]
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()
    return s


def parse_json_object(raw: str) -> dict[str, Any] | None:
    s = _strip_fence(raw)
    try:
        parsed = json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", s)
        if not m:
            return None
        try:
            parsed = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def parse_findings(raw: str, *, node_id: str) -> list[Finding]:
    """Extract structured findings from a worker reply.

    Prefer a JSON object with a `findings` array. If the model returned
    prose, wrap the whole reply as one un-evidenced candidate claim —
    better a coarse finding than dropping the work.
    """
    parsed = parse_json_object(raw)
    items: list[Any] = []
    if parsed is not None:
        if isinstance(parsed.get("findings"), list):
            items = parsed["findings"]
        elif "claim" in parsed:
            items = [parsed]
    out: list[Finding] = []
    for item in items:
        f = Finding.from_dict(item, node_id=node_id)
        if f.claim.strip():
            out.append(f)
    if out:
        return out
    text = (raw or "").strip()
    if not text:
        return []
    return [Finding(
        claim=text[:4000],
        node_id=node_id,
        confidence=0.3,
        assumptions=["unstructured worker output; no JSON findings"],
    )]


def parse_verification(raw: str, *, node_id: str) -> VerificationRecord:
    parsed = parse_json_object(raw) or {}
    classif = parsed.get("classifications") or parsed.get("results") or []
    if not isinstance(classif, list):
        classif = []
    cleaned: list[dict[str, Any]] = []
    conflicts = 0
    unsupported = 0
    for row in classif:
        if not isinstance(row, dict):
            continue
        verdict = str(row.get("verdict") or "insufficient").lower()
        if verdict == "insufficient evidence":
            verdict = "insufficient"
        if verdict == "mutually inconsistent":
            verdict = "inconsistent"
        if verdict not in VERDICTS:
            verdict = "insufficient"
        fid = str(row.get("finding_id") or row.get("claim_id") or "")
        cleaned.append({
            "finding_id": fid,
            "verdict": verdict,
            "notes": str(row.get("notes") or "")[:2000],
        })
        if verdict in ("contradicted", "inconsistent"):
            conflicts += 1
        if verdict == "insufficient":
            unsupported += 1
    try:
        conf = float(parsed.get("confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    unresolved = parsed.get("unresolved") or []
    if not isinstance(unresolved, list):
        unresolved = []
    rec = VerificationRecord(
        node_id=node_id,
        classifications=cleaned,
        confidence=max(0.0, min(1.0, conf)),
        unresolved=[str(u)[:500] for u in unresolved],
        conflicts=int(parsed.get("conflicts") or conflicts),
        unsupported=int(parsed.get("unsupported") or unsupported),
    )
    return rec
