# ADR-004b: Embed v2 — same-document interactive mount

- **Status:** Accepted (Embed v2)
- **Date:** 2026-09-19
- **Parent:** [ADR-004](./ADR-004-same-origin-embed-proxy.md)
- **Contract:** umbrella `CONTRACT-EMBED-V2.md`

## Context

Phase 4a (`ProxiedSkillPanel`) fetched `/embed/*` HTML and injected a
**script-stripped** body. That proved the reverse-proxy path but left Graph
and Agents inert (no pan/zoom, no desk controls). Charter + ADR-004 forbid
`<iframe>` / nested frames for skill surfaces.

CE and okstratr already honor `CE_PUBLIC_BASE` / `OKSTRATR_PUBLIC_BASE`
(`_/embed/ce_`, `_/embed/okstratr_`) and inject `window.*_PUBLIC_BASE` so
API helpers resolve under the proxy. Relative asset tags (`static/main.js`,
`observer.css`) still need rewriting when the HTML is mounted into a
Switchbay panel rather than navigated as a top-level document.

## Decision

**Same-document microfrontend mount** (no nested browsing context):

1. **Wait chrome first.** While the panel is open, poll
   `GET /api/core-skills/status` (~2s). Banner states: `starting` /
   `unhealthy` / `building_wiki` / `live`. Do **not** flash a full 502
   error while the supervisor is still `starting` or `stopped` —
   status chrome explains the wait (`suppressFetchError`).
2. **Fetch** proxied HTML from `/embed/ce/…` or `/embed/okstratr/…` only
   when the skill slice is `healthy` (`allowMount`).
3. **Rewrite** relative / root-relative / loopback asset URLs onto the
   public base (`frontend/src/widgets/embed/embedMount.ts`).
4. **Extract** `<script>` tags (classic + `type=module`); inject remaining
   markup (body + head stylesheets) into a dedicated panel root via
   `innerHTML`.
5. **Execute** scripts by `document.createElement("script")` + append
   (with rewritten `src`, or inline `textContent`). Browsers never run
   scripts inserted via `innerHTML` alone.
6. **Tear down** before soft-reload (`sy:files-changed`) or unmount:
   remove tracked script nodes and clear the panel root so listeners /
   duplicate roots do not accumulate.
7. **JSON** responses keep the pretty-print path (no script mount).

Built-in `GraphTab` is **not** deleted (parity checklist / Ben lock).

## Consequences

- Interactive CE / okstratr chrome can run under `/embed/*` without iframes.
- Skill UIs share the Switchbay document: global ID collisions and
  `document`-level assumptions are residual risks; skills should prefer
  scoped queries when possible.
- **WebSocket upgrade** through the embed proxy remains deferred (HTTP
  first). Live features that require WS may be limited until proxyed.
- Unit tests cover URL rewrite, script extraction, and status-banner
  mapping (`embedMount.test.ts`).

## Alternatives considered

| Option | Why not |
|--------|---------|
| Keep script-stripping | Inert UI; fails Embed v2 acceptance |
| Same-origin `<iframe src="/embed/…">` | Nested frame; charter / ADR-004 forbid |
| `srcdoc` iframe | Still a nested browsing context |
| Shadow DOM isolation | Extra complexity; CE/okstratr expect light DOM + `getElementById` |

## Mount algorithm (short)

```
poll status → if !healthy: banner only
else:
  teardown prior mount
  html = fetch(/embed/…/)
  { markup, scripts } = prepareEmbedHtml(html, publicBase, pagePath)
  root.innerHTML = markup
  for s in scripts: createElement(script); set src|text; append; await load
on files_changed / unmount: teardown
```
