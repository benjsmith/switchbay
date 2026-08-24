/**
 * VS Code webview host for the real Switch Bay graph / Atlas viewer.
 * Graph data is posted from the extension (CE data.json). Clicks open
 * markdown via postMessage — no daemon, no in-graph doc modal.
 */
import "./widgets/graph/load";
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

function bind(data: GraphData): void {
  mountGraph(mount, data, { onSelectPage: (id) => openNode(data, id) });
  if (window.Modal) {
    window.Modal.open = (id: string) => {
      openNode(data, id);
      return false;
    };
  }
  window.addEventListener("hashchange", () => {
    const m = location.hash.match(/page=([^&]+)/);
    if (m) openNode(data, decodeURIComponent(m[1]));
  });
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
    const node = findNode(data, id);
    if (node) showMenu(ev.clientX, ev.clientY, node);
  });
  document.addEventListener("click", () => { menu.hidden = true; });
}

window.addEventListener("message", (ev: MessageEvent) => {
  const graph = ev.data?.graph as GraphData | undefined;
  if (!graph || !Array.isArray(graph.nodes)) return;
  bind(graph);
});
vscode.postMessage({ type: "ready" });
