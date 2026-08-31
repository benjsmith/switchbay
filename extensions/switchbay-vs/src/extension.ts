import * as path from "path";
import * as vscode from "vscode";
import { listNamedAgents, openAgentsWindow, optIntoAgentsWindow, startNamedAgentSession } from "./agentsSession";
import { disposeMcp, tryStartWorkspaceMcp, writeWorkspaceMcpJson } from "./mcp";
import { notifyMcpDefinitionsChanged, registerMcpProvider } from "./mcpProvider";
import { registerChat } from "./chat";
import { invalidateKuzuCache, readCachedGraph, rebuildKuzuGraph, rebuildViewer, wikiPageUri, type GraphNode } from "./ce";
import { startChatObserver } from "./chatObserve";
import { ingestWithProgress, pickAndIngest } from "./ingest";
import { offerKeepRunning } from "./keepAlive";
import { applyOrchestrationReport, recordMcpActivity, recordWikiWrite, startCurate } from "./orch";
import { workspaceFolder } from "./paths";
import { chooseKnowledgeHarness, registerOpenFolder, rememberWiki } from "./registerRepo";
import {
  invalidateWikiRootCache, knowledgeHarnessOn, modeLabel, pickWikiRoot,
  resolveWiki, wikiFolderUri, wikiFsPath,
} from "./wikiRoot";
import { getPreference, preferenceLabel, setPreference } from "./preference";
import { openWikiPage, openWikiPreview } from "./preview";
import { ProjectsTreeProvider } from "./projectsTree";
import { startScheduleTicker, upsertSchedule } from "./schedules";
import { configurePython, maybeOfferSetup, probeSwitchbay } from "./setup";
import { checkAndOfferUpdate } from "./update";
import { openAgents, openGraph, openHopper, openHtml } from "./webviews";
import { WikiSearchDecorations, WikiTreeProvider } from "./wikiTree";
import { registerLocalModels } from "./localModels";

function updateWikiContext(): void {
  invalidateWikiRootCache();
  const res = resolveWiki();
  void vscode.commands.executeCommand("setContext", "switchbay.hasWiki", Boolean(res.wikiRoot));
  void vscode.commands.executeCommand("setContext", "switchbay.modeCodeRepo", res.mode === "code-repo");
  void vscode.commands.executeCommand("setContext", "switchbay.harnessOn", knowledgeHarnessOn());
}

export function activate(context: vscode.ExtensionContext): void {
  const log = vscode.window.createOutputChannel("Switch Bay VS");
  context.subscriptions.push(log);
  const wiki = new WikiTreeProvider();
  const wikiDecor = new WikiSearchDecorations();
  const projects = new ProjectsTreeProvider();
  // Wiki tree marks the matched pages; the Explorer badges every file
  // behind the search, the vault sources of those pages included.
  const applyGraphSearch = (paths: string[], sourcePaths: string[] = []) => {
    wiki.setSearchPaths(paths);
    const folder = wikiFolderUri();
    if (!folder) {
      wikiDecor.setHits([]);
      return;
    }
    wikiDecor.setHits(
      [...paths, ...sourcePaths].map((p) => wikiPageUri(folder, p).fsPath),
    );
  };
  // Views first — MCP/chat failures must not leave "no data provider".
  context.subscriptions.push(
    vscode.window.createTreeView("switchbay.wiki", { treeDataProvider: wiki }),
    vscode.window.registerFileDecorationProvider(wikiDecor),
    vscode.window.registerTreeDataProvider("switchbay.projects", projects),
    vscode.commands.registerCommand("switchbay.openWorkspace", () =>
      vscode.commands.executeCommand("workbench.action.files.openFolder")),
    vscode.commands.registerCommand("switchbay.refreshTrees", async () => {
      updateWikiContext();
      const root = wikiFsPath();
      if (root) {
        invalidateKuzuCache();
        await vscode.window.withProgress(
          { location: vscode.ProgressLocation.Notification, title: "Rebuilding knowledge graph…" },
          async () => {
            const result = await rebuildKuzuGraph(root, { force: true });
            if (!result.ok) {
              void vscode.window.showWarningMessage(
                `Graph rebuild failed; tree shows last kuzu snapshot.\n${result.text.slice(-300)}`,
              );
            }
          },
        );
      }
      wiki.refresh();
      projects.refresh();
    }),
    vscode.commands.registerCommand("switchbay.ingestFile", () => pickAndIngest(context, false)),
    vscode.commands.registerCommand("switchbay.ingestFolder", () => pickAndIngest(context, true)),
    vscode.commands.registerCommand("switchbay.ingestPath", async (uri?: vscode.Uri) => {
      const target = uri?.fsPath;
      if (!target) {
        await pickAndIngest(context, false);
        return;
      }
      await ingestWithProgress(context, target);
    }),
    vscode.commands.registerCommand("switchbay.setWikiRoot", async () => {
      const dir = await pickWikiRoot();
      if (!dir) return;
      await rememberWiki(context, dir);
      writeWorkspaceMcpJson(context);
      notifyMcpDefinitionsChanged();
      ping();
      void vscode.window.showInformationMessage(`Wiki workspace: ${dir}`);
    }),
    vscode.commands.registerCommand("switchbay.registerFolder", async () => {
      await registerOpenFolder(context);
      writeWorkspaceMcpJson(context);
      notifyMcpDefinitionsChanged();
      ping();
    }),
    vscode.commands.registerCommand("switchbay.chooseHarness", async () => {
      const next = await chooseKnowledgeHarness();
      if (next == null) return;
      updateWikiContext();
      writeWorkspaceMcpJson(context);
      notifyMcpDefinitionsChanged();
    }),
    vscode.commands.registerCommand("switchbay.toggleHarness", () =>
      vscode.commands.executeCommand("switchbay.chooseHarness")),
    vscode.commands.registerCommand("switchbay.openGraph", () =>
      openGraph(context, { onSearch: applyGraphSearch })),
    vscode.commands.registerCommand("switchbay.openPreview", (uri?: vscode.Uri) => openWikiPreview(uri)),
    vscode.commands.registerCommand("switchbay.openAgents", () => openAgents(context)),
    vscode.commands.registerCommand("switchbay.openAgentsWindow", () => openAgentsWindow()),
    vscode.commands.registerCommand("switchbay.keepRunning", () => offerKeepRunning()),
    vscode.commands.registerCommand("switchbay.curate", async () => {
      if (!knowledgeHarnessOn()) {
        void vscode.window.showWarningMessage("Knowledge harness is off. Toggle it on to curate.");
        return;
      }
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
      const folder = wikiFolderUri() || workspaceFolder();
      if (!folder || !node) return;
      const uri = wikiPageUri(folder, node.path);
      await openWikiPage(uri);
    }),
    vscode.commands.registerCommand("switchbay.rebuildViewer", async () => {
      const root = wikiFsPath();
      if (!root) {
        void vscode.window.showWarningMessage("Open a curiosity-engine folder first.");
        return;
      }
      await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: "Rebuilding wiki viewer…" },
        async () => {
          const result = await rebuildViewer(context, root);
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
    writeWorkspaceMcpJson(context);
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
  startChatObserver(context);
  updateWikiContext();
  void tryStartWorkspaceMcp();

  const ping = () => {
    updateWikiContext();
    wiki.refresh();
    projects.refresh();
  };
  const folder = workspaceFolder();
  const wikiRoot = wikiFsPath();
  const watchBases: vscode.Uri[] = [];
  if (folder) watchBases.push(folder);
  if (wikiRoot) {
    const wikiUri = vscode.Uri.file(wikiRoot);
    if (!folder || path.resolve(wikiRoot) !== path.resolve(folder.fsPath)) watchBases.push(wikiUri);
  }
  const onWiki = (uri: vscode.Uri) => {
    ping();
    const open = folder?.fsPath || wikiRoot;
    if (!open) return;
    const rel = wikiRoot
      ? path.relative(wikiRoot, uri.fsPath)
      : path.relative(open, uri.fsPath);
    recordWikiWrite(open, rel);
  };
  const onGraphDb = () => {
    invalidateKuzuCache();
    ping();
  };
  for (const base of watchBases) {
    for (const glob of ["wiki/**/*.md", ".workbench/proposals/**"]) {
      const watcher = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(base, glob));
      watcher.onDidChange(onWiki);
      watcher.onDidCreate(onWiki);
      watcher.onDidDelete(onWiki);
      context.subscriptions.push(watcher);
    }
    for (const glob of [".curator/graph.kuzu", ".curator/graph.kuzu/**"]) {
      const watcher = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(base, glob));
      watcher.onDidChange(onGraphDb);
      watcher.onDidCreate(onGraphDb);
      watcher.onDidDelete(onGraphDb);
      context.subscriptions.push(watcher);
    }
    const onReport = () => applyOrchestrationReport(folder?.fsPath || wikiRoot || base.fsPath);
    const reportWatch = vscode.workspace.createFileSystemWatcher(
      new vscode.RelativePattern(base, ".workbench/state/orchestration-report.json"),
    );
    reportWatch.onDidChange(onReport);
    reportWatch.onDidCreate(onReport);
    context.subscriptions.push(reportWatch);
    const onMcp = () => recordMcpActivity(folder?.fsPath || wikiRoot || base.fsPath);
    const mcpWatch = vscode.workspace.createFileSystemWatcher(
      new vscode.RelativePattern(base, ".workbench/state/mcp-activity.json"),
    );
    mcpWatch.onDidChange(onMcp);
    mcpWatch.onDidCreate(onMcp);
    context.subscriptions.push(mcpWatch);
  }

  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
  const harness = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 80);
  const paintHarness = () => {
    const on = knowledgeHarnessOn();
    harness.text = on ? "$(check) SBH on" : "$(circle-slash) SBH off";
    harness.tooltip = on
      ? "Switch Bay knowledge harness on — @switchbay / Curator / MCP in this window. Click to change."
      : "Switch Bay knowledge harness off — coding Chat only. Click to turn wiki tools on.";
    harness.backgroundColor = new vscode.ThemeColor(
      on ? "statusBarItem.prominentBackground" : "statusBarItem.warningBackground",
    );
    harness.command = "switchbay.chooseHarness";
  };
  const paintStatus = (pythonOk: boolean) => {
    paintHarness();
    if (!pythonOk) {
      status.text = "$(warning) Switch Bay VS · configure Python";
      status.command = "switchbay.configurePython";
      status.tooltip = "import switchbay failed — click to set repoRoot / pythonPath";
      status.backgroundColor = new vscode.ThemeColor("statusBarItem.warningBackground");
      return;
    }
    const res = resolveWiki();
    const cached = res.wikiRoot ? readCachedGraph(res.wikiRoot) : null;
    status.text = cached
      ? `$(type-hierarchy) ${modeLabel(res)} · ${cached.nodes.length} pages`
      : `$(type-hierarchy) ${modeLabel(res)}`;
    status.command = res.mode === "unresolved" ? "switchbay.registerFolder" : "switchbay.openGraph";
    status.tooltip = res.wikiRoot
      ? `Open Graph — wiki at ${res.wikiRoot}`
      : "Register this folder with a shared wiki";
    status.backgroundColor = undefined;
  };
  const refreshPythonStatus = async () => {
    const result = await probeSwitchbay(context);
    paintStatus(result.ok);
  };
  paintStatus(true);
  status.show();
  harness.show();
  context.subscriptions.push(
    status,
    harness,
    vscode.commands.registerCommand("switchbay.configurePython", async () => {
      const ok = await configurePython(context);
      if (ok) {
        writeWorkspaceMcpJson(context);
        notifyMcpDefinitionsChanged();
        paintStatus(true);
      } else void refreshPythonStatus();
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
      await startNamedAgentSession(context, pick.label, `Run as ${pick.label}.`);
    }),
    vscode.commands.registerCommand("switchbay.checkUpdate", () => checkAndOfferUpdate(context)),
    vscode.commands.registerCommand("switchbay.restartMcp", async () => {
      writeWorkspaceMcpJson(context);
      notifyMcpDefinitionsChanged();
      const started = await tryStartWorkspaceMcp();
      void vscode.window.showInformationMessage(
        started
          ? "Switch Bay MCP: restart requested. If Chat still has no wiki tools, start a new chat."
          : "Switch Bay MCP: wrote .vscode/mcp.json. Command Palette → MCP: List Servers → start switchbay, then a new chat.",
      );
    }),
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (
        e.affectsConfiguration("switchbay.repoRoot")
        || e.affectsConfiguration("switchbay.pythonPath")
      ) {
        void refreshPythonStatus();
      }
      if (
        e.affectsConfiguration("switchbay.wikiRoot")
        || e.affectsConfiguration("switchbay.knowledgeHarness")
      ) {
        invalidateWikiRootCache();
        ping();
        writeWorkspaceMcpJson(context);
        notifyMcpDefinitionsChanged();
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
