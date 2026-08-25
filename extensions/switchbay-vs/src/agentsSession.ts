import * as vscode from "vscode";

const AGENTS_WINDOW_COMMANDS = [
  "workbench.action.openAgentsWindow",
  "workbench.action.chat.openAgentsWindow",
  "workbench.action.chat.openWorkspaceInAgentsWindow",
];

const EXTENSION_ID = "switchbay.switchbay";

/** Opt this extension into the Agents window (user setting is a map of ids). */
export async function optIntoAgentsWindow(): Promise<void> {
  const cfg = vscode.workspace.getConfiguration("extensions");
  const current = cfg.get<Record<string, boolean>>("supportAgentsWindow") ?? {};
  if (current[EXTENSION_ID] === true) return;
  try {
    await cfg.update(
      "supportAgentsWindow",
      { ...current, [EXTENSION_ID]: true },
      vscode.ConfigurationTarget.Global,
    );
  } catch (err) {
    console.log("[switchbay] could not set extensions.supportAgentsWindow", err);
  }
}

export async function openAgentsWindow(): Promise<boolean> {
  for (const id of AGENTS_WINDOW_COMMANDS) {
    try {
      await vscode.commands.executeCommand(id);
      return true;
    } catch {
      continue;
    }
  }
  return false;
}

/**
 * Start a Local Agents session on the Switch Bay Auto custom agent.
 * VS Code owns duration, approvals, and the sessions list.
 */
export async function startAutoAgentsSession(prompt: string): Promise<{ opened: boolean; via: string }> {
  const query = prompt.trim() || "Curate this wiki. Search first, then propose sourced pages.";
  const windowOpened = await openAgentsWindow();

  const attempts: unknown[] = [
    { query, isPartialQuery: false, mode: "Auto" },
    { query, isPartialQuery: false, modeId: "Auto" },
    { query, isPartialQuery: false, agentMode: true, mode: "Auto" },
    { query, isPartialQuery: false },
  ];
  for (const opts of attempts) {
    try {
      await vscode.commands.executeCommand("workbench.action.chat.open", opts);
      return { opened: true, via: windowOpened ? "agents-window" : "chat" };
    } catch {
      continue;
    }
  }
  if (windowOpened) return { opened: true, via: "window-only" };
  return { opened: false, via: "failed" };
}
