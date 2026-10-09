/**
 * VS Code graph view: Curiosity Engine's own viewer (window.CEEmbed),
 * the same one the PWA's Graph tab mounts. The extension serves CE's
 * built wiki-view bundle as webview resources and answers CE's API
 * calls (data.json, page edits, curation history) over postMessage —
 * see widgets/embed/vscodeGraphBridge.ts. No daemon involved.
 */
import embedShellHtml from "./widgets/embed/ceEmbedShell.html?raw";
import { loadCeModules, type CeCreateHandle } from "./widgets/embed/ceEmbedBootstrap.ts";
import { bindCeReplay, currentModalPageId, renderMath, waitForCeToast } from "./widgets/embed/ceHostBridge.ts";
import {
  ceThemeFor, installFetchBridge, nodeRef, searchHitPaths, vscodeCeApi,
  type BridgeRequest, type NodeRef, type ViewData,
} from "./widgets/embed/vscodeGraphBridge.ts";

type VsCodeApi = { postMessage(msg: unknown): void };
declare function acquireVsCodeApi(): VsCodeApi;

type BootConfig = { bundle: string; workspace: string };
type CeGlobals = Window & {
  CE_PUBLIC_BASE?: string;
  CE_HOSTED?: string;
  ceApi?: (path: string) => string;
  CEEmbed?: { create?: (o: Record<string, unknown>) => Promise<CeCreateHandle> };
};

/** CE's own key for the Atlas / Classic choice (atlas.js). */
const CE_VIEWER_KEY = "curiosity-engine.viewer";

const vscode = acquireVsCodeApi();
const win = window as CeGlobals;
const mount = document.getElementById("mount") as HTMLDivElement;
const statusEl = document.getElementById("status") as HTMLDivElement;
const menu = document.getElementById("ctx") as HTMLDivElement;

function readConfig(): BootConfig | null {
  const raw = document.getElementById("sy-graph-config")?.textContent;
  if (!raw) return null;
  try {
    const cfg = JSON.parse(raw) as BootConfig;
    return cfg.bundle ? cfg : null;
  } catch {
    return null;
  }
}

function showStatus(text: string): void {
  statusEl.textContent = text;
  statusEl.hidden = !text;
}

function applyTheme(): void {
  document.documentElement.dataset.theme = ceThemeFor(document.body.className);
}

let handle: CeCreateHandle | null = null;

function viewData(): ViewData | null {
  return (handle?.getData?.() as ViewData | undefined) ?? null;
}

/* ---- page actions (VS Code-only: open the file behind a page) ---- */

const ACTIONS: Array<[string, string]> = [
  ["Open markdown", "open"],
  ["Open preview", "preview"],
  ["Reveal in Explorer", "reveal"],
  ["To plot", "plot"],
  ["To sketch", "sketch"],
  ["To slideshow", "deck"],
];

function send(type: string, node: NodeRef): void {
  vscode.postMessage({ type, node });
}

function showMenu(x: number, y: number, node: NodeRef): void {
  menu.innerHTML = "";
  for (const [label, type] of ACTIONS) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.onclick = () => {
      send(type, node);
      menu.hidden = true;
    };
    menu.appendChild(b);
  }
  menu.hidden = false;
  menu.style.left = `${Math.min(x, window.innerWidth - 200)}px`;
  menu.style.top = `${Math.min(y, window.innerHeight - 220)}px`;
}

/** Action row under the page title in CE's page window. */
function decorateModal(): void {
  const id = currentModalPageId();
  const content = document.getElementById("modal-content");
  const title = document.getElementById("modal-title");
  if (!id || !content || !title) return;
  let row = content.querySelector<HTMLDivElement>(".sy-vscode-page-actions");
  if (!row) {
    row = document.createElement("div");
    row.className = "sy-vscode-page-actions";
    title.insertAdjacentElement("afterend", row);
  }
  if (row.dataset.page === id) return;
  row.dataset.page = id;
  row.innerHTML = "";
  for (const [label, type] of ACTIONS.slice(0, 3)) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "ctrl-btn";
    b.textContent = label;
    b.onclick = () => send(type, nodeRef(viewData(), id));
    row.appendChild(b);
  }
  const more = document.createElement("button");
  more.type = "button";
  more.className = "ctrl-btn";
  more.textContent = "More…";
  more.onclick = (ev) => {
    ev.stopPropagation();
    const r = more.getBoundingClientRect();
    showMenu(r.left, r.bottom + 4, nodeRef(viewData(), id));
  };
  row.appendChild(more);
}

function watchModal(): void {
  const body = document.getElementById("modal-body");
  const modal = document.getElementById("modal");
  if (!body || !modal) return;
  new MutationObserver(() => {
    renderMath(body);
    decorateModal();
  }).observe(body, { childList: true });
  new MutationObserver(decorateModal).observe(modal, { attributes: true, attributeFilter: ["class"] });
}

/* ---- search hits → VS Code wiki tree + Explorer badges ---- */

function hookSearch(): void {
  const sidebar = window.Sidebar;
  if (!sidebar) return;
  const orig = sidebar.setSearchHits?.bind(sidebar);
  sidebar.setSearchHits = (ids: string[]) => {
    const list = Array.isArray(ids) ? ids : [];
    const { paths, sourcePaths } = searchHitPaths(viewData(), list);
    const input = document.getElementById("graph-search-input") as HTMLInputElement | null;
    vscode.postMessage({ type: "search", query: input?.value || "", ids: list, paths, sourcePaths });
    try {
      orig?.(list);
    } catch {
      /* CE's page list isn't mounted in VS Code */
    }
  };
}

/* ---- mount / refresh ---- */

function paint(): void {
  if (!handle) return;
  mount.innerHTML = embedShellHtml;
  // Splitting a workspace needs Switch Bay's daemon (registry, both graphs).
  mount.querySelector("#split-toggle")?.remove();
  handle.mountCanvas(mount);
  bindCeReplay(mount, handle.getData?.());
  watchModal();
  const ping = () => window.dispatchEvent(new Event("resize"));
  requestAnimationFrame(() => {
    ping();
    window.setTimeout(ping, 200);
  });
}

let refreshing: Promise<void> | null = null;
let refreshAgain = false;

async function refresh(): Promise<void> {
  if (!handle) return;
  if (refreshing) {
    refreshAgain = true;
    return refreshing;
  }
  refreshing = (async () => {
    do {
      refreshAgain = false;
      const page = currentModalPageId() || undefined;
      try {
        await waitForCeToast();
        await handle!.revalidate?.(page);
        handle!.unmountCanvas?.({ destroy: true });
        paint();
      } catch (e) {
        console.error("[graph] refresh failed", e);
      }
    } while (refreshAgain);
  })();
  try {
    await refreshing;
  } finally {
    refreshing = null;
  }
}

async function boot(): Promise<void> {
  applyTheme();
  new MutationObserver(applyTheme).observe(document.body, { attributes: true, attributeFilter: ["class"] });
  const cfg = readConfig();
  if (!cfg) {
    showStatus("Graph configuration missing.");
    return;
  }
  const deliver = installFetchBridge(window, (m: BridgeRequest) => vscode.postMessage(m));
  window.addEventListener("message", (ev: MessageEvent) => {
    if (deliver(ev.data)) return;
    if (ev.data?.type === "refresh") void refresh();
  });
  win.CE_PUBLIC_BASE = cfg.bundle;
  win.CE_HOSTED = "switchbay-vscode";
  win.ceApi = vscodeCeApi;
  document.documentElement.dataset.syHost = "1";
  document.body.classList.add("sy-embed-hosting", "sy-vscode-graph");

  showStatus("Loading graph…");
  await loadCeModules(cfg.bundle);
  applyTheme();
  const create = win.CEEmbed?.create;
  if (typeof create !== "function") {
    showStatus("This Curiosity Engine install has no embeddable viewer. Update Curiosity Engine to see the graph here.");
    return;
  }
  handle = await create({
    embed: true,
    dataUrl: vscodeCeApi("/data.json"),
    publicBase: cfg.bundle,
    chrome: false,
    workspace: cfg.workspace,
  });
  hookSearch();
  // CE source citations open the vault file in an editor tab.
  window.__syOpenVault = (detail) => {
    const p = detail?.path || (detail?.name ? `vault/${detail.name}` : "");
    if (p) send("open", { id: p, path: p, title: detail?.name || p });
  };
  paint();
  applyTheme();
  showStatus("");

  // CE's view: chooser reloads the page; a webview must not navigate, so
  // remount in place (same as the PWA Graph tab).
  mount.addEventListener("click", (ev) => {
    const btn = (ev.target as Element | null)?.closest?.("#viewer-mode");
    if (!btn) return;
    ev.preventDefault();
    ev.stopImmediatePropagation();
    const current = (mount.querySelector("#viewer-mode-state")?.textContent || "").trim();
    try { localStorage.setItem(CE_VIEWER_KEY, current === "atlas" ? "classic" : "atlas"); } catch { /* ignore */ }
    handle?.unmountCanvas?.({ destroy: true });
    paint();
  }, true);
  mount.addEventListener("contextmenu", (ev) => {
    const el = (ev.target as HTMLElement | null)?.closest?.("[data-id]");
    const id = el?.getAttribute("data-id");
    if (!id) return;
    ev.preventDefault();
    showMenu(ev.clientX, ev.clientY, nodeRef(viewData(), id));
  });
  document.addEventListener("click", () => { menu.hidden = true; });
  vscode.postMessage({ type: "ready" });
}

boot().catch((e) => {
  console.error("[graph] boot failed", e);
  showStatus(`Could not load the graph: ${e instanceof Error ? e.message : String(e)}`);
});
