# Changelog

Human-curated release notes. Earlier 0.9.x notes also live on the
[GitHub releases](https://github.com/benjsmith/switchbay/releases) page.

## 2026-08-18 — v0.9.10 — new-install pin, global skills, honest picker

**Migration:** none. **Breaking:** none.

A new Mac with system Python 3.14 can install CE/kuzu. Skills resolve
from `~/.agents/skills` without Claude Code. Copilot and other
HTTP/CLI providers can run CE scripts as Switch Bay tools. The rail
picker only lists signed-in / present models. Atlas first paint is
the individual-node log-rim.

### Fixed

- **CE install on Python 3.14** — workspace `.venv` is pinned to 3.13
  (kuzu has no newer wheel). `install.sh` / daemon setup install the
  global curiosity-engine skill non-interactively (`skills add -g -y`).
- **Global skills without Claude Code** — discovery and new user
  skills use `~/.agents/skills` (the `npx skills add -g` target).
  `~/.claude/skills` is still scanned when present. CLI spawns set
  `CURIOSITY_ENGINE_SCRIPTS_DIR` so Copilot / Grok / Codex / Muse
  find CE without a Claude skill tree.
- **CE tools on HTTP providers** — every CE script is a Switch Bay
  tool (`ce_run` + first-class wrappers). Copilot no longer has to
  fake the skill from a sandbox without it.
- **Rail model picker** — hide unsigned / unavailable providers
  (Claude Code CLI present but not logged in is hidden). Copilot /
  MLX / llama.cpp / Ollama lists match Settings (live, not a 24h
  stale suggestion set).
- **Wiki browser after authoring** — new pages are injected into the
  viewer bundle, `[[wikilinks]]` are wired deterministically, and
  kuzu is rebuilt so the wiki list and graph update without `/curate`.
- **Plot → figure** — caption, origin, and related pages ride along
  as frontmatter + `[[wikilinks]]`.
- **Proposal review** — View stashes the report so the Reports tab
  is not empty; Accept refreshes the wiki browser and graph.
- **Atlas first paint** — opens as individual nodes with
  log-compressed rim scaling, not clustered type bubbles. Dragging the
  boundary streams the corpus (streaks + nodes/s) instead of panning
  the middle graph.

## 2026-08-17 — v0.9.9 — local MLX, plot legends, sheet SQL

**Migration:** none. **Breaking:** none.

Detect MLX weights already on disk (including other apps' Hugging Face
caches). Plot cards keep a category color legend. Table/Sheet SQL can
read workspace CSVs in DuckDB-WASM. Unsent composer text survives a
Zen ↔ Power switch.

### Fixed

- **Plot color legend** — `legend: null` on one layer no longer hides
  the shared category key (countries vanished; only dash style
  remained). Row-facet headers sit above each panel instead of
  colliding with the y-axis title. The card no longer paints a native
  “Double-click to edit” tooltip over the chart.
- **Table / DuckDB-WASM** — `read_csv_auto('/api/fs/raw/…')` and
  host-absolute paths failed in the browser. Workspace files are
  registered as buffers; SQL paths are rewritten. BigInt cells no
  longer crash `JSON.stringify`.
- **Sheet** — reuse a sheet by name instead of creating `…NG1`
  duplicates. `sheet_set_values` writes a grid in one call.
- **Grok Build spawn** — 1.0.4 rejects `--deny NotebookEdit(*)`;
  unknown deny prefixes are skipped.
- **PWA mid-restart** — a 503 while `frontend/dist` is missing is now
  a self-reloading HTML page instead of a dead “frontend not built”
  text response.
- **Settings selects** — ladder provider/model menus no longer wrap
  one letter per line.
- **Composer drafts** — unsent Zen/Power text is kept when switching
  modes or mid-prompt model picker.

### Added

- **On-disk MLX** — Settings → Local agent model lists MLX snapshots
  already in Hugging Face hub caches (including sandboxed Mac app
  caches). **Use this** starts `mlx_lm.server --model <snapshot>`
  without downloading again.
- **Per-rung effort** — each ladder row has its own effort control.

### Version

0.9.9 (micro). History retained.

## 2026-08-16 — v0.9.8 — Atlas click + preview sources

**Migration:** none. **Breaking:** none.

Clicking an Atlas node in Zen opens the page in the Editor. The Editor
preview now parses YAML source lists (same as the Graph modal) and
collapses long `sources` blocks in both previews.

### Fixed

- **Atlas node click** — a single click writes the page selection
  (hover id on pointer-down, plus `focus-changed`). Zen switches to
  the Editor; Power still opens the Graph modal. Hover no longer
  leaves a sticky focus ring on the previously clicked node.
- **Editor YAML lists** — `sources:` block lists and `[flow]` lists
  were dropped by the one-line frontmatter reader, so the preview
  showed an empty sources cell.

### Added

- **Collapsible sources** — lists with more than one entry start
  collapsed (`▸ N sources`) in the Editor preview and the Graph doc
  modal. Open/closed is remembered across pages.

### Version

0.9.8 (micro). History retained.

## 2026-08-15 — v0.9.7 — Atlas minimap wheel zoom

**Migration:** none. **Breaking:** none.

Wheel-zoom while hovering the overview map now works in Atlas the same
way it already did in Classic. In Zen the map re-parks from the live
chat-box / pill rectangle, so float, tab, and collapse do not cover it
or swallow the gesture.

### Fixed

- **Atlas minimap wheel** — the overview canvas sat on top of the
  plotting area with no wheel handler, so hover-zoom died. The host now
  forwards that wheel to the main Atlas canvas, keeping the current
  view centre (Classic's contract).
- **Zen map lift** — `--sy-minimap-bottom` is measured from the graph
  pane vs the floating box or collapsed pill, not a fixed `boxH + 30`.
  Docked chat (right-pane tab) leaves the map in the default corner.

### Version

0.9.7 (micro). History retained.
