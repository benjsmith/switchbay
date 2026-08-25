import * as crypto from "crypto";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import * as vscode from "vscode";
import { startNamedAgentSession } from "./agentsSession";
import { getMcp } from "./mcp";
import { workspaceFsPath } from "./paths";
import { effortInstruction, getPreference, preferenceLabel } from "./preference";

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
  preference: number;
  agent?: string;
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
    preference: rec.preference,
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
      const rec = JSON.parse(fs.readFileSync(file, "utf8")) as RunRecord;
      if (typeof rec.preference !== "number") rec.preference = 0.5;
      out.push(rec);
    } catch { /* skip */ }
  }
  return out.sort((a, b) => b.started_at - a.started_at).slice(0, 20);
}

function node(
  id: string,
  kind: string,
  objective: string,
  dependencies: string[] = [],
  extra: Partial<PlanNode> = {},
): PlanNode {
  return { node_id: id, kind, role: kind, objective, dependencies, status: "pending", ...extra };
}

/** DAG shape is an *outcome* of the slider, matching PWA policy labels. */
function nodesForPreference(objective: string, preference: number): PlanNode[] {
  if (preference <= 0.2) {
    return [node("answer", "answer", "Direct wiki search; no subagents")];
  }
  const investigate = node(
    "investigate",
    "investigate",
    "Read-only wiki/vault research",
    [],
    { retrieval_query: objective },
  );
  const synthesize = node(
    "synthesize",
    "synthesize",
    "Propose sourced wiki pages and rebuild the graph",
    preference >= 0.8 ? ["verify"] : ["investigate"],
  );
  if (preference >= 0.8) {
    return [
      investigate,
      node("verify", "verify", "Check contested claims against sources", ["investigate"]),
      synthesize,
    ];
  }
  return [investigate, synthesize];
}

function seedPlan(objective: string, preference: number, agent = "Auto"): RunRecord {
  const id = `vs-${Date.now().toString(36)}-${crypto.randomBytes(3).toString("hex")}`;
  const now = Date.now() / 1000;
  return {
    orchestration_id: id,
    objective,
    strategy: preferenceLabel(preference).toLowerCase(),
    phase: "planning",
    started_at: now,
    updated_at: now,
    via: "pending",
    preference,
    agent,
    nodes: nodesForPreference(objective, preference),
  };
}

async function nativeWave(context: vscode.ExtensionContext, workspace: string, rec: RunRecord): Promise<void> {
  const mark = (id: string, status: string) => {
    const n = rec.nodes.find((x) => x.node_id === id);
    if (n) n.status = status;
  };
  try {
    const mcp = await getMcp(context);
    const ids = rec.nodes.map((n) => n.node_id);
    const runTool = async (id: string, tool: string) => {
      if (!ids.includes(id)) return true;
      mark(id, "running");
      rec.phase = id;
      persist(workspace, rec);
      const result = await mcp.callTool(tool, {});
      mark(id, result.isError ? "failed" : "done");
      rec.note = ((rec.note || "") + "\n\n" + result.text).trim().slice(0, 2300);
      persist(workspace, rec);
      return !result.isError;
    };
    if (ids.includes("answer")) {
      await runTool("answer", "ce_epoch_summary");
    } else {
      if (!await runTool("investigate", "ce_epoch_summary")) return;
      if (ids.includes("verify")) await runTool("verify", "ce_lint");
    }
    // Writing stays in the Agents session (Curator / Auto). Native wave
    // only primes evidence so the Dashboard has a DAG before the LM loop.
    const last = rec.nodes[rec.nodes.length - 1];
    if (last) mark(last.node_id, "running");
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
  opts?: { preference?: number; via?: string; agent?: string },
): Promise<{ text: string; orchestrationId: string }> {
  const workspace = workspaceFsPath();
  if (!workspace) {
    return { text: "Open a curiosity-engine folder first.", orchestrationId: "" };
  }
  const objective = prompt.trim() || "curate the wiki";
  const preference = opts?.preference ?? getPreference();
  const agent = opts?.agent || "Auto";
  const rec = seedPlan(objective, preference, agent);
  persist(workspace, rec);

  const session = await startNamedAgentSession(
    agent,
    `You are Switch Bay ${agent}. ${objective}\n\n`
    + `${effortInstruction(preference)}\n\n`
    + `Use Switch Bay MCP tools (search_wiki, ce_planner, ce_sweep, propose_wiki_page). `
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
