import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";
import { parseWikiFrontmatter } from "./ce";
import { nextWikiPlacement, previewButtonPlacement, PREVIEW_TYPE } from "./layout";
import { workspaceFolder } from "./paths";

const WIKILINK_RE = /\[\[([^\]|]+?)(?:\|([^\]]+))?\]\]/g;

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c] as string
  ));
}

function expandWikilinks(md: string): string {
  return md.replace(WIKILINK_RE, (_full, target: string, display?: string) => {
    const raw = target.trim();
    const text = (display ?? target).trim();
    const show = raw.match(/^slideshow:(.+)$/i);
    if (show) {
      return `<a class="wikilink wikilink--slideshow" data-slideshow="${escapeHtml(show[1].trim())}" href="#">${escapeHtml(text)}</a>`;
    }
    const rep = raw.match(/^report:(.+)$/i);
    if (rep) {
      return `<a class="wikilink wikilink--report" data-report="${escapeHtml(rep[1].trim())}" href="#">${escapeHtml(text)}</a>`;
    }
    const slug = raw.toLowerCase().replace(/\s+/g, "-");
    return `<a class="wikilink" data-page="${escapeHtml(slug)}" href="#">${escapeHtml(text)}</a>`;
  });
}

/** Tiny markdown subset: headings, tables, images, code, paragraphs. */
function renderMarkdown(md: string): string {
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  const out: string[] = [];
  let i = 0;
  const flushPara = (buf: string[]) => {
    if (!buf.length) return;
    out.push(`<p>${buf.join(" ")}</p>`);
    buf.length = 0;
  };
  const para: string[] = [];
  while (i < lines.length) {
    const line = lines[i] ?? "";
    if (line.startsWith("```")) {
      flushPara(para);
      const lang = escapeHtml(line.slice(3).trim());
      const code: string[] = [];
      i++;
      while (i < lines.length && !(lines[i] ?? "").startsWith("```")) {
        code.push(lines[i] ?? "");
        i++;
      }
      out.push(`<pre><code class="${lang}">${escapeHtml(code.join("\n"))}</code></pre>`);
      i++;
      continue;
    }
    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) {
      flushPara(para);
      const n = h[1].length;
      out.push(`<h${n}>${h[2]}</h${n}>`);
      i++;
      continue;
    }
    if (line.includes("|") && i + 1 < lines.length && /^\s*\|?[\s:|-]+\|/.test(lines[i + 1] ?? "")) {
      flushPara(para);
      const rows: string[][] = [];
      while (i < lines.length && (lines[i] ?? "").includes("|")) {
        const cells = (lines[i] ?? "").split("|").slice(1, -1).map((c) => c.trim());
        if (!/^[\s:|-]+$/.test((lines[i] ?? "").replace(/\|/g, ""))) rows.push(cells);
        i++;
        if (i < lines.length && !(lines[i] ?? "").includes("|")) break;
      }
      if (rows.length) {
        const head = rows[0]!;
        const body = rows.slice(1);
        out.push(
          "<table><thead><tr>"
          + head.map((c) => `<th>${c}</th>`).join("")
          + "</tr></thead><tbody>"
          + body.map((r) => "<tr>" + r.map((c) => `<td>${c}</td>`).join("") + "</tr>").join("")
          + "</tbody></table>",
        );
      }
      continue;
    }
    if (/^!\[/.test(line)) {
      flushPara(para);
      const m = line.match(/^!\[([^\]]*)\]\(([^)]+)\)/);
      if (m) out.push(`<img alt="${escapeHtml(m[1])}" data-src="${escapeHtml(m[2])}" />`);
      i++;
      continue;
    }
    if (!line.trim()) {
      flushPara(para);
      i++;
      continue;
    }
    para.push(line.trim());
    i++;
  }
  flushPara(para);
  return out.join("\n");
}

function nonce(): string {
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  let s = "";
  for (let i = 0; i < 32; i++) s += chars[Math.floor(Math.random() * chars.length)];
  return s;
}

const previewPanels = new Set<vscode.WebviewPanel>();

function panelInColumn(column: vscode.ViewColumn): vscode.WebviewPanel | undefined {
  for (const p of previewPanels) {
    if (p.viewColumn === column) return p;
  }
  return [...previewPanels].find((p) => p.visible);
}

function sourceAnchor(raw: string): string {
  const label = path.basename(raw);
  return `<a class="source-link" href="#" data-source="${escapeHtml(raw)}">${escapeHtml(label)}</a>`;
}

function propertiesTable(properties: Record<string, string>, lists: Record<string, string[]>): string {
  const keys = new Set([...Object.keys(properties), ...Object.keys(lists)]);
  keys.delete("title");
  const rows: string[] = [];
  for (const k of keys) {
    const items = lists[k]?.length ? lists[k] : (properties[k] ? [properties[k]] : []);
    if (!items.length) continue;
    const isPathish = k === "sources" || k === "relates_to" || items.some((v) => /\.(md|pdf|png|jpg)$/i.test(v) || v.startsWith("vault:"));
    const cell = isPathish
      ? `<div class="source-list">${items.map(sourceAnchor).join("")}</div>`
      : escapeHtml(items.join(", "));
    rows.push(`<tr><td class="k">${escapeHtml(k)}</td><td class="v">${cell}</td></tr>`);
  }
  return rows.length ? `<section class="properties"><table>${rows.join("")}</table></section>` : "";
}

function expandVaultCites(html: string): string {
  return html.replace(/\(vault:([^)]+)\)/g, (_m, raw: string) => {
    const p = String(raw).trim();
    return `(vault:${sourceAnchor(p)})`;
  });
}

async function paintPreview(
  panel: vscode.WebviewPanel,
  docUri: vscode.Uri,
  folder: vscode.Uri,
): Promise<void> {
  const doc = await vscode.workspace.openTextDocument(docUri);
  const { properties, lists, body } = parseWikiFrontmatter(doc.getText());
  let htmlBody = renderMarkdown(expandWikilinks(body));
  htmlBody = expandVaultCites(htmlBody);
  htmlBody = htmlBody.replace(
    /<img alt="([^"]*)" data-src="([^"]+)" \/>/g,
    (_m, alt: string, src: string) => {
      const rel = src.replace(/^\.\//, "");
      try {
        const web = panel.webview.asWebviewUri(vscode.Uri.joinPath(folder, rel));
        return `<img alt="${alt}" src="${web}" />`;
      } catch {
        return `<img alt="${alt}" />`;
      }
    },
  );
  const n = nonce();
  const csp = [
    `default-src 'none'`,
    `style-src ${panel.webview.cspSource} 'unsafe-inline'`,
    `img-src ${panel.webview.cspSource} data: https:`,
    `script-src 'nonce-${n}'`,
  ].join("; ");
  panel.title = `Preview: ${path.basename(docUri.fsPath)}`;
  panel.webview.html = `<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8" />
<meta http-equiv="Content-Security-Policy" content="${csp}" />
<style>
  body { font-family: var(--vscode-font-family); padding: 1.5rem 2rem; color: var(--vscode-foreground); }
  a.wikilink, a.source-link { color: var(--vscode-textLink-foreground); cursor: pointer; }
  a.source-link { display: block; margin: 0.15rem 0; }
  table { border-collapse: collapse; margin: 1rem 0; }
  th, td { border: 1px solid var(--vscode-widget-border, #444); padding: 0.25rem 0.6rem; vertical-align: top; }
  .properties { margin-bottom: 1.5rem; }
  .k { opacity: 0.7; }
  img { max-width: 100%; }
  pre { background: var(--vscode-textCodeBlock-background); padding: 0.8rem; overflow: auto; }
  .ctx { position: fixed; background: var(--vscode-menu-background); color: var(--vscode-menu-foreground);
         border: 1px solid var(--vscode-menu-border, #444); padding: 0.2rem 0; z-index: 10; }
  .ctx button { display: block; width: 100%; text-align: left; background: none; border: 0; color: inherit;
                padding: 0.3rem 0.8rem; cursor: pointer; font: inherit; }
  .ctx button:hover { background: var(--vscode-menu-selectionBackground); }
</style>
</head>
<body>
  <h1>${escapeHtml(properties.title || path.basename(docUri.fsPath, ".md"))}</h1>
  ${propertiesTable(properties, lists)}
  <article class="md">${htmlBody}</article>
  <div id="ctx" class="ctx" hidden></div>
  <script nonce="${n}">
    const vscode = acquireVsCodeApi();
    document.addEventListener("click", (ev) => {
      const a = ev.target.closest("a.wikilink, a.source-link");
      if (!a) { document.getElementById("ctx").hidden = true; return; }
      ev.preventDefault();
      if (a.classList.contains("source-link")) {
        vscode.postMessage({ type: "source", action: "open", path: a.dataset.source || "" });
        return;
      }
      vscode.postMessage({
        type: "wikilink",
        page: a.dataset.page || "",
        slideshow: a.dataset.slideshow || "",
        report: a.dataset.report || "",
      });
    });
    document.addEventListener("contextmenu", (ev) => {
      const a = ev.target.closest("a.source-link");
      if (!a) return;
      ev.preventDefault();
      const menu = document.getElementById("ctx");
      menu.hidden = false;
      menu.style.left = ev.pageX + "px";
      menu.style.top = ev.pageY + "px";
      menu.innerHTML = "";
      const src = a.dataset.source || "";
      for (const [label, action] of [
        ["Open", "open"],
        ["Reveal in Explorer", "reveal"],
        ["Reveal in OS", "revealOS"],
      ]) {
        const b = document.createElement("button");
        b.textContent = label;
        b.onclick = () => { vscode.postMessage({ type: "source", action, path: src }); menu.hidden = true; };
        menu.appendChild(b);
      }
    });
  </script>
</body>
</html>`;
}

function bindPreviewMessages(panel: vscode.WebviewPanel, folder: vscode.Uri): void {
  panel.webview.onDidReceiveMessage(async (msg: {
    type?: string; page?: string; slideshow?: string; report?: string; action?: string; path?: string;
  }) => {
    if (msg.type === "wikilink") {
      if (msg.slideshow) {
        const deck = vscode.Uri.joinPath(folder, "slideshows", msg.slideshow, "index.html");
        await vscode.commands.executeCommand("switchbay.openHtml", deck);
        return;
      }
      if (msg.page) {
        const guess = wikiGuess(folder, msg.page);
        if (guess) await openWikiPage(guess);
      }
      return;
    }
    if (msg.type === "source" && msg.path) {
      await handleSourceAction(folder, msg.action || "open", msg.path);
    }
  });
}

async function showPreviewInColumn(docUri: vscode.Uri, column: vscode.ViewColumn, preserveFocus: boolean): Promise<void> {
  const folder = workspaceFolder();
  if (!folder) return;
  let panel = panelInColumn(column);
  if (!panel) {
    panel = vscode.window.createWebviewPanel(
      PREVIEW_TYPE,
      `Preview: ${path.basename(docUri.fsPath)}`,
      { viewColumn: column, preserveFocus },
      { enableScripts: true, retainContextWhenHidden: true, localResourceRoots: [folder] },
    );
    previewPanels.add(panel);
    panel.onDidDispose(() => previewPanels.delete(panel!));
    bindPreviewMessages(panel, folder);
  } else {
    panel.reveal(column, preserveFocus);
  }
  await paintPreview(panel, docUri, folder);
}

/** Wiki tree / graph / wikilink: respect the current split layout. */
export async function openWikiPage(uri: vscode.Uri): Promise<void> {
  const place = nextWikiPlacement();
  if (place.md != null) {
    await vscode.window.showTextDocument(uri, {
      viewColumn: place.md,
      preview: true,
      preserveFocus: false,
    });
  }
  if (place.preview != null) {
    await showPreviewInColumn(uri, place.preview, place.md != null);
  }
}

export async function openWikiPreview(uri?: vscode.Uri): Promise<void> {
  const docUri = uri ?? vscode.window.activeTextEditor?.document.uri;
  if (!docUri) {
    void vscode.window.showWarningMessage("Open a markdown file first.");
    return;
  }
  const place = previewButtonPlacement();
  const column = place.preview ?? vscode.ViewColumn.Beside;
  await showPreviewInColumn(docUri, column, false);
}

function wikiGuess(folder: vscode.Uri, slug: string): vscode.Uri | undefined {
  const trimmed = slug.replace(/^wiki\//, "").replace(/\.md$/i, "");
  const candidates = [
    `wiki/${trimmed}.md`,
    `wiki/${trimmed}`,
    `${trimmed}.md`,
  ];
  for (const rel of candidates) {
    const uri = vscode.Uri.joinPath(folder, rel);
    if (fs.existsSync(uri.fsPath)) return uri;
  }
  return vscode.Uri.joinPath(folder, "wiki", `${trimmed}.md`);
}

function resolveSourceUri(folder: vscode.Uri, raw: string): vscode.Uri {
  const cleaned = raw.replace(/^["']|["']$/g, "").replace(/^vault:/, "").replace(/^\.\//, "");
  const base = path.basename(cleaned);
  const cands = [
    path.isAbsolute(cleaned) ? cleaned : "",
    path.join(folder.fsPath, cleaned),
    path.join(folder.fsPath, "vault", cleaned),
    path.join(folder.fsPath, "vault", base),
    path.join(folder.fsPath, "wiki", cleaned),
    path.join(folder.fsPath, "wiki", base),
  ].filter(Boolean);
  for (const p of cands) {
    if (fs.existsSync(p)) return vscode.Uri.file(p);
  }
  return vscode.Uri.joinPath(folder, "vault", base);
}

async function handleSourceAction(folder: vscode.Uri, action: string, raw: string): Promise<void> {
  const cleaned = raw.replace(/^["']|["']$/g, "");
  if (/^https?:\/\//.test(cleaned)) {
    await vscode.env.openExternal(vscode.Uri.parse(cleaned));
    return;
  }
  const uri = resolveSourceUri(folder, cleaned);
  if (action === "revealOS") {
    await vscode.commands.executeCommand("revealFileInOS", uri);
    return;
  }
  if (action === "reveal") {
    await vscode.commands.executeCommand("revealInExplorer", uri);
    return;
  }
  try {
    await vscode.window.showTextDocument(uri, { preview: true });
  } catch {
    await vscode.env.openExternal(uri);
  }
}
