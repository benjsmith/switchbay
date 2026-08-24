import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";

export function repoRoot(context: vscode.ExtensionContext): string {
  const configured = vscode.workspace.getConfiguration("switchbay").get<string>("repoRoot")?.trim();
  if (configured) return configured;
  return path.resolve(context.extensionPath, "..", "..");
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
