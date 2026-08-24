import { spawn, type ChildProcessWithoutNullStreams } from "child_process";
import * as vscode from "vscode";
import { pythonBin, repoRoot, srcDir, workspaceFsPath } from "./paths";

export const MCP_SERVER_LABEL = "switchbay";

export type McpLaunch = {
  command: string;
  args: string[];
  cwd: string;
  env: Record<string, string>;
};

export function mcpLaunch(context: vscode.ExtensionContext): McpLaunch | undefined {
  const workspace = workspaceFsPath();
  if (!workspace) return undefined;
  const repo = repoRoot(context);
  const env: Record<string, string> = {};
  for (const [k, v] of Object.entries(process.env)) {
    if (typeof v === "string") env[k] = v;
  }
  env.PYTHONPATH = srcDir(repo);
  env.CSWY_WORKSPACE = workspace;
  env.CSWY_PROFILE = "vscode";
  return {
    command: pythonBin(repo),
    args: ["-m", "switchbay.mcp_server"],
    cwd: workspace,
    env,
  };
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
