import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";
import { openAgentsWindow, optIntoAgentsWindow } from "./agentsSession";
import { registerChat } from "./chat";
import { readCachedGraph, rebuildViewer, wikiPageUri, type GraphNode } from "./ce";
import { disposeMcp } from "./mcp";
import { registerMcpProvider } from "./mcpProvider";
import { startCurate } from "./orch";
import { workspaceFolder } from "./paths";
import { openWikiPreview } from "./preview";
import { ProjectsTreeProvider } from "./projectsTree";
import { openAgents, openGraph, openHopper, openHtml } from "./webviews";
import { WikiTreeProvider } from "./wikiTree";

function updateWikiContext(): void {
  const folder = workspaceFolder();
  const hasWiki = Boolean(folder && fs.existsSync(path.join(folder.fsPath, "wiki")));
  void vscode.commands.executeCommand("setContext", "switchbay.hasWiki", hasWiki);
}

export function activate(context: vscode.ExtensionContext): void {
  const log = vscode.window.createOutputChannel("Switch Bay");
  context.subscriptions.push(log);
  const wiki = new WikiTreeProvider();
  const projects = new ProjectsTreeProvider();
  // Views first — MCP/chat failures must not leave "no data provider".
  context.subscriptions.push(
    vscode.window.registerTreeDataProvider("switchbay.wiki", wiki),
    vscode.window.registerTreeDataProvider("switchbay.projects", projects),
    vscode.commands.registerCommand("switchbay.openWorkspace", () =>
      vscode.commands.executeCommand("workbench.action.files.openFolder")),
    vscode.commands.registerCommand("switchbay.refreshTrees", () => {
      updateWikiContext();
      wiki.refresh();
      projects.refresh();
    }),
    vscode.commands.registerCommand("switchbay.openGraph", () => openGraph(context)),
    vscode.commands.registerCommand("switchbay.openPreview", (uri?: vscode.Uri) => openWikiPreview(uri)),
    vscode.commands.registerCommand("switchbay.openAgents", () => openAgents()),
    vscode.commands.registerCommand("switchbay.openAgentsWindow", () => openAgentsWindow()),
    vscode.commands.registerCommand("switchbay.curate", async () => {
      const prompt = await vscode.window.showInputBox({
        title: "Switch Bay Auto",
        prompt: "What should we curate or research?",
        placeHolder: "curate the wiki",
      });
      if (prompt === undefined) return;
      const { text } = await startCurate(context, prompt);
      void vscode.window.showInformationMessage(text.replace(/[*`]/g, "").slice(0, 200));
    }),
    vscode.commands.registerCommand("switchbay.fireThrusters", () => openHopper(context)),
    vscode.commands.registerCommand("switchbay.openHtml", (uri: vscode.Uri) => openHtml(uri)),
    vscode.commands.registerCommand("switchbay.openPage", async (node: GraphNode) => {
      const folder = workspaceFolder();
      if (!folder || !node) return;
      const uri = wikiPageUri(folder, node.path);
      await vscode.window.showTextDocument(uri);
    }),
    vscode.commands.registerCommand("switchbay.rebuildViewer", async () => {
      const folder = workspaceFolder();
      if (!folder) {
        void vscode.window.showWarningMessage("Open a folder first.");
        return;
      }
      await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: "Rebuilding wiki viewer…" },
        async () => {
          const result = await rebuildViewer(context, folder.fsPath);
          if (result.ok) {
            wiki.refresh();
            projects.refresh();
            void vscode.window.showInformationMessage("Wiki viewer rebuilt.");
          } else {
            void vscode.window.showErrorMessage(`Viewer rebuild failed.\n${result.text.slice(-500)}`);
          }
        },
      );
    }),
  );

  try {
    registerMcpProvider(context);
  } catch (err) {
    log.appendLine(`MCP provider failed: ${err}`);
  }
  try {
    registerChat(context);
  } catch (err) {
    log.appendLine(`Chat participant failed: ${err}`);
  }
  void optIntoAgentsWindow();
  updateWikiContext();

  const ping = () => {
    updateWikiContext();
    wiki.refresh();
    projects.refresh();
  };
  context.subscriptions.push(vscode.workspace.onDidChangeWorkspaceFolders(() => ping()));
  const folder = workspaceFolder();
  if (folder) {
    const watcher = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(folder, "wiki/**/*.md"));
    watcher.onDidChange(ping);
    watcher.onDidCreate(ping);
    watcher.onDidDelete(ping);
    context.subscriptions.push(watcher);
  }

  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
  status.command = "switchbay.openGraph";
  const cached = folder ? readCachedGraph(folder.fsPath) : null;
  status.text = cached
    ? `$(type-hierarchy) Switch Bay · ${cached.nodes.length} nodes`
    : "$(type-hierarchy) Switch Bay";
  status.tooltip = "Open Graph (no daemon)";
  status.show();
  context.subscriptions.push(status);
}

export function deactivate(): void {
  disposeMcp();
}
