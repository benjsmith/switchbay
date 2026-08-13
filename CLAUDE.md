# Orientation for Claude sessions

Switch Bay is a local single-user workbench over knowledge bases: one
Python daemon (`src/switchbay/`) + a browser frontend (`frontend/`),
talking over a WebSocket. Start with the **README** for the run-dev
workflow and architecture, and skim `docs/concepts-and-data-flow.md`.
Provider implementation state (first-class vs preview) is
`docs/providers.md` — don't treat every picker row as equivalent.

Don't run `python` / `pip` / `npm` directly — use `make` for Python and
`pnpm --dir frontend` for JS.

> If this checkout carries local project docs (`charter.md`,
> `work-plan.md`, `log.md`), read them first — they're the canonical
> record of architectural intent and current plan, and override this
> file where they disagree. They're git-ignored (private working notes),
> so a fresh clone won't have them; this file is the durable public
> orientation.

## Common slips to avoid

- Don't add a `kind: slides` ontology back, **nor a reveal.js "Slides"
  tab** (removed as flaky + redundant). Sketch decks (`kind: deck`),
  authored/viewed in the **Sketch tab carousel**, are the only deck
  surface; reveal.js / pptx are *export* targets (`deck_export.py`), not
  a tab or parallel format.
- The `curiosity-engine` skill is a **read-only upstream dependency** —
  Switch Bay consumes its retrieval/graph substrate (shell out, read its
  DBs); never modify or re-implement it.
- Don't pull a heavy UI framework (no React-heavy kits) or LiteLLM.
- When picking package versions, ensure none is younger than 48 hours
  (prompt-injection mitigation; project policy).
