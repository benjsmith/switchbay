import * as crypto from "crypto";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import * as vscode from "vscode";
import { startNamedAgentSession } from "./agentsSession";
import { getMcp } from "./mcp";
import { workspaceFsPath } from "./paths";
import { wikiFsPath } from "./wikiRoot";
import { getPreference, preferenceLabel, spawnCuratePlan, spawnPlan } from "./preference";
import {
  isLiveRun, markNodesTerminal, settlePhase, TERMINAL_PHASES,
  type PlanNode, type RunEvent, type RunRecord,
} from "./runStatus";

export type { PlanNode, RunEvent, RunRecord };
export { isLiveRun };
export const LIVE_TTL_S = 12 * 60;

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
  const now = Date.now() / 1000;
  const out: RunRecord[] = [];
  for (const name of fs.readdirSync(root)) {
    const file = path.join(root, name, "plugin-run.json");
    if (!fs.existsSync(file)) continue;
    try {
      const rec = JSON.parse(fs.readFileSync(file, "utf8")) as RunRecord;
      if (typeof rec.preference !== "number") rec.preference = 0.5;
      const settled = settlePhase(rec, now);
      if (settled !== "live" && !TERMINAL_PHASES.has(rec.phase || "") && !rec.ended_at) {
        rec.phase = settled;
        rec.ended_at = rec.updated_at || now;
        rec.activity = settled === "done"
          ? "Wave finished — wiki writes went quiet (Chat may still be open)"
          : "No activity for a while — marked idle";
        markNodesTerminal(rec, settled);
        persist(workspace, rec);
      }
      out.push(rec);
    } catch { /* skip */ }
  }
  const byObj = new Map<string, RunRecord>();
  for (const rec of out.sort((a, b) => b.updated_at - a.updated_at)) {
    if (!isLiveRun(rec, now)) continue;
    const key = (rec.objective || rec.orchestration_id).trim().toLowerCase();
    const prev = byObj.get(key);
    if (!prev) {
      byObj.set(key, rec);
      continue;
    }
    rec.phase = "superseded";
    rec.ended_at = now;
    rec.activity = "Duplicate of the live DAG — archived";
    persist(workspace, rec);
  }
  return out.sort((a, b) => b.started_at - a.started_at).slice(0, 20);
}

export function archiveLiveRuns(workspace: string, exceptId?: string): void {
  const now = Date.now() / 1000;
  for (const rec of listRuns(workspace)) {
    if (!isLiveRun(rec, now)) continue;
    if (exceptId && rec.orchestration_id === exceptId) continue;
    rec.phase = "superseded";
    rec.ended_at = now;
    rec.activity = "Replaced by a newer Curate";
    const last = rec.nodes[rec.nodes.length - 1];
    if (last && (last.status === "running" || last.status === "pending")) last.status = "done";
    persist(workspace, rec);
  }
}

export function clearFinishedRuns(workspace: string): number {
  const now = Date.now() / 1000;
  const root = runsRoot(workspace);
  if (!fs.existsSync(root)) return 0;
  let n = 0;
  for (const rec of listRuns(workspace)) {
    if (isLiveRun(rec, now)) continue;
    const d = runDir(workspace, rec.orchestration_id);
    try {
      fs.rmSync(d, { recursive: true, force: true });
      n += 1;
    } catch { /* skip */ }
  }
  return n;
}

export function finishRun(workspace: string, id: string, phase = "done"): void {
  const rec = listRuns(workspace).find((r) => r.orchestration_id === id);
  if (!rec) return;
  rec.phase = phase;
  rec.ended_at = Date.now() / 1000;
  rec.activity = rec.activity || (phase === "done" ? "Wave finished" : "Marked finished");
  markNodesTerminal(rec, phase);
  persist(workspace, rec);
}

const CHAT_STOP_COMMANDS = [
  "workbench.action.chat.stop",
  "workbench.action.chat.cancel",
  "workbench.action.chat.abort",
  "workbench.action.chat.stopGenerating",
  "inlineChat.stop",
];

async function tryStopChat(): Promise<boolean> {
  for (const id of CHAT_STOP_COMMANDS) {
    try {
      await vscode.commands.executeCommand(id);
      return true;
    } catch { /* next */ }
  }
  return false;
}

function writeStopReport(workspace: string, id: string): void {
  const payload = JSON.stringify({
    at: Date.now() / 1000,
    phase: "cancelled",
    detail: "Stopped from Agent Dashboard",
    orchestration_id: id,
  }, null, 2) + "\n";
  const roots = new Set([workspace]);
  const wiki = wikiFsPath();
  if (wiki) roots.add(wiki);
  for (const root of roots) {
    const file = path.join(root, ".workbench", "state", "orchestration-report.json");
    try {
      fs.mkdirSync(path.dirname(file), { recursive: true });
      fs.writeFileSync(file, payload, "utf8");
    } catch { /* ignore */ }
  }
}

/** Mark the DAG cancelled, tell Curator via orchestration-report, try to halt Chat. */
export async function stopRun(workspace: string, id: string): Promise<void> {
  const rec = listRuns(workspace).find((r) => r.orchestration_id === id);
  if (rec) {
    rec.activity = "Stopped from Agent Dashboard";
    rec.events = [...(rec.events || []), {
      at: Date.now() / 1000,
      kind: "stop",
      detail: rec.activity,
    }].slice(-24);
    finishRun(workspace, id, "cancelled");
  }
  writeStopReport(workspace, id);
  await tryStopChat();
}

export function applyOrchestrationReport(workspace: string): boolean {
  const file = path.join(workspace, ".workbench", "state", "orchestration-report.json");
  if (!fs.existsSync(file)) return false;
  let report: { at?: number; phase?: string; detail?: string; orchestration_id?: string };
  try {
    report = JSON.parse(fs.readFileSync(file, "utf8")) as typeof report;
  } catch {
    return false;
  }
  const phase = String(report.phase || "");
  if (!phase) return false;
  const runs = listRuns(workspace);
  const rec = (report.orchestration_id
    ? runs.find((r) => r.orchestration_id === report.orchestration_id)
    : undefined)
    || runs.find((r) => isLiveRun(r))
    || runs[0];
  if (!rec) return false;
  if (rec.ended_at && report.at && rec.ended_at >= report.at) return false;
  if (phase === "done" || phase === "failed" || phase === "cancelled") {
    rec.activity = report.detail || rec.activity;
    finishRun(workspace, rec.orchestration_id, phase);
    return true;
  }
  if (phase === "running" && isLiveRun(rec)) {
    rec.activity = report.detail || rec.activity;
    rec.events = [...(rec.events || []), {
      at: Date.now() / 1000,
      kind: "report",
      detail: rec.activity || "running",
    }].slice(-24);
    const last = rec.nodes[rec.nodes.length - 1];
    if (last && last.status !== "done") last.status = "running";
    persist(workspace, rec);
    return true;
  }
  return false;
}

export function recordMcpActivity(workspace: string): void {
  const file = path.join(workspace, ".workbench", "state", "mcp-activity.json");
  if (!fs.existsSync(file)) return;
  let rec: { at?: number; tool?: string; detail?: string };
  try {
    rec = JSON.parse(fs.readFileSync(file, "utf8")) as typeof rec;
  } catch {
    return;
  }
  const detail = String(rec.detail || rec.tool || "MCP tool").slice(0, 240);
  recordWorkspaceEvent(workspace, "mcp", detail);
}

export function recordWorkspaceEvent(
  workspace: string,
  kind: string,
  detail: string,
  writeCount = 0,
): void {
  let rec = listRuns(workspace).find((r) => isLiveRun(r));
  if (!rec) rec = ensureLiveRun(workspace, detail.slice(0, 240), { via: "fs" });
  rec.activity = detail;
  rec.events = [...(rec.events || []), { at: Date.now() / 1000, kind, detail }].slice(-24);
  if (kind === "wiki-write") rec.wiki_writes = (rec.wiki_writes || 0) + Math.max(1, writeCount);
  persist(workspace, rec);
}

const wikiQueues = new Map<string, { files: string[]; timer?: ReturnType<typeof setTimeout> }>();

/** Batch wiki markdown writes onto the newest live DAG (Chat has no tool-call bus). */
export function recordWikiWrite(workspace: string, relPath: string): void {
  const norm = relPath.replace(/\\/g, "/");
  let q = wikiQueues.get(workspace);
  if (!q) {
    q = { files: [] };
    wikiQueues.set(workspace, q);
  }
  q.files.push(norm);
  if (q.timer) clearTimeout(q.timer);
  q.timer = setTimeout(() => {
    const files = [...new Set(q!.files)];
    q!.files = [];
    const latest = files[files.length - 1] || "wiki";
    const detail = files.length === 1 ? latest : `${files.length} wiki writes · latest ${latest}`;
    recordWorkspaceEvent(workspace, "wiki-write", detail, files.length);
    const rec = listRuns(workspace).find((r) => isLiveRun(r));
    if (!rec) return;
    const last = rec.nodes[rec.nodes.length - 1];
    if (last && last.status !== "done") last.status = "running";
    rec.phase = "agents-session";
    persist(workspace, rec);
  }, 450);
}

function summarizeTool(name: string, text: string): string {
  const t = text.trim();
  try {
    const j = JSON.parse(t) as { page_counts?: Record<string, unknown>; error?: string };
    if (j?.page_counts && typeof j.page_counts === "object") {
      const bits = Object.entries(j.page_counts).map(([k, v]) => `${v} ${k}`);
      return `Wiki snapshot · ${bits.join(", ")}`;
    }
    if (typeof j?.error === "string") return `${name}: ${j.error}`;
  } catch { /* plain text */ }
  const line = t.split("\n").find((l) => l.trim()) || t;
  return `${name}: ${line.slice(0, 180)}`;
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

function nodesForCurate(objective: string, preference: number): PlanNode[] {
  const prime = node("prime", "execute", "ce_wave_prime (planner pick-mode)");
  const curate = node(
    "curate",
    "synthesize",
    "CE CURATE Phase 2 for the primed mode",
    ["prime"],
  );
  if (preference <= 0.2) {
    return [prime, curate];
  }
  return [prime, curate];
}

/** DAG shape is an *outcome* of the slider, matching PWA policy labels. */
function nodesForPreference(objective: string, preference: number): PlanNode[] {
  if (preference <= 0.2) {
    return [node("answer", "answer", "Direct wiki search; no subagents")];
  }
  const a = node(
    "investigate-a",
    "investigate",
    "Read-only slice A (stale / thin / unlinked)",
    [],
    { retrieval_query: objective },
  );
  const b = node(
    "investigate-b",
    "investigate",
    "Read-only slice B (sources / contradictions / planner)",
    [],
    { retrieval_query: objective },
  );
  if (preference >= 0.8) {
    return [
      a,
      b,
      node("verify", "verify", "Check contested claims against sources", ["investigate-a", "investigate-b"]),
      node("synthesize", "synthesize", "Propose sourced wiki pages and rebuild the graph", ["verify"]),
    ];
  }
  return [
    a,
    b,
    node("synthesize", "synthesize", "Propose sourced wiki pages and rebuild the graph", ["investigate-a", "investigate-b"]),
  ];
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
    nodes: agent === "Curator"
      ? nodesForCurate(objective, preference)
      : nodesForPreference(objective, preference),
  };
}

/**
 * Attach dashboard Agent Space to work that did not go through Curate
 * (plain Auto Chat, @switchbay questions). Does not open a new session.
 */
export function ensureLiveRun(
  workspace: string,
  objective: string,
  opts?: { via?: string; agent?: string; requestId?: string; kind?: "chat" | "curate" },
): RunRecord {
  const obj = objective.trim().slice(0, 240) || "Chat";
  const now = Date.now() / 1000;
  const live = listRuns(workspace).find((r) => isLiveRun(r, now));
  if (live) {
    const prev = (live.objective || "").trim().toLowerCase();
    const next = obj.toLowerCase();
    const same = prev === next
      || (opts?.requestId && live.note === opts.requestId)
      || (prev.length >= 24 && next.startsWith(prev.slice(0, 24)))
      || (next.length >= 24 && prev.startsWith(next.slice(0, 24)));
    if (same) {
      if (opts?.requestId && live.note !== opts.requestId) {
        live.note = opts.requestId;
        persist(workspace, live);
      }
      return live;
    }
    archiveLiveRuns(workspace);
  }
  const preference = getPreference();
  const rec = seedPlan(obj, opts?.kind === "curate" ? preference : Math.min(preference, 0.2), opts?.agent);
  rec.via = opts?.via || "chat";
  rec.phase = "agents-session";
  rec.activity = "Waiting for wiki tools…";
  rec.note = opts?.requestId || rec.note;
  rec.events = [{ at: rec.started_at, kind: "start", detail: "Started from Chat" }];
  const last = rec.nodes[rec.nodes.length - 1];
  if (last) last.status = "running";
  persist(workspace, rec);
  return rec;
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
      rec.activity = summarizeTool(tool, result.text);
      rec.events = [...(rec.events || []), {
        at: Date.now() / 1000,
        kind: result.isError ? "prime-fail" : "prime",
        detail: rec.activity,
      }].slice(-24);
      rec.note = rec.activity;
      persist(workspace, rec);
      return !result.isError;
    };
    const inv = ids.filter((id) => id.startsWith("investigate"));
    if (ids.includes("prime")) {
      await runTool("prime", "ce_wave_prime");
    } else if (ids.includes("answer")) {
      await runTool("answer", "ce_epoch_summary");
    } else if (inv.length) {
      if (!await runTool(inv[0], "ce_epoch_summary")) return;
      for (const id of inv.slice(1)) mark(id, "done");
      persist(workspace, rec);
      if (ids.includes("verify")) await runTool("verify", "ce_lint");
    }
    // Writing stays in Chat (Curator / Auto). Do not pulse Synthesize
    // as running until wiki writes arrive — Chat staying open after
    // OBJECTIVE_MET is not a live wave.
    rec.phase = "agents-session";
    rec.activity = rec.activity
      ? `${rec.activity} · waiting on Chat Auto`
      : "Waiting on Chat Curator — wiki writes will pulse here";
    persist(workspace, rec);
  } catch (err) {
    rec.activity = `Native MCP wave failed: ${(err as Error).message}`;
    rec.note = rec.activity;
    rec.phase = "agents-session";
    persist(workspace, rec);
  }
}

/**
 * Dual path for /curate:
 *  1. VS Code Chat session on the Curator custom agent (CE orchestrator).
 *  2. Switch Bay DAG snapshot on disk + ce_wave_prime (Dashboard).
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
  const agent = opts?.agent || "Curator";
  archiveLiveRuns(workspace);
  const rec = seedPlan(objective, preference, agent);
  rec.activity = "Starting Chat Auto…";
  rec.events = [{ at: rec.started_at, kind: "start", detail: objective }];
  persist(workspace, rec);

  const session = await startNamedAgentSession(
    context,
    agent,
    `You are Switch Bay ${agent}. ${objective}\n\n`
    + `${(agent === "Curator" ? spawnCuratePlan : spawnPlan)(preference, objective)}\n\n`
    + `Use Switch Bay MCP tools (ce_wave_prime, ce_sweep, ce_score_diff, ce_wiki_commit, ce_dispatch_worker). `
    + `If those tools are missing, use workspace search/read, then tell the user to `
    + `run “MCP: List Servers” and start **switchbay** (written to .vscode/mcp.json). `
    + `When the wave is complete, call orchestration_report with phase=done and `
    + `detail="OBJECTIVE_MET: yes", then print OBJECTIVE_MET: yes. `
    + `Do not delete pages. Cite [[wikilinks]].`,
  );
  rec.via = session.via;
  rec.phase = session.opened ? "agents-session" : "native-only";
  persist(workspace, rec);

  void vscode.commands.executeCommand("switchbay.openAgents");
  void nativeWave(context, workspace, rec);

  const where = session.opened
    ? `Started the **${agent}** agent in Chat (new session).`
    : "Could not open Chat — native MCP wave still runs for the Dashboard.";
  return {
    orchestrationId: rec.orchestration_id,
    text: [
      where,
      `Switch Bay DAG id \`${rec.orchestration_id}\` is on disk; the Agent Dashboard is watching it.`,
      "Wiki tools come from MCP server **switchbay** (`.vscode/mcp.json`, sandboxed to this folder). Copilot’s `tools:` list enables them; it still confirms MCP calls until the sandbox is on or you **Chat: Manage Tool Approval** → trust **switchbay**. If Copilot errors on `create_slideshow`, restart MCP **switchbay** and use a **new** chat.",
      "Closing this VS Code window stops the session. Use **Keep running 24/7** on the Agent Dashboard if you want desks to keep ticking in a browser tab.",
    ].join("\n\n"),
  };
}
