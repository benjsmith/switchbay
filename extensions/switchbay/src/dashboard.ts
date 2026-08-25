/**
 * Agent Dashboard payload + webview HTML. Mirrors the PWA sections
 * (DAG, running, finished, tools, rules, palettes, providers, skills)
 * from disk / vscode.lm / MCP. Nothing talks to :8765.
 */
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import * as vscode from "vscode";
import { ceRoot, kuzuDbExists, readCachedGraph } from "./ce";
import { getMcp, type McpTool } from "./mcp";
import { listRuns, type RunRecord } from "./orch";

export type DashRule = { id: string; trigger: string; action: string };
export type DashSkill = { name: string; description: string; source: string; path: string };
export type DashAgent = { name: string; description: string; tools: string };
export type DashPalette = { name: string; description: string; tools: string[]; source: string };
export type DashModel = { id: string; name: string; vendor: string; family: string };
export type DashWiki = { nodes: number; edges: number; hasKuzu: boolean; folder: string };

export type DashboardPayload = {
  workspace: string;
  wiki: DashWiki;
  runs: RunRecord[];
  agents: DashAgent[];
  tools: McpTool[];
  rules: DashRule[];
  palettes: DashPalette[];
  models: DashModel[];
  skills: DashSkill[];
  host: string;
};

const SHIPPED_PALETTES: DashPalette[] = [
  {
    name: "curate",
    description: "Wiki curator — investigate, verify, propose pages",
    source: "shipped",
    tools: ["search_wiki", "ce_epoch_summary", "ce_planner", "ce_sweep", "ce_lint", "propose_wiki_page"],
  },
  {
    name: "lint",
    description: "CE lint, naming, small page edits",
    source: "shipped",
    tools: ["search_wiki", "ce_lint", "ce_epoch_summary", "ce_naming", "propose_page_edit"],
  },
  {
    name: "ingest",
    description: "Drain vault sources into wiki pages",
    source: "shipped",
    tools: ["ce_ingest", "ce_vault_search", "read_source", "propose_wiki_page", "list_wiki_pages"],
  },
  {
    name: "plot",
    description: "Vega-Lite plots written as wiki figures",
    source: "shipped",
    tools: ["save_plot", "search_wiki", "table_run_sql"],
  },
  {
    name: "deck",
    description: "HTML slideshow from a wiki page",
    source: "shipped",
    tools: ["author_slide", "make_slides_from_doc", "search_wiki"],
  },
  {
    name: "thrusters",
    description: "Mars Hopper (VS Code webview)",
    source: "plugin",
    tools: [],
  },
];

function rulesPath(workspace: string): string {
  return path.join(workspace, ".workbench", "state", "agent_rules.json");
}

function palettesOverridePath(workspace: string): string {
  return path.join(workspace, ".workbench", "state", "command_palettes.json");
}

export function loadRules(workspace: string): DashRule[] {
  const p = rulesPath(workspace);
  if (!fs.existsSync(p)) return [];
  try {
    const data = JSON.parse(fs.readFileSync(p, "utf8")) as { rules?: DashRule[] };
    return Array.isArray(data.rules) ? data.rules.filter((r) => r.trigger && r.action) : [];
  } catch {
    return [];
  }
}

export function deleteRule(workspace: string, id: string): DashRule[] {
  const rules = loadRules(workspace).filter((r) => r.id !== id);
  const p = rulesPath(workspace);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify({ rules }, null, 2) + "\n", "utf8");
  return rules;
}

function loadPaletteOverrides(workspace: string): Record<string, string[]> {
  const p = palettesOverridePath(workspace);
  if (!fs.existsSync(p)) return {};
  try {
    const data = JSON.parse(fs.readFileSync(p, "utf8")) as { overrides?: Record<string, string[]> };
    return data.overrides && typeof data.overrides === "object" ? data.overrides : {};
  } catch {
    return {};
  }
}

function fm(text: string): Record<string, string> {
  if (!text.startsWith("---")) return {};
  const end = text.indexOf("\n---", 3);
  if (end < 0) return {};
  const out: Record<string, string> = {};
  for (const line of text.slice(3, end).split("\n")) {
    const m = line.match(/^([A-Za-z_][\w-]*)\s*:\s*(.*)$/);
    if (!m) continue;
    out[m[1]] = m[2].trim().replace(/^["']|["']$/g, "");
  }
  return out;
}

function scanSkillRoot(root: string, source: string, into: Map<string, DashSkill>): void {
  if (!fs.existsSync(root)) return;
  let entries: fs.Dirent[];
  try {
    entries = fs.readdirSync(root, { withFileTypes: true });
  } catch {
    return;
  }
  for (const e of entries) {
    if (!e.isDirectory()) continue;
    const md = path.join(root, e.name, "SKILL.md");
    if (!fs.existsSync(md)) continue;
    let text = "";
    try { text = fs.readFileSync(md, "utf8"); } catch { continue; }
    const meta = fm(text);
    const name = meta.name || e.name;
    into.set(name, {
      name,
      description: (meta.description || "").slice(0, 280),
      source,
      path: md,
    });
  }
}

function listSkills(workspace: string): DashSkill[] {
  const byName = new Map<string, DashSkill>();
  const ce = ceRoot();
  if (ce) {
    const md = path.join(ce, "SKILL.md");
    if (fs.existsSync(md)) {
      const meta = fm(fs.readFileSync(md, "utf8"));
      byName.set(meta.name || "curiosity-engine", {
        name: meta.name || "curiosity-engine",
        description: (meta.description || "Curiosity Engine wiki skill").slice(0, 280),
        source: "ce",
        path: md,
      });
    }
  }
  const home = os.homedir();
  for (const rel of [".agents/skills", ".claude/skills", ".codex/skills", ".grok/skills", ".cursor/skills"]) {
    scanSkillRoot(path.join(home, rel), "user", byName);
  }
  scanSkillRoot(path.join(workspace, ".workbench", "skills"), "workspace", byName);
  return [...byName.values()].sort((a, b) => a.source.localeCompare(b.source) || a.name.localeCompare(b.name));
}

function listAgents(extensionPath: string): DashAgent[] {
  const dir = path.join(extensionPath, "agents");
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir)
    .filter((f) => f.endsWith(".agent.md"))
    .map((f) => {
      const text = fs.readFileSync(path.join(dir, f), "utf8");
      const meta = fm(text);
      return {
        name: meta.name || f.replace(/\.agent\.md$/, ""),
        description: meta.description || "",
        tools: meta.tools || "",
      };
    });
}

async function listModels(): Promise<DashModel[]> {
  try {
    const models = await vscode.lm.selectChatModels();
    return models.map((m) => ({
      id: m.id,
      name: m.name || m.id,
      vendor: m.vendor || "unknown",
      family: m.family || "",
    }));
  } catch {
    return [];
  }
}

export async function dashboardPayload(
  context: vscode.ExtensionContext,
  workspace: string | undefined,
): Promise<DashboardPayload> {
  const ws = workspace || "";
  const graph = ws ? readCachedGraph(ws) : null;
  const overrides = ws ? loadPaletteOverrides(ws) : {};
  const palettes = SHIPPED_PALETTES.map((p) => (
    overrides[p.name]?.length
      ? { ...p, tools: overrides[p.name], source: "override" }
      : p
  ));
  let tools: McpTool[] = [];
  if (ws) {
    try {
      const mcp = await getMcp(context);
      tools = await mcp.listTools();
    } catch { /* MCP optional for the static panels */ }
  }
  return {
    workspace: ws,
    wiki: {
      folder: ws ? path.basename(ws) : "",
      nodes: graph?.nodes.length ?? 0,
      edges: (graph?.edges || []).length,
      hasKuzu: ws ? kuzuDbExists(ws) : false,
    },
    runs: ws ? listRuns(ws) : [],
    agents: listAgents(context.extensionPath),
    tools,
    rules: ws ? loadRules(ws) : [],
    palettes,
    models: await listModels(),
    skills: ws ? listSkills(ws) : [],
    host: "vscode-plugin",
  };
}

export function agentsDashboardHtml(nonce: string): string {
  return `<!DOCTYPE html>
<html><head>
<meta charset="UTF-8" />
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}'" />
<style>
  :root { color-scheme: dark; }
  body {
    font-family: var(--vscode-font-family);
    font-size: 13px;
    color: var(--vscode-foreground);
    background: var(--vscode-editor-background);
    margin: 0; padding: 1.1rem 1.35rem 2rem;
  }
  h1 { font-size: 1.15rem; font-weight: 600; margin: 0; }
  .head { display: flex; align-items: center; gap: 0.6rem; flex-wrap: wrap; margin-bottom: 0.35rem; }
  .muted { opacity: 0.65; font-size: 0.82rem; }
  .row-btns { display: flex; gap: 0.4rem; margin-left: auto; }
  button {
    font: inherit; cursor: pointer;
    background: var(--vscode-button-secondaryBackground, #3a3d41);
    color: var(--vscode-button-secondaryForeground, #ccc);
    border: 1px solid var(--vscode-widget-border, #444);
    border-radius: 5px; padding: 0.22rem 0.65rem;
  }
  button.primary {
    background: var(--vscode-button-background);
    color: var(--vscode-button-foreground);
    border-color: transparent;
  }
  button:hover { filter: brightness(1.12); }
  section {
    border: 1px solid var(--vscode-widget-border, #333);
    border-radius: 8px;
    padding: 0.75rem 0.95rem 0.85rem;
    margin: 0.85rem 0;
  }
  section.primary { outline: 1px solid var(--vscode-focusBorder, #0078d4); }
  h2 { font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.06em;
       color: var(--vscode-descriptionForeground); margin: 0 0 0.55rem; font-weight: 600; }
  h2 .count {
    display: inline-block; margin-left: 0.45rem; padding: 0 0.4rem;
    border-radius: 999px; font-size: 0.72rem; letter-spacing: 0;
    background: var(--vscode-badge-background); color: var(--vscode-badge-foreground);
    text-transform: none;
  }
  h2 .sub { margin-left: 0.5rem; font-weight: 400; letter-spacing: 0; text-transform: none; opacity: 0.75; }
  .empty { opacity: 0.55; font-size: 0.85rem; }
  ul { list-style: none; margin: 0; padding: 0; }
  li.row {
    display: flex; gap: 0.7rem; align-items: baseline; flex-wrap: wrap;
    padding: 0.32rem 0; border-top: 1px solid var(--vscode-widget-border, #2a2a2a);
  }
  li.row:first-child { border-top: 0; }
  code, .name { font-family: var(--vscode-editor-font-family, ui-monospace, Menlo, monospace); font-size: 0.84em; }
  .name { min-width: 9rem; }
  .desc { opacity: 0.8; flex: 1; min-width: 12rem; }
  .meta { opacity: 0.6; font-size: 0.8rem; }
  .ok { color: var(--vscode-testing-iconPassed, #89d185); }
  .off { opacity: 0.5; }
  .nodes { display: flex; gap: 0.4rem; flex-wrap: wrap; margin-top: 0.35rem; }
  .node {
    padding: 0.15rem 0.5rem; border-radius: 999px; font-size: 0.75rem;
    background: var(--vscode-badge-background); color: var(--vscode-badge-foreground);
  }
  .node.running { outline: 1px solid var(--vscode-focusBorder); }
  .node.done { opacity: 0.8; }
  .node.failed { background: var(--vscode-inputValidation-errorBackground, #5a1d1d); }
  .node.pending { opacity: 0.55; }
  .run { margin: 0.45rem 0 0.7rem; }
  .dag { display: flex; align-items: center; gap: 0.35rem; flex-wrap: wrap; margin: 0.4rem 0; }
  .arrow { opacity: 0.4; }
  pre { white-space: pre-wrap; font-size: 0.78rem; max-height: 8rem; overflow: auto;
        background: var(--vscode-textCodeBlock-background, #1e1e1e); padding: 0.5rem 0.65rem; border-radius: 6px; }
  .wiki { display: flex; gap: 1.2rem; flex-wrap: wrap; }
  .stat strong { display: block; font-size: 1.15rem; }
</style>
</head>
<body>
  <div class="head">
    <h1>Agent Dashboard</h1>
    <div class="row-btns">
      <button type="button" id="curate" class="primary">Curate</button>
      <button type="button" id="agents">Agents window</button>
      <button type="button" id="refresh">Refresh</button>
    </div>
  </div>
  <p class="muted" id="blurb">VS Code Agents window owns the long-running loop. Dashboard reads the workspace DAG, MCP tools, skills, and Copilot models. Nothing on :8765.</p>
  <div id="root">Loading…</div>
  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({
      "&":"&amp;","<":"&lt;",">":"&gt;","\\u0022":"&quot;","'":"&#39;"
    }[c] || c));
    const live = (phase) => !["done","failed","idle"].includes(phase || "");
    const nodeCls = (s) => (s === "running" || s === "agents-session") ? "running"
      : (s === "done" ? "done" : (s === "failed" ? "failed" : "pending"));
    const groupTool = (name) => {
      if (/^(ce_|wiki|search_wiki|read_wiki|list_wiki|propose_)/.test(name)) return "Wiki / CE";
      if (/slide|deck|sketch|author_slide/.test(name)) return "Deck / sketch";
      if (/^plot|save_plot/.test(name)) return "Plot";
      if (/skill|rule/.test(name)) return "Skills / rules";
      return "Other";
    };
    const section = (title, count, sub, inner, primary) =>
      "<section" + (primary ? " class='primary'" : "") + "><h2>" + esc(title)
      + (count != null ? "<span class='count'>" + count + "</span>" : "")
      + (sub ? "<span class='sub'>" + esc(sub) + "</span>" : "")
      + "</h2>" + inner + "</section>";
    const empty = (t) => "<div class='empty'>" + t + "</div>";
    function render(p) {
      const runs = p.runs || [];
      const running = runs.filter((r) => live(r.phase));
      const finished = runs.filter((r) => !live(r.phase));
      const featured = running[0] || runs[0];
      let dag = empty("No DAG yet. Curate to seed Investigate → Verify → Synthesize.");
      if (featured) {
        const pills = (featured.nodes || []).map((n, i) =>
          (i ? "<span class='arrow'>→</span>" : "")
          + "<span class='node " + nodeCls(n.status) + "'>" + esc(n.kind) + " · " + esc(n.status || "pending") + "</span>"
        ).join("");
        dag = "<div class='run'><strong>" + esc(featured.objective || featured.orchestration_id) + "</strong>"
          + "<div class='muted'>" + esc(featured.phase) + " · " + esc(featured.via) + " · " + esc(featured.orchestration_id) + "</div>"
          + "<div class='dag'>" + pills + "</div>"
          + (featured.note ? "<pre>" + esc(String(featured.note).slice(0, 1600)) + "</pre>" : "")
          + "</div>";
      }
      const runCard = (r) => {
        const pills = (r.nodes || []).map((n) =>
          "<span class='node " + nodeCls(n.status) + "'>" + esc(n.kind) + " · " + esc(n.status || "pending") + "</span>"
        ).join("");
        return "<div class='run'><strong>" + esc(r.objective || r.orchestration_id) + "</strong>"
          + "<div class='muted'>" + esc(r.phase) + " · " + esc(r.via || "") + "</div>"
          + "<div class='nodes'>" + pills + "</div></div>";
      };
      const wiki = p.wiki || {};
      const toolsBy = {};
      (p.tools || []).forEach((t) => {
        const g = groupTool(t.name);
        (toolsBy[g] = toolsBy[g] || []).push(t);
      });
      const toolHtml = (p.tools || []).length
        ? Object.keys(toolsBy).sort().map((g) =>
            "<div class='muted' style='margin:0.4rem 0 0.15rem'>" + esc(g) + "</div>"
            + "<ul>" + toolsBy[g].map((t) =>
              "<li class='row'><code class='name'>" + esc(t.name) + "</code><span class='desc'>" + esc(t.description || "") + "</span></li>"
            ).join("") + "</ul>"
          ).join("")
        : empty("MCP tools not listed yet. Open a CE folder so the stdio server can start.");
      const root = document.getElementById("root");
      root.innerHTML = [
        section("Workspace", null, wiki.folder || "no folder",
          "<div class='wiki'>"
          + "<div class='stat'><strong>" + (wiki.nodes || 0) + "</strong><span class='muted'>wiki nodes</span></div>"
          + "<div class='stat'><strong>" + (wiki.edges || 0) + "</strong><span class='muted'>kuzu edges</span></div>"
          + "<div class='stat'><strong>" + (wiki.hasKuzu ? "yes" : "no") + "</strong><span class='muted'>graph.kuzu</span></div>"
          + "</div>"),
        section("Agent Space", featured ? 1 : 0, "file-watched DAG · last effective roster stays visible", dag, true),
        section("Running", running.length, "VS Code Agents window owns the loop · this list is the Switch Bay DAG",
          running.length ? running.map(runCard).join("") : empty("No live DAG. Use Curate or @switchbay /curate.")),
        section("Recently finished", finished.length, "plugin-run.json under the machine-local runs dir",
          finished.length ? finished.map(runCard).join("") : empty("Nothing finished yet.")),
        section("Custom agents", (p.agents || []).length, "Local harness · Auto / Curator / Investigator / Reviewer",
          (p.agents || []).length
            ? "<ul>" + p.agents.map((a) =>
                "<li class='row'><strong class='name'>" + esc(a.name) + "</strong><span class='desc'>" + esc(a.description) + "</span></li>"
              ).join("") + "</ul>"
            : empty("Bundled .agent.md files not found.")),
        section("Tools", (p.tools || []).length, "plugin MCP allowlist (no :8765 tools)", toolHtml),
        section("Rules", (p.rules || []).length, ".workbench/state/agent_rules.json",
          (p.rules || []).length
            ? "<ul>" + p.rules.map((r) =>
                "<li class='row'><span class='desc'><em>“" + esc(r.trigger) + "”</em> → <code>" + esc(r.action) + "</code></span>"
                + "<button data-del-rule='" + esc(r.id) + "' title='Delete'>×</button></li>"
              ).join("") + "</ul>"
            : empty("No rules yet. In the PWA you’d type “when I say X, do Y”. Here they still live in agent_rules.json.")),
        section("Command palettes", (p.palettes || []).length, "slash desks for @switchbay",
          "<ul>" + (p.palettes || []).map((pl) =>
            "<li class='row'><code class='name'>/" + esc(pl.name) + "</code><span class='desc'>" + esc(pl.description)
            + (pl.tools && pl.tools.length ? " · " + pl.tools.map(esc).join(", ") : "")
            + "</span><span class='meta'>" + esc(pl.source) + "</span></li>"
          ).join("") + "</ul>"),
        section("Providers", (p.models || []).length, "vscode.lm · Copilot is the plugin sign-in",
          (p.models || []).length
            ? "<ul>" + p.models.map((m) =>
                "<li class='row'><strong>" + esc(m.name) + "</strong><span class='meta'>" + esc(m.vendor)
                + (m.family ? " · " + esc(m.family) : "") + "</span>"
                + "<span class='ok'>ready</span></li>"
              ).join("") + "</ul>"
            : empty("No vscode.lm models. Sign in to GitHub Copilot in this window.")),
        section("Skills", (p.skills || []).length, "local SKILL.md · click to open",
          (p.skills || []).length
            ? "<ul>" + p.skills.map((s) =>
                "<li class='row'><button data-skill='" + esc(s.path) + "'>" + esc(s.name) + "</button>"
                + "<span class='desc'>" + esc(s.description) + "</span><span class='meta'>" + esc(s.source) + "</span></li>"
              ).join("") + "</ul>"
            : empty("No SKILL.md files found.")),
      ].join("");
      root.querySelectorAll("[data-skill]").forEach((b) => {
        b.addEventListener("click", () => vscode.postMessage({ type: "openSkill", path: b.getAttribute("data-skill") }));
      });
      root.querySelectorAll("[data-del-rule]").forEach((b) => {
        b.addEventListener("click", () => vscode.postMessage({ type: "deleteRule", id: b.getAttribute("data-del-rule") }));
      });
    }
    document.getElementById("refresh").onclick = () => vscode.postMessage({ type: "refresh" });
    document.getElementById("curate").onclick = () => vscode.postMessage({ type: "curate" });
    document.getElementById("agents").onclick = () => vscode.postMessage({ type: "agentsWindow" });
    window.addEventListener("message", (ev) => {
      if (ev.data && ev.data.payload) render(ev.data.payload);
    });
    vscode.postMessage({ type: "ready" });
  </script>
</body></html>`;
}
