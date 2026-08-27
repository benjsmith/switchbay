import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";
import { frontmatterMeta, readCachedGraph, wikiPageUri } from "./ce";
import { wikiFolderUri } from "./wikiRoot";

type PageRec = { path: string; title: string; type: string };

class PageItem extends vscode.TreeItem {
  constructor(rec: PageRec, folder: vscode.Uri) {
    super(rec.title, vscode.TreeItemCollapsibleState.None);
    this.resourceUri = vscode.Uri.joinPath(folder, rec.path);
    this.description = rec.type;
    this.command = {
      command: "vscode.open",
      title: "Open",
      arguments: [this.resourceUri],
    };
  }
}

class ProjectItem extends vscode.TreeItem {
  constructor(public readonly name: string, public readonly pages: PageRec[]) {
    super(name === "_general" ? "General" : name, vscode.TreeItemCollapsibleState.Collapsed);
    this.description = String(pages.length);
    this.iconPath = new vscode.ThemeIcon("project");
  }
}

export class ProjectsTreeProvider implements vscode.TreeDataProvider<vscode.TreeItem> {
  private _onDidChange = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this._onDidChange.event;

  refresh(): void {
    this._onDidChange.fire();
  }

  getTreeItem(element: vscode.TreeItem): vscode.TreeItem {
    return element;
  }

  getChildren(element?: vscode.TreeItem): vscode.TreeItem[] {
    const folder = wikiFolderUri();
    if (!folder) return [];
    if (element instanceof ProjectItem) {
      return element.pages.map((p) => new PageItem(p, folder));
    }
    if (element) return [];
    try {
      return this.scan(folder);
    } catch (err) {
      console.log("[switchbay] projects tree scan failed", err);
      return [];
    }
  }

  private scan(folder: vscode.Uri): ProjectItem[] {
    const tagged = new Map<string, PageRec[]>();
    const untagged: PageRec[] = [];
    const nodes = readCachedGraph(folder.fsPath)?.nodes ?? [];
    for (const n of nodes) {
      const uri = wikiPageUri(folder, n.path);
      let text = "";
      try {
        text = fs.readFileSync(uri.fsPath, "utf8");
      } catch {
        continue;
      }
      const meta = frontmatterMeta(text);
      const rec: PageRec = {
        path: path.relative(folder.fsPath, uri.fsPath).split(path.sep).join("/"),
        title: meta.title || n.title || n.id,
        type: meta.type || n.type || "unclassified",
      };
      const raw = meta.properties.projects || "";
      const names = [...raw.matchAll(/[A-Za-z][A-Za-z0-9-]*/g)].map((m) => m[0]);
      if (names.length) {
        for (const name of names) {
          const list = tagged.get(name) ?? [];
          list.push(rec);
          tagged.set(name, list);
        }
      } else if (rec.type === "note" || rec.type === "todo" || rec.type === "todo-list") {
        untagged.push(rec);
      }
    }
    const items = [...tagged.keys()].sort().map((n) => new ProjectItem(n, tagged.get(n) ?? []));
    if (untagged.length) items.push(new ProjectItem("_general", untagged));
    return items;
  }
}
