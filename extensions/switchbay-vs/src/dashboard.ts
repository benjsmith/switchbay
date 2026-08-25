/**
 * Agent Dashboard payload + webview HTML. Mirrors the PWA sections
 * (DAG, running, finished, tools, rules, palettes, providers, skills)
 * from disk / vscode.lm / MCP. Nothing talks to :8765.
 */
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import * as vscode from "vscode";
import { listNamedAgents, type NamedAgent } from "./agentsSession";
import { ceRoot, kuzuDbExists, readCachedGraph } from "./ce";
import { getMcp, type McpTool } from "./mcp";
import { listRuns, type RunRecord } from "./orch";
import { listConfiguredLocalModels, probeLocalBackends, type LocalProbe } from "./localModels";
import { getPreference, preferenceLabel } from "./preference";
import { listSchedules, type Schedule } from "./schedules";

export type DashRule = { id: string; trigger: string; action: string };
export type DashSkill = { name: string; description: string; source: string; path: string };
export type DashAgent = NamedAgent;
export type DashPalette = { name: string; description: string; tools: string[]; source: string };
export type DashModel = {
  id: string;
  name: string;
  vendor: string;
  family: string;
  source: "vscode.lm" | "local-settings";
};
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
  localRunning: LocalProbe[];
  skills: DashSkill[];
  schedules: Schedule[];
  preference: number;
  preferenceLabel: string;
  version: string;
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



async function listModels(): Promise<DashModel[]> {
  const out: DashModel[] = [];
  const seen = new Set<string>();
  try {
    for (const m of await vscode.lm.selectChatModels()) {
      const id = `${m.vendor}:${m.id}`;
      seen.add(id);
      out.push({
        id: m.id,
        name: m.name || m.id,
        vendor: m.vendor || "unknown",
        family: m.family || "",
        source: "vscode.lm",
      });
    }
  } catch { /* vscode.lm optional */ }
  for (const m of listConfiguredLocalModels()) {
    const key = `switchbay-local:${m.backend}:${m.model}`;
    if (seen.has(key)) continue;
    out.push({
      id: `${m.backend}:${m.model}`,
      name: m.name,
      vendor: "switchbay-local",
      family: m.backend,
      source: "local-settings",
    });
  }
  return out;
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
    agents: listNamedAgents(context.extensionPath, ws),
    schedules: ws ? listSchedules(ws) : [],
    preference: getPreference(),
    preferenceLabel: preferenceLabel(getPreference()),
    version: String((context.extension.packageJSON as { version?: string }).version || ""),
    tools,
    rules: ws ? loadRules(ws) : [],
    palettes,
    models: await listModels(),
    localRunning: await probeLocalBackends(),
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
  .orch {
    display: flex; align-items: center; gap: 0.45rem; flex-wrap: wrap;
    margin: 0.55rem 0 0.15rem;
  }
  .orch input[type=range] { width: 11rem; accent-color: var(--vscode-focusBorder); }
  .orch-label { font-weight: 600; min-width: 5.5rem; }
  .form { display: grid; gap: 0.35rem; margin: 0.4rem 0 0.6rem; }
  .form input, .form select, .form textarea {
    font: inherit; color: inherit;
    background: var(--vscode-input-background);
    border: 1px solid var(--vscode-input-border, #444);
    border-radius: 4px; padding: 0.28rem 0.45rem;
  }
  .form textarea { min-height: 4.2rem; resize: vertical; }
  .form-row { display: flex; gap: 0.4rem; flex-wrap: wrap; align-items: center; }
  .chip { font-size: 0.75rem; opacity: 0.7; }
</style>
</head>
<body>
  <div class="head">
    <h1>Agent Dashboard</h1>
    <div class="row-btns">
      <button type="button" id="curate" class="primary">Curate</button>
      <button type="button" id="agents">Agents window</button>
      <button type="button" id="update">Update…</button>
      <button type="button" id="refresh">Refresh</button>
    </div>
  </div>
  <p class="muted" id="blurb">VS Code Agents window owns the long-running loop. Nothing on :8765. Closing VS Code stops scheduled runs.</p>
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
    const labelFor = (n) => n <= 0.2 ? "Economy" : n >= 0.8 ? "Maximum" : "Balanced";
    function render(p) {
      const runs = p.runs || [];
      const running = runs.filter((r) => live(r.phase));
      const finished = runs.filter((r) => !live(r.phase));
      const featured = running[0] || runs[0];
      const pref = typeof p.preference === "number" ? p.preference : 0.5;
      const blurb = document.getElementById("blurb");
      if (blurb) blurb.textContent = "v" + (p.version || "?") + " · Agents window owns the loop · schedules fire only while VS Code is open · nothing on :8765";
      let dag = empty("No DAG yet. Curate to seed a run. Economy is a single step; Maximum is Investigate → Verify → Synthesize.");
      if (featured) {
        const pills = (featured.nodes || []).map((n, i) =>
          (i ? "<span class='arrow'>→</span>" : "")
          + "<span class='node " + nodeCls(n.status) + "'>" + esc(n.kind) + " · " + esc(n.status || "pending") + "</span>"
        ).join("");
        dag = "<div class='run'><strong>" + esc(featured.objective || featured.orchestration_id) + "</strong>"
          + "<div class='muted'>" + esc(featured.phase) + " · " + esc(featured.via) + " · "
          + esc(labelFor(featured.preference || pref)) + " · " + esc(featured.orchestration_id) + "</div>"
          + "<div class='dag'>" + pills + "</div>"
          + (featured.note ? "<pre>" + esc(String(featured.note).slice(0, 1600)) + "</pre>" : "")
          + "</div>";
      }
      const runCard = (r) => {
        const pills = (r.nodes || []).map((n) =>
          "<span class='node " + nodeCls(n.status) + "'>" + esc(n.kind) + " · " + esc(n.status || "pending") + "</span>"
        ).join("");
        return "<div class='run'><strong>" + esc(r.objective || r.orchestration_id) + "</strong>"
          + "<div class='muted'>" + esc(r.phase) + " · " + esc(r.via || "") + " · " + esc(labelFor(r.preference || 0.5)) + "</div>"
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
      const invocables = (p.agents || []).filter((a) => a.invocable !== false);
      const agentOpts = invocables.map((a) =>
        "<option value='" + esc(a.name) + "'>" + esc(a.name) + (a.source === "workspace" ? " (workspace)" : "") + "</option>"
      ).join("");
      const schedules = p.schedules || [];
      const schedRows = schedules.map((s) =>
        "<li class='row'><strong class='name'>" + esc(s.title) + "</strong>"
        + "<span class='desc'>" + esc(s.agent || "Auto") + " · " + esc(s.frequency)
        + (s.frequency === "every_n_hours" ? " · " + esc(s.every_hours) + "h" : "")
        + "</span>"
        + (s.enabled === false ? "<span class='chip'>off</span>" : "")
        + (s.running_run_id ? "<span class='chip'>running</span>" : "")
        + "<span class='meta'>" + (s.run_count || 0) + " runs</span>"
        + "<button data-run-sch='" + esc(s.id) + "'>Run</button>"
        + "<button data-toggle-sch='" + esc(s.id) + "' data-on='" + (s.enabled === false ? "0" : "1") + "'>"
        + (s.enabled === false ? "Enable" : "Disable") + "</button>"
        + "<button data-del-sch='" + esc(s.id) + "' title='Delete'>×</button></li>"
        + "<pre>" + esc((s.prompt || "").slice(0, 280) || "(empty prompt)") + "</pre>"
      ).join("");
      const schedForm = "<div class='form' id='sch-form'>"
        + "<input id='sch-title' placeholder='Title' value='Overnight desk' />"
        + "<div class='form-row'>"
        + "<select id='sch-agent'>" + agentOpts + "</select>"
        + "<select id='sch-freq'>"
        + "<option value='hourly'>Hourly</option><option value='daily' selected>Daily</option>"
        + "<option value='weekly'>Weekly</option><option value='every_n_hours'>Every N hours</option>"
        + "</select>"
        + "<input id='sch-n' type='number' min='1' value='24' style='width:4.5rem' title='Hours when Every N' />"
        + "</div>"
        + "<textarea id='sch-prompt' placeholder='Prompt this named agent will run'></textarea>"
        + "<div class='form-row'><button type='button' class='primary' id='sch-save'>Add schedule</button>"
        + "<span class='muted'>New schedules are due on the next tick unless disabled. Tick is ~20s while this window is open.</span></div>"
        + "</div>";
      const orch = "<div class='orch'>"
        + "<span>Economy</span>"
        + "<input type='range' id='orch-pref' min='0' max='100' step='5' value='" + Math.round(pref * 100) + "' aria-label='Cost versus performance' />"
        + "<span>Maximum</span>"
        + "<span class='orch-label' id='orch-label'>" + esc(p.preferenceLabel || labelFor(pref)) + "</span>"
        + "</div>"
        + "<p class='muted'>How much extra quality Auto may buy. Agent count is an outcome of this slider, not a separate control.</p>";
      const root = document.getElementById("root");
      root.innerHTML = [
        section("Workspace", null, wiki.folder || "no folder",
          "<div class='wiki'>"
          + "<div class='stat'><strong>" + (wiki.nodes || 0) + "</strong><span class='muted'>wiki nodes</span></div>"
          + "<div class='stat'><strong>" + (wiki.edges || 0) + "</strong><span class='muted'>kuzu edges</span></div>"
          + "<div class='stat'><strong>" + (wiki.hasKuzu ? "yes" : "no") + "</strong><span class='muted'>graph.kuzu</span></div>"
          + "</div>"),
        section("Orchestrator", null, "Economy ← Balanced → Maximum", orch, true),
        section("Agent Space", featured ? 1 : 0, "file-watched DAG · last effective roster stays visible", dag),
        section("Running", running.length, "VS Code Agents window owns the loop · this list is the Switch Bay DAG",
          running.length ? running.map(runCard).join("") : empty("No live DAG. Use Curate or @switchbay /curate.")),
        section("Recently finished", finished.length, "plugin-run.json under the machine-local runs dir",
          finished.length ? finished.map(runCard).join("") : empty("Nothing finished yet.")),
        section("Schedules", schedules.length, ".workbench/state/schedules.json · named agents",
          schedForm + (schedules.length ? "<ul>" + schedRows + "</ul>" : empty("No schedules yet. Pick an agent and Add schedule."))),
        section("Custom agents", (p.agents || []).length, "Chat agents (.agent.md) — not Skills. Workspace: .github/agents/",
          (p.agents || []).length
            ? "<ul>" + p.agents.map((a) =>
                "<li class='row'><strong class='name'>" + esc(a.name) + "</strong><span class='desc'>" + esc(a.description) + "</span>"
                + "<span class='meta'>" + esc(a.source) + (a.invocable === false ? " · subagent" : "") + "</span>"
                + "<button data-open-agent='" + esc(a.path) + "'>Open</button>"
                + (a.invocable === false ? "" : "<button data-run-agent='" + esc(a.name) + "'>Run</button>")
                + "</li>"
              ).join("") + "</ul>"
            : empty("No .agent.md files found. /create-agent writes .github/agents/.")),
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
        section("Models", (p.models || []).length, "vscode.lm API — not the Chat model picker",
          (function () {
            const rows = (p.models || []).map((m) =>
              "<li class='row'><strong>" + esc(m.name) + "</strong>"
              + "<span class='meta'>" + esc(m.vendor) + (m.family ? " · " + esc(m.family) : "")
              + " · " + esc(m.id) + "</span>"
              + "<span class='ok'>" + (m.source === "local-settings" ? "local" : "lm") + "</span></li>"
            ).join("");
            const probes = (p.localRunning || []).map((b) =>
              "<li class='row'><strong>" + esc(b.backend) + "</strong>"
              + "<span class='desc'>" + esc(b.hint) + "</span>"
              + (b.ok ? "<span class='ok'>running</span>" : "<span class='off'>not found</span>")
              + "</li>"
            ).join("");
            return "<p class='muted'>This list is <code>vscode.lm.selectChatModels()</code> — Copilot's Language Model API plus any Switch Bay local backends you added. "
              + "The Chat model picker is a different Copilot Chat catalog (Auto routing, Copilot CLI, subscriber SKUs). Duplicate display names are different ids.</p>"
              + "<div class='form-row' style='margin:0.35rem 0 0.6rem'><button type='button' class='primary' id='add-local'>Add Ollama / MLX / llama.cpp…</button>"
              + "<span class='muted'>Helper scans :11434 / :8080 / :8888 and registers them as vendor “Switch Bay VS Local”.</span></div>"
              + ((p.models || []).length ? "<ul>" + rows + "</ul>" : empty("No vscode.lm models. Sign in to GitHub Copilot, or add a local backend."))
              + "<div class='muted' style='margin:0.7rem 0 0.2rem'>On this machine</div>"
              + (probes ? "<ul>" + probes + "</ul>" : empty("Local backend scan failed."));
          })()),
        section("Skills", (p.skills || []).length, "SKILL.md toolkits (curiosity-engine, caveman…) — not Chat agents",
          (p.skills || []).length
            ? "<ul>" + p.skills.map((s) =>
                "<li class='row'><button data-skill='" + esc(s.path) + "'>" + esc(s.name) + "</button>"
                + "<span class='desc'>" + esc(s.description) + "</span><span class='meta'>" + esc(s.source) + "</span></li>"
              ).join("") + "</ul>"
            : empty("No SKILL.md files found.")),
      ].join("");
      const slider = document.getElementById("orch-pref");
      const lab = document.getElementById("orch-label");
      if (slider) {
        slider.addEventListener("input", () => {
          const v = Number(slider.value) / 100;
          if (lab) lab.textContent = labelFor(v);
        });
        slider.addEventListener("change", () => {
          vscode.postMessage({ type: "setPreference", value: Number(slider.value) / 100 });
        });
      }
      document.getElementById("sch-save")?.addEventListener("click", () => {
        vscode.postMessage({
          type: "saveSchedule",
          item: {
            title: document.getElementById("sch-title").value,
            agent: document.getElementById("sch-agent").value,
            frequency: document.getElementById("sch-freq").value,
            every_hours: Number(document.getElementById("sch-n").value) || 24,
            prompt: document.getElementById("sch-prompt").value,
            enabled: true,
          },
        });
      });
      root.querySelectorAll("[data-skill]").forEach((b) => {
        b.addEventListener("click", () => vscode.postMessage({ type: "openSkill", path: b.getAttribute("data-skill") }));
      });
      root.querySelectorAll("[data-del-rule]").forEach((b) => {
        b.addEventListener("click", () => vscode.postMessage({ type: "deleteRule", id: b.getAttribute("data-del-rule") }));
      });
      root.querySelectorAll("[data-run-sch]").forEach((b) => {
        b.addEventListener("click", () => vscode.postMessage({ type: "runSchedule", id: b.getAttribute("data-run-sch") }));
      });
      root.querySelectorAll("[data-del-sch]").forEach((b) => {
        b.addEventListener("click", () => vscode.postMessage({ type: "deleteSchedule", id: b.getAttribute("data-del-sch") }));
      });
      root.querySelectorAll("[data-toggle-sch]").forEach((b) => {
        b.addEventListener("click", () => vscode.postMessage({
          type: "toggleSchedule",
          id: b.getAttribute("data-toggle-sch"),
          enabled: b.getAttribute("data-on") !== "1",
        }));
      });
      root.querySelectorAll("[data-run-agent]").forEach((b) => {
        b.addEventListener("click", () => vscode.postMessage({ type: "runAgent", agent: b.getAttribute("data-run-agent") }));
      });
      root.querySelectorAll("[data-open-agent]").forEach((b) => {
        b.addEventListener("click", () => vscode.postMessage({ type: "openSkill", path: b.getAttribute("data-open-agent") }));
      });
      document.getElementById("add-local")?.addEventListener("click", () => {
        vscode.postMessage({ type: "localModels" });
      });
    }
    document.getElementById("refresh").onclick = () => vscode.postMessage({ type: "refresh" });
    document.getElementById("curate").onclick = () => vscode.postMessage({ type: "curate" });
    document.getElementById("agents").onclick = () => vscode.postMessage({ type: "agentsWindow" });
    document.getElementById("update").onclick = () => vscode.postMessage({ type: "checkUpdate" });
    window.addEventListener("message", (ev) => {
      if (ev.data && ev.data.payload) render(ev.data.payload);
    });
    vscode.postMessage({ type: "ready" });
  </script>
</body></html>`;
}
