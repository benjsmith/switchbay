# ADR-005: Settings → okstratr harness registry (SSOT client)

- **Status:** Accepted
- **Date:** 2026-09-19
- **Parent:** [ADR-004](./ADR-004-same-origin-embed-proxy.md) (Settings TODO)
- **Deciders:** Ben / skill-shell rationalization charter

## Context

okstratr owns the harness+model registry (`~/.config/okstratr/harnesses.toml`
via `GET/POST /api/harness…`). Charter: shells are **config UIs** over that
registry — no second Switchbay allowlist. Hosted mode
(`X-Okstratr-Host: switchbay`) already disables okstratr HTML settings, so
Switchbay Settings must become the write path.

## Decision

1. **Thin client module** `switchbay.okstratr_harness`:
   - Server-side calls loopback `SWITCHBAY_OKSTRATR_UPSTREAM`
     (default `http://127.0.0.1:8767`) with hosted-shell header.
   - Loopback guard reused from `embed_proxy` (non-loopback → 502).
   - `normalize_registry()` maps okstratr `list_for_api` JSON; never
     invents an allowlist.
   - Browser may also hit same-origin `/embed/okstratr/api/harness…`.

2. **Daemon routes** (shells/UI need not know embed paths):
   - `GET  /api/okstratr/harness`
   - `POST /api/okstratr/harness/enable`   `{ "id": "…" }`
   - `POST /api/okstratr/harness/disable`  `{ "id": "…" }`
   - `POST /api/okstratr/harness/set`      `{ "key": "…", "value": "…" }`
   - `POST /api/okstratr/harness/reload`

3. **Settings UI** — section **Harness registry · okstratr**: list rows,
   enable/disable, set `harness.<id>.default_model`. Existing Pi / local
   LLM panels remain as **rail** surfaces and are labeled as not the
   desk/agent SSOT.

4. **okbay** mirrors the same thin-client pattern (doc note; full UI
   follow-up) — see okbay `docs/HERDR-AND-REGISTRY.md` and Switchbay
   `/api/okstratr/host-notify` as the precedent for path-native okstratr
   integration.

## Consequences

- okstratr must be healthy (core-skill supervisor) for Settings toggles
  to succeed; UI surfaces a clear 502 when upstream is down.
- No `harnesses.toml` (or equivalent) under Switchbay state dirs.
- Pi harness (`/api/llm/harness`) and local LLM panels stay Switchbay-local
  for rail chat; they must not claim desk registry ownership.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Copy allowlist into Switchbay `app_settings` | Second SSOT; charter forbid |
| Settings UI calls `:8767` cross-origin | Breaks hosted-mode headers / CORS |
| Only document CLI (`okstratr harness …`) | Users need in-app toggles when HTML settings are hosted-off |
