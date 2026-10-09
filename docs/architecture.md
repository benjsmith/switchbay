# Architecture (v0.14)

How Switchbay **hosts** first-party skills today. Product vocabulary and
data flows stay in [`concepts-and-data-flow.md`](concepts-and-data-flow.md).
Release detail: [`releases/v0.13.0.md`](releases/v0.13.0.md).

> If a detail here disagrees with the code, the code wins.

## Shape

```
Browser PWA  ──WS/HTTP──▶  Switchbay daemon :8765
                              │
                              ├── /embed/ce/*       → 127.0.0.1:8766  (curiosity-engine)
                              ├── /embed/okstratr/* → 127.0.0.1:8767  (okstratr)
                              ├── /api/core-skills/*   (auto-start + status)
                              ├── /api/okstratr/harness*  (Settings thin client)
                              └── pack / ingest queues  (.workbench)
```

Same-origin reverse proxy + **same-document** mounts — **no iframes** for
Graph / Agents skill surfaces.

## Same-origin reverse proxy

- Daemon always proxies `/embed/ce/*` and `/embed/okstratr/*` to loopback
  upstreams (`SWITCHBAY_CE_UPSTREAM` / `SWITCHBAY_OKSTRATR_UPSTREAM`;
  non-loopback rejected).
- Injects `X-CE-Host: switchbay` / `X-Okstratr-Host: switchbay`.
- Vite dev proxies `/embed` to the daemon.
- The **Graph** tab is always Curiosity Engine's own viewer, mounted
  through `/embed/ce`. Switchbay has no built-in graph viewer.
- Settings → **Agents: okstratr observer** (`proxied_skill_embeds`) only
  chooses the Agents surface: okstratr observer when on, the built-in
  Agents dashboard when off. It does not affect Graph. The proxy itself
  stays on either way.

## Same-document skill mount

- Poll `GET /api/core-skills/status`; wait chrome while `starting` /
  `building_wiki` / `unhealthy`; mount only when healthy.
- `fetch` proxied HTML, rewrite asset URLs onto `/embed/…`, inject markup,
  **execute** scripts via `createElement` + append.
- Soft-reload on wiki `files_changed`; tear down scripts on unmount.
- Implementation: `frontend/src/widgets/embed/` (`ProxiedSkillPanel`,
  `embedMount.ts`).

## Graph comes from Curiosity Engine

- Graph, the wiki page list, page modal (incl. note editing), search,
  type filters, Atlas/Classic, keybindings and curation replay are all
  CE's viewer, loaded through `/embed/ce` with `window.CEEmbed.create`.
- `GET /api/settings` reports `ce_graph: {installed, has_wiki}`.
  CE not installed → the Graph tab is hidden and Graph shortcuts fall back
  to the Editor. Installed but no `wiki/` yet → a short placeholder.
- Shell left column: CE Pages (`CeSidebarSlot`) above Switchbay's own
  Files | Sources browser. The Files uploader, RAG, Agents and Library do
  not depend on CE.
- Graph pane: canvas only (`CeAtlasEmbed`, wrapped by `CeGraphSurface`);
  one `CeEmbedSession` per workspace shares `data.json` between sidebar and
  canvas, parks the canvas across tab switches and remounts it on wiki
  `files_changed`.
- Host shims (`ceHostBridge.ts`, `ceEmbedShell.html`): page HTML is
  sanitized before CE's modal renders it; KaTeX, table → Sheet / Plot and
  the slideshow button are added to CE's modal; CE's split panel is routed
  to `/api/workspaces/split`; Procedure / Execution label-type rows; the
  sidebar `+` opens Switchbay's upload dialog (`/api/upload-vault`); the
  sidebar header's `{{WORKSPACE}}` placeholder is filled from `data.json`.
- The VS Code extension's graph view mounts the same CE viewer
  (`src/webview-graph.ts`, built by `vite.webview.config.ts` into
  `extensions/switchbay-vs/media/graph/`). The extension builds CE's
  wiki-view bundle with `wiki_render.py`, serves its `static/` scripts and
  figures as webview resources, and answers CE's API calls (`data.json`,
  `/api/page` for notes/todos, curation history) over `postMessage`
  (`vscodeGraphBridge.ts`, `extensions/switchbay-vs/src/graphBundle.ts`).
  Without a CE install the view shows a message instead of a graph.

## Core-skills auto-start

- curiosity-engine and okstratr **always** auto-start with the shell.
- Supervised okstratr serve sets `OKSTRATR_HOSTED=switchbay`.
- Rail receives okstratr `host_notify` envelopes.

## Settings → okstratr harness registry

- `/api/okstratr/harness*` is a thin client over okstratr’s harness /
  model registry. No second Switchbay allowlist.

## Pack + ingest queues

- CE queues pack-runs and ingest-runs under `.workbench/`.
- Switchbay processes pack-runs via the rail LLM and ingest-runs via
  `local_ingest` (prefer CE drop-ingest endpoint; rail LLM only when
  run metadata opts in).

## Built-in Agents

The built-in Agents dashboard and file browser stay available; turning
off **Agents: okstratr observer** in Settings selects the built-in
dashboard. There is no built-in Graph.
