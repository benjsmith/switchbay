/**
 * Overnight desks tick only while this VS Code window is open.
 * VS Code for the Web (`code serve-web` / Remote Tunnel) is the
 * grok-bot-like host: leave a browser tab on the same workspace.
 */
import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";

const SETTING = "keepWindowOpen";

const TUNNEL_COMMANDS = [
  "workbench.action.remote-tunnel.start",
  "workbench.remote.tunnel.start",
  "remote-tunnels.turnOn",
  "workbench.action.remoteTunnel.start",
];

export function isWebHost(): boolean {
  return vscode.env.uiKind === vscode.UIKind.Web;
}

export function keepWindowOpen(): boolean {
  return isWebHost()
    || vscode.workspace.getConfiguration("switchbay").get<boolean>(SETTING) === true;
}

export async function setKeepWindowOpen(value: boolean): Promise<void> {
  await vscode.workspace.getConfiguration("switchbay").update(
    SETTING,
    value,
    vscode.ConfigurationTarget.Global,
  );
}

function codeCli(): string | undefined {
  const bin = vscode.env.appName.includes("Insiders") ? "code-insiders" : "code";
  const candidates = [
    path.join(vscode.env.appRoot, "bin", bin),
    path.join(vscode.env.appRoot, "bin", "code"),
    `/usr/local/bin/${bin}`,
    `/opt/homebrew/bin/${bin}`,
  ];
  return candidates.find((p) => fs.existsSync(p));
}

async function tryTunnel(): Promise<boolean> {
  for (const id of TUNNEL_COMMANDS) {
    try {
      await vscode.commands.executeCommand(id);
      return true;
    } catch {
      continue;
    }
  }
  return false;
}

function startServeWeb(): boolean {
  const cli = codeCli();
  if (!cli) return false;
  const term = vscode.window.createTerminal({ name: "Switch Bay VS Web" });
  term.sendText(`"${cli}" serve-web --accept-server-license-terms --host 127.0.0.1 --port 8000`);
  term.show();
  return true;
}

/**
 * Confirm this window (or a browser tab) will stay open so schedules fire.
 * Returns true if the user accepted a host.
 */
export async function offerKeepRunning(reason?: string): Promise<boolean> {
  if (isWebHost()) {
    await setKeepWindowOpen(true);
    void vscode.window.showInformationMessage(
      "This browser tab is the Switch Bay host. Leave it open — desks stop if you close it.",
    );
    return true;
  }
  if (keepWindowOpen()) return true;

  const detail = reason
    ? `${reason} Desks and schedules only run while this window is open.`
    : "Desks and schedules only run while this VS Code window is open.";

  const pick = await vscode.window.showInformationMessage(
    `${detail} Keep this window open, or open VS Code for the Web in a browser tab you can leave running.`,
    { modal: false },
    "Keep this window open",
    "Open VS Code for the Web…",
    "Remote Tunnel…",
  );
  if (pick === "Keep this window open") {
    await setKeepWindowOpen(true);
    return true;
  }
  if (pick === "Remote Tunnel…") {
    if (await tryTunnel()) {
      await setKeepWindowOpen(true);
      return true;
    }
    void vscode.window.showWarningMessage(
      "Remote Tunnel command was not available. Try Command Palette → “Remote Tunnels”, or Open VS Code for the Web.",
    );
    return false;
  }
  if (pick === "Open VS Code for the Web…") {
    if (startServeWeb()) {
      await setKeepWindowOpen(true);
      void vscode.window.showInformationMessage(
        "VS Code for the Web is starting. Open http://127.0.0.1:8000, then this workspace, so desks keep ticking in that tab.",
      );
      return true;
    }
    void vscode.window.showWarningMessage(
      "Could not find the VS Code CLI (`code serve-web`). Keep this desktop window open instead, or install the `code` shell command.",
    );
    return false;
  }
  return false;
}
