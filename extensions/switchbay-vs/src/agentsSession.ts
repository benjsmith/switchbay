import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import * as vscode from "vscode";
import { tryStartWorkspaceMcp, writeWorkspaceMcpJson } from "./mcp";
import { notifyMcpDefinitionsChanged } from "./mcpProvider";
import { workspaceFsPath } from "./paths";

const AGENTS_WINDOW_COMMANDS = [
  "workbench.action.openAgentsWindow",
  "workbench.action.chat.openAgentsWindow",
  "workbench.action.chat.openWorkspaceInAgentsWindow",
];

/** publisher.name from package.json */
export const EXTENSION_ID = "switchbay.switchbay-vs";

export type NamedAgent = {
  name: string;
  description: string;
  tools: string;
  source: "shipped" | "workspace" | "user";
  path: string;
  invocable: boolean;
};

function fm(text: string): Record<string, string> {
  if (!text.startsWith("---")) return {};
  const end = text.indexOf("\n---", 3);
  if (end < 0) return {};
  const out: Record<string, string> = {};
  for (const line of text.slice(3, end).split("\n")) {
    const m = line.match(/^([A-Za-z_][\w-]*)\s*:\s*(.*)$/);
    if (!m) continue;
    out[m[1]] = m[2].trim().replace(/^["']|["']$/g, "");
  }
  return out;
}

function isAgentFile(name: string): boolean {
  const lower = name.toLowerCase();
  return lower.endsWith(".agent.md") || lower.endsWith(".chatmode.md");
}

function readAgentFile(file: string, source: NamedAgent["source"]): NamedAgent | null {
  if (!fs.existsSync(file) || !isAgentFile(path.basename(file))) return null;
  let text = "";
  try { text = fs.readFileSync(file, "utf8"); } catch { return null; }
  const base = path.basename(file).replace(/\.agent\.md$/i, "").replace(/\.md$/i, "");
  const meta = fm(text);
  const name = meta.name || meta.displayName || base;
  return {
    name,
    description: (meta.description || "").replace(/^"|"$/g, ""),
    tools: meta.tools || "",
    source,
    path: file,
    invocable: meta["user-invocable"] !== "false" && meta.userInvocable !== "false",
  };
}

function scanDir(dir: string, source: NamedAgent["source"], into: Map<string, NamedAgent>): void {
  if (!fs.existsSync(dir)) return;
  let names: string[] = [];
  try { names = fs.readdirSync(dir); } catch { return; }
  for (const name of names) {
    if (name.startsWith(".")) continue;
    const full = path.join(dir, name);
    let st: fs.Stats;
    try { st = fs.statSync(full); } catch { continue; }
    if (st.isDirectory()) {
      if (name === "agents" || name === "prompts") scanDir(full, source, into);
      continue;
    }
    const agent = readAgentFile(full, source);
    if (agent) into.set(`${agent.source}:${agent.name.toLowerCase()}`, agent);
  }
}

function userProfileRoots(): string[] {
  const home = os.homedir();
  const app = process.platform === "darwin"
    ? path.join(home, "Library", "Application Support")
    : process.platform === "win32"
      ? (process.env.APPDATA || path.join(home, "AppData", "Roaming"))
      : path.join(process.env.XDG_CONFIG_HOME || path.join(home, ".config"));
  const products = ["Code", "Code - Insiders", "Cursor", "VSCodium"];
  const roots: string[] = [];
  for (const product of products) {
    const user = path.join(app, product, "User");
    if (fs.existsSync(user)) roots.push(user);
  }
  return roots;
}

/** Shipped Switch Bay agents, workspace `.github/agents`, and user-profile agents. */
export function listNamedAgents(extensionPath: string, workspace?: string): NamedAgent[] {
  const byName = new Map<string, NamedAgent>();
  scanDir(path.join(extensionPath, "agents"), "shipped", byName);
  const ws = workspace || workspaceFsPath();
  if (ws) {
    scanDir(path.join(ws, ".github", "agents"), "workspace", byName);
    scanDir(path.join(ws, ".github", "chatmodes"), "workspace", byName);
    scanDir(path.join(ws, ".agents", "agents"), "workspace", byName);
    scanDir(path.join(ws, ".agents"), "workspace", byName);
    scanDir(path.join(ws, ".claude", "agents"), "workspace", byName);
    scanDir(ws, "workspace", byName);
  }
  for (const user of userProfileRoots()) {
    scanDir(path.join(user, "prompts"), "user", byName);
    scanDir(path.join(user, "agents"), "user", byName);
    const profiles = path.join(user, "profiles");
    if (fs.existsSync(profiles)) {
      for (const name of fs.readdirSync(profiles)) {
        scanDir(path.join(profiles, name, "prompts"), "user", byName);
        scanDir(path.join(profiles, name, "agents"), "user", byName);
      }
    }
  }
  const rank = { shipped: 0, workspace: 1, user: 2 };
  return [...byName.values()].sort((a, b) =>
    rank[a.source] - rank[b.source] || a.name.localeCompare(b.name));
}

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

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Start a named custom agent in editor Chat (Auto, Curator, Draw…).
 * VS Code owns duration, approvals, and the sessions list.
 *
 * Do not open the dedicated Agents *window* here. That window does not
 * inherit the query, so `/curate` used to land on a blank "New session".
 * Copilot also caches a failed tools/list on the current thread — start
 * a new chat so a schema fix can take effect.
 */
export async function startNamedAgentSession(
  context: vscode.ExtensionContext,
  agent: string,
  prompt: string,
): Promise<{ opened: boolean; via: string }> {
  const name = (agent || "Auto").trim() || "Auto";
  const query = prompt.trim() || `Run as ${name}.`;
  writeWorkspaceMcpJson(context);
  notifyMcpDefinitionsChanged();
  await tryStartWorkspaceMcp();

  for (const id of ["workbench.action.chat.newChat", "workbench.action.chat.newAgentSession"]) {
    try {
      await vscode.commands.executeCommand(id);
      break;
    } catch {
      continue;
    }
  }
  await sleep(150);

  const attempts: unknown[] = [
    { query, isPartialQuery: false, mode: name },
    { query, isPartialQuery: false, modeId: name },
    { query, isPartialQuery: false, mode: "agent" },
    { query, isPartialQuery: false, agentMode: true },
  ];
  for (const opts of attempts) {
    try {
      await vscode.commands.executeCommand("workbench.action.chat.open", opts);
      return { opened: true, via: "chat" };
    } catch {
      continue;
    }
  }
  return { opened: false, via: "failed" };
}

export async function startAutoAgentsSession(
  context: vscode.ExtensionContext,
  prompt: string,
): Promise<{ opened: boolean; via: string }> {
  return startNamedAgentSession(context, "Auto", prompt);
}
