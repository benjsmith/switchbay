import * as vscode from "vscode";
import { MCP_SERVER_LABEL, mcpLaunch } from "./mcp";

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
      version: "0.0.1",
    });
  } catch {
    return new Ctor(MCP_SERVER_LABEL, launch.command, launch.args, launch.env, "0.0.1");
  }
}

/** Register Switch Bay's stdio MCP so Local-harness Agents sessions can call wiki/CE tools. */
export function registerMcpProvider(context: vscode.ExtensionContext): void {
  const register = (vscode.lm as unknown as {
    registerMcpServerDefinitionProvider?: (
      id: string,
      provider: {
        provideMcpServerDefinitions: () => vscode.ProviderResult<vscode.McpServerDefinition[]>;
        resolveMcpServerDefinition?: (server: vscode.McpServerDefinition) => vscode.ProviderResult<vscode.McpServerDefinition>;
      },
    ) => vscode.Disposable;
  }).registerMcpServerDefinitionProvider;
  if (!register) {
    console.log("[switchbay] vscode.lm.registerMcpServerDefinitionProvider is unavailable; Agents Local harness will not see Switch Bay MCP");
    return;
  }
  context.subscriptions.push(register(PROVIDER_ID, {
    provideMcpServerDefinitions: () => {
      const launch = mcpLaunch(context);
      if (!launch) return [];
      return [stdioDefinition(launch)];
    },
    resolveMcpServerDefinition: (server) => server,
  }));
}
