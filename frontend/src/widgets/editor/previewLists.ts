/** Shared open/closed memory for long property lists (sources) in
 *  the Editor preview and the Graph doc modal. */
const SOURCES_OPEN_KEY = "sy:preview-sources-open";

export function readSourcesOpen(): boolean {
  try { return localStorage.getItem(SOURCES_OPEN_KEY) === "1"; } catch { return false; }
}

export function writeSourcesOpen(open: boolean): void {
  try { localStorage.setItem(SOURCES_OPEN_KEY, open ? "1" : "0"); } catch { /* quota */ }
}

export function isCollapsibleList(key: string, value: unknown): value is unknown[] {
  return key === "sources" && Array.isArray(value) && value.length > 1;
}
