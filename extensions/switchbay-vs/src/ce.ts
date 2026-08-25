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

function graphKuzuPath(workspace: string): string {
  return path.join(workspace, ".curator", "graph.kuzu");
}

/** True only when the CE graph db is on disk. File or directory both count. */
export function kuzuDbExists(workspace: string): boolean {
  try {
    const st = fs.statSync(graphKuzuPath(workspace));
    return st.isFile() || st.isDirectory();
  } catch {
    return false;
  }
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
  if (!kuzuDbExists(workspace)) return null;
  const db = graphKuzuPath(workspace);
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

/**
 * Run CE ``graph.py rebuild wiki`` only when ``graph.kuzu`` is absent.
 * Markdown harvest happens inside that rebuild, then edges are read
 * from kuzu — never applied from markdown directly.
 */
export function rebuildKuzuGraph(workspace: string): Promise<{ ok: boolean; text: string }> {
  if (kuzuDbExists(workspace)) {
    return Promise.resolve({ ok: true, text: "graph.kuzu already present" });
  }
  const py = pythonWithKuzu(workspace);
  const script = path.join(ceRoot() || "", "scripts", "graph.py");
  if (!py) {
    return Promise.resolve({ ok: false, text: "no Python with kuzu (workspace .venv)" });
  }
  if (!fs.existsSync(script)) {
    return Promise.resolve({ ok: false, text: "curiosity-engine graph.py not found" });
  }
  if (!fs.existsSync(path.join(workspace, "wiki"))) {
    return Promise.resolve({ ok: false, text: "no wiki/ in workspace" });
  }
  return new Promise((resolve) => {
    const proc = spawn(py, [script, "rebuild", "wiki"], {
      cwd: workspace,
      windowsHide: true,
    });
    let text = "";
    proc.stdout?.on("data", (d: Buffer) => { text += d.toString(); });
    proc.stderr?.on("data", (d: Buffer) => { text += d.toString(); });
    const timer = setTimeout(() => {
      proc.kill();
      resolve({ ok: false, text: `${text}\nrebuild timed out`.slice(-4000) });
    }, 180000);
    proc.on("error", (err) => {
      clearTimeout(timer);
      resolve({ ok: false, text: String(err) });
    });
    proc.on("close", (code) => {
      clearTimeout(timer);
      kuzuEdgeCache = null;
      resolve({
        ok: code === 0 && kuzuDbExists(workspace),
        text: text.slice(-4000),
      });
    });
  });
}

/** Overlay kuzu WikiLink/Depicts. Never harvest markdown into edges. */
export function ensureGraphEdges(data: GraphData, workspace?: string): GraphData {
  if (workspace && kuzuDbExists(workspace)) {
    const fromKuzu = readKuzuEdges(workspace);
    if (fromKuzu !== null) data.edges = fromKuzu;
  }
  applyDegrees(data);
  return data;
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

export function loadCurationHistory(
  context: vscode.ExtensionContext,
  workspace: string,
): Promise<unknown> {
  const repo = repoRoot(context);
  const py = pythonBin(repo);
  const script = path.join(__dirname, "..", "scripts", "dump_curation_history.py");
  return new Promise((resolve) => {
    const proc = spawn(py, [script, workspace], {
      cwd: workspace,
      env: { ...process.env, PYTHONPATH: srcDir(repo) },
    });
    let out = "";
    let err = "";
    const timer = setTimeout(() => {
      proc.kill();
      resolve({ duration: 15.0, events: [], source: "timeout" });
    }, 60000);
    proc.stdout?.on("data", (d: Buffer) => { out += d.toString(); });
    proc.stderr?.on("data", (d: Buffer) => { err += d.toString(); });
    proc.on("error", () => {
      clearTimeout(timer);
      resolve({ duration: 15.0, events: [], source: "error" });
    });
    proc.on("close", (code) => {
      clearTimeout(timer);
      if (code !== 0) {
        resolve({ duration: 15.0, events: [], source: err.slice(-200) || "error" });
        return;
      }
      try {
        resolve(JSON.parse(out));
      } catch {
        resolve({ duration: 15.0, events: [], source: "invalid-json" });
      }
    });
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
  const parsed = parseWikiFrontmatter(text);
  const properties = { ...parsed.properties };
  for (const [k, items] of Object.entries(parsed.lists)) {
    if (properties[k] == null) properties[k] = items.join(", ");
  }
  return { properties, body: parsed.body };
}

function unquoteFm(v: string): string {
  return v.trim().replace(/^["']|["']$/g, "");
}

/** Scalars plus YAML `- item` lists (`sources:`, `relates_to:`, …). */
export function parseWikiFrontmatter(text: string): {
  properties: Record<string, string>;
  lists: Record<string, string[]>;
  body: string;
} {
  const empty = { properties: {} as Record<string, string>, lists: {} as Record<string, string[]>, body: text };
  if (!text.startsWith("---")) return empty;
  const end = text.indexOf("\n---", 3);
  if (end < 0) return empty;
  const properties: Record<string, string> = {};
  const lists: Record<string, string[]> = {};
  let currentList: string | null = null;
  for (const raw of text.slice(3, end).split("\n")) {
    const item = raw.match(/^\s+-\s+(.*)$/);
    if (item && currentList) {
      const v = unquoteFm(item[1]);
      if (v) lists[currentList].push(v);
      continue;
    }
    const kv = raw.match(/^([A-Za-z_][\w-]*)\s*:\s*(.*)$/);
    if (!kv) continue;
    const key = kv[1];
    const val = unquoteFm(kv[2]);
    if (val === "" || val === "|" || val === ">") {
      currentList = key;
      lists[key] = lists[key] ?? [];
    } else {
      currentList = null;
      properties[key] = val;
    }
  }
  const rest = text.slice(end + 4).replace(/^\n/, "");
  return { properties, lists, body: rest };
}
