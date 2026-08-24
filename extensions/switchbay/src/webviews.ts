import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";
import { readCachedGraph, scanWikiMarkdown, wikiPageUri, type GraphNode } from "./ce";
import { listRuns, runsRoot } from "./orch";
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
  const folder = workspaceFolder();
  const panel = vscode.window.createWebviewPanel(
    "switchbay.agents",
    "Agent Dashboard",
    vscode.ViewColumn.Beside,
    { enableScripts: true },
  );
  const n = nonce();
  panel.webview.html = `<!DOCTYPE html>
<html><head>
<meta charset="UTF-8" />
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${n}'" />
<style>
  body { font-family: var(--vscode-font-family); padding: 1.25rem 1.5rem; color: var(--vscode-foreground); }
  h1 { font-size: 1.1rem; }
  .muted { opacity: 0.65; font-size: 0.85rem; }
  .run { border: 1px solid var(--vscode-widget-border, #444); border-radius: 6px; padding: 0.8rem 1rem; margin: 0.8rem 0; }
  .nodes { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-top: 0.5rem; }
  .node { padding: 0.2rem 0.55rem; border-radius: 999px; font-size: 0.8rem;
          background: var(--vscode-badge-background); color: var(--vscode-badge-foreground); }
  .node.running { outline: 1px solid var(--vscode-focusBorder); }
  .node.done { opacity: 0.85; }
  .node.failed { background: var(--vscode-inputValidation-errorBackground, #5a1d1d); }
  pre { white-space: pre-wrap; font-size: 0.8rem; max-height: 8rem; overflow: auto; }
</style>
</head>
<body>
  <h1>Agent Dashboard</h1>
  <p class="muted">File-watched Switch Bay DAG. VS Code Agents window owns the long-running loop. Nothing on :8765.</p>
  <div id="list">No runs yet. Use <code>@switchbay /curate</code> or <strong>Switch Bay: Curate</strong>.</div>
  <script nonce="${n}">
    const vscode = acquireVsCodeApi();
    const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\\u0022":"&quot;","'":"&#39;"}[c] || c));
    window.addEventListener("message", (ev) => {
      const runs = ev.data && ev.data.runs;
      if (!Array.isArray(runs)) return;
      const el = document.getElementById("list");
      if (!runs.length) { el.textContent = "No runs yet."; return; }
      el.innerHTML = runs.map((r) => {
        const nodes = (r.nodes || []).map((n) =>
          "<span class='node " + esc(n.status || "") + "'>" + esc(n.kind) + " · " + esc(n.status || "pending") + "</span>"
        ).join("");
        return "<div class='run'><strong>" + esc(r.objective || r.orchestration_id) + "</strong>"
          + "<div class='muted'>" + esc(r.phase || "") + " · " + esc(r.via || "") + " · " + esc(r.orchestration_id) + "</div>"
          + "<div class='nodes'>" + nodes + "</div>"
          + (r.note ? "<pre>" + esc(String(r.note).slice(0, 1200)) + "</pre>" : "")
          + "</div>";
      }).join("");
    });
  </script>
</body></html>`;

  const push = () => {
    const ws = folder?.fsPath;
    if (!ws) {
      void panel.webview.postMessage({ runs: [] });
      return;
    }
    void panel.webview.postMessage({ runs: listRuns(ws) });
  };
  push();
  const ws = folder?.fsPath;
  if (ws) {
    const root = runsRoot(ws);
    fs.mkdirSync(root, { recursive: true });
    try {
      const watcher = fs.watch(root, { recursive: true }, () => push());
      panel.onDidDispose(() => watcher.close());
    } catch {
      const id = setInterval(push, 2000);
      panel.onDidDispose(() => clearInterval(id));
    }
  }
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
