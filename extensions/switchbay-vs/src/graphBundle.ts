/**
 * Curiosity Engine's wiki-view bundle as the VS Code graph view sees it:
 * is CE installed, is the built bundle current, and the small slice of
 * CE's viewer API the embedded viewer calls (answered from disk instead
 * of CE's HTTP server). No `vscode` import, so it runs under node --test.
 */
import * as fs from "fs";
import * as path from "path";

/** CE ships both the bundle builder and an embeddable viewer. */
export function ceViewerAvailable(ceRoot: string | undefined): boolean {
  if (!ceRoot) return false;
  return fs.existsSync(path.join(ceRoot, "scripts", "wiki_render.py"))
    && fs.existsSync(path.join(ceRoot, "template", "wiki-view", "static", "embed.js"));
}

/** Newest mtime under wiki/, directories included (a deletion only touches its folder). */
export function wikiMtime(wikiDir: string): number {
  let newest = 0;
  const walk = (dir: string) => {
    let st: fs.Stats;
    try { st = fs.statSync(dir); } catch { return; }
    newest = Math.max(newest, st.mtimeMs);
    let entries: fs.Dirent[];
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const e of entries) {
      if (e.name.startsWith(".")) continue;
      const p = path.join(dir, e.name);
      if (e.isDirectory()) walk(p);
      else if (e.isFile()) {
        try { newest = Math.max(newest, fs.statSync(p).mtimeMs); } catch { /* raced */ }
      }
    }
  };
  walk(wikiDir);
  return newest;
}

/**
 * Built bundle exists, carries the embeddable viewer, and is not older
 * than the wiki, the other inputs (graph db), or `notBefore` (ms epoch).
 */
export function bundleFresh(
  bundleDir: string,
  wikiDir: string,
  inputs: string[] = [],
  notBefore = 0,
): boolean {
  const data = path.join(bundleDir, "data.json");
  if (!fs.existsSync(path.join(bundleDir, "static", "embed.js"))) return false;
  let built: number;
  try { built = fs.statSync(data).mtimeMs; } catch { return false; }
  if (built < notBefore) return false;
  for (const p of inputs) {
    try {
      if (fs.statSync(p).mtimeMs > built) return false;
    } catch { /* absent input */ }
  }
  return built >= wikiMtime(wikiDir);
}

/** Same rule as CE's viewer server: only notes/ and todos/ .md pages are editable. */
export function safeEditablePage(wikiDir: string, rel: string): string {
  if (!rel || rel.endsWith("/") || rel.includes("\\")) throw new Error("invalid path");
  if (rel.split("/").includes("..")) throw new Error("path may not contain ..");
  const root = path.resolve(wikiDir);
  const candidate = path.resolve(root, rel);
  const inside = path.relative(root, candidate);
  if (!inside || inside.startsWith("..") || path.isAbsolute(inside)) throw new Error("path escapes wiki/");
  const top = inside.split(path.sep)[0];
  if (top !== "notes" && top !== "todos") throw new Error("only notes/ and todos/ pages are editable");
  if (path.extname(candidate) !== ".md") throw new Error("only .md files are editable");
  return candidate;
}

export type ApiReply = { status: number; body: string; contentType?: string };

const json = (status: number, value: unknown): ApiReply => ({ status, body: JSON.stringify(value) });

export type ApiHost = {
  wikiDir: string;
  /** data.json text, rebuilding the bundle first when it is stale. */
  data(): Promise<string | null>;
  /** Rebuild after a page write. */
  rebuild(): Promise<void>;
  history(): Promise<unknown>;
};

/** Answer one CE viewer API call. Unknown routes 404 like CE's server. */
export async function answerCeApi(
  host: ApiHost,
  method: string,
  pathWithQuery: string,
  body?: string,
): Promise<ApiReply> {
  const url = new URL(pathWithQuery, "http://ce.invalid");
  const route = url.pathname;
  if (method === "GET" && route === "/data.json") {
    const text = await host.data();
    return text == null ? json(404, { error: "graph data unavailable" }) : { status: 200, body: text };
  }
  if (route === "/api/page") {
    if (method === "GET") {
      const rel = url.searchParams.get("path") || "";
      let p: string;
      try { p = safeEditablePage(host.wikiDir, rel); } catch (e) { return json(400, { error: (e as Error).message }); }
      if (!fs.existsSync(p)) return json(404, { error: "page missing" });
      return json(200, { path: rel, content: fs.readFileSync(p, "utf8") });
    }
    if (method === "POST") {
      let payload: { path?: unknown; content?: unknown };
      try { payload = JSON.parse(body || "{}"); } catch { return json(400, { error: "invalid JSON body" }); }
      const rel = typeof payload.path === "string" ? payload.path : "";
      let content = payload.content ?? "";
      if (typeof content !== "string") return json(400, { error: "content must be a string" });
      let p: string;
      try { p = safeEditablePage(host.wikiDir, rel); } catch (e) { return json(400, { error: (e as Error).message }); }
      if (content && !content.endsWith("\n")) content += "\n";
      fs.mkdirSync(path.dirname(p), { recursive: true });
      fs.writeFileSync(p, content);
      await host.rebuild();
      return json(200, { ok: true, path: rel });
    }
  }
  if (method === "GET" && route === "/api/curation/history") {
    return json(200, await host.history());
  }
  if (method === "GET" && route === "/api/file-routes") return json(200, { routes: [] });
  return json(404, { error: "not available in VS Code" });
}
