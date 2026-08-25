import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";
import { listNamedAgents, openAgentsWindow, optIntoAgentsWindow, startNamedAgentSession } from "./agentsSession";
import { registerChat } from "./chat";
import { readCachedGraph, rebuildViewer, wikiPageUri, type GraphNode } from "./ce";
import { disposeMcp } from "./mcp";
import { registerMcpProvider } from "./mcpProvider";
import { startCurate } from "./orch";
import { workspaceFolder } from "./paths";
import { getPreference, preferenceLabel, setPreference } from "./preference";
import { openWikiPage, openWikiPreview } from "./preview";
import { ProjectsTreeProvider } from "./projectsTree";
import { startScheduleTicker, upsertSchedule } from "./schedules";
import { configurePython, maybeOfferSetup, probeSwitchbay } from "./setup";
import { checkAndOfferUpdate } from "./update";
import { openAgents, openGraph, openHopper, openHtml } from "./webviews";
import { WikiTreeProvider } from "./wikiTree";
import { registerLocalModels } from "./localModels";

function updateWikiContext(): void {
  const folder = workspaceFolder();
  const hasWiki = Boolean(folder && fs.existsSync(path.join(folder.fsPath, "wiki")));
  void vscode.commands.executeCommand("setContext", "switchbay.hasWiki", hasWiki);
}

export function activate(context: vscode.ExtensionContext): void {
  const log = vscode.window.createOutputChannel("Switch Bay VS");
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
    vscode.commands.registerCommand("switchbay.openAgents", () => openAgents(context)),
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
      await openWikiPage(uri);
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
  registerLocalModels(context);
  updateWikiContext();

  const ping = () => {
    updateWikiContext();
    wiki.refresh();
    projects.refresh();
  };
  const folder = workspaceFolder();
  if (folder) {
    const watcher = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(folder, "wiki/**/*.md"));
    watcher.onDidChange(ping);
    watcher.onDidCreate(ping);
    watcher.onDidDelete(ping);
    context.subscriptions.push(watcher);
  }

  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
  const paintStatus = (pythonOk: boolean) => {
    if (!pythonOk) {
      status.text = "$(warning) Switch Bay VS · configure Python";
      status.command = "switchbay.configurePython";
      status.tooltip = "import switchbay failed — click to set repoRoot / pythonPath";
      status.backgroundColor = new vscode.ThemeColor("statusBarItem.warningBackground");
      return;
    }
    const ws = workspaceFolder();
    const cached = ws ? readCachedGraph(ws.fsPath) : null;
    status.text = cached
      ? `$(type-hierarchy) Switch Bay VS · ${cached.nodes.length} nodes · ${(cached.edges || []).length} edges`
      : "$(type-hierarchy) Switch Bay VS";
    status.command = "switchbay.openGraph";
    status.tooltip = "Open Graph (no daemon)";
    status.backgroundColor = undefined;
  };
  const refreshPythonStatus = async () => {
    const result = await probeSwitchbay(context);
    paintStatus(result.ok);
  };
  paintStatus(true);
  status.show();
  context.subscriptions.push(
    status,
    vscode.commands.registerCommand("switchbay.configurePython", async () => {
      const ok = await configurePython(context);
      if (ok) paintStatus(true);
      else void refreshPythonStatus();
    }),
    vscode.commands.registerCommand("switchbay.setEffort", async () => {
      const current = getPreference();
      const pick = await vscode.window.showQuickPick(
        [
          { label: "Economy", description: "Single-step, no subagents", pref: 0.1 },
          { label: "Balanced", description: "One investigator, then curate", pref: 0.5 },
          { label: "Maximum", description: "Investigate → verify → synthesize", pref: 0.9 },
        ].map((o) => ({
          ...o,
          picked: preferenceLabel(current) === o.label,
          detail: preferenceLabel(current) === o.label ? "current" : undefined,
        })),
        { title: "Switch Bay orchestration effort" },
      );
      if (!pick) return;
      await setPreference(pick.pref);
      void vscode.window.showInformationMessage(`Orchestration effort: ${pick.label}`);
    }),
    vscode.commands.registerCommand("switchbay.addSchedule", async () => {
      const folder = workspaceFolder();
      if (!folder) {
        void vscode.window.showWarningMessage("Open a curiosity-engine folder first.");
        return;
      }
      const agents = listNamedAgents(context.extensionPath, folder.fsPath)
        .filter((a) => a.invocable);
      const agentPick = await vscode.window.showQuickPick(
        agents.map((a) => ({
          label: a.name,
          description: a.source,
          detail: a.description,
        })),
        { title: "Which named agent should this schedule run?" },
      );
      if (!agentPick) return;
      const title = await vscode.window.showInputBox({ title: "Schedule title", value: `${agentPick.label} desk` });
      if (title === undefined) return;
      const prompt = await vscode.window.showInputBox({
        title: `Prompt for ${agentPick.label}`,
        placeHolder: "What should this agent do when it fires?",
      });
      if (prompt === undefined) return;
      const freq = await vscode.window.showQuickPick(
        [
          { label: "Hourly", id: "hourly" as const },
          { label: "Daily", id: "daily" as const },
          { label: "Weekly", id: "weekly" as const },
          { label: "Every N hours", id: "every_n_hours" as const },
        ],
        { title: "Frequency" },
      );
      if (!freq) return;
      upsertSchedule(folder.fsPath, {
        title,
        prompt,
        agent: agentPick.label,
        frequency: freq.id,
        enabled: true,
      });
      void vscode.window.showInformationMessage(`Scheduled “${title}” on ${agentPick.label}.`);
      void vscode.commands.executeCommand("switchbay.openAgents");
    }),
    vscode.commands.registerCommand("switchbay.runNamedAgent", async () => {
      const folder = workspaceFolder();
      const agents = listNamedAgents(context.extensionPath, folder?.fsPath)
        .filter((a) => a.invocable);
      const pick = await vscode.window.showQuickPick(
        agents.map((a) => ({ label: a.name, description: a.source, detail: a.description })),
        { title: "Run named agent" },
      );
      if (!pick) return;
      await startNamedAgentSession(pick.label, `Run as ${pick.label}.`);
    }),
    vscode.commands.registerCommand("switchbay.checkUpdate", () => checkAndOfferUpdate(context)),
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (
        e.affectsConfiguration("switchbay.repoRoot")
        || e.affectsConfiguration("switchbay.pythonPath")
      ) {
        void refreshPythonStatus();
      }
    }),
    vscode.workspace.onDidChangeWorkspaceFolders(() => {
      ping();
      void refreshPythonStatus();
    }),
  );
  maybeOfferSetup(context, paintStatus);
  startScheduleTicker(context);
}

export function deactivate(): void {
  disposeMcp();
}
