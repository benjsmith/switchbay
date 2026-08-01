---
title: "[src] Accelerating Large Language Model Decoding with Speculative Sampling — Chen et al., 2023"
type: source
created: 2023
updated: 2026-07-29
sources: [20260728-230735-local-leviathan-2023-speculative-sampling.pdf.extracted.md]
vault_sha256: 4029b03ccb088f675547e1a378c6c03ea71e6ae6582334b8c1eaec3dbf28507f
attribution_corrected: 2026-07-29
---

Speculative sampling, an algorithm for accelerating transformer decoding by enabling the generation of multiple tokens from each transformer call (vault:20260728-230735-local-leviathan-2023-speculative-sampling.pdf.extracted.md).
Benchmarked with Chinchilla, a 70 billion parameter language model. Authors: Charlie Chen, Sebastian Borgeaud, Geoffrey Irving, Jean-Baptiste Lespiau, Laurent Sifre, John Jumper — all from DeepMind.

**Attribution corrected 2026-07-29.** This vault entry was ingested with mismatched
metadata: its attribution record carries the title *Fast Inference from Transformers via
Speculative Decoding* (Leviathan, Kalman & Matias) paired with `arxiv_id: 2302.01318`.
Those belong to two different papers. 2302.01318 is Chen et al.'s *Accelerating Large
Language Model Decoding with Speculative Sampling*; Leviathan et al. is arXiv 2211.17192.
The PDF was fetched from the ID, so **the stored PDF and its extraction are Chen et al.** —
the title metadata is what was wrong.

The two are genuinely distinct, concurrent 2023 papers describing the same technique, and
the Chen et al. paper explicitly notes the concurrence. Anything sourced from this entry
must be attributed to Chen et al. and DeepMind, not to Leviathan et al.

**Why the stem still reads `leviathan-`.** `naming.py` derives source-stub stems from the
extraction's frontmatter, which still carries `author: leviathan`. Renaming the stub here
would be undone by the next `sweep.py fix-source-stubs` run. The stem is therefore a
legacy identifier, not a claim about authorship. The durable fix is a re-ingest with
corrected metadata, which is a vault operation — vault files are append-only and the
curator does not edit them.

Concept page: [[speculative-decoding]].

<!-- extracted-tables -->
## Extracted tables (2)

- [[tab-leviathan-2023-fast-inference-from-t1]] — Table p.6 — Table 1: Chinchilla performance and speed on XSum and HumanEval with naive (ArS) and speculative (SpS) sampling at batch size 1 and K = 4. XSum used nucleus parameter p = 0.8; HumanEval used p = 0.95 and temperature 0.8.
- [[tab-leviathan-2023-fast-inference-from-t2]] — Table p.10 — Table 2: Hyperparameters for the draft model (compared against the Chinchilla target model)
<!-- /extracted-tables -->
