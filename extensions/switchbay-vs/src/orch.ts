import * as crypto from "crypto";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import * as vscode from "vscode";
import { startAutoAgentsSession } from "./agentsSession";
import { getMcp } from "./mcp";
import { workspaceFsPath } from "./paths";

export type PlanNode = {
  node_id: string;
  kind: string;
  role: string;
  objective: string;
  dependencies: string[];
  status?: string;
  retrieval_query?: string;
};

export type RunRecord = {
  orchestration_id: string;
  objective: string;
  strategy: string;
  phase: string;
  started_at: number;
  updated_at: number;
  via: string;
  nodes: PlanNode[];
  note?: string;
};

function slug(name: string): string {
  return name.replace(/[^A-Za-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "").toLowerCase().slice(0, 40) || "workspace";
}

export function switchbayStateRoot(): string {
  const override = process.env.SWITCHBAY_STATE_DIR;
  if (override) return override;
  const home = os.homedir();
  if (process.platform === "darwin") return path.join(home, "Library", "Application Support", "switchbay");
  if (process.platform === "win32") {
    const base = process.env.LOCALAPPDATA || path.join(home, "AppData", "Local");
    return path.join(base, "switchbay");
  }
  const base = process.env.XDG_STATE_HOME || path.join(home, ".local", "state");
  return path.join(base, "switchbay");
}

export function workspaceStateDir(workspace: string): string {
  const resolved = path.resolve(workspace);
  const digest = crypto.createHash("sha256").update(resolved).digest("hex").slice(0, 12);
  return path.join(switchbayStateRoot(), "workspaces", `${slug(path.basename(resolved))}-${digest}`);
}

export function runsRoot(workspace: string): string {
  return path.join(workspaceStateDir(workspace), "runs");
}

export function runDir(workspace: string, orchestrationId: string): string {
  return path.join(runsRoot(workspace), orchestrationId);
}

function writeJson(file: string, data: unknown): void {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(data, null, 2), "utf8");
}

function persist(workspace: string, rec: RunRecord): void {
  const d = runDir(workspace, rec.orchestration_id);
  rec.updated_at = Date.now() / 1000;
  writeJson(path.join(d, "plan.json"), {
    version: 1,
    orchestration_id: rec.orchestration_id,
    strategy: rec.strategy,
    objective: rec.objective,
    nodes: rec.nodes.map(({ status: _s, ...n }) => n),
    preference: 0.7,
    features: { host: "vscode-plugin" },
    decision: { via: rec.via },
  });
  writeJson(path.join(d, "status.json"), {
    phase: rec.phase,
    completed: rec.nodes.filter((n) => n.status === "done").map((n) => n.node_id),
    failed: rec.nodes.filter((n) => n.status === "failed").map((n) => n.node_id),
    expansions: 0,
    elapsed_s: rec.updated_at - rec.started_at,
    updated_at: rec.updated_at,
    via: rec.via,
    note: rec.note,
    node_status: Object.fromEntries(rec.nodes.map((n) => [n.node_id, n.status || "pending"])),
  });
  writeJson(path.join(d, "plugin-run.json"), rec);
}

export function listRuns(workspace: string): RunRecord[] {
  const root = runsRoot(workspace);
  if (!fs.existsSync(root)) return [];
  const out: RunRecord[] = [];
  for (const name of fs.readdirSync(root)) {
    const file = path.join(root, name, "plugin-run.json");
    if (!fs.existsSync(file)) continue;
    try {
      out.push(JSON.parse(fs.readFileSync(file, "utf8")) as RunRecord);
    } catch { /* skip */ }
  }
  return out.sort((a, b) => b.started_at - a.started_at).slice(0, 20);
}

function seedPlan(objective: string): RunRecord {
  const id = `vs-${Date.now().toString(36)}-${crypto.randomBytes(3).toString("hex")}`;
  const now = Date.now() / 1000;
  return {
    orchestration_id: id,
    objective,
    strategy: "auto",
    phase: "planning",
    started_at: now,
    updated_at: now,
    via: "pending",
    nodes: [
      {
        node_id: "investigate",
        kind: "investigate",
        role: "investigate",
        objective: "Read-only wiki/vault research",
        dependencies: [],
        status: "pending",
        retrieval_query: objective,
      },
      {
        node_id: "verify",
        kind: "verify",
        role: "verify",
        objective: "Check contested claims against sources",
        dependencies: ["investigate"],
        status: "pending",
      },
      {
        node_id: "synthesize",
        kind: "synthesize",
        role: "synthesize",
        objective: "Propose sourced wiki pages and rebuild the graph",
        dependencies: ["verify"],
        status: "pending",
      },
    ],
  };
}

async function nativeWave(context: vscode.ExtensionContext, workspace: string, rec: RunRecord): Promise<void> {
  const mark = (id: string, status: string) => {
    const n = rec.nodes.find((x) => x.node_id === id);
    if (n) n.status = status;
  };
  try {
    const mcp = await getMcp(context);
    mark("investigate", "running");
    rec.phase = "investigating";
    persist(workspace, rec);
    const epoch = await mcp.callTool("ce_epoch_summary", {});
    mark("investigate", epoch.isError ? "failed" : "done");
    rec.note = epoch.text.slice(0, 1500);
    persist(workspace, rec);
    if (epoch.isError) return;
    mark("verify", "running");
    rec.phase = "verifying";
    persist(workspace, rec);
    const lint = await mcp.callTool("ce_lint", {});
    mark("verify", lint.isError ? "failed" : "done");
    rec.note = (rec.note || "") + "\n\n" + lint.text.slice(0, 800);
    persist(workspace, rec);
    mark("synthesize", "running");
    rec.phase = "synthesizing";
    persist(workspace, rec);
    // Writing stays in the Agents session (Curator / Auto). Native wave
    // only primes evidence so the Dashboard has a DAG before the LM loop.
    mark("synthesize", "running");
    rec.phase = "agents-session";
    persist(workspace, rec);
  } catch (err) {
    rec.note = `Native MCP wave failed: ${(err as Error).message}`;
    rec.phase = "agents-session";
    persist(workspace, rec);
  }
}

/**
 * Dual path for /curate:
 *  1. VS Code Agents session on the Auto custom agent (owns the loop).
 *  2. Switch Bay DAG snapshot on disk + a read-only MCP prime wave
 *     (Dashboard watches this; nothing listens on :8765).
 */
export async function startCurate(
  context: vscode.ExtensionContext,
  prompt: string,
): Promise<{ text: string; orchestrationId: string }> {
  const workspace = workspaceFsPath();
  if (!workspace) {
    return { text: "Open a curiosity-engine folder first.", orchestrationId: "" };
  }
  const objective = prompt.trim() || "curate the wiki";
  const rec = seedPlan(objective);
  persist(workspace, rec);

  const session = await startAutoAgentsSession(
    `You are Switch Bay Auto. ${objective}\n\n`
    + `Use Investigator subagents for independent research, then Switch Bay `
    + `MCP tools (search_wiki, ce_planner, ce_sweep, propose_wiki_page). `
    + `Do not delete pages. Cite [[wikilinks]].`,
  );
  rec.via = session.via;
  rec.phase = session.opened ? "agents-session" : "native-only";
  persist(workspace, rec);

  void vscode.commands.executeCommand("switchbay.openAgents");
  void nativeWave(context, workspace, rec);

  const where = session.opened
    ? (session.via === "agents-window"
      ? "Opened the VS Code **Agents window** on the Auto agent."
      : "Opened Chat on the Auto agent (Agents window command was unavailable).")
    : "Could not open an Agents session — native MCP wave still runs for the Dashboard.";
  return {
    orchestrationId: rec.orchestration_id,
    text: [
      where,
      `Switch Bay DAG id \`${rec.orchestration_id}\` is on disk; the Agent Dashboard is watching it.`,
      "Nothing is listening on `:8765`. Closing VS Code stops the Local-harness session.",
    ].join("\n\n"),
  };
}
