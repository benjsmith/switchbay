/**
 * Named agent desks: recurring research over the wiki via desks.json.
 * Research and write; never trade or execute.
 */
import * as fs from "fs";
import * as path from "path";
import { formatDuration, parseDuration } from "./duration";
import { listSchedules, upsertSchedule, type Frequency } from "./schedules";

export type DeskTemplate = {
  id: string;
  title: string;
  agent: string;
  description: string;
  frequency: Frequency;
  durationHours: number | null;
  prompt: string;
  agentMd: string;
};

const SHARED = `You research and write this workspace wiki. You never trade, never
place orders, never send email, never run destructive shell.

Each wave:
1. Read the wiki first (\`search_wiki\`, \`read_wiki_page\`).
2. On Balanced/Maximum effort, spawn two Investigator subagents in the
   SAME turn (\`agent\` / \`runSubagent\`) with distinct queries.
3. Propose sourced pages (\`propose_wiki_page\` / \`propose_page_edit\`).
   Cite [[wikilinks]] and real sources. If you could not verify, say so.
4. \`ce_sweep\` / \`ce_graph_rebuild\` when pages landed.
5. Call \`orchestration_report\` with phase=done and
   detail="OBJECTIVE_MET: yes" when the wave is complete (even if Chat
   stays open). Then print OBJECTIVE_MET: yes.

Tools: ['agent', 'runSubagent', 'search', 'read/file', 'switchbay/*']
`;

export const DESK_TEMPLATES: DeskTemplate[] = [
  {
    id: "wiki-curator",
    title: "Wiki curator",
    agent: "Auto",
    description: "Recurring Auto curation of this wiki for a set window.",
    frequency: "hourly",
    durationHours: 8,
    prompt:
      "Curate this wiki for the current desk window. Investigate stale, thin, "
      + "and unlinked pages; propose sourced edits; rebuild the graph when a "
      + "wave lands. Call orchestration_report phase=done when the wave is complete.",
    agentMd: "",
  },
  {
    id: "science-monitor",
    title: "Science monitor",
    agent: "ScienceMonitor",
    description: "Literature and preprint watch → sourced wiki briefs.",
    frequency: "daily",
    durationHours: 8,
    prompt:
      "Run the Science monitor desk. Scan for new papers, preprints, and "
      + "results on the topics this wiki already covers. Update or propose "
      + "wiki pages with citations. Write a dated brief. Research only.",
    agentMd: `---
name: ScienceMonitor
description: Overnight scientific literature monitor for this wiki.
tools: ['agent', 'runSubagent', 'search', 'read/file', 'switchbay/*']
argument-hint: Topics or venues to watch (defaults to this wiki’s coverage)
---
You are the Science monitor for this curiosity-engine wiki.
${SHARED}
Focus on papers, preprints, datasets, and methods. Prefer primary sources
(DOI, arXiv, venue pages) over blogs. A brief is a wiki note or analysis
page dated today, linked to the concepts it updates.
`,
  },
  {
    id: "startup-desk",
    title: "Startup / market desk",
    agent: "StartupDesk",
    description: "Read-only company and market research. Never trades.",
    frequency: "daily",
    durationHours: 8,
    prompt:
      "Run the Startup / market research desk. Watch companies, funding, and "
      + "markets this wiki already covers. Write a dated brief with sources. "
      + "Research and propose only — never trade, never execute.",
    agentMd: `---
name: StartupDesk
description: Read-only startup and market research desk. Never trades.
tools: ['agent', 'runSubagent', 'search', 'read/file', 'switchbay/*']
argument-hint: Companies, sectors, or questions to watch
---
You are a research desk, not a trading desk.
${SHARED}
You may rank theses and list risks. You must not place orders, size
positions, or talk as if you have an account. Every claim needs a
source; mark unverified items as unverified.
`,
  },
  {
    id: "ai-news",
    title: "AI news & tooling",
    agent: "AiNewsDesk",
    description: "Labs, models, and developer-tooling watch for this wiki.",
    frequency: "daily",
    durationHours: 8,
    prompt:
      "Run the AI news & developer-advances desk. Watch labs, model releases, "
      + "frameworks, and tooling this wiki covers. Propose sourced wiki updates "
      + "and a dated brief. Skip slideshows unless asked.",
    agentMd: `---
name: AiNewsDesk
description: AI labs, models, and developer-tooling monitor for this wiki.
tools: ['agent', 'runSubagent', 'search', 'read/file', 'switchbay/*']
argument-hint: Labs, models, or tools to watch
---
You monitor AI research and developer tooling for this wiki.
${SHARED}
Prefer primary lab posts, papers, and changelogs over aggregators.
Separate rumor from shipped releases.
`,
  },
];

export type DeskConfig = {
  id: string;
  title: string;
  agent: string;
  description: string;
  frequency: Frequency;
  /** Human duration: "15 min", "2h", or a fractional hour string. */
  duration: string | null;
  prompt: string;
  enabled: boolean;
};

export const DESKS_REL = path.join(".workbench", "state", "desks.json");

export function desksPath(workspace: string): string {
  return path.join(workspace, DESKS_REL);
}

function loadFile(workspace: string): { version: number; desks: DeskConfig[] } {
  const p = desksPath(workspace);
  if (!fs.existsSync(p)) return { version: 1, desks: [] };
  try {
    const data = JSON.parse(fs.readFileSync(p, "utf8")) as { desks?: unknown };
    const desks = Array.isArray(data.desks) ? data.desks : [];
    return {
      version: 1,
      desks: desks
        .filter((d): d is Record<string, unknown> => !!d && typeof d === "object")
        .map((d) => ({
          id: String(d.id || "").trim() || `desk-${cryptoRandom()}`,
          title: String(d.title || "Untitled").slice(0, 120),
          agent: String(d.agent || "Auto") || "Auto",
          description: String(d.description || ""),
          frequency: (["hourly", "daily", "weekly", "every_n_hours"].includes(String(d.frequency))
            ? d.frequency
            : "daily") as Frequency,
          duration: (() => {
            const raw = d.duration ?? d.duration_hours
              ?? (d.duration_mins != null ? `${d.duration_mins} min` : null);
            const hours = parseDuration(raw);
            return hours != null ? formatDuration(hours) : (typeof d.duration === "string" ? d.duration : null);
          })(),
          prompt: String(d.prompt || ""),
          enabled: d.enabled === true,
        })),
    };
  } catch {
    return { version: 1, desks: [] };
  }
}

function saveFile(workspace: string, data: { version: number; desks: DeskConfig[] }): void {
  const p = desksPath(workspace);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  const tmp = `${p}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify({ version: 1, desks: data.desks }, null, 2) + "\n", "utf8");
  fs.renameSync(tmp, p);
}

function cryptoRandom(): string {
  return Math.random().toString(16).slice(2, 10);
}

function writeAgentMd(workspace: string, template: DeskTemplate): string | undefined {
  if (!template.agentMd) return undefined;
  const dir = path.join(workspace, ".github", "agents");
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, `${template.agent}.agent.md`);
  if (!fs.existsSync(file)) fs.writeFileSync(file, template.agentMd.trim() + "\n", "utf8");
  return file;
}

function templateToDesk(t: DeskTemplate): DeskConfig {
  return {
    id: t.id,
    title: t.title,
    agent: t.agent,
    description: t.description,
    frequency: t.frequency,
    duration: formatDuration(t.durationHours),
    prompt: t.prompt,
    enabled: false,
  };
}

export function listDesks(workspace: string): DeskConfig[] {
  return loadFile(workspace).desks;
}

/** Write the template into desks.json (disabled) and open that file. Does not start a run. */
export function setupDesk(
  workspace: string,
  templateId: string,
): { ok: boolean; text: string; path: string } {
  const t = DESK_TEMPLATES.find((d) => d.id === templateId);
  if (!t) return { ok: false, text: "Unknown desk template.", path: "" };
  const data = loadFile(workspace);
  if (!data.desks.some((d) => d.id === t.id)) data.desks.push(templateToDesk(t));
  writeAgentMd(workspace, t);
  saveFile(workspace, data);
  return {
    ok: true,
    text: `Opened ${DESKS_REL}. Edit the prompt, then Activate when you want it to tick.`,
    path: desksPath(workspace),
  };
}

export function addBlankDesk(workspace: string): { ok: boolean; text: string; path: string } {
  const data = loadFile(workspace);
  const n = data.desks.length + 1;
  data.desks.push({
    id: `desk-${cryptoRandom()}`,
    title: `New desk ${n}`,
    agent: "Auto",
    description: "Edit this file, then Activate on the Agent Dashboard.",
    frequency: "daily",
    duration: "8h",
    prompt: "What should this desk do each run? Research and write the wiki; never trade.",
    enabled: false,
  });
  saveFile(workspace, data);
  return {
    ok: true,
    text: `Added a desk stub in ${DESKS_REL}. Edit it, then Activate.`,
    path: desksPath(workspace),
  };
}

function scheduleForDesk(workspace: string, desk: DeskConfig, enabled: boolean): void {
  const existing = listSchedules(workspace).find((s) => s.desk_id === desk.id);
  const now = Date.now() / 1000;
  const hours = parseDuration(desk.duration);
  const until_at = hours ? now + hours * 3600 : null;
  upsertSchedule(workspace, {
    id: existing?.id,
    title: desk.title,
    prompt: desk.prompt,
    agent: desk.agent,
    frequency: desk.frequency,
    enabled,
    desk_id: desk.id,
    until_at,
    // Do not fire on Activate — wait for the first interval.
    last_run_at: enabled ? now : existing?.last_run_at ?? null,
  });
}

export function setDeskEnabled(
  workspace: string,
  deskId: string,
  enabled: boolean,
): { ok: boolean; text: string } {
  const data = loadFile(workspace);
  const desk = data.desks.find((d) => d.id === deskId);
  if (!desk) return { ok: false, text: "Desk not in desks.json. Set up first." };
  desk.enabled = enabled;
  saveFile(workspace, data);
  scheduleForDesk(workspace, desk, enabled);
  return {
    ok: true,
    text: enabled
      ? `Activated “${desk.title}” (${desk.frequency}). It ticks while this window is open; first run waits for the interval.`
      : `Deactivated “${desk.title}”.`,
  };
}

export function deactivateAllDesks(workspace: string): { ok: boolean; text: string; n: number } {
  const data = loadFile(workspace);
  let n = 0;
  for (const desk of data.desks) {
    if (!desk.enabled) continue;
    desk.enabled = false;
    scheduleForDesk(workspace, desk, false);
    n += 1;
  }
  saveFile(workspace, data);
  for (const s of listSchedules(workspace)) {
    if (s.desk_id && s.enabled) {
      upsertSchedule(workspace, { id: s.id, enabled: false });
      n += 1;
    }
  }
  return { ok: true, n, text: n ? `Deactivated ${n} overnight desk${n === 1 ? "" : "s"}.` : "No overnight desks were active." };
}

/** Dashboard rows: desks.json, plus templates not yet set up. */
export function deskRows(workspace: string): Array<DeskConfig & { installed: boolean }> {
  const installed = listDesks(workspace);
  const seen = new Set(installed.map((d) => d.id));
  const extras = DESK_TEMPLATES
    .filter((t) => !seen.has(t.id))
    .map((t) => ({ ...templateToDesk(t), installed: false }));
  return [
    ...installed.map((d) => ({ ...d, installed: true })),
    ...extras,
  ];
}
