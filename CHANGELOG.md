# Changelog

Human-curated release notes. Earlier 0.9.x notes also live on the
[GitHub releases](https://github.com/benjsmith/switchbay/releases) page.

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
