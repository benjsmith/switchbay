import * as vscode from "vscode";
import { readCachedGraph, wikiPageUri, type GraphNode } from "./ce";
import { wikiFolderUri } from "./wikiRoot";

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

/** Explorer / wiki-tree badge for graph-search hits. */
export class WikiSearchDecorations implements vscode.FileDecorationProvider {
  private readonly _onDidChange = new vscode.EventEmitter<vscode.Uri | vscode.Uri[] | undefined>();
  readonly onDidChangeFileDecorations = this._onDidChange.event;
  private hits = new Set<string>();

  setHits(fsPaths: string[]): void {
    this.hits = new Set(fsPaths);
    this._onDidChange.fire(undefined);
  }

  provideFileDecoration(uri: vscode.Uri): vscode.FileDecoration | undefined {
    if (!this.hits.has(uri.fsPath)) return undefined;
    return {
      badge: "●",
      tooltip: "Graph search match",
      color: new vscode.ThemeColor("list.highlightForeground"),
      // Carry the badge up to enclosing folders so a hit is findable in
      // the Explorer without expanding wiki/ and vault/ by hand.
      propagate: true,
    };
  }
}

export class WikiTreeProvider implements vscode.TreeDataProvider<vscode.TreeItem> {
  private _onDidChange = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this._onDidChange.event;
  /** Relative wiki/… paths currently highlighted by graph search. */
  private searchRel = new Set<string>();

  refresh(): void {
    this._onDidChange.fire();
  }

  setSearchPaths(relPaths: string[]): void {
    this.searchRel = new Set(relPaths.map((p) => p.replace(/^\.\//, "")));
    this._onDidChange.fire();
  }

  private pathIsHit(nodePath: string): boolean {
    if (this.searchRel.size === 0) return false;
    const rel = nodePath.replace(/^\.\//, "");
    const withWiki = rel.startsWith("wiki/") ? rel : `wiki/${rel}`;
    const without = withWiki.slice("wiki/".length);
    return this.searchRel.has(rel)
      || this.searchRel.has(withWiki)
      || this.searchRel.has(without);
  }

  getTreeItem(element: vscode.TreeItem): vscode.TreeItem {
    return element;
  }

  getChildren(element?: vscode.TreeItem): vscode.TreeItem[] {
    const folder = wikiFolderUri();
    if (!folder) return [];
    if (element instanceof TypeGroupItem) return element.children;
    if (element) return [];

    // Same WikiPage set as the graph webview (graph.kuzu). Markdown on
    // disk is harvested into kuzu by Refresh / graph.py rebuild, not here.
    let nodes: GraphNode[] = [];
    try {
      nodes = readCachedGraph(folder.fsPath)?.nodes ?? [];
    } catch (err) {
      console.log("[switchbay] wiki tree graph read failed", err);
      return [];
    }
    const groups = new Map<string, GraphNode[]>();
    for (const n of nodes) {
      const t = (n.type || "unclassified").toLowerCase();
      const list = groups.get(t) ?? [];
      list.push(n);
      groups.set(t, list);
    }
    const keys = [...groups.keys()].sort((a, b) => a.localeCompare(b));
    return keys.map((k) => {
      const nodesOfType = (groups.get(k) ?? [])
        .slice()
        .sort((a, b) => (a.title || a.id).localeCompare(b.title || b.id));
      const items = nodesOfType.map((n) => {
        const item = new WikiPageItem(n, folder);
        if (this.pathIsHit(n.path)) {
          item.description = "match";
          item.iconPath = new vscode.ThemeIcon("target");
        }
        return item;
      });
      const group = new TypeGroupItem(k, items);
      if (this.searchRel.size > 0 && items.some((it) => it.description === "match")) {
        group.collapsibleState = vscode.TreeItemCollapsibleState.Expanded;
      }
      return group;
    });
  }
}
