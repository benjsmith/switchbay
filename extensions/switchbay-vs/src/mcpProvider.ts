import * as vscode from "vscode";
import { MCP_SCHEMA_REV, MCP_SERVER_LABEL, mcpLaunch, writeWorkspaceMcpJson } from "./mcp";

let mcpChanged: vscode.EventEmitter<void> | undefined;

export function notifyMcpDefinitionsChanged(): void {
  mcpChanged?.fire();
}

const PROVIDER_ID = "switchbay.mcp";

function stdioDefinition(launch: NonNullable<ReturnType<typeof mcpLaunch>>): vscode.McpStdioServerDefinition {
  const Ctor = vscode.McpStdioServerDefinition as unknown as {
    new (label: string, command: string, args?: string[], env?: Record<string, string | number | null>, version?: string): vscode.McpStdioServerDefinition;
    new (opts: {
      label: string;
      command: string;
      args?: string[];
      env?: Record<string, string | number | null>;
      cwd?: vscode.Uri;
      version?: string;
    }): vscode.McpStdioServerDefinition;
  };
  try {
    return new Ctor({
      label: MCP_SERVER_LABEL,
      command: launch.command,
      args: launch.args,
      env: launch.env,
      cwd: vscode.Uri.file(launch.cwd),
      version: MCP_SCHEMA_REV,
    });
  } catch {
    return new Ctor(MCP_SERVER_LABEL, launch.command, launch.args, launch.env, MCP_SCHEMA_REV);
  }
}

/** Register Switch Bay's stdio MCP so Local-harness Agents sessions can call wiki/CE tools. */
export function registerMcpProvider(context: vscode.ExtensionContext): vscode.EventEmitter<void> {
  const changed = new vscode.EventEmitter<void>();
  mcpChanged = changed;
  context.subscriptions.push(changed);
  writeWorkspaceMcpJson(context);
  const register = (vscode.lm as unknown as {
    registerMcpServerDefinitionProvider?: (
      id: string,
      provider: {
        onDidChangeMcpServerDefinitions?: vscode.Event<void>;
        provideMcpServerDefinitions: () => vscode.ProviderResult<vscode.McpServerDefinition[]>;
        resolveMcpServerDefinition?: (server: vscode.McpServerDefinition) => vscode.ProviderResult<vscode.McpServerDefinition>;
      },
    ) => vscode.Disposable;
  }).registerMcpServerDefinitionProvider;
  if (!register) {
    console.log("[switchbay] vscode.lm.registerMcpServerDefinitionProvider is unavailable; Agents Local harness will not see Switch Bay MCP");
    return changed;
  }
  try {
    context.subscriptions.push(register(PROVIDER_ID, {
      onDidChangeMcpServerDefinitions: changed.event,
      provideMcpServerDefinitions: () => {
        try {
          const launch = mcpLaunch(context);
          if (!launch) return [];
          return [stdioDefinition(launch)];
        } catch (err) {
          console.log("[switchbay] MCP definition failed", err);
          return [];
        }
      },
      resolveMcpServerDefinition: (server) => server,
    }));
  } catch (err) {
    console.log("[switchbay] MCP provider registration failed", err);
  }
  queueMicrotask(() => changed.fire());
  return changed;
}
