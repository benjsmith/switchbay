/**
 * Wiki file browser (PWA Files pane equivalent). Shows the attached
 * wiki's on-disk tree so graph-search hits — pages and vault sources —
 * are visible even when the Explorer is a code repo.
 */
import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";
import { dirContainsHit, normalizeRel, relIsHit, withWikiPrefix } from "./searchHits";
import { wikiDisplayName, wikiFsPath } from "./wikiRoot";

const SKIP_DIRS = new Set([
  ".git",
  ".workbench",
  "node_modules",
  ".venv",
  "venv",
  "__pycache__",
  "dist",
  "build",
  ".vite",
  ".cache",
  ".idea",
  ".vscode",
  ".pytest_cache",
]);

export class FileItem extends vscode.TreeItem {
  parent?: FileItem;

  constructor(
    public readonly absPath: string,
    public readonly relPath: string,
    public readonly isDir: boolean,
  ) {
    super(
      relPath ? path.basename(absPath) : (wikiDisplayName() || path.basename(absPath)),
      isDir
        ? vscode.TreeItemCollapsibleState.Collapsed
        : vscode.TreeItemCollapsibleState.None,
    );
    this.id = relPath ? `file:${relPath}` : "switchbay.files-root";
    this.resourceUri = vscode.Uri.file(absPath);
    this.contextValue = isDir ? "switchbay.dir" : "switchbay.file";
    this.tooltip = relPath || absPath;
    if (!isDir) {
      this.command = {
        command: "vscode.open",
        title: "Open",
        arguments: [this.resourceUri],
      };
    }
  }
}

export class FilesTreeProvider implements vscode.TreeDataProvider<FileItem> {
  private _onDidChange = new vscode.EventEmitter<FileItem | undefined>();
  readonly onDidChangeTreeData = this._onDidChange.event;
  private hits = new Set<string>();
  private pages = new Set<string>();
  private pendingReveal: string | undefined;
  treeView?: vscode.TreeView<FileItem>;

  refresh(): void {
    this._onDidChange.fire(undefined);
  }

  setSearch(pagePaths: string[], sourcePaths: string[] = []): void {
    this.pages = new Set(pagePaths.map(normalizeRel).filter(Boolean));
    this.hits = new Set(
      [...pagePaths, ...sourcePaths].map(normalizeRel).filter(Boolean),
    );
    this.pendingReveal = pagePaths[0];
    this._onDidChange.fire(undefined);
  }

  getTreeItem(element: FileItem): FileItem {
    return element;
  }

  getParent(element: FileItem): FileItem | undefined {
    if (!element.relPath) return undefined;
    const root = wikiFsPath();
    if (!root) return undefined;
    const parentRel = normalizeRel(path.posix.dirname(element.relPath).replace(/\\/g, "/"));
    if (!parentRel || parentRel === ".") {
      return this.ensureRoot(root);
    }
    return new FileItem(path.join(root, parentRel), parentRel, true);
  }

  getChildren(element?: FileItem): FileItem[] {
    const rootPath = wikiFsPath();
    if (!rootPath) return [];
    if (!element) {
      const root = this.ensureRoot(rootPath);
      root.collapsibleState = vscode.TreeItemCollapsibleState.Expanded;
      return [root];
    }
    const dir = element.absPath;
    let entries: fs.Dirent[] = [];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return [];
    }
    const kids: FileItem[] = [];
    for (const ent of entries) {
      if (ent.name.startsWith(".")) continue;
      if (ent.isDirectory() && SKIP_DIRS.has(ent.name)) continue;
      if (!ent.isDirectory() && !ent.isFile()) continue;
      const abs = path.join(dir, ent.name);
      const rel = normalizeRel(path.relative(rootPath, abs));
      const item = new FileItem(abs, rel, ent.isDirectory());
      item.parent = element;
      this.paintHit(item);
      kids.push(item);
    }
    kids.sort((a, b) => {
      if (a.isDir !== b.isDir) return a.isDir ? -1 : 1;
      return a.label === b.label
        ? 0
        : String(a.label).localeCompare(String(b.label));
    });
    if (element.relPath === "") this.scheduleReveal();
    return kids;
  }

  private ensureRoot(rootPath: string): FileItem {
    const root = new FileItem(rootPath, "", true);
    root.collapsibleState = vscode.TreeItemCollapsibleState.Expanded;
    return root;
  }

  private paintHit(item: FileItem): void {
    if (this.hits.size === 0) return;
    if (item.isDir) {
      if (dirContainsHit(item.relPath, this.pages.size ? this.pages : this.hits)) {
        item.collapsibleState = vscode.TreeItemCollapsibleState.Expanded;
      }
      return;
    }
    if (relIsHit(item.relPath, this.hits) || relIsHit(withWikiPrefix(item.relPath), this.hits)) {
      item.description = "match";
      item.iconPath = new vscode.ThemeIcon("target");
    }
  }

  private scheduleReveal(): void {
    const rel = this.pendingReveal;
    const view = this.treeView;
    const rootPath = wikiFsPath();
    if (!rel || !view || !rootPath) return;
    this.pendingReveal = undefined;
    const rooted = withWikiPrefix(rel);
    const abs = path.join(rootPath, rooted.replace(/\//g, path.sep));
    const item = new FileItem(abs, rooted, false);
    const parentRel = normalizeRel(path.posix.dirname(rooted));
    if (parentRel && parentRel !== ".") {
      item.parent = new FileItem(path.join(rootPath, parentRel), parentRel, true);
      item.parent.parent = this.ensureRoot(rootPath);
    } else {
      item.parent = this.ensureRoot(rootPath);
    }
    queueMicrotask(() => {
      void view.reveal(item, { select: true, focus: false, expand: 3 });
    });
  }
}
