/**
 * Ingest a file or folder into the resolved CE vault (local_ingest.py).
 * No daemon. Paths outside the wiki use --source-path-only (Mode B).
 */
import * as fs from "fs";
import * as path from "path";
import { spawn } from "child_process";
import * as vscode from "vscode";
import { ceRoot, pythonWithKuzu } from "./ce";
import { pythonBin, repoRoot } from "./paths";
import { resolveWiki, wikiFsPath } from "./wikiRoot";

function within(root: string, candidate: string): boolean {
  const a = path.resolve(root);
  const b = path.resolve(candidate);
  return b === a || b.startsWith(a + path.sep);
}

function ingestPython(wikiRoot: string, context: vscode.ExtensionContext): string {
  return pythonWithKuzu(wikiRoot) || pythonBin(repoRoot(context));
}

function multimodalPendingCount(text: string): number {
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start < 0 || end <= start) return 0;
  try {
    const j = JSON.parse(text.slice(start, end + 1)) as { multimodal_pending?: number };
    return Number(j.multimodal_pending) || 0;
  } catch {
    return 0;
  }
}

export async function ingestFsPath(
  context: vscode.ExtensionContext,
  target: string,
): Promise<{ ok: boolean; text: string }> {
  const wiki = wikiFsPath();
  if (!wiki) {
    return { ok: false, text: "No curiosity-engine wiki resolved. Open a wiki folder, or set switchbay.wikiRoot." };
  }
  const ce = ceRoot();
  const script = path.join(ce || "", "scripts", "local_ingest.py");
  if (!ce || !fs.existsSync(script)) {
    return { ok: false, text: "curiosity-engine local_ingest.py not found." };
  }
  let st: fs.Stats;
  try {
    st = fs.statSync(target);
  } catch {
    return { ok: false, text: `Not found: ${target}` };
  }
  const py = ingestPython(wiki, context);
  const outside = !within(wiki, target);
  const project = resolveWiki().project;
  const args: string[] = [];
  if (st.isFile()) {
    args.push("--file", target);
    if (outside) args.push("--source-path-only");
  } else if (st.isDirectory()) {
    args.push(target);
    if (outside) args.push("--source-path-only");
  } else {
    return { ok: false, text: "Not a file or folder." };
  }
  if (project && !args.includes("--projects")) {
    args.push("--projects", project);
  }
  return new Promise((resolve) => {
    const proc = spawn(py, [script, ...args], {
      cwd: wiki,
      windowsHide: true,
    });
    let text = "";
    proc.stdout?.on("data", (d: Buffer) => { text += d.toString(); });
    proc.stderr?.on("data", (d: Buffer) => { text += d.toString(); });
    const timer = setTimeout(() => {
      proc.kill();
      resolve({ ok: false, text: `${text}\ningest timed out`.slice(-4000) });
    }, 300000);
    proc.on("error", (err) => {
      clearTimeout(timer);
      resolve({ ok: false, text: String(err) });
    });
    proc.on("close", (code) => {
      clearTimeout(timer);
      resolve({ ok: code === 0, text: text.slice(-4000) || (code === 0 ? "ingested" : `exit ${code}`) });
    });
  });
}

export async function ingestWithProgress(
  context: vscode.ExtensionContext,
  target: string,
): Promise<void> {
  await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: `Ingesting ${path.basename(target)}…` },
    async () => {
      const result = await ingestFsPath(context, target);
      if (result.ok) {
        const n = multimodalPendingCount(result.text);
        void vscode.window.showInformationMessage(
          n
            ? `Ingested ${path.basename(target)}. ${n} file(s) flagged for later vision (figures/tables) — run Curate, not ingest.`
            : `Ingested ${path.basename(target)}.`,
        );
        void vscode.commands.executeCommand("switchbay.refreshTrees");
      } else {
        void vscode.window.showErrorMessage(`Ingest failed.\n${result.text.slice(-500)}`);
      }
    },
  );
}

export async function pickAndIngest(
  context: vscode.ExtensionContext,
  folders: boolean,
): Promise<void> {
  const picked = await vscode.window.showOpenDialog({
    canSelectFiles: !folders,
    canSelectFolders: folders,
    canSelectMany: true,
    openLabel: folders ? "Ingest folder" : "Ingest file",
    title: folders ? "Ingest folder into the wiki vault" : "Ingest file into the wiki vault",
  });
  if (!picked?.length) return;
  for (const uri of picked) {
    await ingestWithProgress(context, uri.fsPath);
  }
}
