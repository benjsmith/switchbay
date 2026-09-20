# ADR-007: CE ingest-queue → Switchbay local_ingest / rail drain

- **Status:** Accepted
- **Date:** 2026-09-20
- **Parent:** skill-shell rationalization (CE drop-ingest + pack-run drain parity)
- **Related:** ADR-006 (CE pack-queue → rail LLM drain)
- **Deciders:** Ben / skill-shell rationalization charter

## Context

Curiosity Engine's drop-ingest (`POST /api/ingest/from-upload` /
`from-path`, filebrowser + `/embed/ce/`) stages bytes under
`vault/raw/` and writes only:

```text
.workbench/ingest-runs/<run_id>.json   # status: "queued", mode: "staged"
```

It does **not** run `local_ingest.py` or seat an LLM agent. Pack-runs
already drain via Switchbay (`POST /api/packs/drain`, ADR-006). Without
a sibling drain, ingest-runs sit `queued` forever after drop.

Both processes share the workspace tree, so the queue files are the
handoff surface.

## Decision

1. **Switchbay drains the shared JSON** (no CE `PATCH` required).
   Module `switchbay.ingest_run_drain`:
   - `list_queued_runs` / `write_run_status` (atomic JSON rewrite)
   - `resolve_run_vault_path` — refuse workspace escape / null bytes
   - Prefer **deterministic** `local_ingest` (`ce_tools._ce_ingest`)
     for normal vault sources (`mode: staged` and peers)
   - Escalate to `_dispatch_chat` only when metadata opts in
     (`mode`/`drain` ∈ {llm,rail,agent,dispatch} or
     `prefer_rail` / `use_llm` truthy)
   - `drain_once` — mark `running`, spawn local or rail task, on
     completion mark `done` / `failed`
   - In-memory `app["ingest_run_inflight"]` dedupes concurrent drains

2. **Triggers**
   - Background poll every ~4s while
     `<workspace>/.workbench/ingest-runs/` exists
   - Explicit `POST /api/ingest/drain` → `{drained, skipped, errors}`
   - Opportunistic kick from `_broadcast_files_changed_soon` when
     the ingest-runs dir is present

3. **Out of scope:** rewriting CE's queue writer, changing
   Switchbay's own multipart `/api/ingest/from-upload` (still seats
   rail immediately for non-CE uploads), multimodal CURATE waves.

## Consequences

- CE remains the sandbox/stage edge; Switchbay remains the ingest
  executor. Status fields on the shared JSON are the cross-process
  progress UI.
- Default path stays cheap (no paid model seats). LLM only when the
  run record asks for it.
- Tests mock `local_ingest_fn` / `dispatch_fn` — no CE binary or paid
  model seats in CI.
