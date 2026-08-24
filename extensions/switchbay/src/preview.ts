import * as path from "path";
import * as vscode from "vscode";
import { splitFrontmatter } from "./ce";
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

export async function openWikiPreview(uri?: vscode.Uri): Promise<void> {
  const target = uri
    ?? vscode.window.activeTextEditor?.document.uri
    ?? (vscode.window.activeTextEditor ? undefined : undefined);
  const docUri = target ?? vscode.window.activeTextEditor?.document.uri;
  if (!docUri) {
    void vscode.window.showWarningMessage("Open a markdown file first.");
    return;
  }
  const folder = workspaceFolder();
  if (!folder) return;
  const doc = await vscode.workspace.openTextDocument(docUri);
  const { properties, body } = splitFrontmatter(doc.getText());
  const htmlBody = renderMarkdown(expandWikilinks(body));
  const panel = vscode.window.createWebviewPanel(
    "switchbay.preview",
    `Preview: ${path.basename(docUri.fsPath)}`,
    vscode.ViewColumn.Beside,
    { enableScripts: true, localResourceRoots: [folder] },
  );

  const rewriteImgs = htmlBody.replace(
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

  const propRows = Object.entries(properties)
    .filter(([k]) => k !== "title")
    .map(([k, v]) => `<tr><td class="k">${escapeHtml(k)}</td><td class="v source" data-source="${escapeHtml(v)}">${escapeHtml(v)}</td></tr>`)
    .join("");

  panel.webview.html = `<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8" />
<meta http-equiv="Content-Security-Policy" content="${csp}" />
<style>
  body { font-family: var(--vscode-font-family); padding: 1.5rem 2rem; color: var(--vscode-foreground); }
  a.wikilink { color: var(--vscode-textLink-foreground); }
  table { border-collapse: collapse; margin: 1rem 0; }
  th, td { border: 1px solid var(--vscode-widget-border, #444); padding: 0.25rem 0.6rem; }
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
  ${propRows ? `<section class="properties"><table>${propRows}</table></section>` : ""}
  <article class="md">${rewriteImgs}</article>
  <div id="ctx" class="ctx" hidden></div>
  <script nonce="${n}">
    const vscode = acquireVsCodeApi();
    document.addEventListener("click", (ev) => {
      const a = ev.target.closest("a.wikilink");
      if (!a) return;
      ev.preventDefault();
      vscode.postMessage({
        type: "wikilink",
        page: a.dataset.page || "",
        slideshow: a.dataset.slideshow || "",
        report: a.dataset.report || "",
      });
    });
    document.addEventListener("contextmenu", (ev) => {
      const cell = ev.target.closest("td.source");
      if (!cell) return;
      ev.preventDefault();
      const menu = document.getElementById("ctx");
      menu.hidden = false;
      menu.style.left = ev.pageX + "px";
      menu.style.top = ev.pageY + "px";
      menu.innerHTML = "";
      const src = cell.dataset.source || "";
      for (const [label, action] of [
        ["Reveal in Explorer", "reveal"],
        ["Reveal in OS", "revealOS"],
        ["Open", "open"],
      ]) {
        const b = document.createElement("button");
        b.textContent = label;
        b.onclick = () => { vscode.postMessage({ type: "source", action, path: src }); menu.hidden = true; };
        menu.appendChild(b);
      }
    });
    document.addEventListener("click", () => { document.getElementById("ctx").hidden = true; });
  </script>
</body>
</html>`;

  panel.webview.onDidReceiveMessage(async (msg: { type?: string; page?: string; slideshow?: string; report?: string; action?: string; path?: string }) => {
    if (msg.type === "wikilink") {
      if (msg.slideshow) {
        const deck = vscode.Uri.joinPath(folder, "slideshows", msg.slideshow, "index.html");
        await vscode.commands.executeCommand("switchbay.openHtml", deck);
        return;
      }
      if (msg.page) {
        const guess = wikiGuess(folder, msg.page);
        if (guess) await vscode.window.showTextDocument(guess);
      }
      return;
    }
    if (msg.type === "source" && msg.path) {
      await handleSourceAction(folder, msg.action || "open", msg.path);
    }
  });
}

function wikiGuess(folder: vscode.Uri, slug: string): vscode.Uri | undefined {
  const candidates = [
    `wiki/${slug}.md`,
    `wiki/${slug}`,
    slug.endsWith(".md") ? slug : `${slug}.md`,
  ];
  for (const rel of candidates) {
    const uri = vscode.Uri.joinPath(folder, rel);
    try {
      return uri;
    } catch {
      continue;
    }
  }
  return vscode.Uri.joinPath(folder, "wiki", `${slug}.md`);
}

async function handleSourceAction(folder: vscode.Uri, action: string, raw: string): Promise<void> {
  const cleaned = raw.replace(/^["']|["']$/g, "");
  if (/^https?:\/\//.test(cleaned)) {
    await vscode.env.openExternal(vscode.Uri.parse(cleaned));
    return;
  }
  const rel = cleaned.replace(/^\/+/, "");
  const uri = path.isAbsolute(cleaned)
    ? vscode.Uri.file(cleaned)
    : vscode.Uri.joinPath(folder, rel);
  if (action === "revealOS") {
    await vscode.commands.executeCommand("revealFileInOS", uri);
    return;
  }
  if (action === "reveal") {
    await vscode.commands.executeCommand("revealInExplorer", uri);
    return;
  }
  try {
    await vscode.window.showTextDocument(uri);
  } catch {
    await vscode.env.openExternal(uri);
  }
}
