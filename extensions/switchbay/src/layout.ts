/**
 * Place wiki markdown + Switch Bay previews the way a split workspace
 * already looks. VS Code itself only reuses the *active* group's
 * preview tab (`workbench.editor.enablePreview`). Explorer never
 * creates a column; `ViewColumn.Beside` always does — that's why a
 * second wiki click next to an open preview spawned a third panel.
 */
import * as path from "path";
import * as vscode from "vscode";
import { workspaceFolder } from "./paths";

const PREVIEW_TYPE = "switchbay.preview";

let cycle = 0;

function isWikiMarkdownUri(uri: vscode.Uri): boolean {
  const folder = workspaceFolder();
  if (!folder) return uri.fsPath.endsWith(".md");
  const wiki = path.join(folder.fsPath, "wiki") + path.sep;
  return uri.fsPath.startsWith(wiki) && uri.fsPath.endsWith(".md");
}

function isWikiMdTab(tab: vscode.Tab): boolean {
  const input = tab.input;
  return input instanceof vscode.TabInputText && isWikiMarkdownUri(input.uri);
}

function isPreviewTab(tab: vscode.Tab): boolean {
  const input = tab.input;
  if (input instanceof vscode.TabInputWebview) {
    const vt = input.viewType;
    if (vt === PREVIEW_TYPE || vt.includes("switchbay.preview")) return true;
  }
  return tab.label.startsWith("Preview:");
}

function groupHas(group: vscode.TabGroup, pred: (t: vscode.Tab) => boolean): boolean {
  return group.tabs.some(pred);
}

function sortedGroups(): vscode.TabGroup[] {
  return [...vscode.window.tabGroups.all].sort(
    (a, b) => (a.viewColumn ?? 0) - (b.viewColumn ?? 0),
  );
}

export type WikiPlacement = {
  md?: vscode.ViewColumn;
  preview?: vscode.ViewColumn;
};

/** Columns that currently host wiki markdown / Switch Bay preview. */
export function wikiLanes(): { md: vscode.ViewColumn[]; preview: vscode.ViewColumn[] } {
  const md: vscode.ViewColumn[] = [];
  const preview: vscode.ViewColumn[] = [];
  for (const g of sortedGroups()) {
    const col = g.viewColumn;
    if (col == null) continue;
    if (groupHas(g, isWikiMdTab)) md.push(col);
    if (groupHas(g, isPreviewTab)) preview.push(col);
  }
  return { md, preview };
}

/**
 * Next place to put a wiki page opened from the tree / graph / wikilink.
 * - MD-only groups → cycle those columns, no preview.
 * - Preview-only groups → cycle those, no raw MD.
 * - Both (side-by-side or stacked pairs) → zip in viewColumn order and
 *   cycle pairs so the Nth open goes in the Nth MD + Nth preview.
 */
export function nextWikiPlacement(): WikiPlacement {
  const { md, preview } = wikiLanes();
  if (md.length && preview.length) {
    const n = Math.max(md.length, preview.length);
    const i = cycle++ % n;
    return { md: md[i % md.length], preview: preview[i % preview.length] };
  }
  if (md.length) {
    return { md: md[cycle++ % md.length] };
  }
  if (preview.length) {
    return { preview: preview[cycle++ % preview.length] };
  }
  return { md: vscode.window.activeTextEditor?.viewColumn ?? vscode.ViewColumn.Active };
}

/** Preview button: reuse an existing preview column, else split beside. */
export function previewButtonPlacement(): WikiPlacement {
  const { md, preview } = wikiLanes();
  const active = vscode.window.activeTextEditor?.viewColumn;
  if (preview.length) {
    if (md.length) {
      const idx = active != null ? Math.max(0, md.indexOf(active)) : 0;
      return { preview: preview[idx % preview.length] };
    }
    return { preview: preview[0] };
  }
  return { preview: vscode.ViewColumn.Beside };
}

export { PREVIEW_TYPE };
