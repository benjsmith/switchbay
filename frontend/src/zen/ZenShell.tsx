import { useCallback, useEffect, useRef, useState } from "react";
import { registerCombo } from "../keys";
import type { TabSpec, Workspaces } from "../ws";
import type { GraphData } from "../widgets/graph/types";
import type { TerminalWsApi } from "../rail/PtyThreadSurface";
import type { RailEntry } from "../rail/Rail";
import type { ActiveRun } from "../center/DashboardPanel";
import GraphTab from "../widgets/graph/GraphTab";
import ZenSurfaceHost, { type ZenArtifact } from "./ZenSurfaceHost";
import ZenChatBox from "./ZenChatBox";
import ThemeToggle from "../layout/ThemeToggle";
import ModeToggle from "../layout/ModeToggle";
import PasteboardButton from "../layout/PasteboardButton";
import RunningTasksButton from "../layout/RunningTasksButton";
import HelpButton from "../layout/HelpButton";
import SettingsButton from "../layout/SettingsButton";
import WorkspaceSwitcher from "../layout/WorkspaceSwitcher";

/**
 * Zen mode (charter, designed 2026-07-05): a minimal alternate shell —
 * three parts only. Left = the graph view, always (same GraphTab, no
 * tab header). Right = every other surface, one at a time, behind a
 * dropdown. A draggable central divider resizes them (full-range;
 * double-click resets 50/50). The chat box floats at the bottom over
 * both panes; chrome affordances float too — faint until hovered.
 *
 * Sibling shell in the SAME React tree: App owns all state (WS,
 * entries, threads, tabs); nothing remounts on toggle except the
 * shells' own DOM.
 */

const SPLIT_KEY = "sy:zen-split";

function readSplit(): number {
  try {
    const v = parseFloat(localStorage.getItem(SPLIT_KEY) ?? "");
    if (Number.isFinite(v)) return Math.max(0, Math.min(100, v));
  } catch { /* quota / disabled */ }
  return 50;
}

type Props = {
  workspace: string;
  workspaces: Workspaces;
  graphData: GraphData | null;
  graphError: string | null;
  /** Bumped on `files_changed` — reaches the Browser surface's tree. */
  filesVersion: number;
  /** Visible tabs for the right pane (App already excludes graph/
   *  terminal/agents kinds). */
  tabs: TabSpec[];
  surface: string | null;
  setSurface: (s: string) => void;
  artifact: ZenArtifact | null;
  onJumpArtifact: () => void;
  entries: RailEntry[];
  onSubmit: (text: string, opts: { n: number }) => void;
  focusedThread: string | null;
  focusedThreadKind: string | null;
  onSwitchThread: (threadId: string, kind: string) => void;
  onNewThread: (kind?: "structured-agent" | "interactive-pty") => void;
  termWs: TerminalWsApi | null;
  activeRunIds: Set<string>;
  activeRuns: ActiveRun[];
  hasMoreHistory: boolean;
  loadingOlder: boolean;
  onLoadOlder: () => void;
  onOpenSettings: () => void;
  onOpenHelp: () => void;
};

export default function ZenShell({
  workspace, workspaces, graphData, graphError, filesVersion,
  tabs, surface, setSurface, artifact, onJumpArtifact,
  entries, onSubmit, focusedThread, focusedThreadKind,
  onSwitchThread, onNewThread, termWs, activeRunIds, activeRuns,
  hasMoreHistory, loadingOlder, onLoadOlder,
  onOpenSettings, onOpenHelp,
}: Props) {
  // ── Divider ────────────────────────────────────────────────────
  const [split, setSplit] = useState(readSplit);
  const rootRef = useRef<HTMLDivElement>(null);
  const draggingRef = useRef(false);
  useEffect(() => {
    try { localStorage.setItem(SPLIT_KEY, String(split)); } catch { /* quota */ }
  }, [split]);

  const onDividerDown = useCallback((ev: React.PointerEvent<HTMLDivElement>) => {
    ev.preventDefault();
    draggingRef.current = true;
    (ev.target as HTMLElement).setPointerCapture(ev.pointerId);
  }, []);
  const onDividerMove = useCallback((ev: React.PointerEvent<HTMLDivElement>) => {
    if (!draggingRef.current) return;
    const root = rootRef.current;
    if (!root) return;
    const rect = root.getBoundingClientRect();
    if (rect.width <= 0) return;
    // Full-range: 0..100 — either pane can vanish; the handle itself
    // stays a fixed-width flex item, so it's always grabbable at the
    // extremes to bring the hidden pane back.
    const pct = ((ev.clientX - rect.left) / rect.width) * 100;
    setSplit(Math.max(0, Math.min(100, pct)));
  }, []);
  const onDividerUp = useCallback((ev: React.PointerEvent<HTMLDivElement>) => {
    draggingRef.current = false;
    try {
      (ev.target as HTMLElement).releasePointerCapture(ev.pointerId);
    } catch { /* not captured */ }
    // The CE graph canvas sizes itself on window resize only — nudge
    // it once the divider settles so the layout fills the new width.
    window.dispatchEvent(new Event("resize"));
  }, []);

  // ── PTY promotion (stage 4) ────────────────────────────────────
  // While promoted, the right pane hosts the focused pty thread's
  // terminal at full height and the chat box pills / shows chat.
  // Never render two xterms against one session: the chat box's pty
  // branch is skipped whenever promotion is on.
  const [ptyPromoted, setPtyPromoted] = useState(false);
  useEffect(() => {
    // Leaving the pty thread (switch/archive) drops the promotion.
    if (focusedThreadKind !== "interactive-pty") setPtyPromoted(false);
  }, [focusedThreadKind, focusedThread]);

  // ⌘J opens the Agents surface — the muscle-memory analogue of
  // Power's bottom-panel toggle (that panel isn't mounted in Zen, so
  // its combo is disposed while we're here; no conflict).
  useEffect(() => registerCombo({
    key: "j",
    description: "Agents surface",
    handler: () => setSurface("agents"),
  }), [setSurface]);

  const runningCount = activeRuns.filter(
    (r) =>
      r.provider !== "pty"
      && (!r.status || ["running", "planning", "merging"].includes(r.status)),
  ).length;

  const wsName = workspace.split("/").filter(Boolean).pop() ?? "";

  return (
    <div className="sy-zen" ref={rootRef}>
      <div className="sy-zen-left" style={{ flexBasis: `${split}%` }}>
        {/* Key by workspace: a switch fully remounts the CE graph so
            nothing from the previous workspace lingers (same contract
            as Power's CenterColumn). */}
        <GraphTab
          key={workspace}
          data={graphData}
          error={graphError}
          suppressDocModal
          showAddFile
        />
      </div>
      <div
        className="sy-zen-divider"
        role="separator"
        aria-orientation="vertical"
        title="Drag to resize · double-click for 50/50"
        onPointerDown={onDividerDown}
        onPointerMove={onDividerMove}
        onPointerUp={onDividerUp}
        onDoubleClick={() => {
          setSplit(50);
          window.setTimeout(() => window.dispatchEvent(new Event("resize")), 0);
        }}
      >
        <span className="sy-zen-divider-grip" />
      </div>
      <div className="sy-zen-right">
        <ZenSurfaceHost
          tabs={tabs}
          surface={surface}
          setSurface={setSurface}
          artifact={artifact}
          onJumpArtifact={onJumpArtifact}
          graphData={graphData}
          graphError={graphError}
          filesVersion={filesVersion}
          termWs={termWs}
          runningCount={runningCount}
          promotedPty={
            ptyPromoted && focusedThreadKind === "interactive-pty"
              ? focusedThread
              : null
          }
          onReturnPty={() => setPtyPromoted(false)}
        />
      </div>

      {/* Floating chrome: same affordances as Power's bar/footer, in
          the same screen regions, but sitting directly over the panes
          — faint until hovered (CSS). */}
      {/* Brand doubles as the workspace switcher — same dropdown as
          Power's top-bar pill (switch / add / share / merge / archive),
          just wearing the faint floating-chrome look. */}
      <WorkspaceSwitcher
        variant="zen"
        workspaces={workspaces}
        modeName="zen"
        fallbackLabel={wsName}
      />
      <div className="sy-zen-chrome sy-zen-chrome--top">
        <RunningTasksButton />
        <PasteboardButton />
        <HelpButton onClick={onOpenHelp} />
        <SettingsButton onClick={onOpenSettings} />
      </div>
      <div className="sy-zen-chrome sy-zen-chrome--bottom">
        <ThemeToggle />
        <ModeToggle />
      </div>

      <ZenChatBox
        entries={entries}
        onSubmit={onSubmit}
        focusedThread={focusedThread}
        focusedThreadKind={focusedThreadKind}
        onSwitchThread={onSwitchThread}
        onNewThread={onNewThread}
        termWs={termWs}
        activeRunIds={activeRunIds}
        artifactPending={artifact !== null}
        artifactLabel={artifact?.label ?? null}
        onJumpArtifact={onJumpArtifact}
        ptyPromoted={ptyPromoted}
        onPromotePty={() => setPtyPromoted(true)}
        hasMoreHistory={hasMoreHistory}
        loadingOlder={loadingOlder}
        onLoadOlder={onLoadOlder}
      />
    </div>
  );
}
