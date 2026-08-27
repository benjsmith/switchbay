/**
 * Parse VS Code Copilot chatSessions JSONL (workspaceStorage/<id>/chatSessions/*.jsonl).
 * That log is the only reliable “Chat is working” signal: custom .agent.md
 * sessions do not go through our ChatParticipant, and wiki writes may never happen.
 */

export type ChatSnapshot = {
  requestId: string;
  prompt: string;
  running: boolean;
  completedAt?: number;
  elapsedMs?: number;
  file: string;
};

type PathKey = string;

function keyOf(k: unknown): PathKey {
  return JSON.stringify(k ?? []);
}

function setPath(obj: Record<string, unknown>, path: unknown[], value: unknown): void {
  if (!path.length) return;
  let cur: Record<string, unknown> = obj;
  for (let i = 0; i < path.length - 1; i++) {
    const p = path[i];
    const next = path[i + 1];
    const asNum = typeof next === "number";
    const slot = cur[String(p)];
    if (slot == null || typeof slot !== "object") {
      cur[String(p)] = asNum ? [] : {};
    }
    cur = cur[String(p)] as Record<string, unknown>;
  }
  cur[String(path[path.length - 1])] = value as never;
}

function promptOf(req: Record<string, unknown>): string {
  const message = req.message;
  if (typeof message === "string") return message.trim();
  if (message && typeof message === "object") {
    const text = (message as { text?: unknown }).text;
    if (typeof text === "string" && text.trim()) return text.trim();
  }
  const prompt = req.prompt;
  if (typeof prompt === "string") return prompt.trim();
  return "";
}

function completedAtOf(req: Record<string, unknown>): number | undefined {
  const ms = req.modelState;
  if (ms && typeof ms === "object") {
    const c = (ms as { completedAt?: unknown }).completedAt;
    if (typeof c === "number" && c > 0) return c;
  }
  const result = req.result;
  if (result && typeof result === "object") {
    const timings = (result as { timings?: { totalElapsed?: unknown } }).timings;
    const ts = typeof req.timestamp === "number" ? req.timestamp : 0;
    if (timings && typeof timings.totalElapsed === "number" && timings.totalElapsed > 0) {
      return ts + timings.totalElapsed;
    }
    const elapsed = typeof req.elapsedMs === "number" ? req.elapsedMs : 0;
    if (elapsed > 0 || Object.keys(result).length > 0) return ts + elapsed;
  }
  return undefined;
}

/** Replay one JSONL session into the latest user request. */
export function parseChatJsonl(text: string, file = ""): ChatSnapshot | null {
  const state = new Map<PathKey, unknown>();
  for (const line of text.split("\n")) {
    const s = line.trim();
    if (!s) continue;
    let obj: { kind?: number; k?: unknown; v?: unknown };
    try {
      obj = JSON.parse(s) as typeof obj;
    } catch {
      continue;
    }
    if (obj.k == null) continue;
    state.set(keyOf(obj.k), obj.v);
  }
  const list = state.get(keyOf(["requests"]));
  if (!Array.isArray(list) || !list.length) return null;
  const idx = list.length - 1;
  const lastRaw = list[idx];
  if (!lastRaw || typeof lastRaw !== "object") return null;
  const last = { ...(lastRaw as Record<string, unknown>) };
  for (const [k, v] of state) {
    let path: unknown[];
    try { path = JSON.parse(k) as unknown[]; } catch { continue; }
    if (path[0] !== "requests" || path[1] !== idx || path.length < 3) continue;
    setPath(last, path.slice(2), v);
  }
  const prompt = promptOf(last);
  if (!prompt) return null;
  const requestId = String(last.requestId || `${file}:${idx}`);
  const completedAt = completedAtOf(last);
  const elapsedMs = typeof last.elapsedMs === "number" ? last.elapsedMs : undefined;
  return {
    requestId,
    prompt: prompt.slice(0, 240),
    running: completedAt == null,
    completedAt,
    elapsedMs,
    file,
  };
}
