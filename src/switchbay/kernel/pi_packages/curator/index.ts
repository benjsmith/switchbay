/**
 * Switch Bay Pi pack. Typed CE + research tools, no bash, no MCP inside Pi.
 *
 * Each tool is `python -m switchbay.ce_cli --tool <name> --workspace <cwd>`.
 * The kernel spawns Pi with --no-builtin-tools --no-skills.
 *
 * Parameters MUST be named TypeBox fields. An empty object with
 * additionalProperties allowed makes the model spend the turn on
 * schema archaeology (XML tags, quoted blobs, `args` lists) instead
 * of calling the tool.
 */
import { spawn } from "node:child_process";
import { Type } from "typebox";

type Pi = {
  registerTool: (tool: {
    name: string;
    label: string;
    description: string;
    parameters: unknown;
    execute: (...args: unknown[]) => Promise<unknown>;
  }) => void;
  registerProvider?: (id: string, cfg: Record<string, unknown>) => void;
};

const S = (description: string) => Type.String({ description });
const OptS = (description: string) => Type.Optional(Type.String({ description }));
const OptI = (description: string) => Type.Optional(Type.Integer({ description }));
const OptB = (description: string) => Type.Optional(Type.Boolean({ description }));
const Empty = Type.Object({});

const SlideCard = Type.Object({
  title: OptS("Card title"),
  body: OptS("Card body"),
});

const Slide = Type.Object({
  heading: S("Slide heading (required)"),
  layout: OptS("title | quote | stats | chart | compare | timeline | table | cards | bullets | split | media | close"),
  id: OptS("Optional slide id"),
  eyebrow: OptS("Small kicker above the heading"),
  lede: OptS("One-sentence thesis or lede"),
  bullets: Type.Optional(Type.Array(Type.String(), { description: "Bullet lines" })),
  cards: Type.Optional(Type.Array(SlideCard, { description: "Card objects" })),
  media: OptS("Workspace-relative media path"),
  media_kind: OptS("image | video"),
  figure: OptS("Wiki figure stem to embed"),
  image_prompt: OptS("Generate a figure from this prompt"),
  wiki_table: OptS("wiki/tables/tbl-* stem; inlined as a table"),
  cite: OptS("vault/ or wiki/ citation path"),
  notes: OptS("Speaker notes"),
});

type ToolSpec = {
  name: string;
  description: string;
  parameters: unknown;
};

const TOOLS: ToolSpec[] = [
  {
    name: "ce_wave_prime",
    description: "CURATE Phase 1: pick-mode via switchbay.ce_host. Call first on /curate.",
    parameters: Type.Object({
      mode: OptS("Optional /curate alias or CE wave mode (tables, figures, numeric, repair, …)"),
    }),
  },
  {
    name: "ce_score_diff",
    description: "Score a wiki page write (CE write path). Then ce_scrub_check and ce_wiki_commit.",
    parameters: Type.Object({
      page: S("Wiki page path, e.g. wiki/concepts/attention.md"),
      new_text: OptS("Full page body to gate and write"),
      new_text_file: OptS("Path to a file containing the new page body"),
      new_page: OptB("True when creating a page that does not exist yet"),
    }),
  },
  {
    name: "ce_scrub_check",
    description: "Injection/URL scrub before wiki commit",
    parameters: Type.Object({
      mode: OptS("wiki (default) or vault"),
      path: OptS("Wiki or vault path to scrub"),
    }),
  },
  {
    name: "ce_wiki_commit",
    description: "git -C wiki add -A && commit. Message required; no vault body in the message.",
    parameters: Type.Object({
      message: S("Commit message, e.g. curate: numeric-review"),
    }),
  },
  {
    name: "ce_dispatch_worker",
    description:
      "Fill a CE worker prompt from .curator/prompts.md. Does not launch a child. On the rail the host intercepts this tool; Pi has no launch bridge — use the returned prompt in-session or skip.",
    parameters: Type.Object({
      role: S("figure_extractor | scientific_table_extractor | numeric_transcription_review | …"),
      brief: OptS("Short brief for the worker"),
      substitutions: OptS("JSON object of <PLACEHOLDER> → value"),
    }),
  },
  {
    name: "ce_lint",
    description: "Wiki health scores (lint_scores.py). Higher = worse.",
    parameters: Type.Object({
      top: OptI("How many worst pages"),
      minimal: OptB("Minimal output"),
    }),
  },
  {
    name: "ce_planner",
    description: "CURATE mode picker (planner.py pick-mode).",
    parameters: Type.Object({
      verb: OptS("pick-mode (default) or another planner.py verb"),
    }),
  },
  {
    name: "ce_tables",
    description: "Class-table store (tables.py). verb: list, schema, query, sync, …",
    parameters: Type.Object({
      verb: OptS("tables.py verb (default list)"),
    }),
  },
  {
    name: "ce_figures",
    description: "Figure assets (figures.py). verb: list, check, regen, render-all, …",
    parameters: Type.Object({
      verb: OptS("figures.py verb (default list)"),
    }),
  },
  {
    name: "ce_evolve_guard",
    description: "Evolve-guard snapshot/check/hash. Snapshot at wave start; check at wave end.",
    parameters: Type.Object({
      verb: OptS("snapshot | check | hash"),
      path: OptS("Snapshot file (default .curator/.guard.snapshot)"),
    }),
  },
  {
    name: "ce_graph_rebuild",
    description: "Rebuild the wiki graph from pages on disk",
    parameters: Empty,
  },
  {
    name: "ce_epoch_summary",
    description: "CE epoch summary (wiki snapshot)",
    parameters: Empty,
  },
  {
    name: "ce_scan",
    description: "Scan registered project-dirs for new/changed files",
    parameters: Type.Object({
      verb: OptS("all (default) or a scan.py subcommand"),
    }),
  },
  {
    name: "ce_query",
    description: "Structured vault/wiki query. Start with verb=introspect, then sql or cypher.",
    parameters: Type.Object({
      verb: S("introspect | sql | cypher | classify"),
      query: OptS("SQL or Cypher string; omit for introspect"),
    }),
  },
  {
    name: "ce_graph_retrieve",
    description: "Entity-gated graph retrieve (graph.py retrieve)",
    parameters: Type.Object({
      query: S("Named-entity or topical query"),
      seeds: OptI("Semantic seed count"),
      limit: OptI("Max pages"),
      hops: OptI("Graph hops"),
      route: OptS("auto | graph | blend"),
    }),
  },
  {
    name: "search_wiki",
    description: "Search wiki pages by keywords",
    parameters: Type.Object({
      query: S("Keywords, e.g. transformer attention scaling"),
      limit: OptI("Max results (default 8, cap 25)"),
    }),
  },
  {
    name: "read_wiki_page",
    description: "Read one wiki page (frontmatter + body)",
    parameters: Type.Object({
      page: S("Page path, wikilink target, stem, or title"),
    }),
  },
  {
    name: "read_source",
    description: "Read a vault source as readable text. Path stays inside the workspace.",
    parameters: Type.Object({
      path: S("Workspace-relative file (vault extract, cache original, or staged text)"),
    }),
  },
  {
    name: "list_wiki_pages",
    description: "List wiki pages, optionally filtered by type",
    parameters: Type.Object({
      type: OptS("Optional page type: concept, entity, fact, evidence, analysis, note, source"),
    }),
  },
  {
    name: "create_slideshow",
    description:
      "Write an HTML slideshow under slideshows/<slug>/. title and slides[] required; every slide needs heading; title needs a lede; inline wiki_table or a figure; close is the takeaway not wiki metadata.",
    parameters: Type.Object({
      title: S("Deck title"),
      slides: Type.Array(Slide, { description: "6–8 visual slides; each object needs heading" }),
      slug: OptS("Optional URL-safe package name; derived from title by default"),
      wiki_topics: Type.Optional(Type.Array(Type.String(), { description: "Wiki themes used" })),
    }),
  },
  {
    name: "ce_ingest",
    description: "Ingest files into the vault (local_ingest.py). File or directory path.",
    parameters: Type.Object({
      path: OptS("Workspace-relative file or directory (default vault/raw/)"),
      source_path_only: OptB("Index the path without copying"),
    }),
  },
  {
    name: "ce_sweep",
    description: "CE sweep.py hygiene / queue verbs. Always targets wiki.",
    parameters: Type.Object({
      verb: OptS("scan | fix-index | sync-notes | sync-todos | … (default scan)"),
      extraction: OptS("--extraction path"),
      json_file: OptS("--json-file path"),
      tab_page: OptS("--tab-page for apply-numeric-review"),
      verdict: OptS("apply-numeric-review JSON (stringified object ok)"),
    }),
  },
  {
    name: "ce_run",
    description: "Run any curiosity-engine script against this workspace. Prefer named ce_* tools.",
    parameters: Type.Object({
      script: S("CE script name, e.g. sweep.py"),
      args: OptS("Arguments after the script (JSON array string or space-separated)"),
      json: OptB("Expect JSON stdout (default true)"),
      timeout: OptI("Seconds (default 180, cap 900)"),
    }),
  },
  {
    name: "research_search",
    description:
      "Search papers (OpenAlex) and the open web. Returns titles/URLs only — then research_fetch.",
    parameters: Type.Object({
      query: S("Search query"),
      source: OptS("auto (default) | web | papers"),
      limit: OptI("Max hits (default 8, cap 12)"),
    }),
  },
  {
    name: "research_fetch",
    description:
      "Download an http(s) URL into vault/raw/ and ce_ingest. Private/loopback hosts refused.",
    parameters: Type.Object({
      url: S("http(s) URL to fetch"),
      ingest: OptB("Run ce_ingest after save (default true)"),
    }),
  },
  {
    name: "run_command",
    description: "Run a program in the workspace. Builds, tests, git. Not a login shell.",
    parameters: Type.Object({
      command: OptS("Command line (split like a shell)"),
      cwd: OptS("Optional cwd relative to the workspace"),
    }),
  },
  {
    name: "read_workspace_plan",
    description: "Read charter.md, work-plan.md, and workspace-log.md",
    parameters: Empty,
  },
  {
    name: "update_work_plan",
    description: "Overwrite .workbench/plan/work-plan.md",
    parameters: Type.Object({ text: S("Full work-plan markdown") }),
  },
  {
    name: "append_workspace_log",
    description: "Append a dated entry to workspace-log.md",
    parameters: Type.Object({ text: S("Log entry") }),
  },
  {
    name: "propose_charter_edit",
    description: "Propose an edit to charter.md (Reviews). Do not use update_work_plan for this.",
    parameters: Type.Object({ text: S("Full proposed charter markdown") }),
  },
  {
    name: "propose_wiki_page",
    description: "Write a NEW wiki page. kind, title, body required.",
    parameters: Type.Object({
      kind: S("concept | entity | analysis | fact | evidence | source | note"),
      title: S("Page title"),
      body: S("Full page body (frontmatter + markdown)"),
    }),
  },
  {
    name: "propose_page_edit",
    description: "Edit an existing wiki page. path + full new body.",
    parameters: Type.Object({
      path: S("wiki-relative path"),
      body: S("Full new page body"),
    }),
  },
  {
    name: "create_report",
    description: "Write a rich HTML report and open the Report tab",
    parameters: Type.Object({
      title: S("Report title"),
      summary: S("One-line chat summary"),
      html: S("Complete self-contained HTML page"),
    }),
  },
  {
    name: "save_plot",
    description: "Save a Vega-Lite spec and open the Plot tab",
    parameters: Type.Object({
      spec: S("Vega-Lite spec as a JSON string"),
      title: OptS("Plot title"),
    }),
  },
  {
    name: "list_threads",
    description: "List this workspace's conversation threads",
    parameters: Empty,
  },
  {
    name: "ask_thread",
    description: "Ask another thread's agent a question (A2A). Never ask the current thread.",
    parameters: Type.Object({
      message: S("Question for the other thread"),
      thread_id: OptS("Target thread id"),
    }),
  },
  {
    name: "load_skill",
    description: "Load a skill. Frontmatter first; section for a chapter.",
    parameters: Type.Object({
      name: S("Skill name"),
      detail: OptS("frontmatter (default) | full"),
      section: OptS("Heading to load"),
    }),
  },
];

function pythonBin(): string {
  return process.env.SWITCHBAY_PYTHON || process.env.PYTHON || "python3";
}

function runCli(tool: string, workspace: string, input: unknown): Promise<{ code: number; stdout: string; stderr: string }> {
  const payload = (input && typeof input === "object") ? input : {};
  const args = [
    "-m",
    "switchbay.ce_cli",
    "--workspace",
    workspace,
    "--tool",
    tool,
    "--input",
    JSON.stringify(payload),
  ];
  const env = { ...process.env };
  if (process.env.SWITCHBAY_SRC) {
    env.PYTHONPATH = process.env.SWITCHBAY_SRC;
  }
  return new Promise((resolve, reject) => {
    const child = spawn(pythonBin(), args, { cwd: workspace, env });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (c) => {
      stdout += String(c);
    });
    child.stderr.on("data", (c) => {
      stderr += String(c);
    });
    child.on("error", reject);
    child.on("close", (code) => {
      resolve({ code: code ?? 1, stdout, stderr });
    });
  });
}

function registerMlx(pi: Pi) {
  const baseUrl = (process.env.SWITCHBAY_MLX_URL || "").trim();
  const model = (process.env.SWITCHBAY_MLX_MODEL || "").trim();
  if (!baseUrl || !model || typeof pi.registerProvider !== "function") {
    return;
  }
  pi.registerProvider("mlx", {
    name: "MLX",
    baseUrl,
    apiKey: "local",
    api: "openai-completions",
    models: [
      {
        id: model,
        name: model,
        reasoning: false,
        input: ["text"],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: 32768,
        maxTokens: 2048,
      },
    ],
  });
}

function allowedToolNames(): Set<string> | null {
  const raw = (process.env.SWITCHBAY_PACKAGE_TOOLS || "").trim();
  if (!raw) {
    return null;
  }
  return new Set(raw.split(",").map((s) => s.trim()).filter(Boolean));
}

export default function (pi: Pi) {
  registerMlx(pi);
  const allow = allowedToolNames();
  for (const spec of TOOLS) {
    if (allow && !allow.has(spec.name)) {
      continue;
    }
    pi.registerTool({
      name: spec.name,
      label: spec.name,
      description: spec.description,
      parameters: spec.parameters,
      async execute(_id: unknown, params: unknown) {
        const result = await runCli(spec.name, process.cwd(), params);
        const text = [result.stdout.trim(), result.stderr.trim(), `exit=${result.code}`]
          .filter(Boolean)
          .join("\n\n");
        return {
          content: [{ type: "text", text: text || "(no output)" }],
          details: { exitCode: result.code },
          isError: result.code !== 0,
        };
      },
    });
  }
}
