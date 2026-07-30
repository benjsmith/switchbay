/**
 * Zen right-pane surfaces that are NOT workspace tabs.
 *
 * The pane's surface id is normally a TabSpec id; these ids stand for
 * surfaces the mode/tab set never carries — the Agents dashboard, and
 * the Browser (files / wiki / sources) that Power mode keeps in its
 * left column. Shared so the dropdown, the ⌘K→G cycle order, and the
 * stale-surface guard can't drift out of agreement about which ids are
 * legal without a matching tab.
 */

export type ZenSyntheticSurface = "agents" | "browser";

/** Dropdown + cycle order: these trail the real tabs. */
export const ZEN_SYNTHETIC: readonly {
  id: ZenSyntheticSurface;
  title: string;
  /** Shown in the dropdown's right-hand kind column. */
  kind: string;
}[] = [
  { id: "browser", title: "Browser", kind: "files · wiki · sources" },
  { id: "agents", title: "Agents", kind: "dashboard" },
];

const IDS = new Set<string>(ZEN_SYNTHETIC.map((s) => s.id));

export function isZenSynthetic(id: string | null): id is ZenSyntheticSurface {
  return id !== null && IDS.has(id);
}
