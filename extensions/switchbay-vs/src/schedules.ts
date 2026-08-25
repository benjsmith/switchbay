/**
 * Recurring named-agent runs for a CE workspace.
 *
 * Same file as the PWA (`<workspace>/.workbench/state/schedules.json`)
 * plus an optional `agent` field (custom agent name; default Auto).
 * The plugin ticks only while VS Code is open — closing the window
 * stops work, matching the no-daemon rule.
 */
import * as crypto from "crypto";
import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";
import { startNamedAgentSession } from "./agentsSession";
import { workspaceFsPath } from "./paths";

export const FREQUENCIES = ["hourly", "daily", "weekly", "every_n_hours"] as const;
export type Frequency = (typeof FREQUENCIES)[number];

export type Schedule = {
  id: string;
  title: string;
  prompt: string;
  frequency: Frequency;
  every_hours: number;
  enabled: boolean;
  preference?: number | null;
  agent?: string;
  created_at: number;
  created_day: string;
  edited_at: number;
  last_run_at: number | null;
  run_count: number;
  running_run_id: string | null;
};

const VERSION = 1;
const TICK_MS = 20_000;

function filePath(workspace: string): string {
  return path.join(workspace, ".workbench", "state", "schedules.json");
}

function empty(): { version: number; items: Schedule[] } {
  return { version: VERSION, items: [] };
}

function asFreq(value: unknown): Frequency {
  return FREQUENCIES.includes(value as Frequency) ? (value as Frequency) : "daily";
}

function normalize(raw: Record<string, unknown>): Schedule | null {
  const id = String(raw.id || "");
  if (!id) return null;
  return {
    id,
    title: String(raw.title || "Untitled").slice(0, 120),
    prompt: String(raw.prompt || ""),
    frequency: asFreq(raw.frequency),
    every_hours: Number.isFinite(Number(raw.every_hours)) ? Number(raw.every_hours) : 24,
    enabled: raw.enabled !== false,
    preference: typeof raw.preference === "number" ? raw.preference : null,
    agent: String(raw.agent || "Auto") || "Auto",
    created_at: Number(raw.created_at) || Date.now() / 1000,
    created_day: String(raw.created_day || ""),
    edited_at: Number(raw.edited_at) || Date.now() / 1000,
    last_run_at: raw.last_run_at == null ? null : Number(raw.last_run_at) || null,
    run_count: Number(raw.run_count) || 0,
    running_run_id: raw.running_run_id ? String(raw.running_run_id) : null,
  };
}

function loadFile(workspace: string): { version: number; items: Schedule[] } {
  const p = filePath(workspace);
  if (!fs.existsSync(p)) return empty();
  try {
    const data = JSON.parse(fs.readFileSync(p, "utf8")) as { version?: number; items?: unknown };
    if (data.version !== VERSION || !Array.isArray(data.items)) return empty();
    return {
      version: VERSION,
      items: data.items
        .filter((i): i is Record<string, unknown> => !!i && typeof i === "object")
        .map(normalize)
        .filter((i): i is Schedule => i != null),
    };
  } catch {
    return empty();
  }
}

function saveFile(workspace: string, data: { version: number; items: Schedule[] }): void {
  const p = filePath(workspace);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  const tmp = `${p}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify({ version: VERSION, items: data.items }, null, 2) + "\n", "utf8");
  fs.renameSync(tmp, p);
}

export function listSchedules(workspace: string): Schedule[] {
  return loadFile(workspace).items;
}

export function upsertSchedule(workspace: string, patch: Partial<Schedule> & { title?: string }): Schedule {
  const data = loadFile(workspace);
  const now = Date.now() / 1000;
  const existing = patch.id ? data.items.find((i) => i.id === patch.id) : undefined;
  if (existing) {
    if (patch.title !== undefined) existing.title = String(patch.title).trim().slice(0, 120) || "Untitled";
    if (patch.prompt !== undefined) existing.prompt = String(patch.prompt);
    if (patch.frequency !== undefined) existing.frequency = asFreq(patch.frequency);
    if (patch.every_hours !== undefined) existing.every_hours = Number(patch.every_hours) || 24;
    if (patch.enabled !== undefined) existing.enabled = Boolean(patch.enabled);
    if (patch.preference !== undefined) existing.preference = patch.preference;
    if (patch.agent !== undefined) existing.agent = String(patch.agent || "Auto") || "Auto";
    existing.edited_at = now;
    saveFile(workspace, data);
    return existing;
  }
  const item: Schedule = {
    id: `sch-${crypto.randomBytes(5).toString("hex")}`,
    title: (patch.title || "Untitled").trim().slice(0, 120) || "Untitled",
    prompt: patch.prompt || "",
    frequency: asFreq(patch.frequency),
    every_hours: Number(patch.every_hours) || 24,
    enabled: patch.enabled !== false,
    preference: patch.preference ?? null,
    agent: String(patch.agent || "Auto") || "Auto",
    created_at: now,
    created_day: new Date().toISOString().slice(0, 10),
    edited_at: now,
    last_run_at: null,
    run_count: 0,
    running_run_id: null,
  };
  data.items.push(item);
  saveFile(workspace, data);
  return item;
}

export function deleteSchedule(workspace: string, id: string): boolean {
  const data = loadFile(workspace);
  const next = data.items.filter((i) => i.id !== id);
  if (next.length === data.items.length) return false;
  data.items = next;
  saveFile(workspace, data);
  return true;
}

export function intervalSec(item: Schedule): number {
  if (item.frequency === "hourly") return 3600;
  if (item.frequency === "weekly") return 7 * 86400;
  if (item.frequency === "every_n_hours") return Math.max(1, item.every_hours || 24) * 3600;
  return 86400;
}

export function isDue(item: Schedule, now = Date.now() / 1000): boolean {
  if (!item.enabled) return false;
  if (item.running_run_id) return false;
  if (item.last_run_at == null) return true;
  return now - item.last_run_at >= intervalSec(item);
}

function markStarted(workspace: string, id: string, runId: string): Schedule | undefined {
  const data = loadFile(workspace);
  const item = data.items.find((i) => i.id === id);
  if (!item) return undefined;
  item.last_run_at = Date.now() / 1000;
  item.run_count = (item.run_count || 0) + 1;
  item.running_run_id = runId;
  saveFile(workspace, data);
  return item;
}

function setRunning(workspace: string, id: string, runId: string | null): void {
  const data = loadFile(workspace);
  const item = data.items.find((i) => i.id === id);
  if (!item) return;
  item.running_run_id = runId;
  saveFile(workspace, data);
}

function clearRunning(workspace: string, id: string): void {
  setRunning(workspace, id, null);
}

export async function runScheduleNow(
  context: vscode.ExtensionContext,
  workspace: string,
  id: string,
): Promise<{ ok: boolean; text: string }> {
  const item = listSchedules(workspace).find((i) => i.id === id);
  if (!item) return { ok: false, text: "Schedule not found." };
  const agent = (item.agent || "Auto").trim() || "Auto";
  const prompt = item.prompt.trim() || item.title;
  const pending = markStarted(workspace, id, "pending");
  if (!pending) return { ok: false, text: "Schedule not found." };
  try {
    if (agent.toLowerCase() === "auto") {
      const { startCurate } = await import("./orch");
      const { text, orchestrationId } = await startCurate(context, prompt, {
        preference: item.preference ?? undefined,
        via: `schedule:${item.id}`,
      });
      setRunning(workspace, id, orchestrationId || "session");
      setTimeout(() => clearRunning(workspace, id), 8_000);
      return { ok: true, text };
    }
    const session = await startNamedAgentSession(agent, prompt);
    setRunning(workspace, id, session.via || "session");
    setTimeout(() => clearRunning(workspace, id), 8_000);
    return {
      ok: session.opened,
      text: session.opened
        ? `Started **${agent}** for “${item.title}”. Closing VS Code stops the session.`
        : `Could not open the ${agent} agent session.`,
    };
  } catch (err) {
    clearRunning(workspace, id);
    return { ok: false, text: (err as Error).message };
  }
}

export function startScheduleTicker(context: vscode.ExtensionContext): void {
  const tick = async () => {
    const workspace = workspaceFsPath();
    if (!workspace) return;
    for (const item of listSchedules(workspace)) {
      if (!isDue(item)) continue;
      const result = await runScheduleNow(context, workspace, item.id);
      if (result.ok) {
        void vscode.window.showInformationMessage(
          `Switch Bay schedule “${item.title}” fired on ${item.agent || "Auto"}.`,
        );
      } else {
        void vscode.window.showWarningMessage(
          `Switch Bay schedule “${item.title}” failed: ${result.text.slice(0, 180)}`,
        );
      }
    }
  };
  const handle = setInterval(() => { void tick(); }, TICK_MS);
  context.subscriptions.push({ dispose: () => clearInterval(handle) });
  // First tick after a short delay so activation is not blocked.
  setTimeout(() => { void tick(); }, 4_000);
}
