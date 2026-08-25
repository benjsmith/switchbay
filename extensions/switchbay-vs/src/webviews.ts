import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";
import {
  ensureGraphEdges, kuzuDbExists, loadCurationHistory, readCachedGraph,
  rebuildKuzuGraph, scanWikiMarkdown, wikiPageUri, type GraphData, type GraphNode,
} from "./ce";
import { startNamedAgentSession } from "./agentsSession";
import {
  agentsDashboardHtml, dashboardPayload, deleteRule,
} from "./dashboard";
import { runsRoot } from "./orch";
import { hopperDir, workspaceFolder } from "./paths";
import { setPreference } from "./preference";
import { openWikiPage } from "./preview";
import { deleteSchedule, runScheduleNow, upsertSchedule } from "./schedules";
import { checkAndOfferUpdate } from "./update";

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
    if (msg.type === "history") {
      const history = await loadCurationHistory(context, folder.fsPath);
      void panel.webview.postMessage({ type: "curation-history", history });
      return;
    }
    const node = msg.node;
    if (!node) return;
    const uri = wikiPageUri(folder, node.path);
    if (msg.type === "open") {
      await openWikiPage(uri);
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
  const dir = hopperDir(context);
  if (!fs.existsSync(path.join(dir, "index.html"))) {
    void vscode.window.showErrorMessage("Mars Hopper assets are not bundled in this install.");
    return;
  }
  const root = vscode.Uri.file(dir);
  const panel = vscode.window.createWebviewPanel(
    "switchbay.thrusters",
    "Mars Hopper",
    vscode.ViewColumn.One,
    { enableScripts: true, localResourceRoots: [root] },
  );
  const css = panel.webview.asWebviewUri(vscode.Uri.joinPath(root, "style.css"));
  const js = panel.webview.asWebviewUri(vscode.Uri.joinPath(root, "game.js"));
  let html = fs.readFileSync(path.join(dir, "index.html"), "utf8");
  html = html
    .replace('href="/api/easter/mars-hopper/style.css"', `href="${css}"`)
    .replace('src="/api/easter/mars-hopper/game.js"', `src="${js}"`);
  panel.webview.html = html;
  context.subscriptions.push(panel);
}

export function openAgents(context: vscode.ExtensionContext): void {
  const folder = workspaceFolder();
  const panel = vscode.window.createWebviewPanel(
    "switchbay.agents",
    "Agent Dashboard",
    vscode.ViewColumn.Beside,
    { enableScripts: true, retainContextWhenHidden: true },
  );
  panel.webview.html = agentsDashboardHtml(nonce());
  const push = () => {
    void dashboardPayload(context, folder?.fsPath).then((payload) => {
      void panel.webview.postMessage({ payload });
    });
  };
  panel.webview.onDidReceiveMessage(async (msg: {
    type?: string;
    path?: string;
    id?: string;
    value?: number;
    item?: Record<string, unknown>;
    enabled?: boolean;
    agent?: string;
  }) => {
    if (msg.type === "ready" || msg.type === "refresh") {
      push();
      return;
    }
    if (msg.type === "curate") {
      await vscode.commands.executeCommand("switchbay.curate");
      push();
      return;
    }
    if (msg.type === "agentsWindow") {
      await vscode.commands.executeCommand("switchbay.openAgentsWindow");
      return;
    }
    if (msg.type === "checkUpdate") {
      await checkAndOfferUpdate(context);
      return;
    }
    if (msg.type === "setPreference" && typeof msg.value === "number") {
      await setPreference(msg.value);
      push();
      return;
    }
    if (msg.type === "saveSchedule" && folder && msg.item) {
      upsertSchedule(folder.fsPath, {
        title: String(msg.item.title || ""),
        prompt: String(msg.item.prompt || ""),
        frequency: msg.item.frequency as "hourly" | "daily" | "weekly" | "every_n_hours",
        every_hours: Number(msg.item.every_hours) || 24,
        agent: String(msg.item.agent || "Auto"),
        enabled: msg.item.enabled !== false,
      });
      push();
      return;
    }
    if (msg.type === "deleteSchedule" && folder && msg.id) {
      deleteSchedule(folder.fsPath, msg.id);
      push();
      return;
    }
    if (msg.type === "toggleSchedule" && folder && msg.id) {
      upsertSchedule(folder.fsPath, { id: msg.id, enabled: Boolean(msg.enabled) });
      push();
      return;
    }
    if (msg.type === "runSchedule" && folder && msg.id) {
      const result = await runScheduleNow(context, folder.fsPath, msg.id);
      void vscode.window.showInformationMessage(result.text.replace(/[*`]/g, "").slice(0, 220));
      push();
      return;
    }
    if (msg.type === "runAgent" && msg.agent) {
      const session = await startNamedAgentSession(msg.agent, `Run as ${msg.agent}.`);
      if (!session.opened) {
        void vscode.window.showWarningMessage(`Could not open the ${msg.agent} agent.`);
      }
      return;
    }
    if (msg.type === "localModels") {
      await vscode.commands.executeCommand("switchbay.localModels");
      push();
      return;
    }
    if (msg.type === "openSkill" && msg.path) {
      const uri = vscode.Uri.file(msg.path);
      await vscode.window.showTextDocument(uri, { preview: true });
      return;
    }
    if (msg.type === "deleteRule" && msg.id && folder) {
      deleteRule(folder.fsPath, msg.id);
      push();
    }
  });
  push();
  const ws = folder?.fsPath;
  if (ws) {
    const root = runsRoot(ws);
    fs.mkdirSync(root, { recursive: true });
    const watchers: fs.FSWatcher[] = [];
    let debounce: ReturnType<typeof setTimeout> | undefined;
    const pushSoon = () => {
      clearTimeout(debounce);
      debounce = setTimeout(push, 250);
    };
    const watch = (dir: string) => {
      try {
        watchers.push(fs.watch(dir, { recursive: true }, () => pushSoon()));
      } catch { /* ignore */ }
    };
    watch(root);
    const rulesDir = path.join(ws, ".workbench", "state");
    fs.mkdirSync(rulesDir, { recursive: true });
    watch(rulesDir);
    const githubAgents = path.join(ws, ".github", "agents");
    fs.mkdirSync(githubAgents, { recursive: true });
    watch(githubAgents);
    panel.onDidDispose(() => {
      clearTimeout(debounce);
      watchers.forEach((w) => w.close());
    });
  }
  const cfgWatch = vscode.workspace.onDidChangeConfiguration((e) => {
    if (e.affectsConfiguration("switchbay.orchestrationPreference")) push();
  });
  panel.onDidDispose(() => cfgWatch.dispose());
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
