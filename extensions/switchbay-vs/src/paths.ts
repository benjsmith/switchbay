import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";

export function repoRoot(context: vscode.ExtensionContext): string {
  const configured = vscode.workspace.getConfiguration("switchbay").get<string>("repoRoot")?.trim();
  if (configured) return configured;
  // F5 / in-tree: extensions/switchbay-vs → repo root. A Marketplace VSIX
  // lives under ~/.vscode/extensions/, so only use parent.parent when it
  // actually contains src/switchbay.
  const inTree = path.resolve(context.extensionPath, "..", "..");
  if (fs.existsSync(path.join(inTree, "src", "switchbay", "mcp_server.py"))) {
    return inTree;
  }
  return context.extensionPath;
}

/** Mars Hopper assets: bundled in the VSIX, else the in-tree static/ copy. */
export function hopperDir(context: vscode.ExtensionContext): string {
  const bundled = path.join(context.extensionPath, "static", "mars-hopper");
  if (fs.existsSync(path.join(bundled, "index.html"))) return bundled;
  return path.join(repoRoot(context), "static", "mars-hopper");
}

export function pythonBin(repo: string): string {
  const configured = vscode.workspace.getConfiguration("switchbay").get<string>("pythonPath")?.trim();
  if (configured) return configured;
  const unix = path.join(repo, ".venv", "bin", "python");
  const win = path.join(repo, ".venv", "Scripts", "python.exe");
  if (fs.existsSync(unix)) return unix;
  if (fs.existsSync(win)) return win;
  return "python3";
}

export function srcDir(repo: string): string {
  return path.join(repo, "src");
}

export function workspaceFolder(): vscode.Uri | undefined {
  return vscode.workspace.workspaceFolders?.[0]?.uri;
}

export function workspaceFsPath(): string | undefined {
  return workspaceFolder()?.fsPath;
}
