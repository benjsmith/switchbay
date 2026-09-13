/**
 * Detect + prepare HTML-heavy vault extractions for the Editor tab.
 *
 * Files like `foo.html.extracted.md` store a YAML frontmatter header
 * plus a full HTML document body. Opening them in CodeMirror shows
 * raw tags; we want a sandboxed HTML preview instead, with a Source
 * toggle for power users. Normal markdown `.extracted.md` files stay
 * on the plain code path.
 */

import DOMPurify from "dompurify";

const FM_RE = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/;

function parseFrontmatterLite(raw: string): {
  properties: Record<string, string>;
  body: string;
} {
  const m = (raw || "").match(FM_RE);
  if (!m) return { properties: {}, body: raw || "" };
  const properties: Record<string, string> = {};
  for (const line of m[1].split(/\r?\n/)) {
    const km = line.match(/^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$/);
    if (!km) continue;
    properties[km[1]] = km[2].trim();
  }
  return { properties, body: m[2] };
}

const HTML_EXTRACTED_NAME_RE = /\.html?\.extracted\.md$/i;
const HTML_DOC_START_RE = /^(?:<!DOCTYPE\s+html\b|<(?:html|head|body)\b)/i;
const HTML_BLOCK_TAG_RE = /<(?:div|p|span|table|article|section|body|main|header|nav|ul|ol|h[1-6])\b/i;

/** Filename pattern used by CE for HTML vault extractions. */
export function isHtmlExtractedFilename(path: string): boolean {
  const base = (path || "").split("/").pop() || path || "";
  return HTML_EXTRACTED_NAME_RE.test(base);
}

/**
 * True when this vault source should open as an HTML preview rather
 * than a monospace code dump of tags.
 *
 * Filename `*.html.extracted.md` / `*.htm.extracted.md` always wins.
 * Otherwise look at the body (after frontmatter / optional title /
 * fetch banner): DOCTYPE/html/head start, or mostly-tagged HTML.
 */
export function isHtmlHeavyExtraction(path: string, text: string): boolean {
  if (isHtmlExtractedFilename(path)) return true;
  const sample = stripToHtmlCandidate(text);
  if (!sample) return false;
  if (HTML_DOC_START_RE.test(sample)) return true;
  if (sample.length < 200) return false;
  const tags = sample.match(/<[^>]+>/g);
  if (!tags || tags.length < 8) return false;
  const tagChars = tags.reduce((n, t) => n + t.length, 0);
  if (tagChars / sample.length < 0.12) return false;
  return HTML_BLOCK_TAG_RE.test(sample);
}

/** Frontmatter-stripped body with the ingest banner / leading H1 removed. */
export function stripToHtmlCandidate(raw: string): string {
  const { body } = parseFrontmatterLite(raw || "");
  let s = body.trim();
  s = s.replace(/^<!--\s*BEGIN FETCHED CONTENT[\s\S]*?-->\s*/i, "");
  s = s.replace(/^#[^\n]*\n+/, "");
  return s.trim();
}

export type HtmlExtractionParts = {
  html: string;
  sourceUrl: string | null;
  title: string | null;
};

/** Pull the HTML payload + optional `source_url` from an extraction. */
export function extractHtmlParts(raw: string): HtmlExtractionParts {
  const { properties, body } = parseFrontmatterLite(raw || "");
  let html = body.trim();
  html = html.replace(/^<!--\s*BEGIN FETCHED CONTENT[\s\S]*?-->\s*/i, "");
  html = html.replace(/^#[^\n]*\n+/, "");
  html = html.trim();

  const sourceUrl =
    typeof properties.source_url === "string"
    && /^https?:\/\//i.test(properties.source_url.trim())
      ? properties.source_url.trim()
      : null;
  const title =
    typeof properties.title === "string" && properties.title.trim()
      ? properties.title.trim()
      : null;
  return { html, sourceUrl, title };
}

function escapeAttr(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

/**
 * Sanitize a (possibly whole) HTML document for iframe `srcdoc`.
 * Strips scripts / event handlers / forms; keeps style + safe http(s)
 * links. Optionally injects a controlled `<base href>` from provenance
 * so relative images resolve against the original site.
 *
 * Callers must still host this in a sandboxed iframe (no
 * allow-scripts / allow-same-origin).
 */
export function sanitizeHtmlDocument(
  html: string,
  opts?: { baseHref?: string | null },
): string {
  let input = (html || "").trim();
  if (!input) {
    input = "<!DOCTYPE html><html><head><meta charset=\"utf-8\"></head><body></body></html>";
  } else if (!/<html[\s>]/i.test(input) && !/<!DOCTYPE\s/i.test(input)) {
    input = (
      "<!DOCTYPE html><html><head><meta charset=\"utf-8\"></head>"
      + `<body>${input}</body></html>`
    );
  }

  let out = DOMPurify.sanitize(input, {
    WHOLE_DOCUMENT: true,
    ADD_TAGS: ["link", "meta", "style"],
    ADD_ATTR: [
      "target", "class", "charset", "content", "http-equiv", "name",
      "property", "rel", "href", "type", "media", "sizes", "crossorigin",
      "role", "aria-label", "aria-hidden", "alt", "width", "height",
      "colspan", "rowspan",
    ],
    FORBID_TAGS: [
      "script", "iframe", "object", "embed", "form", "input", "button",
      "textarea", "select", "base",
    ],
    FORBID_ATTR: ["srcdoc"],
    ALLOWED_URI_REGEXP:
      /^(?:(?:https?|mailto|tel|data):|[^a-z]|[a-z+.-]+(?:[^a-z+.:-]|$)|#)/i,
  });

  const base = opts?.baseHref?.trim() || "";
  if (/^https?:\/\//i.test(base) && !/<base\b/i.test(out)) {
    const tag = `<base href="${escapeAttr(base)}" target="_blank">`;
    if (/<head[^>]*>/i.test(out)) {
      out = out.replace(/<head[^>]*>/i, (m) => `${m}${tag}`);
    } else {
      out = `${tag}${out}`;
    }
  }
  return out;
}

/** Build the srcdoc string for an extraction draft. */
export function htmlExtractionSrcDoc(raw: string): string {
  const { html, sourceUrl } = extractHtmlParts(raw);
  return sanitizeHtmlDocument(html, { baseHref: sourceUrl });
}
