# Changelog

Human-curated release notes. Earlier 0.9.x notes also live on the
[GitHub releases](https://github.com/benjsmith/switchbay/releases) page.

## 2026-09-07 — v0.12.14 — Switch Bay VS 0.3.17

**Migration:** none. **Breaking:** none. After pull, run
`make refresh BUILD=1` (frontend changed). No new VSIX.

Standing desks, wiki lookup, and HTML slideshow quality (desk kernel
on `main` plus the follow-up).

### Added

- **Standing desks.** `/curate`, `/work`, and `/code` always seat a
  named desk (working / quiet / dismissed). Authoring an HTML slideshow
  reuses one Deck desk. Wiki questions (`what do we know about X`)
  take the fast lookup path and do not seat. Agents → Desks: Start
  (resumes a quiet DAG), Edit, Dismiss, Schedule. `/steer` remains a
  silent alias of `/work`.
- **HTML slideshow layouts** for quotes, stats, charts, compare,
  timeline, and wiki tables. `create_slideshow` refuses curator-speak
  and drops ingest/TODO punch-list slides. `[[slideshow:slug]]` in the
  rail and Zen chat opens the Slideshow tab.

### Changed

- Copilot, MLX, and llama.cpp drive `/curate` and Deck through the
  host tool loop (no shell). Ollama stays chat-only and cannot curate.
  Small local Deck workers keep `create_slideshow` with a compact wiki
  set; ram16 rail palettes still omit it.
- Enterprise `media_generation: false` skips slideshow image generation.
- Stop cancels in-flight sibling workers; Dismiss marks the run
  dismissed and only clears the org this desk owns.
- A schedule `until_at` window disables that row. It only quiets a
  standing desk when the row names one (`desk_id`), and Start can
  still resume.

### Fixed

- `wiki_table` inlines the wiki cells, not an agent-invented `table`
  under a wiki cite.
- Compare slides count as a visual; title + compare + close is a
  valid deck.
- `wiki_table` / `quote_from` refuse paths outside the workspace.
- The SSRF unit test no longer hits real DNS (that broke later
  `git init` forks on macOS).

## 2026-09-04 — v0.12.13 — Switch Bay VS 0.3.17

**Migration:** none. **Breaking:** none. After pull, run
`make restart`. No frontend rebuild. No new VSIX.

### Added

- **Copilot `/responses` for models that refuse chat completions.**
  Newer GPT/Codex rows that only advertise `/responses` now appear
  in the picker. Switch Bay posts `/chat/completions` when the
  catalog lists it, `/responses` otherwise, and retries the other
  path on a 400 `unsupported_api_for_model` so model switching stays
  seamless. Tool-less and non-chat rows stay hidden.

### Changed

- **The rail picker is the primary model** for questions, `/curate`,
  and the chief of staff. Auto may still assign other
  dashboard-allowlisted models to workers for opinion independence
  or token efficiency (local backends count as maximally
  token-efficient).
- Copilot IDE headers match current VS Code Copilot Chat
  (`vscode/1.137.0`, `copilot-chat/0.65.0`). Tool turns send
  `Openai-Intent: conversation-agent` and `X-Initiator: agent`.
- Cold-cache Copilot suggestions drop `gpt-5-mini`. Live
  `GET /models` remains authoritative.

## 2026-09-02 — v0.12.12 — Switch Bay VS 0.3.17

**Migration:** none. **Breaking:** none. Sideload the new VSIX
(`make vsix` then `code --install-extension dist/switchbay-vs-0.3.17.vsix`)
and **Developer: Reload Window**. No daemon restart.

### Added

- **Wiki and Files name the attached wiki.** Both Switch Bay VS
  sidebar views show the wiki folder (`curiosity-test`) as the first
  row and as the view subtitle, so a code-repo window is not mistaken
  for the wiki.
- **Graph search highlights files.** A Files tree (`wiki/` + `vault/`
  on disk) sits under Wiki. Graph search marks matching Wiki pages and
  Files rows, expands to the first page hit, and still badges Explorer.

## 2026-09-02 — v0.12.11 — Switch Bay VS 0.3.16

**Migration:** none. **Breaking:** none. After pull, run
`make restart` — launchd has to reload so it drops the old log fd.
No frontend rebuild.

### Fixed

- **The daemon log grew without bound and hid every real error.**
  launchd pointed stdout and stderr at
  `~/Library/Logs/switchbay-daemon.log` and never rotated it, so a
  300+ MB file of `GET /api/health` / `GET /api/runs/active` (the
  clients poll those every 1–2 s) buried the trail you need when the
  daemon wedges. Python now owns that file with a 100 MB rotating
  handler (one backup); launchd stdio goes to `/dev/null`. Successful
  hits on those two endpoints are no longer access-logged; 4xx/5xx
  still are. `make restart` rewrites the plist so an existing agent
  picks this up.

## 2026-09-01 — v0.12.10 — Switch Bay VS 0.3.16

**Migration:** none. **Breaking:** none. Skill bump only — no app code
changed since v0.12.9.

### Changed

- Bundled skills move to **curiosity-engine v1.5.0** (graph search in the
  CE viewer, one mark per hit, the Classic/Atlas chooser always offered)
  and **curiosity-merge v0.8.2** (unmerge reverses identity `same_as`;
  source-stub wikilink folding).
- Verified before adopting: the subgraph export the workspace-split tool
  shells out to is byte-identical between curiosity-merge v0.8.0 and
  v0.8.2, as is its one import (`preflight.py`). The files the unmerge
  work touched — `identity.py`, `reconcile.py`, `unmerge.py`, `merge.py`
  — are never imported by the exporter, and Switch Bay never invokes
  `unmerge`. A live export of three pages under both versions produced
  byte-identical trees (3 pages, 11 vault files) and identical manifest
  keys.

## 2026-09-01 — v0.12.9 — Switch Bay VS 0.3.16

**Migration:** none. **Breaking:** none. After pull, run
`make refresh BUILD=1`.

### Fixed

- **The Update button could not recover from a rewritten release tag.**
  `git fetch --tags` refuses to move a local tag that points elsewhere
  and fails the *whole* fetch with "would clobber existing tag", so one
  force-pushed tag upstream left Update permanently failing until
  someone deleted tags by hand in a terminal. The updater now fetches
  with `--force --prune-tags` — for a thing whose job is "put me on the
  published release", the published tag is the truth — and says what a
  failed fetch means instead of quoting git at you.
- **Help reported skill versions from a constant.** `related_version`
  was a number compiled into Switch Bay and shown as the installed
  skill's version, so it was right only until the next skill release.
  It is gone. Versions now come from the install itself (git tag, or
  the skill's own CHANGELOG); a skill carrying neither —
  curiosity-engine keeps its changelog outside the installed tree — is
  identified by matching its SKILL.md against recent releases, memoized
  per install. Offline, Help says "installed" rather than printing a
  version nobody verified.
- Graph search no longer binds `⌘F`. Scoped to the graph pane, it only
  fired when focus happened to be there; everywhere else the browser's
  own find bar opened, so the shortcut produced two search boxes.

## 2026-09-01 — v0.12.8 — Switch Bay VS 0.3.15

**Migration:** none. **Breaking:** none. After pull, run
`make refresh BUILD=1` — the version fix is server-side, so the daemon
has to restart before Help shows the right number.

### Fixed

- **Help reported v0.12.1 on every release since v0.12.1.** The release
  checklist bumped `pyproject.toml`, `package.json` and the docs but not
  `switchbay.__version__`, which is what Help → versions and the update
  checker read — so a current install looked five releases stale and was
  offered "updates" it was already past. `tests/unit/test_version_sync.py`
  now fails the build when the version, the frontend package and the
  newest CHANGELOG heading disagree.
- A wikilink that resolves to nothing now says so instead of failing
  silently — a dead link and a broken click handler looked identical.

## 2026-09-01 — v0.12.7 — Switch Bay VS 0.3.14

**Migration:** none. **Breaking:** none. After pull, run
`make refresh BUILD=1`.

### Changed

- **The agent DAG follows the plan's own dependencies.** Lineage was
  inferred from node *kind*, which made the blackboard the parent of
  every verify/synthesize node: a lone synthesizer hung off the board
  with no chief edge at all, and the board looked like it was running
  the orchestration. A node now hangs off its declared dependencies, or
  off the chief when it has none, and the board gets one edge per worker
  pointing the way that worker uses it.
- **Token and tool pulses travel the dispatch edge**, not to the
  blackboard. Board traffic is drawn only when the board actually gains
  a row — each row names the node that posted it. An idle board no
  longer looks busy.
- The daemon no longer announces verify/synthesize nodes as
  `blackboard → node`. The dispatcher is the chief (or the node's
  dependencies); the board gets its own `reads` handoff, and only when
  it has something on it.

### Added

- **Editor: wikilinks are clickable.** `[[links]]` in the preview render
  as `#page=<link text>`, which the hash router could not resolve to a
  page id, so clicking did nothing. They now go through the same fuzzy
  resolver the rail uses (id, path stem, title) and open in the Editor
  rather than bouncing to the Graph tab.
- **Editor: a Back button** (top left) returns to the previously viewed
  page. The trail survives tab switches.

## 2026-08-31 — v0.12.6 — Switch Bay VS 0.3.13

**Migration:** none. **Breaking:** none. After pull, run
`make refresh BUILD=1` so the graph-search and dashboard changes load.

### Changed

- **Graph search marks hits and nothing else.** Both viewers now use the
  same dashed halo; Classic no longer recolours every edge that touches
  a hit (a 40-hit query drew the whole canvas in accent), and no longer
  forces a label onto each hit. Labels stay on the user's `labels`
  setting and type filter; hovering names the node under the cursor.
- **Search no longer auto-zooms** to the hits. The camera stays where
  you put it.
- The wiki page list marks search hits the same way the Files browser
  does, and opens the type groups that contain them for the search.
- **Atlas** drops the accent "current focus" mark. With the wiki
  resident as one scene the engine never rebuilds on focus, so that
  ring sat on an entry node nobody picked for the whole session.

### Fixed

- Graph search reported a page's `sources:` entries as `wiki/<name>`.
  They are vault files, so every source behind a hit silently matched
  nothing in the browsers (10 of 15 paths on one query here). The
  Explorer decoration in Switch Bay VS was wrong the same way, and now
  propagates to enclosing folders.
- Atlas search hits got stuck highlighted: each keystroke pinned them,
  and pinning asks for a scene rebuild, so a rebuild landing after the
  search was cleared repainted stale halos.
- Clicking empty Atlas canvas opened whatever page was last hovered —
  hover only updates on pointer *move*, so the id was routinely stale.
  Empty clicks now hit-test, and clear the selection.
- Mounting the graph with no query now clears the browsers, so a
  workspace switch cannot strand the previous workspace's highlights.
- **Agent Dashboard:** the chief of staff had no edge to the blackboard,
  leaving it floating above its own DAG when the only worker was fed by
  the board.
- **Blackboard counters were structurally zero** on the CE-curate path:
  each worker ran against a throwaway board, so nothing reached the
  parent. Workers now publish what they hand back, and clicking the
  blackboard shows the live rows in a scrollable panel.
- **CE fan-out workers appear in the DAG.** Providers that drive their
  own agent loop (claude-code) call `ce_dispatch_worker` over MCP, where
  the host's spawn interception never fires. Those dispatches are now
  recorded as DAG nodes and board rows, labelled `ce:<role> (cli)`, and
  retire with the node that dispatched them.

## 2026-08-31 — v0.12.5 — Switch Bay VS 0.3.12

**Migration:** none. **Breaking:** none. After pull, run
`make refresh BUILD=1` so the Agents tab and graph-search fix load.

### Changed

- **Agents** is a core tab (last before custom tabs). The collapsible
  bottom panel is gone. ⌘J and rail ↗ open that tab.
- The Agent Dashboard shows the **active workspace** only. A small
  Workspaces expander at the top lists running-agent counts; clicking
  a row **switches workspace** and opens that desk's dashboard.
- Chief-of-staff model checkboxes are **per workspace**. Each provider
  row has **Deselect all** on the right of the name, for catalogs full
  of older customer-compat models.
- The **Schedules** tab is removed from the strip; start/pause/stop
  stays on the Agents dashboard (can return to a tab if that feels
  crowded).

### Fixed

- Graph search highlighted files but not canvas nodes when Atlas (or a
  stuck page selection) had focused a single node. Search now highlights
  matching nodes and closes the dimming doc modal while the query is
  active.

## 2026-08-31 — v0.12.4 — Switch Bay VS 0.3.11

**Migration:** none. **Breaking:** none. After pull, run
`make refresh BUILD=1` — a daemon restart alone does not rebuild
the Agent Dashboard JS.

### Changed

- Auto / chief of staff **prefers signed-in non-local catalogs** (GitHub
  Copilot, subscriptions, BYOK) over a local rail picker. A Copilot +
  MLX desk no longer locks investigators onto MLX or a single local
  worker. Intra-provider Copilot families still fan out. Local models
  remain the fallback when remotes are denied or cooled down.
- Agent Dashboard **Chief of staff models** checkboxes under the DAG
  allowlist which catalog rows Auto may use. The effort slider still
  buys fan-out and how readily flagship models are recruited.
- `/curate` stays one CE curator (not a Switch Bay investigator DAG)
  but that curator uses the same non-local preference unless the CE
  hard rung or a per-run provider override is pinned.
- Provider-backed `/curate` again runs CE Phase 2 **workers**: the
  curator dispatches `ce_dispatch_worker` (page workers, extractors,
  then `batch_reviewer`) as fresh-context child runs on the DAG.
  Local models keep the single-session fallback (the curator *is* the
  worker) so a 7B does not nest another local server. The effort
  slider prices how many CE workers the wave may buy.

## 2026-08-28 — v0.12.3 — Switch Bay VS 0.3.10

**Migration:** none. **Breaking:** none.

### Added

- Graph view **search** (center-top). Matches wiki nodes; highlights
  them on the canvas and their files in the File browser. **×** (or
  Escape) clears. Same overlay in the VS Code graph webview, which
  badges matching Wiki-tree / Explorer files.

### Fixed

- VS Code graph **view / labels / types** controls sit at the
  bottom-left again (search took the top).
- PWA Agent Dashboard no longer lists **Recently finished** (Agent
  Space still pages recent DAGs). Compact Agents strip shows live
  runs only. Run-row extras no longer overlap neighbouring rows.

## 2026-08-27 — v0.12.2 — Switch Bay VS 0.3.9

**Migration:** none. **Breaking:** none. PWA daemon unchanged.

### Added

- **Register this folder with a wiki…** — one click from a code/docs
  window (or link folders from a wiki window). Writes
  `.curiosity/config.toml` and CE `project-dirs.json`. SBH defaults off
  in the code window.
- Status-bar **SBH on/off** pill (click → On / Off). `@switchbay /sbh`,
  `/sbh on`, `/sbh off`.
- **Ingest file… / folder…** (Wiki view, Explorer, Dashboard) via CE
  `local_ingest.py`. Paths outside the wiki use `--source-path-only`.
  Mechanical only: pypdf/text + `vault.db`. Vision stays on CURATE’s
  bounded queues (figure-extract, multimodal-table-extract,
  numeric-review) when `multimodal_recommended` is set.

### Fixed

- Wiki / Projects trees and the graph webview share WikiPage nodes from
  `.curator/graph.kuzu` (same query as CE `wiki_render`). Refresh runs
  `graph.py rebuild wiki`.
- Wiki preview resolves CE / Obsidian figure embeds (`![[figures/_assets/…]]`,
  `_assets/` relative to the page).
- Graph webview waits for a non-zero panel size before `fit`, keeps Atlas /
  label HUD inside the webview, and allows wiki figure paths as webview
  resources.
- Agent Dashboard **Stop** retires the DAG and writes `orchestration-report`
  cancelled (then tries VS Code Chat stop commands).
- Code-repo mode: resolve wiki from `.curiosity/config.toml` or
  `switchbay.wikiRoot`. Dual-cockpit (PWA or VS Code for the Web + this
  window) is documented, not a third pointer.

## 2026-08-27 — v0.12.1 — CE-faithful curate + Switch Bay VS 0.3.5

**Migration:** none. **Breaking:** `/curate` is CE CURATE (score_diff +
wiki git commit, planner pick-mode), not Switch Bay Investigators +
`propose_wiki_page`. Reviews stays for charter / non-curate proposals.

### Added

- CE-faithful **CURATE / QUERY** on PWA and Switch Bay VS: `ce_wave_prime`
  (evolve_guard + pick-mode), `ce_score_diff(new_text)`, `ce_wiki_commit`,
  `ce_evolve_guard`, `ce_dispatch_worker`, sweep verbs for numeric-review
  and multimodal table extract. Plugin `/curate` starts **Curator** with
  CE worker agents (NumericReviewer, TableExtractor, FigureExtractor, …).
- Agent Dashboard **overnight desks** (wiki curator, science monitor,
  startup/market research, AI news) with a duration. Research only.
- **Keep running 24/7** — VS Code for the Web (`code serve-web`) or
  Remote Tunnel so a browser tab can host schedules.
- MCP tool `orchestration_report` so Auto can retire a DAG when the
  wave is done (Chat staying open is not “still running”).

### Fixed

- Agent Dashboard no longer keeps finished Chat waves in **Running**.
- User-facing Switch Bay VS copy no longer mentions `:8765`.
- Install docs no longer tell you to check out `exp/vscode-plugin`
  (that branch was deleted; the plugin lives on `main`).

## 2026-08-26 — v0.12.0 — Switch Bay VS (VS Code, no daemon)

**Migration:** none. **Breaking:** none. The PWA daemon at `:8765` is
unchanged. VS Code is an additional install path.

Switch Bay can run inside VS Code as **Switch Bay VS** (`extensions/switchbay-vs/`,
VSIX 0.2.0): wiki tree, Graph/Atlas, Agent Dashboard, `@switchbay` chat,
and custom agents. Nothing listens on `:8765`. Closing VS Code stops
scheduled runs. Sideload from this repo (`make vsix`); not on the
Marketplace yet. Walkthrough: [`docs/vscode.md`](docs/vscode.md).

### Added

- **Switch Bay VS** — in-tree VSIX. First-run **Configure Python…**
  points at a Switch Bay checkout (`switchbay.repoRoot` /
  `switchbay.pythonPath`).
- **Agent Dashboard** — Economy → Maximum effort slider, named-agent
  schedules (`.workbench/state/schedules.json`), custom agents from
  `.github/agents/*.agent.md`, Models panel.
- **Local models helper** — Ollama / llama.cpp / MLX: list running
  servers and on-disk GGUF/MLX weights, pull tags, register as vendor
  **Switch Bay VS Local**.
- Sideload **update** path: install a newer VSIX over
  `switchbay.switchbay-vs`, then Reload Window.

### Fixed

- Atlas first-paint / HUD / replay wiring used by the Graph webview.

## 2026-08-25 — v0.11.4 — Reviews tab renders a page preview

**Migration:** none. **Breaking:** none.

### Fixed

- Reviews shows proposed wiki pages as a rendered preview (frontmatter
  properties + markdown), not a raw markdown dump.

## 2026-08-25 — v0.11.3 — Graph modal source links actually click

**Migration:** none. **Breaking:** none.

### Fixed

- Graph document-modal ``sources`` bind clicks on the modal root
  (not a global ``#modal-properties`` that can miss the mounted
  tab). Basename refs try ``vault/`` then ``wiki/`` from the
  frontend so Open works even if the running daemon is older.

## 2026-08-25 — v0.11.2 — Frontmatter sources open natively

**Migration:** none. **Breaking:** none.

### Fixed

- Wiki frontmatter ``sources`` (Editor preview and Graph document
  modal) are links. Click opens the file with the OS default app
  (Preview, browser, …), resolving a basename under ``vault/`` or
  ``wiki/`` when needed.

## 2026-08-25 — v0.11.1 — Enterprise Update + tester install

**Migration:** none. **Breaking:** none.

### Fixed

- Settings → Update no longer flashes on for enterprise while policy is
  loading (fail-closed). When `in_app_update` is off, the control is a
  disabled “IT package” button instead of a live GitHub update.
- In-app update, when IT bakes it on, keeps `admin.json` /
  `admin.baked.json` / `SWITCHBAY_PROFILE` across git checkout and
  rebuild. Packaged (non-git) trees skip with a message to use the
  organization package. Skill `npx` updates honour
  `install_skills_npx`; enterprise defaults to Switch Bay only
  (`updates.include_skills: false`).

### Added

- `service install --enterprise-user` (also `make install-service
  ENTERPRISE_USER=1` / `bash scripts/install.sh --enterprise-user`)
  writes `<repo>/admin.json` from the enterprise template with no
  `/Library` or ProgramData access — for testers.
- Bake `--in-app-update` and `--update-repo owner/name` so a fleet can
  self-update from GitHub without a new portal package per version,
  while keeping the bake-time policy.

## 2026-08-25 — v0.11.0 — Slideshows, Reviews, and install hardening

**Migration:** leftover `kind: deck` wiki pages are kept as ordinary
documents; their sketches stay in the Sketch library. Presentations
are HTML slideshows under `slideshows/<slug>/`. **Breaking:** sketch-deck
authoring tools (`make_slides_from_doc`, `compose_analysis`,
`author_slide`) and Sketch-tab deck mode are removed. Use
`create_slideshow` / **→ Slideshow** and `author_sketch` instead.

### Added

- HTML slideshows as the only presentation surface, with a Slideshow
  tab, markdown-from-doc creation, and **Save as PDF** (one 16:9 page
  per slide, fonts and local assets resolved).
- Reviews tab as the only proposal surface: provisional wiki writes,
  reject restores prior content, comments keep the page and feed the
  next curation cycle, close/ignore keeps remaining drafts.
- Clicking a local source or `(vault:…)` citation switches the sidebar
  to Files, expands ancestors, and highlights the row.

### Changed

- Installs consume locked `uv.lock` / `pnpm-lock.yaml`; pnpm 11 build
  scripts are an explicit allowlist.
- Enterprise Add Workspace may run only the bundled Curiosity Engine
  `scripts/setup.sh` through a narrow trusted path.
- `/curate` uses the adaptive orchestrator; Copilot-only runs can
  still spread work across distinct available models.
- Agent Space keeps the last DAG while idle and pages concurrent root
  DAGs. Atlas mounts individual nodes on the first frame.

### Fixed

- Proposal accept/reject cards no longer appear in the rail.
- Sketch tab is a library of ordinary drawings, not a slide carousel.

## 2026-08-24 — v0.10.0 — Auto orchestration

**Migration:** none. **Breaking:** none. Explicit `n≥2` fan-out and
`/route` keep their previous semantics.

Ordinary rail chat now goes through **Auto orchestration**: a
conservative policy chooses one ordinary Run, or a sparse DAG of Runs
(investigate → optional verify → synthesize), from the task and a
cost/performance preference (Economy → Maximum). Auto may still pick a
single agent. Investigators get read-only wiki/graph tools; durable
wiki writes still go through propose → reviewer.

Each workspace is its own desk. Recipe weights (which DAG to buy for
similar tasks) and last-good provider roster are stored per vault;
one workspace does not train another. Roles are computational kinds
(investigate / verify / synthesize / execute), not a user-built
standing org. The parent Run is a long-running **chief of staff**:
it can sit overnight, spawn waves while ΔU stays positive, and stop
on `OBJECTIVE_MET: yes`, idle (no stop token / no new evidence), or
user kill. A stuck *child* still times out at 15 minutes. Runtime is
constrained by provider availability and API credits, not a parent wall
clock.

### Added

- **Auto orchestration** — default for plain chat. Plan IR, DAG
  scheduler, evidence blackboard, evidence-based verifier, targeted
  expansion, hierarchical reduction when N is large.
- **Cost/performance slider** on the rail (and Zen composer). Explicit
  worker count is an advanced override (`n` on `user_input`).
- **Per-workspace learning** — recipe bandit + last-good roster, keyed
  by this vault and a coarse task-type bucket (research, finance,
  code, …). The quality proxy rewards completed, source-diverse,
  verifier-supported work, wiki/report artifacts that *landed*, and desk
  pages *reused* later — not Reviews clicks (Reviews is an undo backlog).
  `GET /api/orchestration/policy` and
  Settings reset apply to the focused workspace only. Hard bounds are
  not learnable. Provider outages (weekly limits) are a separate TTL.
- **N=1 token accounting** — ordinary Auto Runs record prompt/completion
  tokens so the learner does not treat single-agent chat as free.
- **DAG resume** — interrupted orchestrations persist a checkpoint
  (`plan.json`, `results.json`, blackboard). Daemon restart and
  `POST /api/orchestration/{id}/resume` skip finished nodes. Cancel
  does not auto-resume.
- **Overnight chief** — `OBJECTIVE_MET` stop token; after-synth
  continuation waves while ΔU > 0; `waiting_limits` pause that
  auto-resumes when a channel reopens; rail cards to start the local
  model server or spend BYOK API credits after subscriptions are
  exhausted. Credit exhaustion is reported, not tight-retried.
- **Agent space** — live DAG projection on the Agent Dashboard:
  chief-of-staff overview, handoff pulses, click a worker for its
  transcript. Canvas + rAF; no embedding model on the animation path.
- **`.orchestrator/` desk folder** — watchlist, dated briefs, filing
  cache, append-only log, playbook. Shared *input and artifacts*
  across Auto runs, not a worker group-chat.
- **Quant / lab task priors** — filings/earnings-shaped prompts and
  scientific experiment prompts get independent investigators plus
  verification; a single `execute` node may inherit parent
  `run_command` (never granted to investigators).
- **Copilot / enterprise model diversity** — when only one gateway is
  allowed, independent workers pick different models from that
  catalog. Admin policy still blocks disallowed providers.
- **Inspectable Auto trail** — when the synthesizer names concrete
  recommendations it must emit per-item wiki analysis + evidence
  pages and link them from the report.
- **Reproducible benchmark appendices** — the public bench now includes
  the repeated-use compounding pipeline, frozen held-out and supplementary
  questions, CE/raw-vault-RAG/closed-book controls, pooled noise-floor
  analysis, Sonnet archive/rewind, and the Opus curator rerun. The intro
  deck carries the updated chart on page 6 and the full Appendix Q readout.

### Changed

- **No planner LLM on Auto** — workers get deterministic slices
  (sub-questions + method-specific retrieval queries). Explicit `n≥2`
  fan-out still uses the historical planner.
- **Compact blackboard views** — verifiers see unclassified candidates;
  synthesizers see classified rows and keep minority evidence. Worker
  transcripts are never the coordination channel.
- **Utility policy** — candidate topologies scored
  `U = Q − λc(s) C − λl(s) L`; expansion uses the same ΔU test.
  Maximum still stops at diminishing returns.
- **CE model ladder** is no longer a Settings control. Auto allocates
  from the picker + keyed providers; micro-edits keep their own
  fast-model row.
- Child worker timeout is 15 minutes (was 180s, which killed
  grok-build mid-retrieval and left CLI processes running). The
  parent is not wall-clock capped. Lifetime spawn caps (max nodes /
  expansions / continuations) are off — ΔU and `OBJECTIVE_MET` are
  the brake. Parallelism on the machine is still capped.
- **Schedules tab** — recurring Auto prompts per workspace (frequency,
  prompt, started / edited / last run / run count). The daemon ticks
  due items even when that vault is not focused.
- **Readable ingest staging** — `ce_ingest` accepts a file (CE
  `local_ingest` is a directory or `--file`). Large HTML/XML/JSON
  (papers, dumps, filings) is staged as visible text so CE's 200 KiB
  extract cap indexes content, not schema. Originals stay put.
  `read_source` re-reads with the same conversion. A native iXBRL
  extractor is a future CE upgrade, not a Switch Bay parser.

### Fixed

- **Agent space looked idle** on a busy worker: child tool/text now
  persist to the run transcript; the DAG paints tool counts, provider,
  and the current tool; telemetry is *N running / M done*, not `0/5`
  while investigators are mid-retrieval.
- **Weekly-limit workers** abort on the first limit banner, cool that
  channel, and retry the same node on the next available provider.
  If none remain, Auto asks to start the local model server (then
  BYOK, then waits for a reset).
- **Chief-of-staff lead** — Agent Space quotes the *current* roster
  (N investigators → verifier → synthesizer, plus expansion counts),
  not the opening recipe's canned "three diverse investigators then
  verify". The original arm is kept as "Opened as: …" when it differs.
- **Agent space flow** — the blackboard is a DAG node; workers pulse
  amber while emitting tokens and blue while reading tools; token
  packets travel the edges. Failed/pruned nodes drop off. After a run
  the last effective roster stays as a standing desk org (at rest)
  until the next run replaces it.
- **Resume snapshots** — a snapshot worker writes `SNAPSHOT.md` every
  15s (plus per-node `live-*.json` on tools) so a daemon restart can
  restore in-flight investigators. The chief of staff is told the run
  was interrupted and gets the original goal plus that snapshot.
  Auto-resume on boot now scans every registered workspace.
- **Library report-doc ✕** — closing a durable report drops the
  transient tab.
- **Rail workspace isolation** — a background Auto in another vault
  no longer streams into the focused rail.
- **Composer crowding** — Auto slider, reasoning effort, mic, and
  prefix hints no longer overlap.
- **Settings → Restart** on a foreground `serve` re-execs that
  process.
- **Wiki browser after file-browser delete** — `wiki/**/*.md` drops
  from the page list on the next refetch.
- Vacuous verify no longer rubber-stamps empty findings as
  confidence 1.0.

### Version

0.10.0 (pre-1.0 minor). History retained.

## 2026-08-21 — v0.9.18 — plot layout

**Migration:** none. **Breaking:** none.

Long axis titles wrap instead of clipping the Plot tab tiles. Packaging
documentation lists packaging, then trust models, then endpoint
management.

### Fixed

- **Plot cards** — rotated y-axis titles no longer lose their first
  letters at the top of the tile; long x-axis titles wrap rather than
  running off the right edge.

### Version

0.9.18 (micro). History retained.

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
