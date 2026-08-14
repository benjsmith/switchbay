import { Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { Selection, TabSpec } from "../ws";
import type { GraphData } from "../widgets/graph/types";
import type { TerminalWsApi } from "../rail/PtyThreadSurface";
import PtyThreadSurface from "../rail/PtyThreadSurface";
import AgentDashboardTab from "../widgets/agents/AgentDashboardTab";
import PlaceholderTab from "../center/PlaceholderTab";
import { lookupTabKind, onRegistryChange } from "../center/tabRegistry";
import TabErrorBoundary from "../center/TabErrorBoundary";
import ZenBrowserTab from "./ZenBrowserTab";
import { ZEN_SYNTHETIC, isZenSynthetic } from "./surfaces";

/**
 * Zen right pane: every non-graph tab kind, one at a time — no tab
 * strip. A dropdown switcher at the top (provider-picker style)
 * chooses the surface; "Agents" and "Browser" are first-class entries
 * rendering surfaces that aren't workspace tabs at all (the dashboard,
 * and the files/wiki/sources browsers Power keeps in its sidebar).
 * Artifacts NEVER auto-switch the pane — the dropdown carries a pulse
 * badge that JUMPS straight to the latest artifact surface on click
 * (charter Zen rulings, 2026-07-05).
 */

export type ZenArtifact = {
  kind: string;
  label: string;
  /** Ready-to-apply selection from the daemon's artifact event — the
   *  jump opens the exact plot/deck/page. null on optimistic CLI-path
   *  emits that only knew the tool input. */
  selection?: Selection | null;
};

type Props = {
  /** Visible tabs minus graph/terminal kinds (Zen owns those surfaces). */
  tabs: TabSpec[];
  /** Active surface: a tab id, or a ZEN_SYNTHETIC id. null = first tab. */
  surface: string | null;
  setSurface: (s: string) => void;
  artifact: ZenArtifact | null;
  onJumpArtifact: () => void;
  graphData: GraphData | null;
  graphError: string | null;
  /** Counter bumped on `files_changed` — drives the Browser surface's
   *  file tree refresh, same as the Power sidebar's. */
  filesVersion: number;
  termWs: TerminalWsApi | null;
  /** Non-pty runs currently executing (faint count dot, top-right). */
  runningCount: number;
  /** Promoted pty thread (stage 4): overrides the surface with a
   *  full-height terminal until returned to the chat box. */
  promotedPty: string | null;
  onReturnPty: () => void;
  /** Docked zen chat — rendered when the Chat synthetic surface is active. */
  chatSurface?: ReactNode;
};

export default function ZenSurfaceHost({
  tabs, surface, setSurface, artifact, onJumpArtifact,
  graphData, graphError, filesVersion, termWs, runningCount,
  promotedPty, onReturnPty, chatSurface,
}: Props) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  // Pack tab kinds can register after first render — retick like
  // TabStrip does so their surfaces resolve.
  const [, setTick] = useState(0);
  useEffect(() => onRegistryChange(() => setTick((t) => t + 1)), []);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const active = useMemo(() => {
    if (isZenSynthetic(surface)) return surface;
    const t = tabs.find((x) => x.id === surface);
    return t ?? tabs[0] ?? null;
  }, [surface, tabs]);

  /** Narrowing helper: `active` is either a synthetic id or a TabSpec. */
  const activeSynthetic = typeof active === "string" ? active : null;
  const activeTab = typeof active === "string" ? null : active;
  const activeTitle = activeSynthetic
    ? ZEN_SYNTHETIC.find((s) => s.id === activeSynthetic)?.title ?? activeSynthetic
    : activeTab?.title ?? "—";

  const renderSurface = () => {
    if (promotedPty) {
      return (
        <PtyThreadSurface
          key={`zen-pane-${promotedPty}`}
          threadId={promotedPty}
          ws={termWs}
          surface="tab"
          onPopIn={onReturnPty}
          popInLabel={{
            label: "⇲ chat box",
            title: "Return this terminal to the floating chat box (thread and session keep running)",
          }}
        />
      );
    }
    if (activeSynthetic === "agents") return <AgentDashboardTab />;
    if (activeSynthetic === "chat") return <>{chatSurface}</>;
    if (activeSynthetic === "browser") {
      return (
        <ZenBrowserTab
          data={graphData}
          error={graphError}
          filesVersion={filesVersion}
        />
      );
    }
    if (!activeTab) return <PlaceholderTab tab={null} comingInStep={undefined} />;
    const entry = lookupTabKind(activeTab.kind);
    if (!entry) return <PlaceholderTab tab={activeTab} comingInStep={undefined} />;
    const Comp = entry.component;
    return (
      <Comp tab={activeTab} graphData={graphData} graphError={graphError} termWs={termWs} />
    );
  };

  return (
    <div className="sy-zen-surf">
      <div className="sy-zen-surf-head">
        <div className="sy-zen-surf-pickwrap" ref={wrapRef} data-tour="zen-tabs">
          <button
            type="button"
            className="sy-zen-surf-pickbtn"
            onClick={() => setOpen((o) => !o)}
            title="Choose what this pane shows"
          >
            {activeTitle}
            <span className="sy-zen-surf-caret">▾</span>
          </button>
          {artifact && (
            <button
              type="button"
              className="sy-zen-surf-pulse"
              onClick={(ev) => {
                // The badge is a JUMP, not a menu-opener — one click
                // lands on the newest artifact surface (amended ruling).
                ev.stopPropagation();
                setOpen(false);
                onJumpArtifact();
              }}
              title={`New: ${artifact.label} — click to open`}
              aria-label="Open latest artifact"
            >
              <span className="sy-zen-pulse-dot" />
            </button>
          )}
          {open && (
            <div className="sy-zen-surf-menu" role="menu">
              {tabs.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  role="menuitem"
                  className={
                    "sy-zen-surf-item"
                    + (activeTab?.id === t.id ? " sy-zen-surf-item--sel" : "")
                  }
                  onClick={() => { setSurface(t.id); setOpen(false); }}
                >
                  <span className="sy-zen-surf-item-dot">
                    {activeTab?.id === t.id ? "●" : "○"}
                  </span>
                  {t.title}
                  <span className="sy-zen-surf-item-kind">{t.kind}</span>
                </button>
              ))}
              {ZEN_SYNTHETIC.map((s, i) => (
                <button
                  key={s.id}
                  type="button"
                  role="menuitem"
                  className={
                    `sy-zen-surf-item sy-zen-surf-item--syn sy-zen-surf-item--${s.id}`
                    // The rule divides tabs from non-tab surfaces, so it
                    // rides the first synthetic whatever the order is.
                    + (i === 0 ? " sy-zen-surf-item--syn-first" : "")
                    + (activeSynthetic === s.id ? " sy-zen-surf-item--sel" : "")
                  }
                  onClick={() => { setSurface(s.id); setOpen(false); }}
                >
                  <span className="sy-zen-surf-item-dot">
                    {activeSynthetic === s.id ? "●" : "○"}
                  </span>
                  {s.title}
                  <span className="sy-zen-surf-item-kind">{s.kind}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        {promotedPty && (
          <span className="sy-zen-surf-ptynote">terminal promoted — ⇲ returns it to the chat box</span>
        )}
        <span className="sy-spacer" />
        {runningCount > 0 && (
          <button
            type="button"
            className="sy-zen-running-dot"
            onClick={() => setSurface("agents")}
            title={`${runningCount} agent run${runningCount === 1 ? "" : "s"} active — open the Agents surface`}
            aria-label="Open Agents surface"
          >
            <span className="sy-zen-running-count">{runningCount}</span>
          </button>
        )}
      </div>
      <div className="sy-zen-surf-body">
        <TabErrorBoundary
          key={activeSynthetic ?? activeTab?.id ?? "none"}
          label={activeSynthetic ?? activeTab?.kind}
        >
          <Suspense fallback={<div className="sy-placeholder"><p>Loading…</p></div>}>
            {renderSurface()}
          </Suspense>
        </TabErrorBoundary>
      </div>
    </div>
  );
}
