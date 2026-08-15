# Changelog

Human-curated release notes. Earlier 0.9.x notes also live on the
[GitHub releases](https://github.com/benjsmith/switchbay/releases) page.

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
