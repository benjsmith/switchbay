import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import { spawn, spawnSync } from "child_process";
import * as vscode from "vscode";
import { pythonBin, repoRoot, srcDir } from "./paths";

export type GraphNode = {
  id: string;
  path: string;
  type: string;
  title: string;
  degree?: number;
};

export type GraphPage = {
  id: string;
  title: string;
  type: string;
  path: string;
  properties?: Record<string, unknown>;
  body_html?: string;
};

export type GraphData = {
  workspace?: string;
  generated_at?: string;
  palette?: Record<string, string>;
  nodes: GraphNode[];
  edges: Array<{ source: string; target: string; type?: string }>;
  pages?: Record<string, GraphPage>;
};

export function dataJsonPath(workspace: string): string {
  return path.join(
    os.homedir(),
    ".cache",
    "curiosity-engine",
    "wiki-view",
    path.basename(workspace),
    "data.json",
  );
}

export function readCachedGraph(workspace: string): GraphData | null {
  const p = dataJsonPath(workspace);
  if (!fs.existsSync(p)) return null;
  try {
    const data = JSON.parse(fs.readFileSync(p, "utf8")) as GraphData;
    if (!data || !Array.isArray(data.nodes)) return null;
    // wiki_render emits nodes-only when the build interpreter lacks
    // kuzu. Edges live in ``.curator/graph.kuzu`` (WikiLink / Depicts).
    return ensureGraphEdges(data, workspace);
  } catch {
    return null;
  }
}

const WIKILINK_RE = /\[\[([^\]|#\n]+)(?:\|[^\]]*)?\]\]/g;
const DATA_PAGE_RE = /data-page=["']([^"']+)["']/g;
const HASH_PAGE_RE = /#page=([^"'&]+)/g;
const REL_FIELDS = [
  "sources", "relates_to", "facts", "evidence", "figures",
  "tables", "concepts", "entities", "projects",
] as const;

function stemOf(id: string): string {
  return id.replace(/\.md$/i, "").split("/").pop() || id;
}

function indexIds(nodes: GraphNode[]): { ids: Set<string>; stemToId: Map<string, string> } {
  const ids = new Set(nodes.map((n) => n.id));
  const stemToId = new Map<string, string>();
  for (const id of ids) {
    const stem = stemOf(id);
    if (!stemToId.has(stem)) stemToId.set(stem, id);
  }
  return { ids, stemToId };
}

function resolveTarget(
  raw: string,
  ids: Set<string>,
  stemToId: Map<string, string>,
): string | null {
  let t = raw.trim();
  try { t = decodeURIComponent(t); } catch { /* keep */ }
  t = t.replace(/^\.\//, "");
  if (t.startsWith("wiki/")) t = t.slice(5);
  t = t.replace(/\.md$/i, "");
  if (ids.has(t)) return t;
  return stemToId.get(stemOf(t)) ?? null;
}

function addEdge(
  out: Map<string, { source: string; target: string; type: string }>,
  source: string,
  target: string,
): void {
  if (!source || !target || source === target) return;
  const key = `${source}\0${target}`;
  if (!out.has(key)) out.set(key, { source, target, type: "wikilink" });
}

function harvestFromWikiMarkdown(
  workspace: string,
  ids: Set<string>,
  stemToId: Map<string, string>,
  out: Map<string, { source: string; target: string; type: string }>,
): void {
  const wiki = path.join(workspace, "wiki");
  if (!fs.existsSync(wiki)) return;
  const walk = (dir: string) => {
    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const e of entries) {
      const full = path.join(dir, e.name);
      if (e.isDirectory()) {
        if (e.name.startsWith(".")) continue;
        walk(full);
        continue;
      }
      if (!e.name.endsWith(".md")) continue;
      const rel = path.relative(wiki, full).split(path.sep).join("/");
      const source = rel.replace(/\.md$/i, "");
      if (!ids.has(source)) continue;
      let text = "";
      try { text = fs.readFileSync(full, "utf8"); } catch { continue; }
      WIKILINK_RE.lastIndex = 0;
      for (const m of text.matchAll(WIKILINK_RE)) {
        const target = resolveTarget(m[1], ids, stemToId);
        if (target) addEdge(out, source, target);
      }
    }
  };
  walk(wiki);
}

function graphKuzuPath(workspace: string): string {
  return path.join(workspace, ".curator", "graph.kuzu");
}

/** Interpreter that can `import kuzu` — workspace .venv first (it wrote the db). */
export function pythonWithKuzu(workspace: string): string | undefined {
  const cands: string[] = [
    path.join(workspace, ".venv", "bin", "python"),
    path.join(workspace, ".venv", "bin", "python3"),
    path.join(workspace, ".venv", "Scripts", "python.exe"),
  ];
  const ce = ceRoot();
  if (ce) {
    cands.push(
      path.join(ce, ".venv", "bin", "python"),
      path.join(ce, ".venv", "bin", "python3"),
      path.join(ce, ".venv", "Scripts", "python.exe"),
    );
  }
  return cands.find((p) => fs.existsSync(p));
}

function dumpKuzuScript(): string {
  return path.join(__dirname, "..", "scripts", "dump_kuzu_edges.py");
}

type EdgeCache = { key: string; edges: GraphData["edges"] };
let kuzuEdgeCache: EdgeCache | null = null;

/** WikiLink + Depicts from ``.curator/graph.kuzu``. Null if unreadable. */
export function readKuzuEdges(workspace: string): GraphData["edges"] | null {
  const db = graphKuzuPath(workspace);
  if (!fs.existsSync(db)) return null;
  const py = pythonWithKuzu(workspace);
  const script = dumpKuzuScript();
  if (!py || !fs.existsSync(script)) return null;
  let st: fs.Stats;
  try { st = fs.statSync(db); } catch { return null; }
  const key = `${db}:${st.mtimeMs}:${st.size}`;
  if (kuzuEdgeCache?.key === key) return kuzuEdgeCache.edges;
  const r = spawnSync(py, [script, db], {
    encoding: "utf8",
    timeout: 15000,
    maxBuffer: 32 * 1024 * 1024,
    windowsHide: true,
  });
  if (r.status !== 0) return null;
  try {
    const edges = JSON.parse(r.stdout || "[]") as GraphData["edges"];
    if (!Array.isArray(edges)) return null;
    kuzuEdgeCache = { key, edges };
    return edges;
  } catch {
    return null;
  }
}

/** Prefer kuzu WikiLink/Depicts; fall back to body wikilinks if no db. */
export function ensureGraphEdges(data: GraphData, workspace?: string): GraphData {
  if (workspace) {
    const fromKuzu = readKuzuEdges(workspace);
    if (fromKuzu !== null) {
      data.edges = fromKuzu;
      applyDegrees(data);
      return data;
    }
  }
  if (!Array.isArray(data.edges) || data.edges.length === 0) {
    data.edges = harvestWikilinkEdges(data, workspace);
  }
  applyDegrees(data);
  return data;
}

export function harvestWikilinkEdges(
  data: GraphData,
  workspace?: string,
): GraphData["edges"] {
  const { ids, stemToId } = indexIds(data.nodes || []);
  const out = new Map<string, { source: string; target: string; type: string }>();
  const add = (source: string, raw: string) => {
    const target = resolveTarget(raw, ids, stemToId);
    if (target && ids.has(source)) addEdge(out, source, target);
  };

  if (data.pages) {
    for (const [pid, page] of Object.entries(data.pages)) {
      const source = ids.has(pid) ? pid : resolveTarget(page.id || pid, ids, stemToId);
      if (!source) continue;
      const html = page.body_html || "";
      DATA_PAGE_RE.lastIndex = 0;
      for (const m of html.matchAll(DATA_PAGE_RE)) add(source, m[1]);
      HASH_PAGE_RE.lastIndex = 0;
      for (const m of html.matchAll(HASH_PAGE_RE)) add(source, m[1]);
      const props = page.properties || {};
      for (const field of REL_FIELDS) {
        const raw = props[field];
        const items = Array.isArray(raw) ? raw : typeof raw === "string" && raw ? [raw] : [];
        for (const item of items) add(source, String(item));
      }
    }
  }

  if (out.size === 0 && workspace) {
    harvestFromWikiMarkdown(workspace, ids, stemToId, out);
  }
  return [...out.values()];
}

function applyDegrees(data: GraphData): void {
  const nbr = new Map<string, Set<string>>();
  const touch = (a: string, b: string) => {
    if (!nbr.has(a)) nbr.set(a, new Set());
    nbr.get(a)!.add(b);
  };
  for (const e of data.edges || []) {
    const s = typeof e.source === "string" ? e.source : "";
    const t = typeof e.target === "string" ? e.target : "";
    if (!s || !t || s === t) continue;
    touch(s, t);
    touch(t, s);
  }
  for (const n of data.nodes || []) {
    n.degree = nbr.get(n.id)?.size ?? 0;
  }
}

export function wikiPageUri(folder: vscode.Uri, nodePath: string): vscode.Uri {
  const trimmed = nodePath.replace(/^\.\//, "");
  const rel = trimmed.startsWith("wiki/") ? trimmed : path.posix.join("wiki", trimmed);
  return vscode.Uri.joinPath(folder, rel);
}

export function ceRoot(): string | undefined {
  const home = os.homedir();
  const env = process.env.SWITCHBAY_CE_ROOT;
  const cands = [
    env ? env : "",
    path.join(home, ".claude", "skills", "curiosity-engine"),
    path.join(home, ".agents", "skills", "curiosity-engine"),
    path.join(home, "Documents", "bin", "curiosity-engine"),
  ].filter(Boolean);
  for (const c of cands) {
    if (fs.existsSync(path.join(c, "scripts"))) return c;
  }
  return cands[0];
}

export function rebuildViewer(
  context: vscode.ExtensionContext,
  workspace: string,
): Promise<{ ok: boolean; text: string }> {
  const repo = repoRoot(context);
  // wiki_render._build_graph imports kuzu; Switch Bay's venv does not
  // ship it. Use the workspace (or CE skill) interpreter that wrote
  // graph.kuzu so data.json gets WikiLink/Depicts edges.
  const py = pythonWithKuzu(workspace) || pythonBin(repo);
  const renderPy = path.join(ceRoot() || "", "scripts", "wiki_render.py");
  const outDir = path.dirname(dataJsonPath(workspace));
  const wiki = path.join(workspace, "wiki");
  const args = fs.existsSync(renderPy)
    ? [renderPy, "build", wiki, "--output-dir", outDir]
    : ["-c", "raise SystemExit('curiosity-engine wiki_render.py not found')"];
  return new Promise((resolve) => {
    const proc = spawn(py, args, {
      cwd: workspace,
      env: {
        ...process.env,
        PYTHONPATH: srcDir(repo),
      },
    });
    let text = "";
    proc.stdout?.on("data", (d: Buffer) => { text += d.toString(); });
    proc.stderr?.on("data", (d: Buffer) => { text += d.toString(); });
    proc.on("error", (err) => resolve({ ok: false, text: String(err) }));
    proc.on("close", (code) => resolve({ ok: code === 0, text: text.slice(-4000) }));
  });
}

export function scanWikiMarkdown(workspace: string): GraphNode[] {
  const wiki = path.join(workspace, "wiki");
  if (!fs.existsSync(wiki)) return [];
  const out: GraphNode[] = [];
  const walk = (dir: string) => {
    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const e of entries) {
      const full = path.join(dir, e.name);
      if (e.isDirectory()) {
        if (e.name.startsWith(".")) continue;
        walk(full);
        continue;
      }
      if (!e.name.endsWith(".md")) continue;
      const rel = path.relative(wiki, full).split(path.sep).join("/");
      const text = fs.readFileSync(full, "utf8");
      const { title, type } = frontmatterMeta(text);
      out.push({
        id: rel.replace(/\.md$/i, ""),
        path: rel,
        type: type || "unclassified",
        title: title || path.basename(rel, ".md"),
      });
    }
  };
  walk(wiki);
  return out;
}

export function frontmatterMeta(text: string): { title: string; type: string; properties: Record<string, string> } {
  const properties: Record<string, string> = {};
  if (!text.startsWith("---")) return { title: "", type: "", properties };
  const end = text.indexOf("\n---", 3);
  if (end < 0) return { title: "", type: "", properties };
  const block = text.slice(3, end);
  for (const line of block.split("\n")) {
    const m = line.match(/^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$/);
    if (!m) continue;
    properties[m[1]] = m[2].trim().replace(/^["']|["']$/g, "");
  }
  return {
    title: properties.title || "",
    type: (properties.type || "").toLowerCase(),
    properties,
  };
}

export function splitFrontmatter(text: string): { properties: Record<string, string>; body: string } {
  const meta = frontmatterMeta(text);
  if (!text.startsWith("---")) return { properties: {}, body: text };
  const end = text.indexOf("\n---", 3);
  if (end < 0) return { properties: meta.properties, body: text };
  const bodyStart = end + 4;
  const rest = text.slice(bodyStart).replace(/^\n/, "");
  return { properties: meta.properties, body: rest };
}
