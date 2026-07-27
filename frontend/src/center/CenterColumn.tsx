import { useState } from "react";
import TabStrip from "./TabStrip";
import DashboardPanel, { type ActiveRun } from "./DashboardPanel";
import type { TabSpec } from "../ws";
import type { GraphData } from "../widgets/graph/types";
import type { TerminalWsApi } from "../rail/PtyThreadSurface";

type Props = {
  tabs: TabSpec[];
  activeId: string | null;
  onSelect: (id: string) => void;
  graphData: GraphData | null;
  graphError: string | null;
  /** Live runs (App's /api/runs/active poll) for the bottom panel. */
  activeRuns: ActiveRun[];
  workspace: string;
  onJumpToRun: (run: ActiveRun) => void;
  /** Tab scoping (user tabs): flip workspace-wide ↔ focused-thread. */
  onToggleTabScope: (tab: TabSpec) => void;
  hasFocusedThread: boolean;
  /** term.* WS adapter for terminal-kind tabs (popped-out PTYs). */
  termWs: TerminalWsApi | null;
};

/**
 * Centre-column wrapper: TabStrip on top, the 3-level agents
 * DashboardPanel docked at the bottom (Foundation C) — the slot the
 * old terminal panel occupied until terminals became
 * `interactive-pty` threads (Foundation B). When the panel expands
 * to the full dashboard it takes over the column; the tab area stays
 * mounted (hidden) so tab state survives the round trip.
 */
export default function CenterColumn(props: Props) {
  const {
    tabs, activeId, onSelect, graphData, graphError,
    activeRuns, workspace, onJumpToRun,
    onToggleTabScope, hasFocusedThread, termWs,
  } = props;
  const [dashExpanded, setDashExpanded] = useState(false);
  return (
    <div className="sy-center-col">
      <div
        className="sy-center-col-main"
        style={dashExpanded ? { display: "none" } : undefined}
      >
        <TabStrip
          tabs={tabs}
          activeId={activeId}
          onSelect={onSelect}
          graphData={graphData}
          graphError={graphError}
          onToggleScope={onToggleTabScope}
          hasFocusedThread={hasFocusedThread}
          termWs={termWs}
        />
      </div>
      <DashboardPanel
        runs={activeRuns}
        workspace={workspace}
        onJump={onJumpToRun}
        onExpandedChange={setDashExpanded}
      />
    </div>
  );
}
