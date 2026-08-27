import { spawn, type ChildProcessWithoutNullStreams } from "child_process";
import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";
import { pythonBin, repoRoot, srcDir, workspaceFsPath } from "./paths";
import { knowledgeHarnessOn, wikiFsPath } from "./wikiRoot";

export const MCP_SERVER_LABEL = "switchbay";
/** Bump with Copilot-facing schema changes so VS Code drops cached tools/list. */
export const MCP_SCHEMA_REV = "0.3.3";

export type McpLaunch = {
  command: string;
  args: string[];
  cwd: string;
  env: Record<string, string>;
};

/** Directories that contain an `rg` binary the MCP sandbox wrapper looks for. */
export function ripgrepDirs(): string[] {
  const dirs: string[] = [];
  const appRoot = vscode.env.appRoot;
  const arch = process.arch === "arm64" ? "darwin-arm64" : "darwin-x64";
  for (const rel of [
    `node_modules.asar.unpacked/@vscode/ripgrep-universal/bin/${arch}`,
    `node_modules.asar.unpacked/@github/copilot-${arch}/ripgrep/bin/${arch}`,
    `extensions/copilot/node_modules/@github/copilot/sdk/ripgrep/bin/${arch}`,
  ]) {
    const dir = path.join(appRoot, rel);
    if (fs.existsSync(path.join(dir, "rg"))) dirs.push(dir);
  }
  for (const dir of ["/opt/homebrew/bin", "/usr/local/bin", path.join(osHomedir(), ".local", "bin")]) {
    if (fs.existsSync(path.join(dir, "rg"))) dirs.push(dir);
  }
  return dirs;
}

function osHomedir(): string {
  return process.env.HOME || process.env.USERPROFILE || "";
}

export function ripgrepAvailable(): boolean {
  if (ripgrepDirs().length) return true;
  const pathEnv = process.env.PATH || "";
  return pathEnv.split(path.delimiter).some((dir) => fs.existsSync(path.join(dir, "rg")));
}

export function mcpLaunch(context: vscode.ExtensionContext): McpLaunch | undefined {
  if (!knowledgeHarnessOn()) return undefined;
  const openFolder = workspaceFsPath();
  if (!openFolder) return undefined;
  // Mode B: CE tools must run against the wiki, not the code folder.
  const workspace = wikiFsPath() || openFolder;
  const repo = repoRoot(context);
  const env: Record<string, string> = {};
  for (const [k, v] of Object.entries(process.env)) {
    if (typeof v === "string") env[k] = v;
  }
  env.PYTHONPATH = srcDir(repo);
  env.CSWY_WORKSPACE = workspace;
  env.CSWY_PROFILE = "vscode";
  env.CSWY_MCP_REV = MCP_SCHEMA_REV;
  const rg = ripgrepDirs();
  if (rg.length) {
    env.PATH = [...rg, env.PATH || process.env.PATH || ""].filter(Boolean).join(path.delimiter);
  }
  return {
    command: pythonBin(repo),
    args: ["-m", "switchbay.mcp_server"],
    cwd: workspace,
    env,
  };
}

/**
 * Copilot Chat / Agents window only reliably see stdio MCP from
 * `.vscode/mcp.json`. The extension definition provider is not enough
 * for a custom .agent.md session.
 */
type McpFile = {
  servers?: Record<string, unknown>;
  sandbox?: { filesystem?: { allowWrite?: unknown } };
};

/**
 * Copilot confirms every MCP tool unless the stdio server is sandboxed
 * (macOS/Linux). Workspace writes only — wiki/CE stay inside the folder.
 */
function withWorkspaceSandbox(data: McpFile): McpFile["sandbox"] {
  const existing = Array.isArray(data.sandbox?.filesystem?.allowWrite)
    ? data.sandbox.filesystem.allowWrite.filter((p): p is string => typeof p === "string")
    : [];
  const allowWrite = [...new Set([...existing, "${workspaceFolder}"])];
  return {
    ...(data.sandbox || {}),
    filesystem: {
      ...(data.sandbox?.filesystem || {}),
      allowWrite,
    },
  };
}

export function writeWorkspaceMcpJson(context: vscode.ExtensionContext): boolean {
  const workspace = workspaceFsPath();
  if (!workspace) return false;
  if (!knowledgeHarnessOn()) {
    const file = path.join(workspace, ".vscode", "mcp.json");
    if (!fs.existsSync(file)) return true;
    try {
      const data = JSON.parse(fs.readFileSync(file, "utf8")) as McpFile;
      if (!data.servers?.switchbay) return true;
      delete data.servers.switchbay;
      fs.writeFileSync(file, JSON.stringify(data, null, 2) + "\n", "utf8");
    } catch { /* leave file */ }
    return true;
  }
  const launch = mcpLaunch(context);
  if (!launch) return false;
  const dir = path.join(workspace, ".vscode");
  const file = path.join(dir, "mcp.json");
  let data: McpFile = {};
  if (fs.existsSync(file)) {
    try {
      data = JSON.parse(fs.readFileSync(file, "utf8")) as McpFile;
    } catch {
      data = {};
    }
  }
  data.servers = data.servers && typeof data.servers === "object" ? data.servers : {};
  // Copilot's MCP sandbox wrapper looks for `rg` on the *host* PATH
  // (Dock-launched VS Code does not include Homebrew) and exits 1
  // before Python starts. That is worse than a one-time tool approval.
  const env: Record<string, string> = {
    PYTHONPATH: launch.env.PYTHONPATH,
    CSWY_PROFILE: "vscode",
    // Literal CE workspace — Mode B wiki may sit outside the open folder.
    CSWY_WORKSPACE: launch.env.CSWY_WORKSPACE || workspace,
    CSWY_MCP_REV: MCP_SCHEMA_REV,
  };
  if (launch.env.PATH) env.PATH = launch.env.PATH;
  const next: Record<string, unknown> = {
    type: "stdio",
    command: launch.command,
    args: launch.args,
    env,
    sandboxEnabled: false,
  };
  const sandbox = withWorkspaceSandbox(data);
  const prev = JSON.stringify({ server: data.servers.switchbay ?? null, sandbox: data.sandbox ?? null });
  const want = JSON.stringify({ server: next, sandbox });
  if (prev === want) return true;
  data.servers.switchbay = next;
  data.sandbox = sandbox;
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(file, JSON.stringify(data, null, 2) + "\n", "utf8");
  return true;
}

export async function tryStartWorkspaceMcp(): Promise<boolean> {
  const ids = [
    "mcp.restartServer",
    "workbench.mcp.restartServer",
    "mcp.startServer",
    "workbench.mcp.startServer",
    "mcp.servers.start",
    "mcp.servers.restart",
    "workbench.action.mcp.restartServer",
    "workbench.action.mcp.startServer",
  ];
  const args: unknown[] = [
    "switchbay",
    { name: "switchbay" },
    { id: "switchbay" },
    { server: "switchbay" },
  ];
  for (const id of ids) {
    for (const arg of args) {
      try {
        await vscode.commands.executeCommand(id, arg);
        return true;
      } catch { /* next */ }
    }
  }
  return false;
}

type Pending = {
  resolve: (value: unknown) => void;
  reject: (err: Error) => void;
};

export type McpTool = {
  name: string;
  description?: string;
  inputSchema?: Record<string, unknown>;
};

export class McpClient {
  private proc: ChildProcessWithoutNullStreams;
  private pending = new Map<number, Pending>();
  private nextId = 1;
  private buf = "";

  private constructor(proc: ChildProcessWithoutNullStreams) {
    this.proc = proc;
    proc.stdout.setEncoding("utf8");
    proc.stdout.on("data", (chunk: string) => this.onData(chunk));
    proc.stderr.setEncoding("utf8");
    proc.stderr.on("data", (chunk: string) => {
      const line = chunk.trim();
      if (line) console.log("[switchbay-mcp]", line);
    });
    proc.on("exit", (code) => {
      for (const [, p] of this.pending) {
        p.reject(new Error(`mcp server exited (${code})`));
      }
      this.pending.clear();
    });
  }

  static async start(context: vscode.ExtensionContext): Promise<McpClient> {
    const launch = mcpLaunch(context);
    if (!launch) throw new Error("open a folder first");
    const proc = spawn(launch.command, launch.args, {
      cwd: launch.cwd,
      env: launch.env,
      stdio: ["pipe", "pipe", "pipe"],
    }) as ChildProcessWithoutNullStreams;
    const client = new McpClient(proc);
    await client.request("initialize", {
      protocolVersion: "2025-06-18",
      capabilities: {},
      clientInfo: { name: "switchbay-vscode", version: "0.0.1" },
    });
    client.notify("notifications/initialized", {});
    return client;
  }

  dispose(): void {
    try { this.proc.kill(); } catch { /* already gone */ }
  }

  async listTools(): Promise<McpTool[]> {
    const result = await this.request("tools/list", {}) as { tools?: McpTool[] };
    return result.tools ?? [];
  }

  async callTool(name: string, args: Record<string, unknown>): Promise<{ text: string; isError: boolean }> {
    const result = await this.request("tools/call", {
      name,
      arguments: args,
    }) as { content?: Array<{ type?: string; text?: string }>; isError?: boolean };
    const text = (result.content ?? []).map((c) => c.text ?? "").join("\n");
    return { text, isError: Boolean(result.isError) };
  }

  private notify(method: string, params: unknown): void {
    this.proc.stdin.write(JSON.stringify({ jsonrpc: "2.0", method, params }) + "\n");
  }

  private request(method: string, params: unknown): Promise<unknown> {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.proc.stdin.write(JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n");
    });
  }

  private onData(chunk: string): void {
    this.buf += chunk;
    let nl: number;
    while ((nl = this.buf.indexOf("\n")) >= 0) {
      const line = this.buf.slice(0, nl).trim();
      this.buf = this.buf.slice(nl + 1);
      if (!line) continue;
      let msg: { id?: number; result?: unknown; error?: { message?: string } };
      try {
        msg = JSON.parse(line) as typeof msg;
      } catch {
        continue;
      }
      if (msg.id == null) continue;
      const pending = this.pending.get(msg.id);
      if (!pending) continue;
      this.pending.delete(msg.id);
      if (msg.error) pending.reject(new Error(msg.error.message || "mcp error"));
      else pending.resolve(msg.result);
    }
  }
}

let singleton: McpClient | undefined;
let starting: Promise<McpClient> | undefined;

export async function getMcp(context: vscode.ExtensionContext): Promise<McpClient> {
  if (singleton) return singleton;
  if (!starting) {
    starting = McpClient.start(context).then((c) => {
      singleton = c;
      return c;
    }).finally(() => { starting = undefined; });
  }
  return starting;
}

export function disposeMcp(): void {
  singleton?.dispose();
  singleton = undefined;
}
