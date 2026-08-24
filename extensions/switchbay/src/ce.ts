import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import { spawn } from "child_process";
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
    return data;
  } catch {
    return null;
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
  const py = pythonBin(repo);
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
