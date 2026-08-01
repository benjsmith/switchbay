"""H6 — semantic dissonance / homonym disambiguation corpus.

The dual of H5: the SAME surface term is used in two contexts with DIFFERENT
meanings + different facts. Curation should SPLIT the term into two provenanced
entities; raw RAG should risk CONFLATING them.

Each collision term T appears in two project contexts:
  - context A: T means sense-A (e.g. a process), with fact-A (a unique figure);
  - context B: T means sense-B (e.g. an output), with fact-B (a different figure).
The query disambiguates by CONTEXT (the project), never by the fact:
  "In {project}, what figure is reported for the {term}?"
Correct = that context's figure; CONFLATION = the other context's figure.

Terms are coined (not in the ML haystack). Senses are cleanly distinct
(process vs output) — the clean end of a spectrum we don't otherwise claim.

Plus single-context controls: a term used in only ONE place (no collision) —
a positive control that every arm should answer.
"""

from __future__ import annotations

import json
from pathlib import Path

QTPL = "In {project}, what figure is reported for the {term}?"
# Ambiguous: NO context cue in the query — the term is a homonym and the system
# must separate the two senses itself (or blend / mis-attribute them).
QTPL_AMBIG = "What do we know about the {term}? Report each figure."


def _marker(project: str) -> str:
    """The distinctive proper-noun token of a project string, used to check
    which sense a figure is attributed to (Project Atlas → Atlas)."""
    for w in project.split():
        if w[:1].isupper() and w not in ("Project", "The"):
            return w
    return project.split()[-1]

# (term, projA, senseA, factA, goldA, projB, senseB, factB, goldB)
COLLISIONS = [
    ("Doohickey", "Project Atlas", "the nightly validation step", "cleared 3,412 records", "3,412",
     "Project Borealis", "the exported ledger file", "weighed 88.4 MB", "88.4"),
    ("Sprocket", "the Vega team", "the data-cleaning routine", "ran for 6.2 hours", "6.2",
     "the Lyra team", "the packaged model artifact", "measured 517 MB", "517"),
    ("Widget", "Project Cobalt", "the intake screening pass", "handled 9,340 items", "9,340",
     "Project Dinar", "the printed summary sheet", "spanned 46 pages", "46"),
    ("Gizmo", "the Meridian group", "the reconciliation process", "took 12.5 minutes", "12.5",
     "the Solace group", "the archived export bundle", "held 214 files", "214"),
    ("Flange", "Project Onyx", "the approval workflow", "cleared in 3.8 days", "3.8",
     "Project Pearl", "the fabricated end panel", "weighed 71 kg", "71"),
    ("Grommet", "the Talon unit", "the escalation procedure", "resolved 88% of cases", "88%",
     "the Wren unit", "the moulded seal part", "rated to 260 psi", "260"),
    ("Kobble", "Project Sable", "the reindex operation", "processed 1.9M rows", "1.9M",
     "Project Yarn", "the compiled lookup table", "occupied 33 MB", "33"),
    ("Thimble", "the Cirrus desk", "the sign-off review", "averaged 4.5 hours", "4.5",
     "the Delta desk", "the exported audit file", "listed 612 entries", "612"),
    ("Nubbin", "Project Ember", "the calibration run", "shifted the baseline by 2.3%", "2.3",
     "Project Frost", "the rendered preview image", "came to 4.1 MB", "4.1"),
    ("Snig", "the Harbor team", "the triage step", "cut backlog by 57 tickets", "57",
     "the Ridge team", "the generated manifest", "named 128 assets", "128"),
]
# (term, project, sense, fact, gold) — single context, positive control
SINGLE = [
    ("Bramble", "Project Quill", "the onboarding checklist", "listed 23 steps", "23"),
    ("Fernback", "the Tundra team", "the nightly backup", "copied 4.7 TB", "4.7"),
    ("Halyard", "Project Verde", "the release gate", "held for 5.5 hours", "5.5"),
    ("Muntin", "the Cove desk", "the intake form", "captured 61 fields", "61"),
    ("Pintle", "Project Wisp", "the failover drill", "recovered in 92 seconds", "92"),
    ("Quoin", "the Basin unit", "the audit sweep", "flagged 14 items", "14"),
]


def _doc(term: str, project: str, sense: str, fact: str) -> str:
    return (f"# {term} — {project}\n\n"
            f"In {project}, the {term} is {sense}. In the latest run it {fact}. "
            f"Logged by the team and reviewed.\n")


def build_corpus(raw_dir: Path) -> list[dict]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    qs: list[dict] = []
    for i, (term, pa, sa, fa, ga, pb, sb, fb, gb) in enumerate(COLLISIONS):
        (raw_dir / f"coll-{i}-A.md").write_text(_doc(term, pa, sa, fa), encoding="utf-8")
        (raw_dir / f"coll-{i}-B.md").write_text(_doc(term, pb, sb, fb), encoding="utf-8")
        # two queries — one per sense; the OTHER sense's gold is the conflation trap
        qs.append({"kind": "collision", "term": term, "project": pa, "sense": sa,
                   "gold": ga, "conflation_gold": gb, "query": QTPL.format(project=pa, term=term)})
        qs.append({"kind": "collision", "term": term, "project": pb, "sense": sb,
                   "gold": gb, "conflation_gold": ga, "query": QTPL.format(project=pb, term=term)})
        # ambiguous: no context cue — must separate the two senses itself
        qs.append({"kind": "ambiguous", "term": term, "query": QTPL_AMBIG.format(term=term),
                   "goldA": ga, "markerA": _marker(pa), "senseA": sa,
                   "goldB": gb, "markerB": _marker(pb), "senseB": sb})
    for i, (term, project, sense, fact, gold) in enumerate(SINGLE):
        (raw_dir / f"single-{i}.md").write_text(_doc(term, project, sense, fact), encoding="utf-8")
        qs.append({"kind": "single", "term": term, "project": project, "sense": sense,
                   "gold": gold, "conflation_gold": None, "query": QTPL.format(project=project, term=term)})
    return qs


if __name__ == "__main__":
    import tempfile
    d = Path(tempfile.mkdtemp()) / "vault" / "raw"
    qs = build_corpus(d)
    print(f"{len(qs)} queries, {len(list(d.iterdir()))} docs")
    from collections import Counter
    print(Counter(q["kind"] for q in qs))
    print(json.dumps(qs[0], indent=2))
