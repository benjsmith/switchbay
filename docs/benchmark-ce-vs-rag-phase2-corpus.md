# Phase 2 corpus-selection record

**Status:** the CE9010 position-controlled pilot is locked. Three held-out
source-family selections are now pinned and locally extracted, but the
cross-course confirmatory run remains gated. No Phase 2 retrieval, generation,
or judgment result has been inspected.

## Decision

LectureBank is used as a source registry, not as a redistributable corpus. Its
metadata links to third-party files and LectureBank itself does not grant a
repository-wide content license. The first vetted source is the CE9010:
Introduction to Data Science course, selected from LectureBank 2.0 records
476 through 485.

- Registry: https://github.com/Yale-LILY/LectureBank
- Source: https://github.com/xbresson/CE9010_2018
- Pinned source commit: 996ba323d2400ff789599e59ddad99263b68a74b
- Terms checked at that commit: MIT License, copyright Xavier Bresson (2018).
- Tracked selection specification:
  bench/phase2/source-manifests/lecturebank-ce9010-pilot.json
- Local generated corpus manifest:
  bench/phase2/corpus/lecturebank-ce9010/corpus_manifest.json
  (intentionally ignored, since it is a generated artifact).

The extractor verifies the commit, license hash, and every source-PDF hash
before producing canonical UTF-8 text. It makes no network request and keeps
the raw extractor bytes, including form-feeds, rather than silently cleaning
the source. Its command is documented in bench/phase2/corpus/README.md.

## Pilot inventory

The locked source specification contains only the ten LectureBank-linked course
slides, not tutorials, student projects, or unrelated repository files.
Canonical extraction was checked with pdftotext version 26.04.0.

| LectureBank ID | Topic | Pages | Unicode characters | Whitespace words |
| --- | --- | ---: | ---: | ---: |
| 476 | Introduction to Data Science | 23 | 13,400 | 929 |
| 477 | Learning Techniques | 30 | 12,300 | 985 |
| 478 | Supervised Linear Regression | 81 | 71,112 | 4,691 |
| 479 | Supervised Classification | 42 | 36,034 | 2,411 |
| 480 | Gradient Descent Tricks | 25 | 15,831 | 1,056 |
| 481 | Generalization and Regularization | 32 | 22,934 | 1,728 |
| 482 | Developing Data Science Projects | 52 | 46,394 | 3,423 |
| 483 | Unsupervised Learning | 66 | 57,227 | 3,392 |
| 484 | Recommender Systems | 31 | 31,959 | 2,154 |
| 485 | Neural Networks | 62 | 69,987 | 3,947 |

Every document exceeds the existing whole-source vault's 8,000-character
vector cap and has substantially more than the approximate 512-token
embedding window. A head/middle/tail visual and text extraction check of the
62-page Neural Networks deck confirmed that the material remains readable
through the final section. Before questions are written, the actual frozen
tokenizer must still record exact token counts and the exact model-visible
embedding limit.

## Scope and independence

This corpus is intentionally useful for a controlled truncation and
evidence-position pilot: all ten long documents are from a single coherent
course, source version, and license. It is not suitable by itself for a
cross-course generalization claim. It may calibrate extraction, annotations,
trace provenance, budget enforcement, and tail retrieval, but cannot decide a
confirmatory CE-versus-RAG headline.

The held-out local corpus is specified by
bench/phase2/source-manifests/confirmatory-families.json. It contains 45
canonical-text documents in three independent course-source families:

| Family | Pinned source and terms evidence | Selected long documents | Extraction / boundary |
| --- | --- | ---: | --- |
| University of Michigan EECS 445 | MIT; commit 298407af9fd417c1b6daa6127b17cb2c34c2c772 | 20; 9,924–59,068 characters | Canonical lecture PDFs only; excludes discussion, hands-on, PPTX duplicate, short Lecture 3, and supplemental EM notes. |
| UW–Madison STAT 453 | MIT; commit 61534929fe671b30e751733577d0c2b5d4898669 | 15; 15,770–75,306 characters | LectureBank-mapped instructor decks L01–L15 that clear the long-document threshold. strip_latexit_payloads_v2 removes only opaque formula-export payloads; raw and canonical hashes plus marker counts are recorded per document. |
| McGill COMP 599 | CC BY-SA 4.0 “unless otherwise noted” in the README; commit a15bc199536cd7a3860469965eb04bf4612a7e73 | 10; 8,750–25,815 characters | Long core instructor decks only; excludes guest/student decks, Project/, and short core decks. |

Each selection specification pins the source commit, license-evidence hash,
source-PDF hashes, page counts, extractor configuration, and every selected
LectureBank ID. The ignored local aggregate manifest
bench/phase2/corpus/lecturebank-long-document-confirmatory-v1-manifest.json
links every document to its source family and selection hash for hierarchical
analysis.

The published repository terms support source acquisition and private local
evaluation under the stated MIT or CC BY-SA terms. That is not a claim that
every embedded image, quotation, or cited reading is independently
redistributable. Raw PDFs and generated text therefore remain ignored; publish
only the acquisition tooling, provenance metadata, and derived aggregate
statistics unless a separate asset-level redistribution audit is completed.

Development and held-out questions must be split by entire course family, never
by individual slide deck. CE9010 remains development/pilot-only and is not one
of the three confirmatory families.

## Gates before a model call

1. Freeze the local reference tokenizer and actual model-visible token budget;
   preserve full rendered-prompt token counts per generator.
2. Freeze the exact tokenizer and actual model-visible embedding window, then
   verify every selected document exceeds the resulting window and record its
   token count. The three source-family selections and text hashes are ready.
3. Create and SHA-pin `bench/phase2/embedding_lock.json`. It must name the
   exact CE embedder/config, explicit backend/model, package and model-artifact
   hashes, dimension, deterministic probe, and effective embedding limit.
   Rebuild every semantic CE index and the raw chunked index from this lock;
   no historical index or backend fallback is admissible.
4. Freeze the CE curation/provenance contract: raw input, extraction,
   curator model/prompt/config, wiki and graph snapshots, source-to-wiki
   coverage, and exact wiki-to-raw evidence mapping.
5. Annotate balanced natural head, middle, and tail evidence spans; tail spans
   must lie beyond the measured embedding limit and outside artificial chunk
   boundary edge cases unless boundary robustness is the explicit condition.
6. Freeze questions, atomic themes, weights, scoring rubric, randomized private
   arm map, all retrieval configurations, and retry/failure policy.
