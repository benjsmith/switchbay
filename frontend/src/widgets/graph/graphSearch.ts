/**
 * Graph-view search: match wiki nodes, highlight them on the canvas,
 * and tell the FileBrowser (and VS Code wiki tree) which files to mark.
 */
import type { GraphData } from "./types";

export type GraphSearchHit = {
  id: string;
  path: string;
  title: string;
};

export function wikiFilePath(raw: string | undefined): string {
  const p = (raw || "").replace(/^\.\//, "").replace(/^\/+/, "");
  if (!p) return "";
  if (
    p.startsWith("wiki/")
    || p.startsWith("vault/")
    || p.startsWith("slideshows/")
    || p.startsWith("reports/")
    || p.startsWith("sketches/")
  ) {
    return p;
  }
  return `wiki/${p}`;
}

/**
 * A page's `sources:` entries are vault-relative: mostly bare ingest
 * filenames (`20260417-…-resnet.md.extracted.md`), occasionally a
 * rooted path (`vault/raw/x.pdf`, `wiki/projects/y.md`). Bare names used
 * to get the `wiki/` prefix, so every source file a hit came from
 * silently failed to match the file tree.
 */
function sourceFilePath(raw: string): string {
  const p = raw.replace(/^\.\//, "").replace(/^\/+/, "");
  if (!p) return "";
  return p.includes("/") ? wikiFilePath(p) : `vault/${p}`;
}

function extraSourcePaths(props: Record<string, unknown> | undefined): string[] {
  if (!props) return [];
  const out: string[] = [];
  for (const key of ["source", "sources", "file", "path"]) {
    const v = props[key];
    const vals = Array.isArray(v) ? v : v != null ? [v] : [];
    for (const item of vals) {
      const s = String(item);
      if (!s || s.startsWith("http://") || s.startsWith("https://")) continue;
      if (s.includes("/") || s.endsWith(".md") || s.endsWith(".pdf")) {
        const path = sourceFilePath(s);
        if (path) out.push(path);
      }
    }
  }
  return out;
}

function haystack(data: GraphData, id: string): string {
  const n = data.nodes.find((x) => x.id === id);
  const page = data.pages?.[id];
  const bits = [
    n?.id, n?.title, n?.path, n?.type,
    page?.id, page?.title, page?.path, page?.type,
  ];
  const props = page?.properties;
  if (props) {
    for (const v of Object.values(props)) {
      if (v == null) continue;
      bits.push(Array.isArray(v) ? v.join(" ") : String(v));
    }
  }
  return bits.filter(Boolean).join(" ").toLowerCase();
}

/** Substring match over title, id, path, type, and page properties. */
export function matchGraphNodes(data: GraphData, query: string): GraphSearchHit[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const hits: GraphSearchHit[] = [];
  for (const n of data.nodes) {
    if (!haystack(data, n.id).includes(q)) continue;
    const page = data.pages?.[n.id];
    hits.push({
      id: n.id,
      path: wikiFilePath(n.path || page?.path),
      title: n.title || page?.title || n.id,
    });
  }
  return hits;
}

/** The matched pages themselves. */
export function hitPagePaths(hits: GraphSearchHit[]): string[] {
  const paths = new Set<string>();
  for (const h of hits) if (h.path) paths.add(h.path);
  return [...paths];
}

/** The vault files the matched pages were extracted from. */
export function hitSourcePaths(data: GraphData, hits: GraphSearchHit[]): string[] {
  const paths = new Set<string>();
  const pages = new Set(hitPagePaths(hits));
  for (const h of hits) {
    const page = data.pages?.[h.id];
    for (const p of extraSourcePaths(page?.properties)) {
      if (!pages.has(p)) paths.add(p);
    }
  }
  return [...paths];
}

export type GraphSearchDetail = {
  query: string;
  ids: string[];
  /** Matched wiki pages. Browsers reveal (expand + scroll to) these. */
  paths: string[];
  /** Provenance behind the matches — highlighted where the tree already
   *  shows them, never auto-revealed: one broad query pulls in half the
   *  vault, and expanding it buries the pages that actually matched. */
  sourcePaths: string[];
};

/** Lives outside GraphTab so leaving for Editor doesn't wipe the query. */
let persistedQuery = "";
let persistedWorkspace = "";

export function peekPersistedQuery(workspace?: string): string {
  if (workspace != null && persistedWorkspace && persistedWorkspace !== workspace) {
    return "";
  }
  return persistedQuery;
}

export function persistGraphQuery(workspace: string, query: string): void {
  persistedWorkspace = workspace;
  persistedQuery = query;
}

function paint(
  data: GraphData,
  query: string,
  clearBtn: HTMLButtonElement,
  countEl: HTMLElement | null,
): GraphSearchDetail {
  const q = query.trim();
  persistGraphQuery(data.workspace || "", q);
  const hits = matchGraphNodes(data, q);
  const ids = hits.map((h) => h.id);
  const paths = hitPagePaths(hits);
  const sourcePaths = hitSourcePaths(data, hits);
  try {
    window.Graph.highlightSearch?.(ids);
  } catch { /* classic or atlas facade not ready */ }
  // The wiki page list rings the same hits as the canvas. Always call —
  // an empty list is how a cancelled search clears the browser.
  try {
    window.Sidebar.setSearchHits?.(ids);
  } catch { /* sidebar not mounted (webview / no wiki) */ }
  clearBtn.hidden = !q;
  if (countEl) {
    if (!q) {
      countEl.hidden = true;
      countEl.textContent = "";
    } else {
      countEl.hidden = false;
      countEl.textContent = String(hits.length);
    }
  }
  const detail: GraphSearchDetail = { query: q, ids, paths, sourcePaths };
  window.dispatchEvent(new CustomEvent("sy:graph-search", { detail }));
  return detail;
}

/** Bind the host-level search overlay (`#graph-search-input`). */
export function installGraphSearch(data: GraphData): void {
  const input = document.getElementById("graph-search-input") as HTMLInputElement | null;
  const clearBtn = document.getElementById("graph-search-clear") as HTMLButtonElement | null;
  const countEl = document.getElementById("graph-search-count");
  const host = input?.closest(".sy-graph-host") ?? document.getElementById("graph-pane");
  if (!input || !clearBtn) return;

  const prev = (input as HTMLInputElement & { _sbSearchAbort?: AbortController })._sbSearchAbort;
  prev?.abort();
  const ac = new AbortController();
  (input as HTMLInputElement & { _sbSearchAbort?: AbortController })._sbSearchAbort = ac;
  const { signal } = ac;

  let timer = 0;
  const applyNow = (q: string) => {
    window.clearTimeout(timer);
    paint(data, q, clearBtn, countEl);
  };

  input.addEventListener("input", () => {
    const q = input.value;
    if (!q.trim()) {
      applyNow("");
      return;
    }
    window.clearTimeout(timer);
    timer = window.setTimeout(() => paint(data, q, clearBtn, countEl), 160);
  }, { signal });
  clearBtn.addEventListener("click", () => {
    input.value = "";
    applyNow("");
    input.focus();
  }, { signal });
  input.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape") return;
    ev.preventDefault();
    ev.stopPropagation();
    if (input.value) {
      input.value = "";
      applyNow("");
    } else {
      input.blur();
    }
  }, { signal });
  host?.addEventListener("keydown", (ev) => {
    const ke = ev as KeyboardEvent;
    if (!(ke.metaKey || ke.ctrlKey) || ke.key.toLowerCase() !== "f") return;
    ke.preventDefault();
    input.focus();
    input.select();
  }, { signal });

  const saved = peekPersistedQuery(data.workspace || "");
  input.value = saved;
  // Paint unconditionally, including the empty case: a workspace switch
  // gives this mount a blank box, and the browsers would otherwise keep
  // highlighting the previous workspace's hits forever.
  applyNow(saved);
}
