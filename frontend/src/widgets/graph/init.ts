/**
 * Forked CE wiki-view orchestrator. Mirrors the work of CE's
 * `template/wiki-view/static/main.js`, but mounts inside React
 * containers instead of taking over `<body>`. The sidebar lives in
 * Switch Bay's Browser column; this file only renders the graph-tab
 * portion (graph pane + modal + subgraph).
 *
 * Hash routing is owned by App.tsx (translates `#page=<id>` →
 * selection layer dispatch). Modal-close → selection clear is wired by
 * GraphTab.tsx so it can use the React context.
 */

import { atlasEnabled, destroyAtlas, initAtlasChoice, mountAtlas, type ViewerMode } from "./atlas";
import { template } from "./template";
import type { GraphData } from "./types";

export type GraphMount = { mode: ViewerMode };

export function mountGraph(
  container: HTMLElement,
  data: GraphData,
  opts?: { onSelectPage?: (id: string) => void },
): GraphMount {
  destroyAtlas();
  container.classList.add("ce-graph-root");
  container.innerHTML = template;

  // Clear any leftover modal-open state from a previous mount /
  // workspace switch. The CSS rule `body[data-modal="open"] #graph`
  // dims the canvas to 0.25 opacity; if a previous mount left the
  // attribute set without a corresponding modal close, the new
  // graph paints near-invisibly.
  if (document.body.dataset.modal === "open") {
    document.body.dataset.modal = "";
  }

  window.Subgraph.init(data);
  window.Modal.init(data);
  let mode: ViewerMode = "classic";
  if (atlasEnabled(data) && mountAtlas(data, { onSelectPage: opts?.onSelectPage })) {
    mode = "atlas";
  } else {
    window.Graph.init(data);
  }
  document.body.dataset.viewer = mode;
  initAtlasChoice(data, mode);

  // Edit module wires the modal padlock + textarea editor. The refetch
  // callback re-pulls the rebuilt data.json (cebridge updates its
  // cache server-side after POST /api/page).
  if (window.Edit) {
    window.Edit.init(data, async (currentPageId) => {
      const res = await fetch(`/api/graph/data?t=${Date.now()}`);
      if (!res.ok) return;
      const fresh = await res.json();
      window.Sidebar.init(fresh);
      window.Subgraph.init(fresh);
      if (window.Modal.refresh) window.Modal.refresh(fresh);
      if (currentPageId && window.Modal.open) {
        window.Modal.open(currentPageId);
        window.Sidebar.setActive(currentPageId);
      }
    });
  }
  return { mode };
}
