import TabStrip from "./TabStrip";
import type { TabSpec } from "../ws";
import type { GraphData } from "../widgets/graph/types";
import type { TerminalWsApi } from "../rail/PtyThreadSurface";

type Props = {
  tabs: TabSpec[];
  activeId: string | null;
  onSelect: (id: string) => void;
  graphData: GraphData | null;
  graphError: string | null;
  /** Tab scoping (user tabs): flip workspace-wide ↔ focused-thread. */
  onToggleTabScope: (tab: TabSpec) => void;
  hasFocusedThread: boolean;
  /** term.* WS adapter for terminal-kind tabs (popped-out PTYs). */
  termWs: TerminalWsApi | null;
};

/** Centre column: core/pack/user tabs. Agents is a core tab. */
export default function CenterColumn(props: Props) {
  const {
    tabs, activeId, onSelect, graphData, graphError,
    onToggleTabScope, hasFocusedThread, termWs,
  } = props;
  return (
    <div className="sy-center-col">
      <div className="sy-center-col-main">
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
    </div>
  );
}
