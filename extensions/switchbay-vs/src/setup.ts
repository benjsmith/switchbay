import { spawn } from "child_process";
import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";
import { pythonBin, repoRoot, srcDir } from "./paths";

const DISMISS_KEY = "switchbay.setupDismissed";
const REPO_URL = "https://github.com/benjsmith/switchbay";

export type ProbeResult = {
  ok: boolean;
  python: string;
  repo: string;
  detail: string;
};

export function looksLikeRepo(dir: string): boolean {
  return fs.existsSync(path.join(dir, "src", "switchbay", "mcp_server.py"));
}

export function probeSwitchbayAt(repo: string, py: string): Promise<ProbeResult> {
  const src = srcDir(repo);
  if (!looksLikeRepo(repo)) {
    return Promise.resolve({
      ok: false,
      python: py,
      repo,
      detail: "folder has no src/switchbay (not a Switch Bay checkout)",
    });
  }
  return new Promise((resolve) => {
    const proc = spawn(py, ["-c", "import switchbay"], {
      env: { ...process.env, PYTHONPATH: src },
      windowsHide: true,
    });
    let err = "";
    let done = false;
    const finish = (result: ProbeResult) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      resolve(result);
    };
    const timer = setTimeout(() => {
      proc.kill();
      finish({ ok: false, python: py, repo, detail: "python probe timed out" });
    }, 8000);
    proc.stderr?.on("data", (d: Buffer) => { err += d.toString(); });
    proc.on("error", (e) => {
      finish({ ok: false, python: py, repo, detail: String(e) });
    });
    proc.on("close", (code) => {
      if (code === 0) {
        finish({ ok: true, python: py, repo, detail: "" });
        return;
      }
      finish({
        ok: false,
        python: py,
        repo,
        detail: err.trim().slice(-500) || `python exited ${code}`,
      });
    });
  });
}

export function probeSwitchbay(context: vscode.ExtensionContext): Promise<ProbeResult> {
  const repo = repoRoot(context);
  return probeSwitchbayAt(repo, pythonBin(repo));
}

function defaultPython(repo: string): string | undefined {
  const unix = path.join(repo, ".venv", "bin", "python");
  const win = path.join(repo, ".venv", "Scripts", "python.exe");
  if (fs.existsSync(unix)) return unix;
  if (fs.existsSync(win)) return win;
  return undefined;
}

export async function configurePython(context: vscode.ExtensionContext): Promise<boolean> {
  const picked = await vscode.window.showOpenDialog({
    canSelectFolders: true,
    canSelectFiles: false,
    canSelectMany: false,
    title: "Select the Switch Bay git checkout (contains src/switchbay and usually .venv)",
    openLabel: "Use this checkout",
  });
  if (!picked?.[0]) return false;
  const repo = picked[0].fsPath;
  if (!looksLikeRepo(repo)) {
    void vscode.window.showErrorMessage(
      "That folder has no src/switchbay. Clone Switch Bay and run `make install`, then try again.",
    );
    return false;
  }

  let py = defaultPython(repo);
  if (!py) {
    const choice = await vscode.window.showWarningMessage(
      "No .venv in that checkout. Run `make install` there, or pick a Python that can `import switchbay`.",
      "Pick Python…",
      "Cancel",
    );
    if (choice !== "Pick Python…") return false;
    const pyPicked = await vscode.window.showOpenDialog({
      canSelectFiles: true,
      canSelectFolders: false,
      canSelectMany: false,
      title: "Python that can import switchbay",
      openLabel: "Use this Python",
    });
    if (!pyPicked?.[0]) return false;
    py = pyPicked[0].fsPath;
  }

  const cfg = vscode.workspace.getConfiguration("switchbay");
  await cfg.update("repoRoot", repo, vscode.ConfigurationTarget.Global);
  await cfg.update("pythonPath", py, vscode.ConfigurationTarget.Global);
  await context.globalState.update(DISMISS_KEY, false);

  const result = await probeSwitchbayAt(repo, py);
  if (!result.ok) {
    void vscode.window.showErrorMessage(
      `Python still cannot import switchbay.\n${py}\n${result.detail}\nFrom the checkout run: make install`,
    );
    return false;
  }
  void vscode.window.showInformationMessage(`Switch Bay VS is using ${py}`);
  return true;
}

export function maybeOfferSetup(
  context: vscode.ExtensionContext,
  onChange?: (ok: boolean) => void,
): void {
  void (async () => {
    const result = await probeSwitchbay(context);
    onChange?.(result.ok);
    if (result.ok) return;
    if (context.globalState.get<boolean>(DISMISS_KEY)) return;
    const choice = await vscode.window.showWarningMessage(
      "Switch Bay VS needs a local Switch Bay checkout (Python src + .venv). Graph rebuild and MCP will not work until it is configured.",
      "Configure…",
      "How to install",
      "Later",
    );
    if (choice === "Configure…") {
      const ok = await configurePython(context);
      onChange?.(ok);
      return;
    }
    if (choice === "How to install") {
      await vscode.env.openExternal(vscode.Uri.parse(REPO_URL));
      const again = await vscode.window.showInformationMessage(
        "Clone the repo, run `make install`, then point this extension at that folder.",
        "Configure…",
        "Later",
      );
      if (again === "Configure…") {
        const ok = await configurePython(context);
        onChange?.(ok);
        return;
      }
    }
    await context.globalState.update(DISMISS_KEY, true);
  })();
}
