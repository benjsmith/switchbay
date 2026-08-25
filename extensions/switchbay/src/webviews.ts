import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";
import {
  ensureGraphEdges, kuzuDbExists, readCachedGraph, rebuildKuzuGraph,
  scanWikiMarkdown, wikiPageUri, type GraphData, type GraphNode,
} from "./ce";
import { listRuns, runsRoot } from "./orch";
import { repoRoot, workspaceFolder } from "./paths";

function nonce(): string {
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  let s = "";
  for (let i = 0; i < 32; i++) s += chars[Math.floor(Math.random() * chars.length)];
  return s;
}

function graphMediaRoot(context: vscode.ExtensionContext): vscode.Uri {
  return vscode.Uri.joinPath(context.extensionUri, "media", "graph");
}

function graphWebviewHtml(webview: vscode.Webview, mediaRoot: vscode.Uri): string | null {
  const index = path.join(mediaRoot.fsPath, "webview-graph.html");
  if (!fs.existsSync(index)) return null;
  let html = fs.readFileSync(index, "utf8");
  const csp = [
    `default-src 'none'`,
    `img-src ${webview.cspSource} data:`,
    `font-src ${webview.cspSource} data:`,
    `style-src ${webview.cspSource} 'unsafe-inline'`,
    `script-src ${webview.cspSource}`,
  ].join("; ");
  html = html.replace(
    "<head>",
    `<head>\n<meta http-equiv="Content-Security-Policy" content="${csp}" />`,
  );
  html = html.replace(/(src|href)="(\.\/[^"]+)"/g, (_m, attr: string, rel: string) => {
    const uri = webview.asWebviewUri(vscode.Uri.joinPath(mediaRoot, rel.replace(/^\.\//, "")));
    return `${attr}="${uri}"`;
  });
  return html;
}

export function openGraph(context: vscode.ExtensionContext): void {
  const folder = workspaceFolder();
  if (!folder) {
    void vscode.window.showWarningMessage("Open a curiosity-engine folder first.");
    return;
  }
  const mediaRoot = graphMediaRoot(context);
  const panel = vscode.window.createWebviewPanel(
    "switchbay.graph",
    "Graph",
    vscode.ViewColumn.One,
    {
      enableScripts: true,
      retainContextWhenHidden: true,
      localResourceRoots: [mediaRoot],
    },
  );
  const html = graphWebviewHtml(panel.webview, mediaRoot);
  if (!html) {
    panel.webview.html = `<p style="padding:1.5rem;font-family:sans-serif">Graph viewer is not built yet.
      From the Switch Bay repo run <code>pnpm --dir frontend run build:webview</code> then F5 again.</p>`;
    return;
  }
  const sendGraph = async () => {
    const ws = folder.fsPath;
    if (!kuzuDbExists(ws)) {
      await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: "Building knowledge graph (graph.kuzu missing)…",
          cancellable: false,
        },
        async () => {
          const r = await rebuildKuzuGraph(ws);
          if (!r.ok) {
            void vscode.window.showWarningMessage(
              `Could not build graph.kuzu: ${r.text.slice(0, 300)}`,
            );
          }
        },
      );
    }
    const graph: GraphData = readCachedGraph(ws) ?? ensureGraphEdges({
      nodes: scanWikiMarkdown(ws),
      edges: [],
    }, ws);
    if (graph.pages) {
      for (const page of Object.values(graph.pages)) delete page.body_html;
    }
    void panel.webview.postMessage({ graph });
  };
  panel.webview.onDidReceiveMessage(async (msg: { type?: string; node?: GraphNode }) => {
    if (msg.type === "ready") {
      await sendGraph();
      return;
    }
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
  panel.webview.html = html;
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
