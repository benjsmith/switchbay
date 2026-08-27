/**
 * Watch Copilot chatSessions JSONL for this workspace and mirror
 * in-flight requests onto the Agent Dashboard. Custom Auto sessions
 * never hit our ChatParticipant, so without this the DAG stays empty.
 */
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import * as vscode from "vscode";
import { parseChatJsonl, type ChatSnapshot } from "./chatSessions";
import { tryStartWorkspaceMcp, writeWorkspaceMcpJson } from "./mcp";
import { notifyMcpDefinitionsChanged } from "./mcpProvider";
import { ensureLiveRun, finishRun, isLiveRun, listRuns } from "./orch";
import { workspaceFsPath } from "./paths";

const DEBOUNCE_MS = 250;

function vscodeUserDir(): string {
  const home = os.homedir();
  const app = vscode.env.appName.includes("Insiders") ? "Code - Insiders" : "Code";
  if (process.platform === "darwin") {
    return path.join(home, "Library", "Application Support", app, "User");
  }
  if (process.platform === "win32") {
    return path.join(process.env.APPDATA || path.join(home, "AppData", "Roaming"), app, "User");
  }
  return path.join(process.env.XDG_CONFIG_HOME || path.join(home, ".config"), app, "User");
}

function sessionsDir(context: vscode.ExtensionContext, workspace?: string): string | undefined {
  const uri = context.storageUri;
  if (uri) {
    const dir = path.join(path.dirname(uri.fsPath), "chatSessions");
    if (fs.existsSync(dir)) return dir;
  }
  if (!workspace) return uri ? path.join(path.dirname(uri.fsPath), "chatSessions") : undefined;
  const root = path.join(vscodeUserDir(), "workspaceStorage");
  if (!fs.existsSync(root)) return undefined;
  const want = path.resolve(workspace);
  try {
    for (const name of fs.readdirSync(root)) {
      const wj = path.join(root, name, "workspace.json");
      if (!fs.existsSync(wj)) continue;
      let folder = "";
      try {
        const data = JSON.parse(fs.readFileSync(wj, "utf8")) as { folder?: string };
        folder = String(data.folder || "").replace(/^file:\/\//, "");
        try { folder = decodeURIComponent(folder); } catch { /* keep */ }
      } catch { continue; }
      if (path.resolve(folder) !== want) continue;
      const dir = path.join(root, name, "chatSessions");
      if (fs.existsSync(dir)) return dir;
    }
  } catch { /* skip */ }
  return undefined;
}

function readSnapshot(dir: string): ChatSnapshot | null {
  if (!fs.existsSync(dir)) return null;
  let running: ChatSnapshot | null = null;
  let latest: ChatSnapshot | null = null;
  for (const name of fs.readdirSync(dir)) {
    if (!name.endsWith(".jsonl")) continue;
    const file = path.join(dir, name);
    let text = "";
    try { text = fs.readFileSync(file, "utf8"); } catch { continue; }
    const snap = parseChatJsonl(text, file);
    if (!snap) continue;
    if (snap.running) {
      try {
        const ageMs = Date.now() - fs.statSync(file).mtimeMs;
        if (ageMs > 90_000) {
          snap.running = false;
          snap.completedAt = snap.completedAt || Date.now();
        }
      } catch { /* keep */ }
    }
    if (snap.running) running = snap;
    if (!latest || (snap.completedAt || 0) > (latest.completedAt || 0)) latest = snap;
  }
  return running || latest || null;
}

function applySnapshot(workspace: string, snap: ChatSnapshot, opts?: { onNewRequest?: () => void }): void {
  if (snap.running) {
    const before = listRuns(workspace).find((r) => isLiveRun(r));
    const rec = ensureLiveRun(workspace, snap.prompt, {
      via: "chat",
      agent: "Auto",
      requestId: snap.requestId,
      kind: "chat",
    });
    if (!before || before.orchestration_id !== rec.orchestration_id) opts?.onNewRequest?.();
    return;
  }
  const live = listRuns(workspace).find((r) => isLiveRun(r));
  const sameLive = live && (
    live.note === snap.requestId
    || (live.objective || "").trim() === snap.prompt.trim()
  );
  if (sameLive && live) {
    live.activity = "Chat finished this turn";
    finishRun(workspace, live.orchestration_id, "done");
    return;
  }
  const justNow = snap.completedAt && Date.now() - snap.completedAt < 120_000;
  if (!justNow) return;
  const already = listRuns(workspace).some((r) => r.note === snap.requestId);
  if (already) return;
  const rec = ensureLiveRun(workspace, snap.prompt, {
    via: "chat",
    agent: "Auto",
    requestId: snap.requestId,
    kind: "chat",
  });
  rec.activity = "Chat finished this turn";
  finishRun(workspace, rec.orchestration_id, "done");
}

export function startChatObserver(context: vscode.ExtensionContext): void {
  const workspace = () => workspaceFsPath();
  let watched: string | undefined;
  let dirWatcher: fs.FSWatcher | undefined;

  const tick = () => {
    const ws = workspace();
    if (!ws) return;
    const dir = sessionsDir(context, ws);
    if (dir && dir !== watched) {
      try { dirWatcher?.close(); } catch { /* */ }
      watched = dir;
      try {
        fs.mkdirSync(dir, { recursive: true });
        dirWatcher = fs.watch(dir, { persistent: false }, () => soon());
        context.subscriptions.push({ dispose: () => dirWatcher?.close() });
      } catch { /* watch optional */ }
    }
    if (!dir) return;
    const snap = readSnapshot(dir);
    if (!snap) return;
    applySnapshot(ws, snap, {
      onNewRequest: () => {
        writeWorkspaceMcpJson(context);
        notifyMcpDefinitionsChanged();
        void tryStartWorkspaceMcp();
      },
    });
  };

  let debounce: ReturnType<typeof setTimeout> | undefined;
  const soon = () => {
    clearTimeout(debounce);
    debounce = setTimeout(tick, DEBOUNCE_MS);
  };

  const interval = setInterval(tick, 2000);
  context.subscriptions.push({ dispose: () => clearInterval(interval) });
  setTimeout(tick, 800);
}
