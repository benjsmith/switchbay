/**
 * VS Code webview host for the real Switch Bay graph / Atlas viewer.
 * Graph data is posted from the extension (CE data.json). Clicks open
 * markdown via postMessage — no daemon, no in-graph doc modal.
 */
import "./widgets/graph/load";
import { paletteFromCss } from "./widgets/graph/atlas";
import { installReplayChrome, type HistoryDoc } from "./widgets/graph/curationReplayAnim";
import { mountGraph } from "./widgets/graph/init";
import type { GraphData } from "./widgets/graph/types";

type VsCodeApi = { postMessage(msg: unknown): void };
declare function acquireVsCodeApi(): VsCodeApi;

const vscode = acquireVsCodeApi();
const mount = document.getElementById("mount")!;
const menu = document.getElementById("ctx") as HTMLDivElement;

document.documentElement.dataset.theme = document.body.classList.contains("vscode-light")
  ? "light"
  : "dark";

type NodeRef = { id: string; path: string; title?: string; type?: string };

function findNode(data: GraphData, id: string): NodeRef | null {
  const n = data.nodes.find((x) => x.id === id);
  if (n) return n;
  const page = data.pages?.[id];
  if (page) return { id: page.id, path: page.path, title: page.title, type: page.type };
  return { id, path: id, title: id };
}

function openNode(data: GraphData, id: string): void {
  const node = findNode(data, id);
  if (node) vscode.postMessage({ type: "open", node });
}

function showMenu(x: number, y: number, node: NodeRef): void {
  menu.hidden = false;
  menu.style.left = `${x}px`;
  menu.style.top = `${y}px`;
  menu.innerHTML = "";
  const items: Array<[string, string]> = [
    ["Open markdown", "open"],
    ["Open preview", "preview"],
    ["Reveal in Explorer", "reveal"],
    ["To plot", "plot"],
    ["To sketch", "sketch"],
    ["To slideshow", "deck"],
  ];
  for (const [label, type] of items) {
    const b = document.createElement("button");
    b.textContent = label;
    b.onclick = () => {
      vscode.postMessage({ type, node });
      menu.hidden = true;
    };
    menu.appendChild(b);
  }
}

let live: AbortController | null = null;
let resizeObs: ResizeObserver | null = null;
let historyWaiter: ((h: HistoryDoc | null) => void) | null = null;

function loadHistory(): Promise<HistoryDoc | null> {
  return new Promise((resolve) => {
    const t = window.setTimeout(() => {
      if (historyWaiter === wrapped) historyWaiter = null;
      resolve(null);
    }, 60000);
    const wrapped = (h: HistoryDoc | null) => {
      window.clearTimeout(t);
      resolve(h);
    };
    historyWaiter = wrapped;
    vscode.postMessage({ type: "history" });
  });
}

function waitForSize(el: HTMLElement, timeoutMs = 2500): Promise<void> {
  if (el.clientWidth > 32 && el.clientHeight > 32) return Promise.resolve();
  return new Promise((resolve) => {
    const ro = new ResizeObserver(() => {
      if (el.clientWidth > 32 && el.clientHeight > 32) {
        ro.disconnect();
        resolve();
      }
    });
    ro.observe(el);
    window.setTimeout(() => {
      ro.disconnect();
      resolve();
    }, timeoutMs);
  });
}

async function bind(data: GraphData): Promise<void> {
  live?.abort();
  live = new AbortController();
  const { signal } = live;
  resizeObs?.disconnect();
  await waitForSize(mount);

  const themed: GraphData = {
    ...data,
    palette: { ...paletteFromCss(), ...(data.palette || {}) },
  };
  mountGraph(mount, themed, {
    onSelectPage: (id) => openNode(themed, id),
    skipEdit: true,
  });
  const pane = mount.querySelector("#graph-pane");
  if (pane instanceof HTMLElement) {
    const stopReplay = installReplayChrome(pane, loadHistory);
    signal.addEventListener("abort", stopReplay, { once: true });
  }
  const pingSize = () => window.dispatchEvent(new Event("resize"));
  requestAnimationFrame(() => {
    pingSize();
    window.setTimeout(pingSize, 120);
    window.setTimeout(pingSize, 400);
    window.setTimeout(pingSize, 1200);
  });
  resizeObs = new ResizeObserver(pingSize);
  resizeObs.observe(mount);
  if (pane instanceof HTMLElement) resizeObs.observe(pane);
  if (window.Modal) {
    window.Modal.open = (id: string) => {
      openNode(themed, id);
      return false;
    };
  }
  window.addEventListener("hashchange", () => {
    const m = location.hash.match(/page=([^&]+)/);
    if (m) openNode(themed, decodeURIComponent(m[1]));
  }, { signal });
  window.addEventListener("sy:graph-viewer-change", () => {
    bind(data);
  }, { signal });
  mount.addEventListener("contextmenu", (ev) => {
    const t = ev.target as HTMLElement | null;
    const el = t?.closest?.("[data-id]");
    let id = el?.getAttribute("data-id") || "";
    if (!id) {
      const canvas = mount.querySelector("canvas:not(.atlas-minimap)") as HTMLCanvasElement | null;
      id = canvas?.dataset.hoverId || "";
    }
    if (!id) return;
    ev.preventDefault();
    const node = findNode(themed, id);
    if (node) showMenu(ev.clientX, ev.clientY, node);
  }, { signal });
  document.addEventListener("click", () => { menu.hidden = true; }, { signal });
}

window.addEventListener("message", (ev: MessageEvent) => {
  if (ev.data?.type === "curation-history") {
    historyWaiter?.(ev.data.history ?? null);
    historyWaiter = null;
    return;
  }
  const graph = ev.data?.graph as GraphData | undefined;
  if (!graph || !Array.isArray(graph.nodes)) return;
  bind(graph);
});
vscode.postMessage({ type: "ready" });
