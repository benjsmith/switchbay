# ADR-006: CE pack-queue → Switchbay rail LLM drain

- **Status:** Accepted
- **Date:** 2026-09-19
- **Parent:** skill-shell rationalization (CE filebrowser packs Phase 2b)
- **Deciders:** Ben / skill-shell rationalization charter

## Context

Curiosity Engine's proxied filebrowser accepts
`POST /api/packs/<pack>/action/<action>` and, after sandbox checks,
writes only:

```text
.workbench/pack-runs/<run_id>.json   # status: "queued"
```

It does **not** seat an LLM agent. Switchbay already has
`handle_pack_action` which seats `_dispatch_chat` with skill
`<pack>-<action>`, but the CE path never hits that handler — so
CE-queued runs stayed `queued` forever.

Both processes share the workspace tree, so the queue files are the
handoff surface.

## Decision

1. **Switchbay drains the shared JSON** (no CE `PATCH` required).
   Module `switchbay.pack_run_drain`:
   - `list_queued_runs` / `write_run_status` (atomic JSON rewrite)
   - `build_pack_prompt` — same text as `handle_pack_action`
   - `drain_once` — validate pack enabled + skill exists, mark
     `running`, spawn `_dispatch_chat` (injectable for tests), on
     task completion mark `done` / `failed`
   - In-memory `app["pack_run_inflight"]` dedupes concurrent drains

2. **Triggers**
   - Background poll every ~4s while
     `<workspace>/.workbench/pack-runs/` exists
   - Explicit `POST /api/packs/drain` → `{drained, skipped, errors}`
   - Opportunistic kick from `_broadcast_files_changed_soon` when
     the pack-runs dir is present

3. **Out of scope (this ADR):** reveal-in-OS, drop-ingest, rewriting
   CE's queue writer, and refactoring `handle_pack_action` to also
   write pack-runs JSON (nice-to-have; CE files are the required
   consumer).

## Consequences

- CE remains the sandbox/accept edge; Switchbay remains the skill/LLM
  seat. Status fields on the shared JSON are the cross-process progress
  UI.
- Tests mock `dispatch_fn` — no paid model seats in CI.
