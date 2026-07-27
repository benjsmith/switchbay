import type { TabSpec } from "../ws";

type Props = {
  tab: TabSpec | null;
  comingInStep: string | undefined;
};

const KIND_BLURB: Record<string, { lead: string; bullets: string[] }> = {
  markdown: {
    lead: "Split-view editor (raw markdown + preview) styled to match the modal-body view.",
    bullets: [
      "Tab-swap button: open the current selection in the Graph tab and vice versa.",
      "Wikilink autocomplete with recency weighting.",
    ],
  },
  duckdb: {
    lead: "Embeds the actual DuckDB Web UI; daemon spawns `duckdb -ui` attached to .workbench/state.db via the SQLite extension.",
    bullets: [],
  },
  univer: {
    lead: "Univer spreadsheet. `!exc` rail prefix authors formulas via the LLM Excel skill.",
    bullets: [],
  },
  vega: {
    lead: "Vega-Lite plotting with linked cross-filter signals across panels.",
    bullets: [
      "Pin / clone semantics; each plot persisted to `.workbench/plots/<id>.json`.",
      "Selecting in one chart filters all others on the page.",
    ],
  },
  sketch: {
    lead: "Excalidraw + drawio sketcher with slide-deck navigation.",
    bullets: [],
  },
  agents: {
    lead: "Live dashboard of running agents in this workspace, grouped by task with state and progress bars.",
    bullets: [
      "Foreground + background agents in one view.",
      "Click an agent → expand to its transcript + per-step status.",
      "Per-task aggregation when fan-out runs (planner + N workers + merger).",
      "Quick-actions: kill, push to background, retry the failed step.",
    ],
  },
};

export default function PlaceholderTab({ tab, comingInStep }: Props) {
  if (!tab) {
    return (
      <div className="sy-placeholder">
        <h2>No tabs in this mode</h2>
        <p>
          Add tabs in <code>.workbench/mode.json</code> or use the default mode (which
          ships seven pinned tabs).
        </p>
      </div>
    );
  }
  const blurb = KIND_BLURB[tab.kind];
  return (
    <div className="sy-placeholder">
      <h2>{tab.title}</h2>
      <p>
        Tab kind: <code>{tab.kind}</code>
        {comingInStep ? <> · arrives in step <code>{comingInStep}</code>.</> : null}
      </p>
      {blurb && <p>{blurb.lead}</p>}
      {blurb && blurb.bullets.length > 0 && (
        <ul style={{ marginTop: 8, paddingLeft: 18 }}>
          {blurb.bullets.map((b, i) => (
            <li key={i}>{b}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
