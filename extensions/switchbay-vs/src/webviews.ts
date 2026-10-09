import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";
import {
  ceRoot, dataJsonPath, kuzuDbExists, loadCurationHistory,
  rebuildKuzuGraph, rebuildViewer, wikiPageUri, type GraphNode,
} from "./ce";
import {
  answerCeApi, bundleFresh, ceViewerAvailable, type ApiHost, type ApiReply,
} from "./graphBundle";
import { startNamedAgentSession } from "./agentsSession";
import {
  agentsDashboardHtml, dashboardPayload, deleteRule,
} from "./dashboard";
import {
  addBlankDesk, deactivateAllDesks, desksPath, setDeskEnabled, setupDesk,
} from "./desks";
import { offerKeepRunning } from "./keepAlive";
import { applyOrchestrationReport, clearFinishedRuns, finishRun, listRuns, recordMcpActivity, runsRoot, stopRun } from "./orch";
import { hopperDir, workspaceFolder } from "./paths";
import { wikiFolderUri } from "./wikiRoot";
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

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));
}

function messageHtml(title: string, text: string): string {
  return `<!DOCTYPE html><html><head><meta charset="UTF-8" />
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'" />
<style>body{font:13px/1.5 var(--vscode-font-family,sans-serif);color:var(--vscode-foreground);padding:2rem;max-width:42rem}
h2{font-weight:600;font-size:1.1rem;margin:0 0 .5rem}code{font-family:var(--vscode-editor-font-family,monospace)}</style>
</head><body><h2>${escapeHtml(title)}</h2><p>${text}</p></body></html>`;
}

/**
 * The graph view is Curiosity Engine's viewer. Its scripts, styles and
 * figures come from CE's built wiki-view bundle (served as webview
 * resources); its API calls come back over postMessage.
 */
function graphWebviewHtml(
  webview: vscode.Webview,
  mediaRoot: vscode.Uri,
  bundle: vscode.Uri,
  workspace: string,
): string | null {
  const index = path.join(mediaRoot.fsPath, "webview-graph.html");
  if (!fs.existsSync(index)) return null;
  let html = fs.readFileSync(index, "utf8");
  const csp = [
    `default-src 'none'`,
    `img-src ${webview.cspSource} data: blob:`,
    `font-src ${webview.cspSource} data:`,
    `style-src ${webview.cspSource} 'unsafe-inline'`,
    `script-src ${webview.cspSource}`,
    `worker-src ${webview.cspSource} blob:`,
  ].join("; ");
  html = html.replace(/(src|href)="(\.\/[^"]+)"/g, (_m, attr: string, rel: string) => {
    const uri = webview.asWebviewUri(vscode.Uri.joinPath(mediaRoot, rel.replace(/^\.\//, "")));
    return `${attr}="${uri}"`;
  });
  const bundleUri = webview.asWebviewUri(bundle).toString().replace(/\/$/, "");
  // JSON data block, never executed; `<` escaped so page text can't close it.
  const config = JSON.stringify({ bundle: bundleUri, workspace }).replace(/</g, "\\u003c");
  html = html.replace(
    "<head>",
    `<head>\n<meta http-equiv="Content-Security-Policy" content="${csp}" />`
    // CE's page bodies reference figures relative to the bundle root.
    + `\n<base href="${bundleUri}/" />`
    + `\n<script type="application/json" id="sy-graph-config">${config}</script>`,
  );
  return html;
}

type GraphOpts = { onSearch?: (paths: string[], sourcePaths?: string[]) => void };

let graphPanel: vscode.WebviewPanel | undefined;
let graphRender: (() => Promise<void>) | undefined;
let graphRefreshTimer: ReturnType<typeof setTimeout> | undefined;
/** Wiki or graph db changed at this time; older bundles get rebuilt. */
let graphStaleSince = 0;

/** Our own bundle builds read graph.kuzu; ignore db events they cause. */
let graphBuilding = false;
let graphQuietUntil = 0;

/**
 * Wiki pages or the graph db changed on disk: rebuild CE's bundle on
 * next fetch and repaint an open graph.
 */
export function refreshGraph(source: "wiki" | "db" = "wiki"): void {
  if (source === "db" && (graphBuilding || Date.now() < graphQuietUntil)) return;
  graphStaleSince = Date.now();
  if (!graphPanel) return;
  if (graphRefreshTimer) clearTimeout(graphRefreshTimer);
  graphRefreshTimer = setTimeout(() => {
    graphRefreshTimer = undefined;
    void graphPanel?.webview.postMessage({ type: "refresh" });
  }, 600);
}

/** The wiki root setting changed: reload an open graph for the new workspace. */
export function graphWorkspaceChanged(): void {
  void graphRender?.();
}

export function openGraph(context: vscode.ExtensionContext, opts?: GraphOpts): void {
  if (graphPanel) {
    graphPanel.reveal(graphPanel.viewColumn ?? vscode.ViewColumn.One);
    return;
  }
  if (!(wikiFolderUri() || workspaceFolder())) {
    void vscode.window.showWarningMessage("Open a curiosity-engine folder first.");
    return;
  }
  const mediaRoot = graphMediaRoot(context);
  const panel = vscode.window.createWebviewPanel(
    "switchbay.graph",
    "Graph",
    vscode.ViewColumn.One,
    { enableScripts: true, retainContextWhenHidden: true, localResourceRoots: [mediaRoot] },
  );
  graphPanel = panel;
  let workspace = "";

  const rebuild = async (): Promise<void> => {
    graphBuilding = true;
    let r: { ok: boolean; text: string };
    try {
      if (!kuzuDbExists(workspace)) await rebuildKuzuGraph(workspace);
      r = await rebuildViewer(context, workspace);
    } finally {
      graphBuilding = false;
      graphQuietUntil = Date.now() + 3000;
    }
    if (!r.ok) {
      void vscode.window.showWarningMessage(`Could not build the graph: ${r.text.slice(-300)}`);
    }
  };
  let building: Promise<void> | null = null;
  const ensureBundle = async (progress: boolean): Promise<void> => {
    const bundleDir = path.dirname(dataJsonPath(workspace));
    if (bundleFresh(bundleDir, path.join(workspace, "wiki"), [], graphStaleSince)) return;
    if (!building) {
      const run = progress
        ? () => Promise.resolve(vscode.window.withProgress(
          { location: vscode.ProgressLocation.Notification, title: "Building knowledge graph…" },
          rebuild,
        ))
        : rebuild;
      building = run().finally(() => { building = null; });
    }
    await building;
  };

  const host = (): ApiHost => ({
    wikiDir: path.join(workspace, "wiki"),
    data: async () => {
      await ensureBundle(false);
      try { return fs.readFileSync(dataJsonPath(workspace), "utf8"); } catch { return null; }
    },
    rebuild: async () => {
      graphStaleSince = Date.now();
      await ensureBundle(false);
    },
    history: () => loadCurationHistory(context, workspace),
  });

  const render = async (): Promise<void> => {
    const folder = wikiFolderUri() || workspaceFolder();
    if (!folder) {
      panel.webview.html = messageHtml("No workspace", "Open a curiosity-engine folder to see its graph.");
      return;
    }
    workspace = folder.fsPath;
    panel.title = `Graph — ${path.basename(workspace)}`;
    const ce = ceRoot();
    if (!ceViewerAvailable(ce)) {
      // Same rule as the PWA, which hides its Graph tab without CE.
      panel.webview.html = messageHtml(
        "Graph needs Curiosity Engine",
        "The graph is Curiosity Engine's viewer, and no Curiosity Engine install was found "
        + "(looked in <code>~/.claude/skills/curiosity-engine</code>, <code>~/.agents/skills/curiosity-engine</code> "
        + "and <code>$SWITCHBAY_CE_ROOT</code>). Install or update Curiosity Engine, then reopen the graph.",
      );
      return;
    }
    if (!fs.existsSync(path.join(mediaRoot.fsPath, "webview-graph.html"))) {
      panel.webview.html = messageHtml(
        "Graph viewer is not built yet",
        "From the Switch Bay repo run <code>pnpm --dir frontend run build:webview</code>, then reload.",
      );
      return;
    }
    panel.webview.html = messageHtml("Graph", "Building knowledge graph…");
    await ensureBundle(true);
    const bundle = vscode.Uri.file(path.dirname(dataJsonPath(workspace)));
    if (!fs.existsSync(path.join(bundle.fsPath, "static", "embed.js"))) {
      panel.webview.html = messageHtml(
        "Graph could not be built",
        "Curiosity Engine did not produce a viewer bundle for this workspace. See the warning for details.",
      );
      return;
    }
    panel.webview.options = {
      enableScripts: true,
      localResourceRoots: [mediaRoot, bundle],
    };
    panel.webview.html = graphWebviewHtml(panel.webview, mediaRoot, bundle, path.basename(workspace))
      ?? messageHtml("Graph", "Graph viewer is missing.");
  };
  graphRender = render;

  panel.webview.onDidReceiveMessage(async (msg: {
    type?: string;
    id?: number;
    method?: string;
    path?: string;
    body?: string;
    node?: GraphNode;
    paths?: string[];
    sourcePaths?: string[];
  }) => {
    if (msg.type === "api" && typeof msg.id === "number") {
      let reply: ApiReply;
      try {
        reply = await answerCeApi(host(), (msg.method || "GET").toUpperCase(), msg.path || "/", msg.body);
      } catch (e) {
        reply = { status: 500, body: JSON.stringify({ error: String(e) }) };
      }
      void panel.webview.postMessage({ type: "api-result", id: msg.id, ...reply });
      return;
    }
    if (msg.type === "search") {
      opts?.onSearch?.(msg.paths ?? [], msg.sourcePaths ?? []);
      return;
    }
    const node = msg.node;
    if (!node || !workspace) return;
    const uri = wikiPageUri(vscode.Uri.file(workspace), node.path);
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
  panel.onDidDispose(() => {
    graphPanel = undefined;
    graphRender = undefined;
    opts?.onSearch?.([]);
  });
  context.subscriptions.push(panel);
  void render();
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

let agentsPanel: vscode.WebviewPanel | undefined;
let agentsRefresh: (() => void) | undefined;

export function openAgents(context: vscode.ExtensionContext): void {
  if (agentsPanel) {
    agentsPanel.reveal(agentsPanel.viewColumn ?? vscode.ViewColumn.Beside);
    agentsRefresh?.();
    return;
  }
  const folder = workspaceFolder();
  const panel = vscode.window.createWebviewPanel(
    "switchbay.agents",
    "Agent Dashboard",
    vscode.ViewColumn.Beside,
    { enableScripts: true, retainContextWhenHidden: true },
  );
  agentsPanel = panel;
  panel.webview.html = agentsDashboardHtml(nonce());
  const push = () => {
    void dashboardPayload(context, folder?.fsPath).then((payload) => {
      void panel.webview.postMessage({ payload });
    });
  };
  agentsRefresh = push;
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
      if (folder) {
        applyOrchestrationReport(folder.fsPath);
        recordMcpActivity(folder.fsPath);
      }
      push();
      return;
    }
    if (msg.type === "curate") {
      await vscode.commands.executeCommand("switchbay.curate");
      push();
      return;
    }
    if (msg.type === "finishRun" && folder && msg.id) {
      finishRun(folder.fsPath, msg.id);
      push();
      return;
    }
    if (msg.type === "stopRun" && folder && msg.id) {
      await stopRun(folder.fsPath, msg.id);
      push();
      return;
    }
    if (msg.type === "ingestFile") {
      await vscode.commands.executeCommand("switchbay.ingestFile");
      push();
      return;
    }
    if (msg.type === "ingestFolder") {
      await vscode.commands.executeCommand("switchbay.ingestFolder");
      push();
      return;
    }
    if (msg.type === "registerFolder") {
      await vscode.commands.executeCommand("switchbay.registerFolder");
      push();
      return;
    }
    if (msg.type === "clearFinished" && folder) {
      const n = clearFinishedRuns(folder.fsPath);
      void vscode.window.showInformationMessage(
        n ? `Cleared ${n} finished run${n === 1 ? "" : "s"} from the dashboard.` : "Nothing to clear.",
      );
      push();
      return;
    }
    if (msg.type === "keepRunning") {
      await offerKeepRunning();
      push();
      return;
    }
    if (msg.type === "setupDesk" && folder && msg.id) {
      const result = setupDesk(folder.fsPath, msg.id);
      if (result.ok) {
        await vscode.window.showTextDocument(vscode.Uri.file(result.path), { preview: false });
        void vscode.window.showInformationMessage(result.text);
      } else {
        void vscode.window.showWarningMessage(result.text);
      }
      push();
      return;
    }
    if (msg.type === "activateDesk" && folder && msg.id) {
      const result = setDeskEnabled(folder.fsPath, msg.id, true);
      if (result.ok) void offerKeepRunning(result.text);
      else void vscode.window.showWarningMessage(result.text);
      push();
      return;
    }
    if (msg.type === "deactivateDesk" && folder && msg.id) {
      const result = setDeskEnabled(folder.fsPath, msg.id, false);
      void vscode.window.showInformationMessage(result.text);
      push();
      return;
    }
    if (msg.type === "deactivateAllDesks" && folder) {
      const result = deactivateAllDesks(folder.fsPath);
      void vscode.window.showInformationMessage(result.text);
      push();
      return;
    }
    if (msg.type === "addDesk" && folder) {
      const result = addBlankDesk(folder.fsPath);
      await vscode.window.showTextDocument(vscode.Uri.file(result.path), { preview: false });
      void vscode.window.showInformationMessage(result.text);
      push();
      return;
    }
    if (msg.type === "editDesks" && folder) {
      const p = desksPath(folder.fsPath);
      if (!fs.existsSync(p)) addBlankDesk(folder.fsPath);
      await vscode.window.showTextDocument(vscode.Uri.file(desksPath(folder.fsPath)), { preview: false });
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
        until_at: msg.item.until_at == null ? null : Number(msg.item.until_at) || null,
      });
      void offerKeepRunning("This schedule will fire only while VS Code is open.");
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
      const session = await startNamedAgentSession(context, msg.agent, `Run as ${msg.agent}.`);
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
    const proposals = path.join(ws, ".workbench", "proposals");
    fs.mkdirSync(proposals, { recursive: true });
    watch(proposals);
    const tick = setInterval(() => {
      applyOrchestrationReport(ws);
      recordMcpActivity(ws);
      listRuns(ws);
      push();
    }, 8000);
    panel.onDidDispose(() => clearInterval(tick));
    const githubAgents = path.join(ws, ".github", "agents");
    fs.mkdirSync(githubAgents, { recursive: true });
    watch(githubAgents);
    panel.onDidDispose(() => {
      clearTimeout(debounce);
      watchers.forEach((w) => w.close());
      if (agentsPanel === panel) {
        agentsPanel = undefined;
        agentsRefresh = undefined;
      }
    });
  }
  const cfgWatch = vscode.workspace.onDidChangeConfiguration((e) => {
    if (e.affectsConfiguration("switchbay.orchestrationPreference")) push();
  });
  panel.onDidDispose(() => {
    cfgWatch.dispose();
    if (agentsPanel === panel) {
      agentsPanel = undefined;
      agentsRefresh = undefined;
    }
  });
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
