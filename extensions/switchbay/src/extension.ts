import * as vscode from "vscode";
import { registerChat } from "./chat";
import { readCachedGraph, rebuildViewer, wikiPageUri, type GraphNode } from "./ce";
import { disposeMcp } from "./mcp";
import { workspaceFolder } from "./paths";
import { openWikiPreview } from "./preview";
import { ProjectsTreeProvider } from "./projectsTree";
import { openAgents, openGraph, openHopper, openHtml } from "./webviews";
import { WikiTreeProvider } from "./wikiTree";

export function activate(context: vscode.ExtensionContext): void {
  const wiki = new WikiTreeProvider();
  const projects = new ProjectsTreeProvider();
  context.subscriptions.push(
    vscode.window.registerTreeDataProvider("switchbay.wiki", wiki),
    vscode.window.registerTreeDataProvider("switchbay.projects", projects),
    vscode.commands.registerCommand("switchbay.openGraph", () => openGraph(context)),
    vscode.commands.registerCommand("switchbay.openPreview", (uri?: vscode.Uri) => openWikiPreview(uri)),
    vscode.commands.registerCommand("switchbay.openAgents", () => openAgents()),
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
  registerChat(context);

  const folder = workspaceFolder();
  if (folder) {
    const watcher = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(folder, "wiki/**/*.md"));
    const ping = () => { wiki.refresh(); projects.refresh(); };
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
