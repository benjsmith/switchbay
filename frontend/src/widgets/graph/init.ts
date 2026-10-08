/**
 * Forked CE wiki-view orchestrator for the VS Code graph webview
 * (src/webview-graph.ts). Mirrors CE's `template/wiki-view/static/main.js`
 * but mounts into a given container instead of taking over `<body>`.
 *
 * The PWA does not use this: its Graph tab is Curiosity Engine's own
 * viewer mounted through /embed/ce (widgets/embed/).
 */

import { installSyHostMarker } from "../../lib/localPath";
import { atlasEnabled, destroyAtlas, initAtlasChoice, mountAtlas, type ViewerMode } from "./atlas";
import { installGraphSearch } from "./graphSearch";
import { template } from "./template";
import type { GraphData } from "./types";

export type GraphMount = { mode: ViewerMode };

export function mountGraph(
  container: HTMLElement,
  data: GraphData,
  opts?: {
    onSelectPage?: (id: string) => void;
    /** Pin classic or atlas. Unset follows the PWA localStorage/query choice. */
    forceMode?: ViewerMode;
  },
): GraphMount {
  destroyAtlas();
  container.classList.add("ce-graph-root");
  container.innerHTML = template;
  // CE vault.js looks for this marker (or window.__syOpenVault) before
  // falling back to a browser tab / OS default app.
  installSyHostMarker();

  // Clear any leftover modal-open state from a previous mount /
  // workspace switch. The CSS rule `body[data-modal="open"] #graph`
  // dims the canvas to 0.25 opacity; if a previous mount left the
  // attribute set without a corresponding modal close, the new
  // graph paints near-invisibly.
  if (document.body.dataset.modal === "open") {
    document.body.dataset.modal = "";
  }

  window.Subgraph.init(data);
  window.Modal.init(data, container);
  let mode: ViewerMode = "classic";
  try {
    const wantAtlas = opts?.forceMode === "atlas"
      || (opts?.forceMode !== "classic" && atlasEnabled(data));
    if (wantAtlas && mountAtlas(data, { onSelectPage: opts?.onSelectPage })) {
      mode = "atlas";
    } else {
      window.Graph.init(data);
    }
  } catch (err) {
    console.error("[switchbay] graph mount failed", err);
  }
  document.body.dataset.viewer = mode;
  initAtlasChoice(data, mode);
  installGraphSearch(data);
  return { mode };
}
