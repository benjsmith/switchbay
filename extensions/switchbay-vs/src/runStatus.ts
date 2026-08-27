/**
 * Pure run-lifecycle rules for the Agent Dashboard.
 *
 * Copilot Chat has no session-end hook. A wave is live until Auto
 * reports done, wiki writes go quiet, or a hard idle cap hits.
 * Chat remaining open with “Keep curating” is not “still running”.
 */

export type PlanNode = {
  node_id: string;
  kind: string;
  role: string;
  objective: string;
  dependencies: string[];
  status?: string;
  retrieval_query?: string;
};

export type RunEvent = {
  at: number;
  kind: string;
  detail: string;
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
  activity?: string;
  events?: RunEvent[];
  wiki_writes?: number;
  ended_at?: number;
};

export const TERMINAL_PHASES = new Set([
  "done", "failed", "idle", "superseded", "stale",
]);

/** After wiki writes (or MCP tools) stop, the wave is finished even if Chat stays open. */
export const DONE_AFTER_WRITES_S = 120;

/** Chat-only card with no tools/writes — don't sit on "live" for a quarter hour. */
export const IDLE_CHAT_ONLY_S = 90;

/** No wiki writes — Chat stalled, waiting on approval, or never started. */
export const IDLE_NO_WRITES_S = 12 * 60;

/** Absolute cap so a heartbeat cannot keep a dead DAG live forever. */
export const HARD_TTL_S = 30 * 60;

export function lastActivity(rec: RunRecord): number {
  const events = rec.events || [];
  const lastEvent = events.length ? Math.max(...events.map((e) => e.at || 0)) : 0;
  return Math.max(rec.updated_at || 0, rec.started_at || 0, lastEvent);
}

export function settlePhase(
  rec: RunRecord,
  now = Date.now() / 1000,
): "live" | "done" | "idle" {
  if (TERMINAL_PHASES.has(rec.phase || "") || rec.ended_at) {
    if (rec.phase === "failed") return "idle";
    if (rec.phase === "idle" || rec.phase === "stale") return "idle";
    return "done";
  }
  const quiet = now - lastActivity(rec);
  const writes = rec.wiki_writes || 0;
  const kinds = new Set((rec.events || []).map((e) => e.kind));
  const hasMcp = kinds.has("mcp");
  if (writes > 0 && quiet >= DONE_AFTER_WRITES_S) return "done";
  if (writes === 0 && hasMcp && quiet >= DONE_AFTER_WRITES_S) return "done";
  if (writes === 0 && !hasMcp && quiet >= IDLE_CHAT_ONLY_S) return "idle";
  if (writes === 0 && quiet >= IDLE_NO_WRITES_S) return "idle";
  if (quiet >= HARD_TTL_S) return "idle";
  return "live";
}

export function isLiveRun(rec: RunRecord, now = Date.now() / 1000): boolean {
  return settlePhase(rec, now) === "live";
}

export function markNodesTerminal(rec: RunRecord, phase: string): void {
  const failed = phase === "failed";
  for (const n of rec.nodes) {
    if (n.status === "running" || n.status === "pending") {
      n.status = failed ? "failed" : "done";
    }
  }
}
