/**
 * Resolve the curiosity-engine workspace for the open VS Code folder.
 *
 * Mode A: the folder itself has wiki/ (wiki-native).
 * Mode B: `.curiosity/config.toml` points at a wiki elsewhere (code-repo).
 * Mode C (dual cockpit) is a usage pattern, not a third pointer.
 */
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import { spawnSync } from "child_process";
import * as vscode from "vscode";
import { ceRoot } from "./ce";
import { workspaceFsPath } from "./paths";
import {
  expandUserPath, looksLikeCeWorkspace, parseCuriosityConfig,
  type CuriosityPointer,
} from "./wikiPointer";

export type OperatingMode = "wiki-native" | "code-repo" | "unresolved";

export type WikiResolution = {
  mode: OperatingMode;
  /** CE workspace (directory that contains wiki/). */
  wikiRoot: string | undefined;
  /** VS Code open folder. */
  openFolder: string | undefined;
  project?: string;
  pointerPath?: string;
};

let cached: { key: string; value: WikiResolution } | null = null;

function marksAt(dir: string) {
  return {
    hasWikiDir: fs.existsSync(path.join(dir, "wiki")),
    hasCuratorConfig: fs.existsSync(path.join(dir, ".curator", "config.json")),
    hasWikiGit: fs.existsSync(path.join(dir, "wiki", ".git")),
  };
}

function gitRoot(start: string): string | undefined {
  let d = path.resolve(start);
  for (let i = 0; i < 48; i++) {
    if (fs.existsSync(path.join(d, ".git"))) return d;
    const parent = path.dirname(d);
    if (parent === d) return undefined;
    d = parent;
  }
  return undefined;
}

/** Walk up to the git root looking for `.curiosity/config.toml`. */
export function findCuriosityPointer(start: string): string | undefined {
  const root = gitRoot(start);
  let d = path.resolve(start);
  while (true) {
    const p = path.join(d, ".curiosity", "config.toml");
    if (fs.existsSync(p)) return p;
    if (!root || d === root) break;
    const parent = path.dirname(d);
    if (parent === d) break;
    d = parent;
  }
  return undefined;
}

function configuredWikiRoot(): string | undefined {
  const raw = vscode.workspace.getConfiguration("switchbay").get<string>("wikiRoot")?.trim();
  if (!raw) return undefined;
  const expanded = expandUserPath(raw, os.homedir());
  return path.resolve(expanded);
}

function resolveFromPointer(pointerPath: string): { root?: string; pointer: CuriosityPointer } | undefined {
  let text = "";
  try {
    text = fs.readFileSync(pointerPath, "utf8");
  } catch {
    return undefined;
  }
  const pointer = parseCuriosityConfig(text);
  if (!pointer) return undefined;
  const root = path.resolve(path.dirname(pointerPath), expandUserPath(pointer.workspace, os.homedir()));
  return { root: fs.existsSync(root) ? root : undefined, pointer };
}

function resolveViaCeScript(from: string): string | undefined {
  const ce = ceRoot();
  if (!ce) return undefined;
  const script = path.join(ce, "scripts", "code_repo.py");
  if (!fs.existsSync(script)) return undefined;
  const py = pythonWithAny(from);
  const r = spawnSync(py, [script, "resolve-workspace", "--from", from], {
    encoding: "utf8",
    timeout: 8000,
    windowsHide: true,
  });
  if (r.status !== 0) return undefined;
  const line = (r.stdout || "").trim().split(/\r?\n/).filter(Boolean).pop();
  if (!line) return undefined;
  const resolved = path.resolve(line.trim());
  return fs.existsSync(resolved) ? resolved : undefined;
}

function pythonWithAny(workspace: string): string {
  const cands = [
    path.join(workspace, ".venv", "bin", "python"),
    path.join(workspace, ".venv", "bin", "python3"),
  ];
  const ce = ceRoot();
  if (ce) {
    cands.push(path.join(ce, ".venv", "bin", "python"), path.join(ce, ".venv", "bin", "python3"));
  }
  return cands.find((p) => fs.existsSync(p)) || "python3";
}

export function invalidateWikiRootCache(): void {
  cached = null;
}

export function resolveWiki(openFolder?: string): WikiResolution {
  const folder = openFolder || workspaceFsPath();
  const override = configuredWikiRoot();
  const key = `${folder || ""}|${override || ""}`;
  if (cached?.key === key) return cached.value;

  const empty: WikiResolution = { mode: "unresolved", wikiRoot: undefined, openFolder: folder };
  if (!folder && !override) {
    cached = { key, value: empty };
    return empty;
  }

  if (override && looksLikeCeWorkspace(marksAt(override))) {
    const value: WikiResolution = {
      mode: folder && path.resolve(folder) !== path.resolve(override) ? "code-repo" : "wiki-native",
      wikiRoot: override,
      openFolder: folder,
    };
    cached = { key, value };
    return value;
  }

  if (folder && looksLikeCeWorkspace(marksAt(folder))) {
    const value: WikiResolution = { mode: "wiki-native", wikiRoot: folder, openFolder: folder };
    cached = { key, value };
    return value;
  }

  if (folder) {
    const pointerPath = findCuriosityPointer(folder);
    if (pointerPath) {
      const parsed = resolveFromPointer(pointerPath);
      const root = parsed?.root || resolveViaCeScript(folder);
      if (root && looksLikeCeWorkspace(marksAt(root))) {
        const value: WikiResolution = {
          mode: "code-repo",
          wikiRoot: root,
          openFolder: folder,
          project: parsed?.pointer.project,
          pointerPath,
        };
        cached = { key, value };
        return value;
      }
    }
    const viaScript = resolveViaCeScript(folder);
    if (viaScript && looksLikeCeWorkspace(marksAt(viaScript))) {
      const value: WikiResolution = {
        mode: "code-repo",
        wikiRoot: viaScript,
        openFolder: folder,
      };
      cached = { key, value };
      return value;
    }
  }

  cached = { key, value: empty };
  return empty;
}

export function wikiFsPath(): string | undefined {
  return resolveWiki().wikiRoot;
}

export function wikiFolderUri(): vscode.Uri | undefined {
  const root = wikiFsPath();
  return root ? vscode.Uri.file(root) : undefined;
}

export function knowledgeHarnessOn(): boolean {
  const v = vscode.workspace.getConfiguration("switchbay").get<boolean>("knowledgeHarness");
  return v !== false;
}

export async function setKnowledgeHarness(on: boolean): Promise<void> {
  await vscode.workspace.getConfiguration("switchbay").update(
    "knowledgeHarness",
    on,
    vscode.ConfigurationTarget.Workspace,
  );
}

export async function pickWikiRoot(): Promise<string | undefined> {
  const picked = await vscode.window.showOpenDialog({
    canSelectFiles: false,
    canSelectFolders: true,
    canSelectMany: false,
    openLabel: "Use as wiki workspace",
    title: "Switch Bay wiki folder (contains wiki/)",
  });
  const dir = picked?.[0]?.fsPath;
  if (!dir) return undefined;
  if (!looksLikeCeWorkspace(marksAt(dir))) {
    void vscode.window.showWarningMessage(
      "That folder does not look like a curiosity-engine workspace (no wiki/ or .curator/).",
    );
    return undefined;
  }
  await vscode.workspace.getConfiguration("switchbay").update(
    "wikiRoot",
    dir,
    vscode.ConfigurationTarget.Workspace,
  );
  invalidateWikiRootCache();
  return dir;
}

export function modeLabel(res = resolveWiki()): string {
  if (res.mode === "wiki-native") return "wiki-native";
  if (res.mode === "code-repo") {
    const name = res.project || (res.wikiRoot ? path.basename(res.wikiRoot) : "wiki");
    return `code-repo → ${name}`;
  }
  return "no wiki";
}
