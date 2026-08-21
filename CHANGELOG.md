# Changelog

Human-curated release notes. Earlier 0.9.x notes also live on the
[GitHub releases](https://github.com/benjsmith/switchbay/releases) page.

## 2026-08-21 — v0.9.17 — enterprise bake

**Migration:** none. **Breaking:** none.

`scripts/bake_enterprise.py` builds an Intune or Jamf installer tree
from the GitHub release archive. Endpoint management may deploy that
tree unsigned (path allowlist on the install directory) or after the
organization signs it. Procedure:
[`enterprise/packaging/README.md`](enterprise/packaging/README.md).

### Added

- **Packaging script** — applies Copilot host, Hugging Face, and skills
  policy; writes the Windows layout and `install.ps1`, or a macOS
  package with LaunchAgent. `make enterprise-bake PAYLOAD=…`.
- **Deployment models** — management-deployed unsigned, or
  organization-signed. SentinelOne: allow the install directory, or
  pin `switchbay.exe` after it is signed.

### Version

0.9.17 (micro). History retained.

## 2026-08-21 — v0.9.16 — enterprise SOC candidate

**Migration:** none for the default **open** profile. **Breaking:** none
on open. Enterprise payloads on this tag are the ones to wrap for a
laptop fleet.

Unsigned Win11 x64 + darwin arm64 trees attach as the workflow
finishes. Company bake Authenticode-signs / notarizes. Playbook:
[`enterprise/packaging/README.md`](enterprise/packaging/README.md).

A 4B MLX local model on a 16 GB Mac survives wiki Q&A (search → read
→ clickable `[[wikilink]]`) without Metal OOM.

### Added

- **Fleet kit** — CPython host (`switchbay.exe`), Edge GUI launcher,
  WiX skeleton + Active Setup, macOS Safari stub + pkg script,
  Intune Win32 fields, SentinelOne exclusions (`switchbay.exe`, not
  `python.exe`), `harvest.py`.
- **HTTP egress gate** — enterprise allows loopback + Copilot/GHE
  (+ HF only if baked on).
- **Tighten-only baked policy** — MDM overlay cannot re-enable a
  baked-off feature. Stamp `hf_model_download` / Copilot host at bake.
- **Win11 ConPTY** — rail terminal matches VS Code's default.
- **Wiki cite on local answers** — host appends `[[page]]` if the
  model forgets; `read_wiki_page` keeps path/title under the token cap.

### Fixed

- **4B Metal OOM** — MLX is a local desk even when the harness still
  says `applies_to: llamacpp`. Prompt-cache / concurrency caps on
  `mlx_lm.server`. Tool JSON clipped in place, not smashed to a
  preview string.
- **`what` as a shell command** — `/usr/bin/what` on macOS no longer
  hijacks "what do we know…".

### Version

0.9.16 (micro). History retained.

## 2026-08-20 — v0.9.15 — Windows paths

**Migration:** none. **Breaking:** none.

Wiki proposals, CE script allowlist matching, and local-server stop
work on Windows. 0.9.14's payloads still attached; wrap **this**
tag for Win11.

### Fixed

- **Wiki proposals** — stored paths are posix (`wiki/concepts/…`) so
  `_writable_rel` accepts them on Windows.
- **CE toolscope** — command prefixes use `as_posix()`, so a Windows
  `uv run python3 C:\…\scripts\sweep.py` matches.
- **SIGKILL** — `getattr(signal, "SIGKILL", SIGTERM)` so Stop doesn't
  crash on Win32.
- **MLX cache bytes** — case-insensitive hub dir match (Linux CI).

### Version

0.9.15 (micro). History retained.

## 2026-08-20 — v0.9.14 — enterprise profile

**Migration:** none for the default **open** profile. **Breaking:** none
on open. `SWITCHBAY_PROFILE=enterprise` (or a machine admin file) locks
to Copilot + local and turns EDR-noisy hooks off.

One codebase, two profiles. Open is today's product. Enterprise is a
flag. Admins may set `features.hf_model_download` true. Windows stop
no longer kills every `python.exe`. CI ships frozen Win11 x64 and
macOS darwin arm64 trees for packaging teams.

### Added

- **Profiles** — `open` (default) vs `enterprise`. Machine admin file
  at `%ProgramData%\SwitchBay\admin.json` / `/Library/Application
  Support/SwitchBay/admin.json`. Template: `config/admin.enterprise.json`.
- **HF downloads admin-opt-in** — enterprise default off; set
  `features.hf_model_download` true to restore Settings → Find & install.
  On-disk models still work when off.
- **Enterprise payloads** — release assets
  `switchbay-enterprise-win11-x64.zip` and
  `switchbay-enterprise-darwin-arm64.tar.gz` (relocatable CPython +
  `frontend/dist`). See `enterprise/packaging/README.md`.

### Fixed

- **Windows service stop** — `taskkill /PID` of the daemon pidfile,
  never `/IM python.exe`.
- **In-app restart** — `python -m switchbay service restart`, not Make.
- **Windows import** — `terminals.py` no longer imports `pty` at
  module level. Interactive PTY stays Unix-only.

### Version

0.9.14 (micro). History retained.

## 2026-08-20 — v0.9.13 — rail picker

**Migration:** none. **Breaking:** none.

The rail model picker opens again. 0.9.11's long-id ellipsis set
`overflow: hidden` on the 34px rail header, which clipped the menu
so a click looked like a no-op.

### Fixed

- **Rail model picker** — menu is no longer clipped by the rail head.
  Long labels still ellipsize on the pill.

### Version

0.9.13 (micro). History retained.

## 2026-08-20 — v0.9.12 — help versions

**Migration:** none. **Breaking:** none.

The Help panel (top-right ?) now shows the running Switch Bay version
and the related curiosity-engine / curiosity-merge versions. Copy
caught up with Power vs Zen, Library, custom tabs, and `/rescan`.

### Added

- **Help → versions** — Switch Bay plus installed curiosity-engine /
  curiosity-merge. npx skill installs without a git tag fall back to
  this release's pairing (CE v1.3.0, merge v0.7.0).

### Changed

- Help text: Power vs Zen, Library + custom tabs, rebuild viewer vs
  `/rescan` for stale Browser folders.

### Version

0.9.12 (micro). History retained.

## 2026-08-20 — v0.9.11 — local desks, honest watch

**Migration:** none. **Breaking:** none.

A 4B local curate no longer dumps the full tool rail (~15k prompt
tokens), Metal-OOM, and stream garbage. RAM-scaled desks plus
slash-specific palettes keep the request inside the budget. Watch
and Stop follow the server that is actually serving. Settings can
pull a GitHub release.

### Fixed

- **Local curate OOM / garbled rail** — the 4B path was offered every
  rail tool. Mid-generate Metal OOM still returned SSE 200 with
  `Privacy Privacy` junk. Local models now get a RAM-scaled desk
  (16–128 GB, capped by loaded model size) and a token budget.
  Incomplete / OOM streams surface as errors. The host runs the
  mechanical sweep so a small model is a worker, not the sweeper.
  Small rungs write Reviews scaffolds, not invented prose.
- **Watch / Stop leftover servers** — Watch always tailed
  `llama-server.log` while MLX wrote `llama-server-mlx_*.log`.
  Settings showed SERVING with no Stop when an orphan
  `start_new_session` process held the port. Watch follows the
  active slot; Stop reaps the port; spawn frees leftovers first.
- **Slash palettes** — `/curate` used the curate desk; deck populate
  and a user `/create-deck` still got the default local chat list
  (deck tools banned). Each agent-backed slash now loads only the
  tools it needs, clipped to the budget. Customize on Agent
  Dashboard → Command palettes.
- **MLX model alias** — a request that did not match `default_model`
  404'd. Alias and default now agree.
- **`yes` as chat** — typing "yes" in the rail no longer spawned the
  unix `yes` command in a new shell thread.
- **Graph remount / Atlas click** — a wiki refresh no longer drops
  the highlight or races the page closed then open again.

### Added

- **Settings → Update** — compare running Switch Bay / curiosity-engine
  / curiosity-merge to GitHub latest and apply in place, then restart.
- **Workspace plan tools** — charter / work-plan / log under
  `.workbench/plan/`.
- **Progressive `load_skill`** — frontmatter first, then one section;
  global skill reads do not raise a permission card.
- **macOS TCC notes** — python3.13 "other apps" / Keychain prompts
  documented in the README (expected on first start).

### Version

0.9.11 (micro). History retained.

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
