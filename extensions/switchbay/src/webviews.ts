import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";
import { readCachedGraph, scanWikiMarkdown, wikiPageUri, type GraphNode } from "./ce";
import { repoRoot, workspaceFolder } from "./paths";

function nonce(): string {
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  let s = "";
  for (let i = 0; i < 32; i++) s += chars[Math.floor(Math.random() * chars.length)];
  return s;
}

export function openGraph(context: vscode.ExtensionContext): void {
  const folder = workspaceFolder();
  if (!folder) {
    void vscode.window.showWarningMessage("Open a curiosity-engine folder first.");
    return;
  }
  const graph = readCachedGraph(folder.fsPath);
  const nodes: GraphNode[] = graph?.nodes?.length ? graph.nodes : scanWikiMarkdown(folder.fsPath);
  const panel = vscode.window.createWebviewPanel(
    "switchbay.graph",
    "Graph",
    vscode.ViewColumn.One,
    { enableScripts: true, retainContextWhenHidden: true },
  );
  const n = nonce();
  const csp = `default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${n}'`;
  const payload = JSON.stringify(nodes);
  panel.webview.html = `<!DOCTYPE html>
<html><head>
<meta charset="UTF-8" />
<meta http-equiv="Content-Security-Policy" content="${csp}" />
<style>
  body { font-family: var(--vscode-font-family); margin: 0; color: var(--vscode-foreground);
         background: var(--vscode-editor-background); }
  header { padding: 0.6rem 1rem; border-bottom: 1px solid var(--vscode-widget-border, #333);
           display: flex; gap: 0.8rem; align-items: baseline; }
  header span { opacity: 0.6; font-size: 0.85rem; }
  input { flex: 1; background: var(--vscode-input-background); color: var(--vscode-input-foreground);
          border: 1px solid var(--vscode-input-border, #444); padding: 0.25rem 0.5rem; }
  .group { padding: 0.4rem 0; }
  .group h2 { font-size: 0.75rem; letter-spacing: 0.08em; text-transform: uppercase;
              margin: 0.6rem 1rem 0.2rem; opacity: 0.55; }
  .node { padding: 0.35rem 1rem; cursor: pointer; display: flex; justify-content: space-between; }
  .node:hover { background: var(--vscode-list-hoverBackground); }
  .id { opacity: 0.5; font-size: 0.8rem; }
  .menu { position: fixed; background: var(--vscode-menu-background); color: var(--vscode-menu-foreground);
          border: 1px solid var(--vscode-widget-border, #444); z-index: 5; min-width: 12rem; }
  .menu button { display: block; width: 100%; text-align: left; background: none; border: 0; color: inherit;
                 padding: 0.35rem 0.8rem; cursor: pointer; font: inherit; }
  .menu button:hover { background: var(--vscode-menu-selectionBackground); }
</style>
</head>
<body>
  <header>
    <strong>Graph</strong>
    <span>click opens markdown · right-click workflows</span>
    <input id="q" placeholder="filter pages" />
  </header>
  <div id="list"></div>
  <div id="menu" class="menu" hidden></div>
  <script nonce="${n}">
    const vscode = acquireVsCodeApi();
    const nodes = ${payload};
    const list = document.getElementById("list");
    const menu = document.getElementById("menu");
    const q = document.getElementById("q");
    function render() {
      const term = (q.value || "").toLowerCase();
      const groups = {};
      for (const n of nodes) {
        const hay = ((n.title || "") + " " + (n.id || "") + " " + (n.path || "")).toLowerCase();
        if (term && !hay.includes(term)) continue;
        const t = (n.type || "unclassified").toLowerCase();
        (groups[t] = groups[t] || []).push(n);
      }
      list.innerHTML = "";
      Object.keys(groups).sort().forEach((t) => {
        const wrap = document.createElement("div");
        wrap.className = "group";
        wrap.innerHTML = "<h2>" + t + "</h2>";
        for (const n of groups[t]) {
          const row = document.createElement("div");
          row.className = "node";
          row.innerHTML = "<span>" + (n.title || n.id) + "</span><span class='id'>" + n.id + "</span>";
          row.addEventListener("click", () => vscode.postMessage({ type: "open", node: n }));
          row.addEventListener("contextmenu", (ev) => {
            ev.preventDefault();
            menu.hidden = false;
            menu.style.left = ev.pageX + "px";
            menu.style.top = ev.pageY + "px";
            menu.innerHTML = "";
            const items = [
              ["Open markdown", "open"],
              ["Open preview", "preview"],
              ["Reveal in Explorer", "reveal"],
              ["To plot", "plot"],
              ["To sketch", "sketch"],
              ["To slideshow", "deck"],
            ];
            for (const [label, action] of items) {
              const b = document.createElement("button");
              b.textContent = label;
              b.onclick = () => { vscode.postMessage({ type: action, node: n }); menu.hidden = true; };
              menu.appendChild(b);
            }
          });
          wrap.appendChild(row);
        }
        list.appendChild(wrap);
      });
    }
    q.addEventListener("input", render);
    document.addEventListener("click", () => { menu.hidden = true; });
    render();
  </script>
</body></html>`;

  panel.webview.onDidReceiveMessage(async (msg: { type?: string; node?: GraphNode }) => {
    const node = msg.node;
    if (!node) return;
    const uri = wikiPageUri(folder, node.path);
    if (msg.type === "open") {
      await vscode.window.showTextDocument(uri);
      return;
    }
    if (msg.type === "preview") {
      await vscode.commands.executeCommand("switchbay.openPreview", uri);
      return;
    }
    if (msg.type === "reveal") {
      await vscode.commands.executeCommand("revealInExplorer", uri);
      return;
    }
    if (msg.type === "plot" || msg.type === "sketch" || msg.type === "deck") {
      const title = node.title || node.id;
      await vscode.commands.executeCommand("workbench.action.chat.open", {
        query: `@switchbay /${msg.type} ${title}`,
        isPartialQuery: false,
      });
    }
  });
  context.subscriptions.push(panel);
}

export function openHopper(context: vscode.ExtensionContext): void {
  const repo = repoRoot(context);
  const hopperDir = path.join(repo, "static", "mars-hopper");
  if (!fs.existsSync(path.join(hopperDir, "index.html"))) {
    void vscode.window.showErrorMessage("Mars Hopper assets are not bundled in this checkout.");
    return;
  }
  const root = vscode.Uri.file(hopperDir);
  const panel = vscode.window.createWebviewPanel(
    "switchbay.thrusters",
    "Mars Hopper",
    vscode.ViewColumn.One,
    { enableScripts: true, localResourceRoots: [root] },
  );
  const css = panel.webview.asWebviewUri(vscode.Uri.joinPath(root, "style.css"));
  const js = panel.webview.asWebviewUri(vscode.Uri.joinPath(root, "game.js"));
  let html = fs.readFileSync(path.join(hopperDir, "index.html"), "utf8");
  html = html
    .replace('href="/api/easter/mars-hopper/style.css"', `href="${css}"`)
    .replace('src="/api/easter/mars-hopper/game.js"', `src="${js}"`);
  panel.webview.html = html;
  context.subscriptions.push(panel);
}

export function openAgents(): void {
  const panel = vscode.window.createWebviewPanel(
    "switchbay.agents",
    "Agent Dashboard",
    vscode.ViewColumn.Beside,
    { enableScripts: true },
  );
  panel.webview.html = `<!DOCTYPE html>
<html><body style="font-family: var(--vscode-font-family); padding: 1.5rem; color: var(--vscode-foreground);">
  <h1>Agent Dashboard</h1>
  <p>DAG animation lands when Auto orchestration runs from <code>@switchbay /curate</code>.</p>
  <p>This spike watches run JSON on disk — nothing listens on <code>:8765</code>.</p>
</body></html>`;
}

export function openHtml(uri: vscode.Uri): void {
  const folder = path.dirname(uri.fsPath);
  const root = vscode.Uri.file(folder);
  const panel = vscode.window.createWebviewPanel(
    "switchbay.html",
    path.basename(folder),
    vscode.ViewColumn.One,
    { enableScripts: true, localResourceRoots: [root] },
  );
  if (!fs.existsSync(uri.fsPath)) {
    panel.webview.html = `<p>No HTML artifact at ${uri.fsPath}</p>`;
    return;
  }
  const htmlUri = panel.webview.asWebviewUri(uri);
  panel.webview.html = `<!DOCTYPE html>
<html><body style="margin:0">
<iframe src="${htmlUri}" style="border:0;width:100%;height:100vh" sandbox="allow-scripts allow-same-origin"></iframe>
</body></html>`;
}
