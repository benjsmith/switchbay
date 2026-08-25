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

/** Prompt addendum so Auto's loop matches the slider. Agent count is an outcome. */
export function effortInstruction(preference: number): string {
  const label = preferenceLabel(preference);
  if (preference <= 0.2) {
    return `Effort is ${label}: stay single-step. Do not spawn subagents. One wiki search or a short answer is enough.`;
  }
  if (preference >= 0.8) {
    return `Effort is ${label}: use Investigator subagents for independent slices, Reviewer on contested claims, then curate. Extra quality is worth the tokens.`;
  }
  return `Effort is ${label}: one Investigator pass, then curate. Skip Reviewer unless claims conflict.`;
}
