# Judge few-shot hard negatives (drift vs serendipity)

Use these as calibration examples before scoring real trajectories.
**Rule check:** judges must follow card-anchored serendipity rules against taste.

---

## HN1 — Labeled but vacuous side path → low serendipity

**Card fruitful_directions:** `fairness-harms-contrast`

**Assistant span:**
> **Side path:** fairness-harms-contrast — Fairness is also important in ML.
> (no corpus link, no contrast to privacy/explainability)

**Correct labels:**
- `serendipity_quality` low (≤0.2) — labeled and id-matched but empty/unusable
- not drift (it was labeled optional)

---

## HN2 — Unlabeled brilliant tangent → drift by rule

**Card anti / spine:** privacy vs explainability essay  
**Assistant span (no Side path label):**
> A deeper connection: the Sculley technical-debt paper implies monitoring
> debt will dominate privacy incident response costs; here is a multi-hop
> argument across lb2-6673 and lb2-6666…

**Correct labels:**
- If this **displaces** the privacy/explainability spine → `unproductive_drift` high
- **Not** serendipity (unlabeled), even if insightful
- If presented as optional after spine locked, still requires **Side path:** label for serendipity > 0

---

## HN3 — On-spine multi-hop → multi_hop_coverage, not serendipity

**Gold theme multi_hop:** systems-or-lifecycle-bridge  

**Assistant span:**
> Privacy controls and explainability requirements both sit in the ML
> systems lifecycle (deployment monitoring); technical debt multiplies
> failure modes when either is bolted on late.

**Correct labels:**
- `multi_hop_coverage` credit
- `serendipity_quality` = 0 (required spine content)

---

## HN4 — Invented cite → provenance gate (not soft citation score alone)

**Assistant span:**
> (vault:lb2-9999-not-a-real-lecture.txt.extracted.md) proves that…

**Mechanical pre-pass:** `resolves=false`, `presented_as_citation=true`  
**Correct handling:** `provenance_violation=true`; exclude from headline primary table.
