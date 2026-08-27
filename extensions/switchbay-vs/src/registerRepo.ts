/**
 * One-click Mode B: attach the open Explorer folder to a shared CE wiki,
 * or from a wiki window attach another project folder. Writes the CE
 * pointer (``.curiosity/config.toml``) and registers the project-dir.
 */
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import { spawnSync } from "child_process";
import * as vscode from "vscode";
import { ceRoot } from "./ce";
import { workspaceFsPath } from "./paths";
import { looksLikeCeWorkspace, parseSbhArg } from "./wikiPointer";
import {
  invalidateWikiRootCache, knowledgeHarnessOn, resolveWiki, setKnowledgeHarness, wikiFsPath,
} from "./wikiRoot";

const RECENT_KEY = "switchbay.recentWikis";

function marks(dir: string) {
  return {
    hasWikiDir: fs.existsSync(path.join(dir, "wiki")),
    hasCuratorConfig: fs.existsSync(path.join(dir, ".curator", "config.json")),
    hasWikiGit: fs.existsSync(path.join(dir, "wiki", ".git")),
  };
}

function isWiki(dir: string): boolean {
  return looksLikeCeWorkspace(marks(dir));
}

function cePython(hint?: string): string {
  const cands: string[] = [];
  if (hint) {
    cands.push(path.join(hint, ".venv", "bin", "python"), path.join(hint, ".venv", "bin", "python3"));
  }
  const ce = ceRoot();
  if (ce) {
    cands.push(path.join(ce, ".venv", "bin", "python"), path.join(ce, ".venv", "bin", "python3"));
  }
  return cands.find((p) => fs.existsSync(p)) || "python3";
}

function codeRepoScript(): string | undefined {
  const ce = ceRoot();
  if (!ce) return undefined;
  const s = path.join(ce, "scripts", "code_repo.py");
  return fs.existsSync(s) ? s : undefined;
}

function runCodeRepo(
  args: string[],
  opts?: { cwd?: string; stdin?: string },
): { status: number; stdout: string; stderr: string } {
  const script = codeRepoScript();
  if (!script) return { status: 1, stdout: "", stderr: "curiosity-engine code_repo.py not found" };
  const r = spawnSync(cePython(opts?.cwd), [script, ...args], {
    cwd: opts?.cwd,
    encoding: "utf8",
    timeout: 15000,
    windowsHide: true,
    input: opts?.stdin,
  });
  return {
    status: r.status ?? 1,
    stdout: r.stdout || "",
    stderr: (r.stderr || r.error?.message || "").trim(),
  };
}

export function recentWikis(context: vscode.ExtensionContext): string[] {
  const raw = context.globalState.get<string[]>(RECENT_KEY) || [];
  return raw.filter((p) => p && isWiki(p));
}

export async function rememberWiki(context: vscode.ExtensionContext, wiki: string): Promise<void> {
  const next = [path.resolve(wiki), ...recentWikis(context).filter((p) => path.resolve(p) !== path.resolve(wiki))];
  await context.globalState.update(RECENT_KEY, next.slice(0, 8));
}

function defaultWikiCandidates(context: vscode.ExtensionContext): string[] {
  const out: string[] = [];
  const add = (p?: string) => {
    if (!p) return;
    const r = path.resolve(expandHome(p));
    if (isWiki(r) && !out.includes(r)) out.push(r);
  };
  add(wikiFsPath());
  for (const p of recentWikis(context)) add(p);
  add(process.env.CURIOSITY_WORKSPACE);
  add(path.join(os.homedir(), "Documents", "curiosity-workspace"));
  add(path.join(os.homedir(), "curiosity-workspace"));
  return out;
}

function expandHome(p: string): string {
  if (p === "~") return os.homedir();
  if (p.startsWith("~/")) return os.homedir() + p.slice(1);
  return p;
}

async function pickExistingWiki(context: vscode.ExtensionContext): Promise<string | undefined> {
  const known = defaultWikiCandidates(context);
  const items: Array<vscode.QuickPickItem & { wiki?: string }> = known.map((p) => ({
    label: path.basename(p),
    description: p,
    wiki: p,
  }));
  items.push({ label: "Browse for a wiki folder…", description: "Folder that contains wiki/" });
  const pick = await vscode.window.showQuickPick(items, {
    title: "Which shared wiki should this folder use?",
    placeHolder: "One wiki, many code/docs folders",
  });
  if (!pick) return undefined;
  if (pick.wiki) return pick.wiki;
  const browsed = await vscode.window.showOpenDialog({
    canSelectFiles: false,
    canSelectFolders: true,
    canSelectMany: false,
    openLabel: "Use as wiki",
    title: "Switch Bay wiki folder (contains wiki/)",
  });
  const dir = browsed?.[0]?.fsPath;
  if (!dir) return undefined;
  if (!isWiki(dir)) {
    void vscode.window.showWarningMessage("That folder is not a curiosity-engine wiki (no wiki/ or .curator/).");
    return undefined;
  }
  return dir;
}

function writePointer(codeDir: string, wiki: string, project: string): { ok: boolean; text: string } {
  const pointer = path.join(codeDir, ".curiosity", "config.toml");
  const cfg = {
    workspace: wiki,
    project,
    project_kind: fs.existsSync(path.join(codeDir, ".git")) ? "code" : "documents",
    code_citation_root: project,
    ingest: {
      enabled: true,
      paths: ["README.md", "CHANGELOG.md", "docs/"],
      pr_capture: true,
      commit_capture: true,
      transcript_capture: true,
    },
    brief: { auto: true, regenerate_on_pull: false },
  };
  const w = runCodeRepo(["write-config", pointer], { stdin: JSON.stringify(cfg) + "\n" });
  if (w.status !== 0) {
    try {
      fs.mkdirSync(path.dirname(pointer), { recursive: true });
      const toml = [
        `workspace = "${wiki.replace(/\\/g, "/")}"`,
        `project = "${project}"`,
        `project_kind = "${cfg.project_kind}"`,
        `code_citation_root = "${project}"`,
        "",
        "[ingest]",
        "enabled = true",
        'paths = ["README.md", "CHANGELOG.md", "docs/"]',
        "",
        "[brief]",
        "auto = true",
        "",
      ].join("\n");
      fs.writeFileSync(pointer, toml, "utf8");
    } catch (err) {
      return { ok: false, text: w.stderr || String(err) };
    }
  }
  const reg = runCodeRepo(
    ["register-project-dir", wiki, "--path", codeDir, "--project", project],
    { cwd: wiki },
  );
  if (reg.status !== 0) {
    return { ok: false, text: reg.stderr || "register-project-dir failed" };
  }
  ignoreSessionBrief(codeDir);
  return { ok: true, text: pointer };
}

function ignoreSessionBrief(codeDir: string): void {
  const exclude = path.join(codeDir, ".git", "info", "exclude");
  if (!fs.existsSync(path.dirname(exclude))) return;
  const line = ".curiosity/session-brief.md";
  let cur = "";
  try { cur = fs.readFileSync(exclude, "utf8"); } catch { /* empty */ }
  if (cur.includes(line)) return;
  try {
    fs.appendFileSync(exclude, (cur.endsWith("\n") || !cur ? "" : "\n") + line + "\n", "utf8");
  } catch { /* ignore */ }
}

async function askProjectName(folder: string): Promise<string | undefined> {
  const value = path.basename(folder).replace(/[^A-Za-z0-9._-]+/g, "-") || "project";
  return vscode.window.showInputBox({
    title: "Project tag on wiki pages from this folder",
    prompt: "Short name (frontmatter `project:`). Defaults to the folder name.",
    value,
  });
}

/**
 * Wiki window: pick a code/docs folder to attach.
 * Code/docs window: pick a wiki and attach this Explorer folder.
 */
export async function registerOpenFolder(context: vscode.ExtensionContext): Promise<void> {
  const folder = workspaceFsPath();
  if (!folder) {
    void vscode.window.showWarningMessage("Open a folder first.");
    return;
  }
  const res = resolveWiki(folder);
  if (res.mode === "wiki-native" && res.wikiRoot) {
    await registerOtherFoldersIntoWiki(context, res.wikiRoot);
    return;
  }
  await registerThisFolder(context, folder, res.wikiRoot);
}

async function registerOtherFoldersIntoWiki(
  context: vscode.ExtensionContext,
  wiki: string,
): Promise<void> {
  const picked = await vscode.window.showOpenDialog({
    canSelectFiles: false,
    canSelectFolders: true,
    canSelectMany: true,
    openLabel: "Link to this wiki",
    title: "Code or docs folders to capture into this wiki",
  });
  if (!picked?.length) return;
  await rememberWiki(context, wiki);
  const names: string[] = [];
  for (const uri of picked) {
    if (isWiki(uri.fsPath)) {
      void vscode.window.showWarningMessage(`Skipped ${path.basename(uri.fsPath)} — that folder is itself a wiki.`);
      continue;
    }
    const project = await askProjectName(uri.fsPath);
    if (project === undefined) return;
    const result = writePointer(uri.fsPath, wiki, project.trim() || path.basename(uri.fsPath));
    if (!result.ok) {
      void vscode.window.showErrorMessage(`Could not register ${uri.fsPath}: ${result.text}`);
      return;
    }
    names.push(project.trim() || path.basename(uri.fsPath));
  }
  invalidateWikiRootCache();
  void vscode.window.showInformationMessage(
    names.length
      ? `Linked ${names.join(", ")} to ${path.basename(wiki)}. Open those folders in other VS Code windows to work; click SBH when you want wiki Chat.`
      : "Nothing linked.",
  );
}

async function registerThisFolder(
  context: vscode.ExtensionContext,
  folder: string,
  currentWiki?: string,
): Promise<void> {
  if (currentWiki) {
    const keep = await vscode.window.showQuickPick(
      [
        { label: `Keep ${path.basename(currentWiki)}`, description: currentWiki, id: "keep" },
        { label: "Choose a different wiki…", id: "change" },
      ],
      { title: "This folder is already linked" },
    );
    if (!keep || keep.id === "keep") return;
  }
  const wiki = await pickExistingWiki(context);
  if (!wiki) return;
  if (path.resolve(wiki) === path.resolve(folder)) {
    void vscode.window.showWarningMessage("That is this folder. Open a code/docs repo to register, or link folders from the wiki window.");
    return;
  }
  const project = await askProjectName(folder);
  if (project === undefined) return;
  const result = writePointer(folder, wiki, project.trim() || path.basename(folder));
  if (!result.ok) {
    void vscode.window.showErrorMessage(`Register failed: ${result.text}`);
    return;
  }
  await rememberWiki(context, wiki);
  await vscode.workspace.getConfiguration("switchbay").update(
    "wikiRoot",
    wiki,
    vscode.ConfigurationTarget.Workspace,
  );
  await setKnowledgeHarness(false);
  invalidateWikiRootCache();
  void vscode.window.showInformationMessage(
    `Registered ${path.basename(folder)} → ${path.basename(wiki)}. SBH is off so coding Chat stays on this repo. Click the SBH pill to turn wiki tools on.`,
  );
}

export { parseSbhArg };

export async function chooseKnowledgeHarness(): Promise<boolean | undefined> {
  const on = knowledgeHarnessOn();
  const pick = await vscode.window.showQuickPick(
    [
      {
        label: "SBH on",
        description: "@switchbay, Curator, and wiki MCP join Chat in this window",
        picked: on,
        value: true,
      },
      {
        label: "SBH off",
        description: "Coding Chat only — wiki tools stay out of this window",
        picked: !on,
        value: false,
      },
    ],
    { title: "Switch Bay knowledge harness (this window)" },
  );
  if (!pick) return undefined;
  await setKnowledgeHarness(pick.value);
  return pick.value;
}
