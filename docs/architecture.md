# Architecture (v0.13)

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
- Settings → **Proxied skill embeds** switches Graph → CE and Agents →
  okstratr observer; turning it off restores built-ins. The proxy itself
  stays on either way.

## Same-document skill mount

- Poll `GET /api/core-skills/status`; wait chrome while `starting` /
  `building_wiki` / `unhealthy`; mount only when healthy.
- `fetch` proxied HTML, rewrite asset URLs onto `/embed/…`, inject markup,
  **execute** scripts via `createElement` + append.
- Soft-reload on wiki `files_changed`; tear down scripts on unmount.
- Implementation: `frontend/src/widgets/embed/` (`ProxiedSkillPanel`,
  `embedMount.ts`).

## Dual-mount Graph

- Shell left column: CE Pages|Files (`CeSidebarSlot`) persists across
  Graph / Agents / Editor when proxied embeds are on for a CE workspace.
- Graph pane: atlas canvas only (`CeAtlasEmbed`); keeps the atlas warm
  when you leave the tab; `atlas-cache.js` + workspace key for cold Graph cache.
- Prefers `window.CEEmbed.create` / `mount` when CE provides it; one
  session survives Graph unmount.

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

## Built-in Graph and Agents

Built-in GraphTab, AgentDashboardTab, and filebrowser stay available.
Proxied skill embeds are opt-in in Settings.
