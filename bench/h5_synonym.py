"""H5 — alias / synonym resolution corpus (v3, pre-registered).

See docs/benchmark-h5-prereg.md for the full design + critique. In short:

  - Needles live in a REAL haystack (curiosity-test, 392 pages) so retrieval is
    a genuine discrimination task, not a 20%-of-the-corpus lookup.
  - Two needle families, each entity has a FACT doc (a unique invented figure
    under one name) + a DEFINITION doc ("B is another name for A"):
      real_syn — a real-world thing named two ways the model/embeddings know
                 (myocardial infarction / heart attack); the fact is invented.
      codename — an invented codename aliasing a descriptive name, connected
                 only by the definition doc (Project Zephyr / the customer-churn
                 prediction service).
  - Aliases are LENGTH-BALANCED across families (no bare acronyms), and each
    alias's length is recorded so "familiar vs codename" is never confounded
    with "short vs long".
  - control — look-alike names (Marlon vs Marlin) with a fact but NO definition;
    the correct behaviour is to ABSTAIN.

Every needle is queried two ways with one fixed template — by its canonical
(fact-doc) name (a positive control) and by its alias — so the alias effect is
measured PAIRED, within entity. Names/values are chosen to not occur in the ML
haystack.
"""

from __future__ import annotations

import json
from pathlib import Path

# One fixed, neutral template. The queried {name} is the only thing that varies.
QTPL = "According to the evaluation, what figure is reported for {name}?"

# real_syn: (fact-doc name = formal term, queried alias = familiar synonym, fact, gold)
REAL_SYN = [
    ("myocardial infarction", "heart attack", "the QX-7 marker reached 412 units", "412"),
    ("renal failure", "kidney failure", "the Osgood protocol saved 34.7 minutes of clearance time", "34.7"),
    ("high blood pressure", "hypertension", "the Trelane index fell by 21.6 points", "21.6"),
    ("cerebrovascular accident", "stroke", "the Marrow grade rose by 3.4 levels", "3.4"),
    ("varicella", "chickenpox", "the Denler count peaked at 780 per sample", "780"),
    ("pertussis", "whooping cough", "the Vint protocol shortened recovery by 12.5 days", "12.5"),
    ("short-sightedness", "myopia", "the Calder shift measured 5.6 diopters", "5.6"),
    ("tetanus", "lockjaw", "the Prynne assay logged 96.4 milli-units", "96.4"),
    ("acid reflux", "heartburn", "the Bexley scale eased by 8.3 points", "8.3"),
    ("renal calculi", "kidney stones", "the Ferris procedure cleared 14.2 fragments per litre", "14.2"),
    ("rubella", "German measles", "the Aldous titre rose to 223", "223"),
    ("influenza", "the flu", "the Renton index hit 61.8 on the panel", "61.8"),
]
# codename: (fact-doc name = descriptive, queried alias = invented codename, fact, gold)
CODENAME = [
    ("the customer-churn prediction service", "Project Zephyr", "posted a 2.7x lift over baseline", "2.7x"),
    ("the settlement reconciliation engine", "Bluewidget", "cleared 48,300 items in the cutover", "48,300"),
    ("the internal document-routing pipeline", "Nimbus", "reached a score of 0.883", "0.883"),
    ("the anonymized cardiology cohort", "Meridian", "enrolled 1,204 participants", "1,204"),
    ("the quarterly pricing overhaul", "Falcon", "raised the average by 13.9 percent", "13.9"),
    ("the fraud-scoring subsystem", "Halcyon", "flagged 7,610 cases", "7,610"),
    ("the warehouse-routing optimizer", "Redwood", "shaved 5.1 hours off the run", "5.1"),
    ("the onboarding automation flow", "Aster", "cut steps by 42.5 percent", "42.5"),
    ("the demand-forecasting model", "Cobalt", "held error to 3.2 percent", "3.2"),
    ("the claims-triage assistant", "Vireo", "handled 9,340 tickets", "9,340"),
    ("the inventory-balancing routine", "Sable", "held stockouts to 1.8 percent", "1.8"),
    ("the sentiment-tagging service", "Larkspur", "scored 0.91 on the audit", "0.91"),
]
# control: (target name with a fact, look-alike name that is QUERIED and never
# defined, fact, gold). Correct behaviour = abstain; false bridge = report gold.
CONTROL = [
    ("Project Marlin", "Project Marlon", "reported 9,120 msg/s", "9,120"),
    ("Cypress-9", "Cypress-4", "held variance at 5.4 percent", "5.4"),
    ("the Onyx programme", "the Onyxx programme", "cut latency by 88 ms", "88"),
    ("Tiberius", "Tiberias", "scored 0.77 on review", "0.77"),
    ("Willow-3", "Willow-8", "logged 3,460 events", "3,460"),
    ("the Cascade initiative", "the Cascadia initiative", "saved 19.5 hours", "19.5"),
    ("Gannet", "Garnet", "reached 517 units", "517"),
    ("Project Vesper", "Project Vellum", "hit 44.2 percent", "44.2"),
]


def _fact_md(name: str, fact: str) -> str:
    return (f"# {name} — evaluation note\n\n"
            f"In the internal evaluation, {name} {fact}. "
            f"The figure was logged by the analytics team and reviewed twice.\n")


def build_corpus(raw_dir: Path) -> list[dict]:
    """Write needle + control docs into vault/raw; return the question set.
    Needles yield TWO questions (canonical + alias); controls yield one."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    qs: list[dict] = []
    for family, pairs, has_def in (("real_syn", REAL_SYN, True),
                                   ("codename", CODENAME, True),
                                   ("control", CONTROL, False)):
        for i, (fact_name, alias, fact, gold) in enumerate(pairs):
            stem = f"{family}-{i}"
            (raw_dir / f"{stem}-fact.md").write_text(_fact_md(fact_name, fact), encoding="utf-8")
            if has_def:
                (raw_dir / f"{stem}-glossary.md").write_text(
                    f"# Glossary\n\n**{alias}** is another name for {fact_name}; "
                    f"the two refer to the same thing.\n", encoding="utf-8")
            base = {"family": family, "entity": fact_name, "gold": gold,
                    "gold_fact_stem": f"{stem}-fact", "alias": alias,
                    "alias_len": len(alias)}
            if family == "control":
                qs.append({**base, "query_type": "control", "name": alias,
                           "query": QTPL.format(name=alias)})
            else:
                qs.append({**base, "query_type": "canonical", "name": fact_name,
                           "query": QTPL.format(name=fact_name)})
                qs.append({**base, "query_type": "alias", "name": alias,
                           "query": QTPL.format(name=alias)})
    return qs


if __name__ == "__main__":
    import tempfile
    d = Path(tempfile.mkdtemp()) / "vault" / "raw"
    qs = build_corpus(d)
    print(f"{len(qs)} questions, {len(list(d.iterdir()))} docs")
    from collections import Counter
    print("by (family, query_type):", Counter((q["family"], q["query_type"]) for q in qs))
    print("alias-length spread:",
          {f: sorted({q["alias_len"] for q in qs if q["family"] == f})
           for f in ("real_syn", "codename")})
    print(json.dumps(qs[0], indent=2))
