import * as vscode from "vscode";
import { workspaceFolder } from "./paths";

const KEY = "orchestrationPreference";

export const PREF_DEFAULT = 0.5;

export function clampPreference(value: unknown, fallback = PREF_DEFAULT): number {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(0, Math.min(1, n));
}

export function preferenceLabel(value: number): string {
  const s = clampPreference(value);
  if (s <= 0.2) return "Economy";
  if (s >= 0.8) return "Maximum";
  return "Balanced";
}

export function getPreference(): number {
  return clampPreference(
    vscode.workspace.getConfiguration("switchbay").get<number>(KEY),
    PREF_DEFAULT,
  );
}

export async function setPreference(value: number): Promise<number> {
  const v = clampPreference(value);
  const target = workspaceFolder()
    ? vscode.ConfigurationTarget.Workspace
    : vscode.ConfigurationTarget.Global;
  await vscode.workspace.getConfiguration("switchbay").update(KEY, v, target);
  return v;
}

/** CE CURATE spawn plan. Not Switch Bay Investigators. */
export function spawnCuratePlan(preference: number, objective: string): string {
  const label = preferenceLabel(preference);
  const goal = objective.trim() || "this wiki";
  const base = [
    `Effort is ${label}. You are the CE CURATE orchestrator for: ${goal}`,
    "Call ce_wave_prime if this thread has no pick-mode JSON yet.",
    "Execute that mode's Phase 2 with ce_* tools (score_diff → scrub → ce_wiki_commit).",
    "Do not spawn Investigator. Do not use propose_wiki_page for wiki writes.",
  ];
  if (preference <= 0.2) {
    base.push("Stay single-step: you ARE the worker (CE single-session fallback). Do not call agent/runSubagent.");
    return base.join("\n");
  }
  base.push(
    "If the mode needs vision workers, spawn at most TWO Copilot subagents in the SAME turn:",
    "numeric-review → NumericReviewer; multimodal-table-extract → TableExtractor;",
    "figure-extract → FigureExtractor; wire → LinkProposer then LinkClassifier;",
    "create/repair → you write via ce_score_diff; BatchReviewer once at wave end if Maximum.",
  );
  if (preference >= 0.8) {
    base.push("Extra quality is worth the tokens — still at most two subagents per turn.");
  }
  return base.join("\n");
}

/** Prompt addendum so Auto's loop matches the slider. Agent count is an outcome. */
export function spawnPlan(preference: number, objective: string): string {
  const label = preferenceLabel(preference);
  const goal = objective.trim() || "this wiki";
  if (preference <= 0.2) {
    return `Effort is ${label}: stay single-step. Do not call agent/runSubagent. One search_wiki or a short edit is enough.`;
  }
  const a = `Investigator A — stale, thin, or poorly linked pages related to: ${goal}`;
  const b = `Investigator B — missing sources, contradictions, and planner mode for: ${goal}`;
  const parallel = [
    `Effort is ${label}. FIRST TURN (mandatory): emit TWO agent/runSubagent tool calls in the SAME response so they run in parallel.`,
    `Both subagents are named Investigator. Distinct prompts:`,
    `1. ${a}`,
    `2. ${b}`,
    `Do not search_wiki, ce_planner, or propose_* yourself until both briefs return. Copilot runs those two workers concurrently.`,
  ];
  if (preference >= 0.8) {
    parallel.push("If the briefs conflict, run Reviewer as a third subagent on the contested pages, then you curate.");
    parallel.push("Extra quality is worth the tokens.");
  } else {
    parallel.push("Then you curate (propose_wiki_page / propose_page_edit, ce_sweep, ce_graph_rebuild). Skip Reviewer unless the briefs disagree.");
  }
  return parallel.join("\n");
}

export function effortInstruction(preference: number, objective = ""): string {
  return spawnPlan(preference, objective);
}
