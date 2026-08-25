import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";
import { EXTENSION_ID } from "./agentsSession";
import { repoRoot } from "./paths";

export function installedVersion(context: vscode.ExtensionContext): string {
  return String((context.extension.packageJSON as { version?: string }).version || "0.0.0");
}

function vsixPath(repo: string, version: string): string {
  return path.join(repo, "dist", `switchbay-vs-${version}.vsix`);
}

function packagedVersion(repo: string): string | undefined {
  const pkg = path.join(repo, "extensions", "switchbay-vs", "package.json");
  if (!fs.existsSync(pkg)) return undefined;
  try {
    const data = JSON.parse(fs.readFileSync(pkg, "utf8")) as { version?: string };
    return data.version;
  } catch {
    return undefined;
  }
}

function isDevHost(context: vscode.ExtensionContext): boolean {
  return context.extensionMode === vscode.ExtensionMode.Development
    || /extensions[/\\]switchbay-vs$/i.test(context.extensionPath);
}

/**
 * Sideload update: install a newer VSIX from the Switch Bay checkout
 * over the same publisher.name. Marketplace auto-update is not used.
 */
export async function checkAndOfferUpdate(context: vscode.ExtensionContext): Promise<void> {
  const current = installedVersion(context);
  if (isDevHost(context)) {
    const choice = await vscode.window.showInformationMessage(
      `Switch Bay VS ${current} is running from F5 (Extension Development Host). `
      + `Reload this window after compile. Sideload updates use a VSIX: make vsix, then `
      + `code --install-extension dist/switchbay-vs-${current}.vsix`,
      "Reload window",
      "Copy install command",
    );
    if (choice === "Reload window") {
      await vscode.commands.executeCommand("workbench.action.reloadWindow");
    } else if (choice === "Copy install command") {
      await vscode.env.clipboard.writeText(`make vsix && code --install-extension dist/switchbay-vs-${current}.vsix`);
    }
    return;
  }

  const repo = repoRoot(context);
  const packaged = packagedVersion(repo);
  const file = packaged ? vsixPath(repo, packaged) : "";
  const hasVsix = Boolean(file && fs.existsSync(file));

  const lines = [
    `Installed: ${current} (${EXTENSION_ID})`,
    packaged ? `Checkout package.json: ${packaged}` : "Checkout package.json not found (set switchbay.repoRoot).",
    hasVsix ? `VSIX on disk: ${file}` : "No matching dist/*.vsix — run `make vsix` in the Switch Bay repo.",
    "Sideload installs do not auto-update. Installing the new VSIX replaces this one; then Reload Window.",
  ];

  const actions: string[] = [];
  if (hasVsix && packaged && packaged !== current) actions.push("Install VSIX");
  else if (hasVsix) actions.push("Reinstall VSIX");
  actions.push("Copy command", "Reload window");

  const choice = await vscode.window.showInformationMessage(lines.join("\n"), { modal: true }, ...actions);
  if (choice === "Install VSIX" || choice === "Reinstall VSIX") {
    const uri = vscode.Uri.file(file);
    try {
      await vscode.commands.executeCommand("workbench.extensions.installExtension", uri);
    } catch {
      await vscode.commands.executeCommand("workbench.extensions.command.installFromVSIX", uri);
    }
    const reload = await vscode.window.showInformationMessage(
      `Installed Switch Bay VS ${packaged}. Reload to finish the update.`,
      "Reload window",
    );
    if (reload === "Reload window") {
      await vscode.commands.executeCommand("workbench.action.reloadWindow");
    }
    return;
  }
  if (choice === "Copy command") {
    const v = packaged || current;
    await vscode.env.clipboard.writeText(`make vsix && code --install-extension dist/switchbay-vs-${v}.vsix`);
    void vscode.window.showInformationMessage("Copied make vsix && code --install-extension …");
  }
  if (choice === "Reload window") {
    await vscode.commands.executeCommand("workbench.action.reloadWindow");
  }
}
