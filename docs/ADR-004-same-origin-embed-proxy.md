# ADR-004: Same-origin embed reverse-proxy (no iframes)

- **Status:** Accepted (Phase 4a)
- **Date:** 2026-09-18
- **Deciders:** Ben / skill-shell rationalization charter

## Context

Switchbay hosts Graph (curiosity-engine atlas/wiki) and Agents (okstratr
observer/desk) surfaces. Cross-origin iframes pointed at
`127.0.0.1:8766` / `:8767` break hosted-mode control (okstratr HTML
settings must hide when `host=switchbay`) and create an opaque nested
browsing context.

Charter locked decision #1: shells **same-origin reverse-proxy** skill
daemons; in-app panels load first-party proxied routes — **not nested
frames**.

## Decision

1. **Daemon reverse-proxy** (always on; independent of the UI flag):
   - `/embed/ce/*` → `http://127.0.0.1:8766/*` (override:
     `SWITCHBAY_CE_UPSTREAM`, must remain loopback)
   - `/embed/okstratr/*` → `http://127.0.0.1:8767/*` (override:
     `SWITCHBAY_OKSTRATR_UPSTREAM`, must remain loopback)
   - Upstream allowlist is **loopback-only** (`127.0.0.1` / `::1` /
     `localhost`). Non-loopback upstreams are rejected (502).
   - Inject hosted-shell headers on every proxied request:
     - `X-CE-Host: switchbay`
     - `X-Okstratr-Host: switchbay`

2. **No iframes** for Graph/Agents skill surfaces. Feature flag
   `proxied_skill_embeds` (default **false**) switches Graph → CE panel
   and Agents → okstratr panel that navigate `/embed/*` via same-origin
   `fetch` + same-document rendering (script-stripped HTML / JSON).
   Built-in GraphTab / AgentDashboardTab / filebrowser remain the
   default and are **not deleted**.

3. **Settings → okstratr registry (TODO).** Switchbay settings will
   become a client that writes okstratr's harness/model registry
   (`harnesses.toml` via API). Out of scope for 4a; tracked here so the
   shell does not grow a second allowlist.

## Consequences

- Dev Vite must proxy `/embed` to the daemon (`vite.config.ts`).
- CE and okstratr should honor public-base + `X-*-Host` (okstratr
  Phase 1a `public_base.py`; CE equivalent TBD).
- Full atlas/observer chrome parity is gated by the parity checklist
  before any Switchbay duplicate deletion (Phase 4b+).
- WebSocket upgrade through the embed proxy is deferred; HTTP(S) first.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Cross-origin iframe to :8766/:8767 | Opaque origin; hosted settings leak; charter forbid |
| Same-origin iframe to `/embed/*` | Still a nested frame; charter: no iframes |
| Delete built-in Graph/Agents now | Violates parity checklist / dual-stack gate |
