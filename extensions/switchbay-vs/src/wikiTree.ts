import * as vscode from "vscode";
import { readCachedGraph, wikiPageUri, type GraphNode } from "./ce";
import { relIsHit } from "./searchHits";
import { wikiDisplayName, wikiFolderUri } from "./wikiRoot";

export class WikiPageItem extends vscode.TreeItem {
  parentGroup?: TypeGroupItem;

  constructor(public readonly node: GraphNode, folder: vscode.Uri) {
    super(node.title || node.id, vscode.TreeItemCollapsibleState.None);
    this.id = `page:${node.path || node.id}`;
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
  parentRoot?: WikiNameItem;

  constructor(public readonly type: string, public readonly children: WikiPageItem[]) {
    super(type, vscode.TreeItemCollapsibleState.Collapsed);
    this.id = `type:${type}`;
    this.description = String(children.length);
    this.contextValue = "switchbay.type";
    this.iconPath = new vscode.ThemeIcon("folder");
  }
}

/** First row of the Wiki view — the attached wiki's folder name. */
export class WikiNameItem extends vscode.TreeItem {
  constructor(name: string, rootPath: string) {
    super(name, vscode.TreeItemCollapsibleState.Expanded);
    this.id = "switchbay.wiki-root";
    this.tooltip = rootPath;
    this.iconPath = new vscode.ThemeIcon("book");
    this.contextValue = "switchbay.wikiName";
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
  private _onDidChange = new vscode.EventEmitter<vscode.TreeItem | undefined>();
  readonly onDidChangeTreeData = this._onDidChange.event;
  /** Relative wiki/… paths currently highlighted by graph search. */
  private searchRel = new Set<string>();
  private pendingReveal: string | undefined;
  private pagesByPath = new Map<string, WikiPageItem>();
  treeView?: vscode.TreeView<vscode.TreeItem>;

  refresh(): void {
    this._onDidChange.fire(undefined);
  }

  setSearchPaths(relPaths: string[]): void {
    this.searchRel = new Set(relPaths.map((p) => p.replace(/^\.\//, "")));
    this.pendingReveal = relPaths[0];
    this._onDidChange.fire(undefined);
  }

  getTreeItem(element: vscode.TreeItem): vscode.TreeItem {
    return element;
  }

  getParent(element: vscode.TreeItem): vscode.TreeItem | undefined {
    if (element instanceof WikiPageItem) return element.parentGroup;
    if (element instanceof TypeGroupItem) return element.parentRoot;
    return undefined;
  }

  getChildren(element?: vscode.TreeItem): vscode.TreeItem[] {
    const folder = wikiFolderUri();
    if (!folder) return [];
    if (element instanceof TypeGroupItem) return element.children;
    if (element instanceof WikiNameItem) return this.typeGroups(folder, element);
    if (element) return [];

    const name = wikiDisplayName() || folder.fsPath.split(/[/\\]/).pop() || "wiki";
    return [new WikiNameItem(name, folder.fsPath)];
  }

  private typeGroups(folder: vscode.Uri, root: WikiNameItem): vscode.TreeItem[] {
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
    this.pagesByPath.clear();
    const keys = [...groups.keys()].sort((a, b) => a.localeCompare(b));
    const searching = this.searchRel.size > 0;
    const out = keys.map((k) => {
      const nodesOfType = (groups.get(k) ?? [])
        .slice()
        .sort((a, b) => (a.title || a.id).localeCompare(b.title || b.id));
      const items = nodesOfType.map((n) => {
        const item = new WikiPageItem(n, folder);
        if (relIsHit(n.path, this.searchRel)) {
          item.description = "match";
          item.iconPath = new vscode.ThemeIcon("target");
        }
        this.pagesByPath.set(n.path, item);
        return item;
      });
      const group = new TypeGroupItem(k, items);
      group.parentRoot = root;
      for (const it of items) it.parentGroup = group;
      if (searching && items.some((it) => it.description === "match")) {
        group.collapsibleState = vscode.TreeItemCollapsibleState.Expanded;
      }
      return group;
    });
    this.scheduleReveal();
    return out;
  }

  private scheduleReveal(): void {
    const rel = this.pendingReveal;
    const view = this.treeView;
    if (!rel || !view) return;
    this.pendingReveal = undefined;
    let target: WikiPageItem | undefined;
    for (const [p, item] of this.pagesByPath) {
      if (relIsHit(p, [rel]) || relIsHit(rel, [p])) {
        target = item;
        break;
      }
    }
    if (!target) return;
    queueMicrotask(() => {
      void view.reveal(target, { select: true, focus: false, expand: 3 });
    });
  }
}
