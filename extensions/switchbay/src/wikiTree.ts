import * as vscode from "vscode";
import { readCachedGraph, scanWikiMarkdown, wikiPageUri, type GraphNode } from "./ce";
import { workspaceFolder } from "./paths";

export class WikiPageItem extends vscode.TreeItem {
  constructor(public readonly node: GraphNode, folder: vscode.Uri) {
    super(node.title || node.id, vscode.TreeItemCollapsibleState.None);
    this.resourceUri = wikiPageUri(folder, node.path);
    this.tooltip = node.path;
    this.description = node.id;
    this.contextValue = "switchbay.page";
    this.command = {
      command: "switchbay.openPage",
      title: "Open",
      arguments: [node],
    };
    this.iconPath = new vscode.ThemeIcon("file");
  }
}

class TypeGroupItem extends vscode.TreeItem {
  constructor(public readonly type: string, public readonly children: WikiPageItem[]) {
    super(type, vscode.TreeItemCollapsibleState.Collapsed);
    this.description = String(children.length);
    this.contextValue = "switchbay.type";
    this.iconPath = new vscode.ThemeIcon("folder");
  }
}

export class WikiTreeProvider implements vscode.TreeDataProvider<vscode.TreeItem> {
  private _onDidChange = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this._onDidChange.event;

  refresh(): void {
    this._onDidChange.fire();
  }

  getTreeItem(element: vscode.TreeItem): vscode.TreeItem {
    return element;
  }

  getChildren(element?: vscode.TreeItem): vscode.TreeItem[] {
    const folder = workspaceFolder();
    if (!folder) return [];
    if (element instanceof TypeGroupItem) return element.children;
    if (element) return [];

    const graph = readCachedGraph(folder.fsPath);
    const nodes = graph?.nodes?.length ? graph.nodes : scanWikiMarkdown(folder.fsPath);
    const groups = new Map<string, GraphNode[]>();
    for (const n of nodes) {
      const t = (n.type || "unclassified").toLowerCase();
      const list = groups.get(t) ?? [];
      list.push(n);
      groups.set(t, list);
    }
    const keys = [...groups.keys()].sort((a, b) => a.localeCompare(b));
    return keys.map((k) => {
      const items = (groups.get(k) ?? [])
        .slice()
        .sort((a, b) => (a.title || a.id).localeCompare(b.title || b.id))
        .map((n) => new WikiPageItem(n, folder));
      return new TypeGroupItem(k, items);
    });
  }
}
