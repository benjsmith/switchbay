# CE embed hook — dual mounts (shell sidebar + Graph canvas)

**Date:** 2026-09-27 (updated)  
**Owners:** Switchbay (mount scaffolding) · CE Benchmarker (CE `embed` mode)

## Goal

- **Shell left column** hosts the **CE sidebar** (Pages | Files + search that
  highlights both list and canvas) — **persistent** across Graph / Agents /
  Editor for CE-backed workspaces.
- **Graph pane** hosts **only the CE atlas canvas** (+ in-canvas graph-search).
- **One CE embed session**, **two mount points**, shared `data.json` /
  module state — same-origin, no iframe, no full-document HTML remount.
- Switchbay keeps tabs, rail, Agents, theme/mode footer. Non-CE / proxied-off
  workspaces keep native WikiPane + Files|Sources.

## Do not

- Keep Pages only inside the Graph tab (must persist across tabs).
- Rebuild Switchbay’s sidebar to imitate CE Pages (search-highlight debt).
- Run two page lists at once.

## Switchbay scaffolding (landed)

| Piece | Role |
|-------|------|
| `ceEmbedSession.ts` | Singleton session: `ensure()` → load `/embed/ce` modules + `data.json`; `attachSidebar` / `attachCanvas` / detach; survives Graph unmount |
| `CeSidebarSlot.tsx` | Shell-left mount (`#ce-sidebar-root`) when `proxied_skill_embeds` |
| `CeAtlasEmbed.tsx` | Graph tab canvas (`#graph-root`); soft-parks atlas on tab leave (instant return) |
| `ceEmbedBootstrap.ts` | `prepareSession()`, script order, fetch shim, `window.CEEmbed` prefer |
| `ceSidebarShell.html` / `ceEmbedShell.html` | DOM fragments (aside vs graph-pane+modal) |

`Sidebar.tsx`: proxied on → `CeSidebarSlot` (full-height); proxied off →
WikiPane + Files|Sources as before. Workspace remount calls
`resetCeEmbedSession()`.

## CE hook to add (CE Benchmarker)

```js
window.CEEmbed = {
  /**
   * Preferred: create a session, then attach external mounts.
   * @param {{
   *   embed: true,
   *   dataUrl: string,       // "/embed/ce/data.json"
   *   publicBase: string,    // "/embed/ce"
   *   chrome?: boolean,      // shell owns theme/rail; CE chrome minimal
   * }} opts
   */
  async create(opts) {
    return {
      /** Mount CE Pages|Files sidebar into Switchbay's left column. */
      mountSidebar(el) { /* Sidebar.init + FileBrowser; search↔canvas */ },
      /** Mount atlas canvas (+ graph-search) into #graph-root. */
      mountCanvas(el) { /* AtlasViewer / Graph; share session data */ },
      destroy() { /* tear both; leave Switchbay fetch/body clean */ },
    };
  },
};
```

Requirements:

- Single shared state / `data.json` for both mounts.
- Sidebar search highlights **list + canvas** (existing GraphSearch wiring).
- `mountCanvas` may be called after `mountSidebar`. Leaving Graph should
  **soft-park** the canvas (`unmountCanvas()` default) — keep atlas/simulation
  + loaded data alive off-DOM; return calls `mountCanvas` again for **instant
  reattach** (no N>10k layout). Pass `unmountCanvas({ destroy: true })` only
  for hard teardown. Optional `revalidate()` refreshes `data.json` in the
  background after reattach.
- Honor `CE_PUBLIC_BASE` / `opts.dataUrl`.
- Optional: `mount({ mounts: { sidebar, canvas } })` one-shot still OK.

Until `CEEmbed.create` exists, Switchbay’s stub loads CE static modules and
calls `Sidebar.init` + `AtlasViewer`/`Graph`/`GraphSearch` itself.

## Verify

- Pages list visible on Agents and Editor (not only Graph).
- One page list (CE), not WikiPane + CE.
- Graph = atlas canvas; rail right-docked; Agents not stuck Loading.
- Leave Graph → Agents → back Graph is **instant** (no "Loading Curiosity Engine atlas…" / no 20s layout).
- `/embed/ce/data.json` and `/api/graph/data` still serve BioCure nodes+edges.
