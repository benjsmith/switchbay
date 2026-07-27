/**
 * Bridge for opening an HTML slideshow when the Slideshow tab may not
 * be mounted yet (lazy tab + first open race).
 *
 * App / file browser / wikilinks call `notifyHtmlDeckOpen`; HtmlDeckTab
 * reads `getLastHtmlDeckOpen()` on mount and also listens for the
 * window event for subsequent opens while already mounted.
 */

export type HtmlDeckShow = { slug: string; title: string };

let last: HtmlDeckShow | null = null;

export function notifyHtmlDeckOpen(slug: string, title?: string): void {
  const s = (slug || "").trim();
  if (!s) return;
  last = { slug: s, title: (title || s).trim() || s };
  window.dispatchEvent(
    new CustomEvent("sy:open-html-deck", {
      detail: { slug: last.slug, title: last.title },
    }),
  );
}

/** Most recent open request (survives the first-mount race). */
export function getLastHtmlDeckOpen(): HtmlDeckShow | null {
  return last;
}

export function clearHtmlDeckOpen(): void {
  last = null;
}
