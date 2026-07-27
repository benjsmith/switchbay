import DOMPurify from "dompurify";

/**
 * Sanitize model/agent/wiki-authored HTML before it is injected via
 * dangerouslySetInnerHTML / innerHTML. The daemon runs on the same
 * origin with filesystem + shell authority, so an unsanitized
 * `<img onerror=fetch('/api/...')>` in an assistant turn or wiki page
 * is effectively local RCE. Every markdown-render path funnels through
 * here.
 *
 * We keep the wikilink anchor contract (`class="sy-wikilink"` +
 * `data-wiki`) that App's delegated click handler depends on, and
 * target="_blank" links, while stripping scripts and event handlers.
 */
export function sanitizeHtml(html: string): string {
  return DOMPurify.sanitize(html, {
    ADD_ATTR: ["target", "data-wiki", "class"],
    // Allow http(s)/mailto and in-page '#' anchors (wikilinks use href="#").
    ALLOWED_URI_REGEXP:
      /^(?:(?:https?|mailto|tel):|[^a-z]|[a-z+.-]+(?:[^a-z+.:-]|$)|#)/i,
  });
}
