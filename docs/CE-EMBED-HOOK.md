# CE embed hook (Switchbay Graph tab)

**Date:** 2026-09-27  
**Owners:** Switchbay (mount) · CE Benchmarker (CE `embed` mode)

## Goal

Graph tab **is** the Curiosity Engine atlas viewer (canvas, graph search,
coloring, node→page click-through) inside Switchbay’s shell — **no iframe**,
**no** full-document HTML remount of CE `index.html` into `ProxiedSkillPanel`.

## Switchbay contract (landed)

When Settings → `proxied_skill_embeds` is on, Graph renders `CeAtlasEmbed`:

1. Dedicated mount node `#graph-root` with CE graph-pane + modal shell only
   (no CE sidebar / workspace title / pages·links strip / theme footer).
2. Loads CE CSS/JS same-origin from `/embed/ce/static/…` (proxy + gzip stay).
3. Bootstraps via `mountCeAtlas()` in `frontend/src/widgets/embed/ceEmbedBootstrap.ts`.
4. Soft-remount on `sy:files-changed` with grace/debounce (does not tear mid
   first `data.json` fetch). Teardown restores `window.fetch` and clears host class.

Agents still use `ProxiedSkillPanel` (okstratr observer) with minimal chrome.

## CE hook to add (CE Benchmarker)

Ship a first-class embed entry so Switchbay can stop using the stub path:

```js
// Exposed from CE wiki-view (e.g. static/embed.js), after atlas modules load.
window.CEEmbed = {
  /**
   * @param {HTMLElement} container  Switchbay #graph-root (already has #graph etc. or empty)
   * @param {{
   *   embed: true,
   *   dataUrl: string,          // e.g. "/embed/ce/data.json"
   *   publicBase: string,       // e.g. "/embed/ce"
   *   chrome?: boolean,         // default false → no sidebar / pages chrome
   * }} opts
   * @returns {{ destroy(): void }}
   */
  mount(container, opts) { /* … */ }
};
```

Requirements:

- **`chrome: false` (default in Switchbay):** do not mount sidebar, workspace
  title bar, theme/footer strips that duplicate Switchbay Files / shell.
- Keep CE **canvas interactions**: graph search, zoom/pan, labels/edges knobs,
  node → page modal.
- Honor `CE_PUBLIC_BASE` / `opts.publicBase` and `opts.dataUrl` (do not assume
  top-level navigation to CE’s document URL).
- Optional CE Pages sidebar: **off by default** in embed (Switchbay Files tree
  remains the file chrome).
- `destroy()` must tear listeners/raf/WebGL and leave Switchbay’s document
  globals (`fetch`, `body` class) clean — or document what Switchbay still
  releases.

Until this exists, Switchbay’s **stub** loads CE modules and calls
`AtlasViewer` / `Graph` / `GraphSearch` / `Modal` without `Sidebar.init`.

## Verify

- Graph shows CE atlas (not Switchbay GraphTab D3) for BioCure.
- No CE “N pages · links” strip; no Switchbay “same-origin via /embed/ce” bar.
- Rail stays right-docked; Agents opens without stuck Loading.
- `GET /embed/ce/data.json` and/or `GET /api/graph/data` still serve nodes+edges.
