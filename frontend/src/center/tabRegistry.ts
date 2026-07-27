import type { ComponentType } from "react";
import type { TabSpec } from "../ws";
import type { GraphData } from "../widgets/graph/types";
import type { TerminalWsApi } from "../rail/PtyThreadSurface";

/**
 * Tab-kind registry — the extension point that lets pack-supplied
 * (or dynamically-loaded) tab components plug into the center tab
 * strip without TabStrip itself knowing anything about them.
 *
 * Built-in tabs register themselves at app startup (see
 * `registerBuiltinTabs` below); packs register theirs after their
 * JS modules are dynamically imported (see `loadPackTabs` below).
 *
 * Components receive a `TabContext` rather than positional args so
 * callers can extend the context (selection layer, graph data,
 * theme info, etc.) without rewriting every entry.
 */

export type TabContext = {
  tab: TabSpec;
  graphData: GraphData | null;
  graphError: string | null;
  /** term.* adapter over the shared rail WS — for tab kinds that host
   *  a PTY surface (popped-out terminal tabs). */
  termWs: TerminalWsApi | null;
};

export type TabComponent = ComponentType<TabContext>;

// Tabs that own their own padding/scroll and want sy-tab-content--bare.
// Built-in tabs flag themselves via `bare: true` at register time;
// pack-supplied tabs pick the same flag in their registration call.
type Entry = { component: TabComponent; bare: boolean };

const REGISTRY = new Map<string, Entry>();
// Aliases: secondary kind names that resolve to the same entry —
// reserved for future tab-kind renames where existing user / pack
// mode.json files would otherwise need to be hand-edited.
const ALIASES = new Map<string, string>();

const subscribers = new Set<() => void>();


export function registerTabKind(
  kind: string,
  component: TabComponent,
  opts: { bare?: boolean; aliases?: string[] } = {},
): void {
  if (!kind) return;
  REGISTRY.set(kind, { component, bare: Boolean(opts.bare) });
  for (const a of opts.aliases ?? []) {
    if (a && a !== kind) ALIASES.set(a, kind);
  }
  for (const s of subscribers) s();
}


export function lookupTabKind(kind: string): Entry | null {
  if (REGISTRY.has(kind)) return REGISTRY.get(kind) ?? null;
  const alias = ALIASES.get(kind);
  if (alias && REGISTRY.has(alias)) return REGISTRY.get(alias) ?? null;
  return null;
}


export function isBareKind(kind: string): boolean {
  const e = lookupTabKind(kind);
  return e?.bare ?? false;
}


export function knownKinds(): string[] {
  return [...new Set([...REGISTRY.keys(), ...ALIASES.keys()])].sort();
}


/** Subscribe to registry changes (e.g. so a hosting component can
 *  re-render when a pack-loaded tab kind appears). Returns the
 *  unsubscribe handle. */
export function onRegistryChange(cb: () => void): () => void {
  subscribers.add(cb);
  return () => subscribers.delete(cb);
}
