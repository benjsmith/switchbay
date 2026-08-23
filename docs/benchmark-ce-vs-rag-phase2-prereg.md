# Phase 2 preregistration — CE vs RAG on long documents

**Status:** pre-run methodology and position-controlled pilot are locked; no
Phase 2 retrieval, generation, or judgment result has been inspected.
**Date:** 2026-07-13. Three held-out source families are pinned and locally
extracted, but exact tokenizer/window measurement and evidence-distribution
review still gate the cross-course confirmatory corpus. This document and
bench/phase2/scoring-rubric.json must be versioned before the first retrieval
run.

## 1. Question

When source documents exceed the embedding/model window, how do CE's curated
wiki + graph retrieval, CE's current chunked wiki retrieval, compressed
retrieval descriptors, CE's whole-source vault retrieval, and production-style
chunked raw-document RAG compare on retrieval recall, faithful answer quality,
and global thematic coverage?

The original global/sensemaking score is not prior evidence for an arm: its
pairwise judge was confounded by answer length. Phase 2 treats it as unresolved.

## 2. Pre-registered hypotheses

- **P2-H1 — tail recall:** chunked raw RAG and curator-distilled CE retrieve
  evidence placed beyond the whole-source embedding window more reliably than
  CE's whole-source/truncated vault vector.
- **P2-H2 — synthesis:** curated wiki/graph context improves multi-document
  synthesis and faithfulness after retrieval recall is held constant.
- **P2-H3 — descriptor granularity:** compressed descriptors improve routing to
  long thematic pages without losing the detailed evidence reachable through
  graph links; they must beat or tie chunked wiki retrieval before replacing it.
- **P2-H4 — global:** no directional prior. CE vs chunked raw RAG on global
  theme coverage is explicitly unresolved.
- **P2-H0 — efficiency:** report index size, retrieval latency, context tokens,
  generation tokens, and model calls; quality gains are not free by assumption.

## 3. Arms

Use blinded arm codes during generation and judging. Decode only in analysis.

1. **CE keyword/shipped control** — retained as a weak/product baseline.
2. **CE graph retrieval** — semantic wiki seed → weighted bidirectional BFS.
3. **CE chunked wiki** — current approximately 900-character wiki chunks.
4. **CE descriptor wiki** — whole-page vector when it fits; otherwise a bounded
   title + abstract + entities/aliases retrieval descriptor.
5. **CE vault whole-source** — current whole-source/truncated vector + FTS
   behavior; label it accurately, never "modern RAG."
6. **Chunked raw-document RAG** — production baseline using the exact frozen CE
   embedding lock, fixed chunk/overlap settings, and the same final model-visible
   context budget.
7. **Adaptive/hybrid candidate** — a frozen, query-only routing rule selected
   without looking at Phase 2 answers. Report constituent arms separately so
   routing cannot hide a weak branch.

No arm may receive a larger generator context or answer budget. Retrieval may
return more candidates internally, but final context assembly is budget-matched.
Task category, evidence band, gold answer, document identity, and source
metadata are prohibited inputs to an adaptive primary arm. A category-oracle
router may be measured only as a clearly labelled upper-bound sensitivity and
is excluded from primary comparisons.

Every arm must record a common retrieval trace: candidate rank and score,
source document and source offsets, selected/truncated/final offsets, final
context hash and token/character counts, index/build metadata, and cold/warm
latency. Tie-breaking is deterministic and frozen. The whole-source vault
control is reported as whole-source vector retrieval plus its stated
FTS/assembly behavior; it is never called a general modern-RAG baseline.

### Hard embedding parity contract

Before any semantic index is built, create `bench/phase2/embedding_lock.json`
from its template and record its SHA-256 in the run manifest. The lock names
the exact CE `embedder.py` and CE embedding config, explicit backend (never
`auto`), model name and model ID, installed backend/runtime versions, a
hash-verified model-artifact manifest, vector dimension and normalization,
the effective embedding-tokenizer limit, and a deterministic probe vector.
`bench.phase2_embedding.load_ce_embedder` fails closed on any mismatch and
does not permit CE's normal backend fallback. The raw baseline must be built
through `build_hard_parity_chunked_raw_rag`; every semantic CE index is freshly
rebuilt from the same lock and its logical index snapshot is hashed.

The keyword/shipped control is intentionally lexical and is the only arm
exempt from embedding parity. Graph seed retrieval, chunked wiki, descriptor
retrieval, whole-source vault semantic retrieval, and chunked raw RAG all use
the lock. Historical CE indexes are never reused merely because their stored
model label appears to match; all vectors, dimensions, row counts, source
surfaces, and graph-neighbour edges are verified after a clean rebuild.

## 4. Corpus and evidence-position design

- Select long study-note/lecture documents that exceed both the measured
  effective embedding window and CE's text[:8000] vault-vector cap. Record
  characters, tokenizer tokens, sections, and headings before question
  creation. Character length alone is not sufficient.
- LectureBank is a source registry, not the corpus itself. The first pinned
  position-controlled pilot is the MIT-licensed CE9010 course (LectureBank 2.0
  IDs 476–485); its source commit, PDF hashes, extraction rule, and local
  manifest are in bench/phase2/source-manifests/lecturebank-ce9010-pilot.json
  and docs/benchmark-ce-vs-rag-phase2-corpus.md. It is development/pilot-only:
  a confirmatory claim requires at least three independently sourced course
  families held out by whole family.
- The held-out source-family index is
  bench/phase2/source-manifests/confirmatory-families.json: UMich EECS 445
  (MIT, 20 selected decks), UW–Madison STAT 453 (MIT, 15 selected decks), and
  McGill COMP 599 (CC BY-SA 4.0, 10 selected instructor decks). Their local
  aggregate manifest records a source-family ID and source-selection hash for
  every document. The source selection is frozen; it does not permit question
  writing until the remaining gates in this section have been satisfied.
- Freeze a provenance contract for every arm: identical raw source snapshot,
  extraction/normalization hashes, curator model/prompt/config, raw/wiki/graph
  and descriptor/index hashes, and a source-to-wiki coverage audit. A curated
  wiki span may count as retrieved evidence for a raw gold span only through a
  frozen exact or audited semantic provenance mapping.
- Define three normalized evidence bands: **head** (0–20%), **middle** (40–60%),
  and **tail** (80–100%). Balance question counts across bands.
- Match evidence bands on answer type, evidence length, lexical distinctiveness,
  number of hops, and distractor count.
- Add matched distractors with overlapping vocabulary but incompatible facts.
- Multi-hop questions must identify every required gold span and document.
- Global questions must have an arm-independent list of atomic themes derived
  from the full source set before retrieval runs.
- Deduplicate near-identical decks before question construction. Keep an entire
  course family in development or held-out evaluation, never both. Global
  themes must span the declared source set rather than exploit a single
  document's head section.
- Questions and rubrics are frozen before any arm answers are generated.

Prefer naturally occurring evidence. If controlled insertions are needed, mark
them as synthetic and report natural and synthetic subsets separately.

## 5. Fixed budgets

- Tokenize contexts with a declared, pinned tokenizer before generation.
- Use one fixed maximum context-token budget across every arm and deterministic
  assembly/truncation rules. Count the fully rendered prompt, including
  instructions, headers, labels, and separators; record both allowed and actual
  reference-token values plus the generator's actual input/output tokens.
- Use one fixed output budget. For global questions, request 60–80 words. A
  non-empty out-of-band answer receives exactly one fixed length-only rewrite
  using the same context; a second out-of-band result is retained and flagged,
  never silently dropped. The primary and in-band sensitivity analyses are both
  reported.
- Same generator prompt, temperature/decoding configuration, and model version
  across arms within a generator.
- Confirm current-generation model IDs at run start, per `charter.md`.

## 6. Outcomes

### Retrieval outcomes — scored before generation

- Gold-document recall@k.
- Gold-span recall in the final model-visible context.
- Recall by head/middle/tail evidence band.
- Context precision and duplicate-context rate.
- Retrieval latency, index size, and context tokens.
- For multi-hop, joint span recall means every required span is visible in the
  final context; per-span recall is also reported.

### Single-hop and multi-hop answer outcomes

- Correct / partial / incorrect against a frozen reference and required atomic
  facts.
- Faithfulness: every material claim supported by supplied context.
- Conditional answer quality given successful gold-span recall, separating
  retrieval failure from generation failure.

### Global outcomes

Primary metric: frozen weighted atomic-theme coverage less fixed penalties for
unsupported material claims and redundant theme units. The exact rule is
max(0, raw coverage - min(0.40, 0.10 * unsupported claims) -
min(0.20, 0.05 * redundant units)); themes have positive finite weights
(default 1.0). Report raw coverage and each penalty count alongside the
composite. The definitions, required judge output, and length-repair policy are
frozen in bench/phase2/scoring-rubric.json; a composite may not hide its parts.

Secondary metric: pairwise comprehensiveness/diversity, blinded, both answer
orderings. A pair is length-matched only when both answers are in the 60–80
word band and their whitespace-word counts differ by at most five. Report both
all in-band pairs and this matched subset; the secondary metric may corroborate
but cannot override the primary theme score.

## 7. Models and bias controls

- At least two current-generation answer generators.
- Both models judge both generators; no self-judge-only conclusion.
- Randomized/blinded arm labels and both pairwise orderings.
- Report each generator×judge cell, per-generator results, and pooled results.
- Measure the relationship between score and answer length. Any material
  generator×arm or length×score interaction blocks a pooled headline until
  explained by a predeclared sensitivity analysis.
- Judge prompts see the question, normalized evidence labels, answers, and
  frozen rubric only. Filenames, page titles, repository names, arm identity,
  ranks, and retrieval method are removed.

## 8. Analysis plan

- Primary uncertainty is a paired hierarchical bootstrap: resample course
  family, then document, then question. A question-level paired bootstrap is a
  sensitivity analysis, not the sole independence assumption.
- Stratify by task type, evidence band, natural/synthetic, and successful/failed
  gold-span retrieval.
- Primary comparisons are CE graph vs chunked raw RAG, CE descriptor vs CE
  chunked wiki, and CE whole-source vault vs chunked raw RAG.
- The three primary comparisons use family-wise alpha 0.05 with Bonferroni
  98.33% confidence intervals. All estimates and unadjusted 95% intervals are
  also reported, without selective significance language.
- Before confirmatory question freeze, use a prospective paired-bootstrap
  simulation targeting 80% power for a 0.10 absolute score difference. The
  confirmatory floor is 90 questions: 30 single-hop, 30 multi-hop, and 30
  global. Each source family contributes 30 questions (10 per category).
  The 60 single/multi-hop items are exactly balanced at 10 per
  category-by-band cell: 10 single-hop and 10 multi-hop items in each of head,
  middle, and tail. Expand the corpus if the simulation does not meet target
  power.
- A material regression is a point estimate of -0.05 or worse on a normalized
  score in any preregistered task type or evidence-band stratum. An aggregate
  gain cannot accept a routing/descriptor policy with such a regression.
- Transport failures retry at most twice with the identical prompt, seed, and
  retrieval trace. A completed answer/judgment is never retried for quality.
  Persistent failures remain explicit missing records; they are neither
  replaced nor silently dropped.
- A routing policy is accepted only if it improves the predeclared aggregate
  without a material regression in any task type or evidence band.

## 9. Decision rules

- **Replace wiki chunks with descriptors** only if descriptors are non-inferior
  within -0.05 on factoid/multi-hop recall and answer quality, and improve
  long-page routing or efficiency without a material-regression stratum.
  Otherwise retain chunking.
- **Claim a CE global win** only if CE improves atomic-theme coverage over
  chunked raw RAG under matched budgets, without more unsupported claims, and
  the direction is stable across generators.
- **Claim a RAG global win** under the symmetric rule.
- If generator directions disagree, report the interaction and no pooled win.
- Product routing changes require Phase 2 evidence; the provisional original
  global score is insufficient.

## 10. Artifacts to prepare before model calls

- Corpus manifest with lengths and hashes. The CE9010 pilot and the three
  independent source-family selections have reproducible local extractors and
  a 45-document aggregate manifest. Exact tokenizer/window measurements and
  evidence-distribution review remain required before question writing.
- Gold-span/evidence-band annotations and atomic-theme rubrics.
- Frozen question set and arm-independent references.
- Blinded arm map stored separately from generation inputs.
- Context assembler with hard token-budget validation. Character/word budget
  backstop is ready; exact reference/generator tokenizer configuration remains
  a model-call gate.
- Output length validator and actual-length report. **Ready.**
- Chunked raw-document vector baseline. **Guard implemented**, side-effect-free
  and using the hard CE embedding lock, with a serializable common retrieval
  trace and hashed logical index snapshot. The filled lock and rebuilt CE
  semantic indexes remain pre-run gates.
- Retrieval-only scorer, answer scorer schema, shard merger, and paired analysis.
  Conflict-safe shard merger and global scoring rubric are ready; scorers and
  paired analysis remain.
- A run manifest recording code revision, model IDs, prompts, seeds, and every
  budget/configuration value. **Template ready** at
  `bench/phase2/run_manifest.template.json`; blinded-arm template ready beside
  it.

Any post-registration change is appended to a deviations section with date and
rationale before affected results are inspected.

## 11. Deviations

### 2026-07-13 — pre-result methodology hardening

No Phase 2 results had been generated or inspected when this amendment was
made. The initial setup language was strengthened after a design audit found
that fixed legacy arm labels, an oracle category router, character-only token
checks, and missing source-offset/provenance contracts could confound an
otherwise fair comparison. The amendment adds dynamic private arm blinding,
query-only routing, strict annotation-manifest linkage/theme validation,
retrieval traces, numerical global scoring, length-repair policy, source-family
independence, hierarchical uncertainty, comparison/error policy, and the
locked CE9010 pilot selection. It does not change or reinterpret any result.

### 2026-07-13 — source-family acquisition and extraction provenance

No Phase 2 result had been generated or inspected. The three previously
reserved held-out families were acquired from their pinned public source
repositories and materialized only as ignored local artifacts: 20 EECS 445
MIT decks, 15 STAT 453 MIT decks, and 10 COMP 599 CC BY-SA 4.0 instructor
decks. The STAT source contains opaque malformed latexit formula-export
payloads; the source manifest therefore declares the narrowly scoped
strip_latexit_payloads_v2 transform, which records raw/canonical hashes and
marker counts. This records corpus provenance and does not alter the
pre-registered comparisons, budgets, or interpretation of any result.

### 2026-07-16 — gate-1/gate-2 measurements and allocation freeze (pre-result)

No Phase 2 retrieval, generation, or judgment result has been produced or
inspected. This entry records measurement outcomes and specification
clarifications, not changes to any comparison, budget, or scoring rule.

- **Reference tokenizer pinned.** The reference tokenizer for all reported
  token counts is the locked embedding model's own tokenizer
  (`qdrant/bge-small-en-v1.5-onnx-q` `tokenizer.json`, sha256
  `d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66`,
  snapshot revision `52398278842ec682c6f32300af41344b1c0b0bb2`), counting
  rule `encode(text, add_special_tokens=False)`. Rationale: it is already
  SHA-pinned by the embedding lock, fully local and deterministic, and one
  measuring stick across arms is what budget parity requires; generator
  tokenizers differ from each other regardless and their actual input/output
  token counts are recorded separately per §5.
- **Model-visible embedding window measured.** By single-token tail
  perturbation with binary search: 510 content tokens visible, position 511
  invisible (= config's 512 positions minus [CLS]/[SEP]). Recorded in
  `bench/phase2/tokenizer-window-measurement.json`; the lock's
  `effective_max_input_tokens` is 510.
- **CE query/passage embedding measured symmetric** for the locked backend
  (byte-identical vectors on two probes); the lock's `query_passage_policy`
  is recorded as `ce_query_embed_measured_symmetric` rather than the
  template's assumed asymmetric value. Implementation fact, no arm change.
- **Corpus measured; inclusion rule confirmed.** All 45 documents exceed
  both limits: min 1,819 / median 5,500 / max 21,007 reference tokens
  (≥3.57× the 510-token window) and all exceed the 8,000-character CE vault
  cap (`bench/phase2/corpus-token-measurement.json`).
- **Evidence-band audit completed** (`bench/phase2/evidence-band-audit.json`):
  130/135 document-bands contain usable natural evidence; the 5 unusable
  bands (code dumps, reference/URL lists, title/activity pages) are excluded
  from question eligibility.
- **Allocation frozen** (`bench/phase2/question-allocation.json`, design
  fixed in `bench/phase2/allocation-design.md` before the audit was read):
  family×band matrices with rows summing to the family quota (10) and
  columns to the band quota (10) per category; every cell feasible after the
  audit with ≥5 documents of headroom, so no reallocation was needed.
- **Multi-hop banding clarified (frozen):** a multi-hop item's evidence band
  is defined only when every required gold span lies in the same normalized
  band (documents may differ). Any fallback requires a further dated
  deviation before results are inspected.
- The prospective power simulation and distractor/theme authoring were still
  open after this entry; both are closed under the 2026-07-17 deviation
  below (provisional power SDs; extractive global themes).

### 2026-07-17 — question freeze + pre-run artifacts (still pre-result)

No Phase 2 retrieval, generation, or judgment result has been produced or
inspected. This entry freezes confirmatory inputs and records open
downstream steps only.

- **90-question set authored and validated** at
  `bench/phase2/annotations.json` (30 single-hop / 30 multi-hop / 30 global)
  via deterministic extractive authoring (`bench.phase2_author_questions`,
  seed `20260717`). Every gold span is an exact unique source substring with
  offsets and bands that pass
  `bench.phase2 validate-annotations --root bench/phase2/corpus`. Method is
  extractive (not free-form LLM prose) so the freeze is fully auditable
  offline; quality is instrumented for a later human/agent polish pass
  without unfreezing IDs if quotes stay fixed.
- **Global atomic themes** authored as two themes per global item, each
  bound to a distinct gold span (validator-enforced).
- **Power simulation** recorded at `bench/phase2/power-simulation.json`.
  CE9010 pilot has no paired arm score deltas yet, so per-question SD is a
  **provisional** hierarchical placeholder. Under `sd_family=0.02`,
  `sd_doc=0.04`, `sd_question=0.20`, the 90-question design reaches
  ~**82.5%** power for Δ=0.10 at Bonferroni 98.33% CI (false-positive
  ~0.25% at Δ=0). Scan across SDs is in the same artifact. Primary
  interpretation remains hierarchical CIs; if empirical pilot SDs later
  exceed 0.20, treat power as exploratory and append a dated deviation
  before claiming powered significance.
- **Private arm map** generated (`bench/phase2/arm_map.private.json`, seed
  `20260717`) and validated against the run manifest's seven public
  `blind-*` codes. Map must not enter model/judge prompts.
- **Run manifest** filled at `bench/phase2/run_manifest.json` (code
  revision, corpus/annotation hashes, lock, public codes, budgets).
  Generation/judge **prompt SHA freezes** and CE wiki provenance hashes
  remain `pending` until prompts are pinned and confirmatory curation
  completes.
- **Chunked raw RAG index** built under the hard lock: 1,093 chunks /
  45 docs; snapshot hash recorded in
  `bench/phase2/chunked-rag-index-meta.json` and the run manifest
  provenance field `chunked_raw_index_snapshot_sha256`.
- **Still open before first generation call:** (1) confirmatory workspace
  trust dialog + CE curate/index for CE arms
  (`~/.cache/sy-phase2-bench/ws` not yet trusted); (2) freeze generation
  and judge prompts (SHA in run manifest); (3) optional human polish of
  extractive question wording without moving gold spans; (4) CE9010
  effort/model calibration smoke on the existing pilot index.

### 2026-07-14 — hard embedding parity lock

No Phase 2 result had been generated or inspected. The earlier wording
“same embedding model where possible” was not enforceable because CE's normal
loader may select `auto` and fall back from fastembed BGE-small to a
sentence-transformers MiniLM space. The preregistration now requires one
explicit, SHA-pinned CE embedding lock, fail-closed loading, deterministic
probe verification, exact vector dimensions, model-artifact/package hashes,
and clean rebuilds of every semantic index before retrieval. The lexical
keyword control remains exempt. This is a pre-result implementation
clarification that removes a backend confound; it does not change an arm,
budget, question, or scoring rule.
