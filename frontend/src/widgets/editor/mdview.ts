/**
 * Light client-side markdown preprocessor for the editor preview, so
 * the live view matches CE's `#modal-body` (which is server-rendered
 * by `wiki_render.py`).
 *
 * Three transforms:
 *   1. Strip leading YAML frontmatter so it doesn't appear as body
 *      text — the parsed key/value pairs go into a Properties table
 *      rendered by EditorTab.
 *   2. Expand `[[wikilink]]` / `[[id|display]]` into anchors with the
 *      `wikilink` class (CE styles this in ce-graph.css).
 *   3. Tokenize the body so each rendered block carries the source
 *      line it came from — lets the editor click→cursor sync land on
 *      the exact paragraph the user clicked on.
 */

import { marked, type Token } from "marked";
import { sanitizeHtml } from "../../lib/sanitizeHtml";

const FM_RE = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/;
const PROP_LINE_RE = /^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$/;
const WIKILINK_RE = /\[\[([^\]|]+?)(?:\|([^\]]+))?\]\]/g;

export type Frontmatter = Record<string, string>;

export function parseFrontmatter(raw: string): { properties: Frontmatter; body: string } {
  const m = raw.match(FM_RE);
  if (!m) return { properties: {}, body: raw };
  const properties: Frontmatter = {};
  for (const line of m[1].split(/\r?\n/)) {
    const km = line.match(PROP_LINE_RE);
    if (!km) continue;
    let v = km[2].trim();
    // Strip surrounding quotes for the simple case; multiline / list
    // values stay raw and will display verbatim.
    if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
      v = v.slice(1, -1);
    }
    properties[km[1]] = v;
  }
  return { properties, body: m[2] };
}

export function expandWikilinks(md: string): string {
  return md.replace(WIKILINK_RE, (_full, target: string, display?: string) => {
    const raw = target.trim();
    const text = (display ?? target).trim();
    // HTML slideshows (NOT Sketch kind:deck): [[slideshow:slug|title]]
    const showM = raw.match(/^slideshow:(.+)$/i);
    if (showM) {
      const slug = showM[1].trim();
      const href = `#slideshow=${encodeURIComponent(slug)}`;
      return (
        `<a class="wikilink wikilink--slideshow" href="${href}" `
        + `data-slideshow-slug="${escapeHtml(slug)}">`
        + `${escapeHtml(text)}</a>`
      );
    }
    // Durable report packages: [[report:slug|title]]
    const repM = raw.match(/^report:(.+)$/i);
    if (repM) {
      const slug = repM[1].trim();
      const href = `#report=${encodeURIComponent(slug)}`;
      return (
        `<a class="wikilink wikilink--report" href="${href}" `
        + `data-report-slug="${escapeHtml(slug)}">`
        + `${escapeHtml(text)}</a>`
      );
    }
    // Named worksheets: [[worksheet:slug|title]]
    const wsM = raw.match(/^worksheet:(.+)$/i);
    if (wsM) {
      const slug = wsM[1].trim();
      const href = `#worksheet=${encodeURIComponent(slug)}`;
      return (
        `<a class="wikilink wikilink--worksheet" href="${href}" `
        + `data-worksheet-slug="${escapeHtml(slug)}">`
        + `${escapeHtml(text)}</a>`
      );
    }
    const slug = raw.toLowerCase().replace(/\s+/g, "-");
    const href = `#page=${encodeURIComponent(slug)}`;
    return `<a class="wikilink" href="${href}">${escapeHtml(text)}</a>`;
  });
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** How many lines of frontmatter precede the body (incl. the closing
 *  `---` and trailing newline). 0 if there's no frontmatter. */
export function frontmatterLineOffset(src: string): number {
  const m = src.match(FM_RE);
  if (!m) return 0;
  return m[0].split("\n").length - 1;
}

export type Block = {
  html: string;
  /** 0-indexed source line where this block begins (in the ORIGINAL
   *  source — i.e. already shifted past any frontmatter). */
  line: number;
  /** How many source lines this block spans. */
  span: number;
};

/** Tokenize the body, render each top-level token in its own HTML
 *  string, and tag it with its starting source line + line span.
 *  Lets EditorTab attach `data-source-line` to each preview block so
 *  click → cursor is exact, not fraction-based.
 *
 *  Wikilinks are expanded inside each block's raw text before rendering
 *  (matches the existing single-blob path).
 */
export function blocksWithLines(originalSource: string): Block[] {
  const fmOffset = frontmatterLineOffset(originalSource);
  const fmMatch = originalSource.match(FM_RE);
  const body = fmMatch ? fmMatch[2] : originalSource;
  const tokens = marked.lexer(body);
  const out: Block[] = [];
  let cursor = 0;
  for (const t of tokens) {
    const raw = (t as Token & { raw?: string }).raw ?? "";
    let found = body.indexOf(raw, cursor);
    if (found < 0) found = cursor;
    const linesBefore = body.slice(0, found).split("\n").length - 1;
    const span = Math.max(1, raw.split("\n").length - (raw.endsWith("\n") ? 1 : 0));
    cursor = found + raw.length;
    if (!raw.trim()) continue; // skip blank-line "space" tokens
    const expanded = expandWikilinks(raw);
    let html: string;
    try {
      html = sanitizeHtml(marked.parse(expanded, { async: false }) as string);
    } catch {
      html = `<pre>${escapeHtml(raw)}</pre>`;
    }
    out.push({ html, line: linesBefore + fmOffset, span });
  }
  return out;
}
