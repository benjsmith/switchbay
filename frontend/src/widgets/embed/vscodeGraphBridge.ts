/**
 * VS Code graph view ↔ extension host plumbing for CE's embedded viewer.
 *
 * The VS Code webview has no daemon to talk to. CE's scripts reach their
 * API through `window.ceApi(path)`; the view points that at a virtual
 * origin and this module turns every fetch to it into a postMessage
 * round-trip that the extension answers from the workspace on disk
 * (data.json, page reads/writes, curation history).
 *
 * Kept free of DOM and VS Code APIs so it runs under `node --test`.
 */

/** Never resolvable (`.invalid` is reserved) — a fetch that slips past the bridge fails loudly. */
export const VSCODE_CE_API = "https://switchbay-vscode.invalid/ce";

export type BridgeRequest = {
  type: "api";
  id: number;
  method: string;
  path: string;
  body?: string;
};

export type BridgeResponse = {
  type: "api-result";
  id: number;
  status: number;
  body: string;
  contentType?: string;
};

type PostMessage = (msg: BridgeRequest) => void;

export function vscodeCeApi(path: string): string {
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${VSCODE_CE_API}${p}`;
}

/** Path + query of a bridged URL, or null for anything else. */
export function bridgedPath(url: string): string | null {
  if (!url.startsWith(VSCODE_CE_API)) return null;
  const rest = url.slice(VSCODE_CE_API.length) || "/";
  return rest.startsWith("/") ? rest : null;
}

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.href;
  return (input as Request).url;
}

/**
 * Wrap `fetch` so bridged URLs go to the extension host. Returns the
 * function that delivers host replies (wire it to window "message").
 */
export function installFetchBridge(
  target: { fetch: typeof fetch },
  post: PostMessage,
  timeoutMs = 120_000,
): (msg: unknown) => boolean {
  const native = target.fetch.bind(target);
  const pending = new Map<number, (r: BridgeResponse) => void>();
  let nextId = 1;

  target.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = requestUrl(input);
    const path = bridgedPath(url);
    if (path === null) return native(input, init);
    const method = (init?.method || (typeof input === "object" && "method" in input ? input.method : "GET") || "GET").toUpperCase();
    let body: string | undefined;
    if (init?.body != null) {
      if (typeof init.body !== "string") {
        return new Response(JSON.stringify({ error: "binary uploads are not available in VS Code" }), {
          status: 501, headers: { "Content-Type": "application/json" },
        });
      }
      body = init.body;
    }
    const id = nextId++;
    const reply = await new Promise<BridgeResponse>((resolve) => {
      const timer = setTimeout(() => {
        pending.delete(id);
        resolve({ type: "api-result", id, status: 504, body: JSON.stringify({ error: "extension did not answer" }) });
      }, timeoutMs);
      pending.set(id, (r) => {
        clearTimeout(timer);
        resolve(r);
      });
      post({ type: "api", id, method, path, body });
    });
    return new Response(reply.body, {
      status: reply.status,
      headers: { "Content-Type": reply.contentType || "application/json" },
    });
  };

  return (msg: unknown) => {
    const m = msg as Partial<BridgeResponse> | null;
    if (!m || m.type !== "api-result" || typeof m.id !== "number") return false;
    const done = pending.get(m.id);
    if (!done) return false;
    pending.delete(m.id);
    done({ type: "api-result", id: m.id, status: m.status ?? 500, body: m.body ?? "", contentType: m.contentType });
    return true;
  };
}

type PageLike = { id?: string; path?: string; title?: string; type?: string; properties?: Record<string, unknown> };
type NodeLike = { id: string; path?: string; title?: string; type?: string };
export type ViewData = { nodes?: NodeLike[]; pages?: Record<string, PageLike> };

export type NodeRef = { id: string; path: string; title: string; type?: string };

export function nodeRef(data: ViewData | null | undefined, id: string): NodeRef {
  const n = data?.nodes?.find((x) => x.id === id);
  const page = data?.pages?.[id];
  return {
    id,
    path: n?.path || page?.path || id,
    title: n?.title || page?.title || id,
    type: n?.type || page?.type,
  };
}

/** Workspace-relative path the VS Code wiki tree uses for a page. */
export function wikiFilePath(raw: string | undefined): string {
  const p = (raw || "").replace(/^\.\//, "").replace(/^\/+/, "");
  if (!p) return "";
  if (/^(wiki|vault|slideshows|reports|sketches)\//.test(p)) return p;
  return `wiki/${p}`;
}

/**
 * A page's `sources:` entries are vault-relative: mostly bare ingest
 * filenames, occasionally a rooted path (`vault/raw/x.pdf`).
 */
function sourceFilePath(raw: string): string {
  const p = raw.replace(/^\.\//, "").replace(/^\/+/, "");
  if (!p) return "";
  return p.includes("/") ? wikiFilePath(p) : `vault/${p}`;
}

function sourcePaths(props: Record<string, unknown> | undefined): string[] {
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

/** Files to mark in the wiki tree for CE's graph-search hits. */
export function searchHitPaths(
  data: ViewData | null | undefined,
  ids: string[],
): { paths: string[]; sourcePaths: string[] } {
  const pages = new Set<string>();
  for (const id of ids) {
    const p = wikiFilePath(nodeRef(data, id).path);
    if (p) pages.add(p);
  }
  const sources = new Set<string>();
  for (const id of ids) {
    for (const p of sourcePaths(data?.pages?.[id]?.properties)) {
      if (!pages.has(p)) sources.add(p);
    }
  }
  return { paths: [...pages], sourcePaths: [...sources] };
}

/** VS Code theme class on <body> → CE's data-theme. */
export function ceThemeFor(bodyClasses: string): "light" | "dark" {
  const c = ` ${bodyClasses} `;
  return c.includes(" vscode-light ") || c.includes(" vscode-high-contrast-light ") ? "light" : "dark";
}
