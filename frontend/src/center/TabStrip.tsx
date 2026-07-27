import { Suspense, useEffect, useState } from "react";
import type { TabSpec } from "../ws";
import type { GraphData } from "../widgets/graph/types";
import type { TerminalWsApi } from "../rail/PtyThreadSurface";
import PlaceholderTab from "./PlaceholderTab";
import TabErrorBoundary from "./TabErrorBoundary";
import { isBareKind, lookupTabKind, onRegistryChange } from "./tabRegistry";

type Props = {
  tabs: TabSpec[];
  activeId: string | null;
  onSelect: (id: string) => void;
  graphData: GraphData | null;
  graphError: string | null;
  /** Tab scoping (user tabs only): flip workspace-wide ↔ scoped to
   *  the focused thread. Scoped tabs carry a ◈ marker. */
  onToggleScope?: (tab: TabSpec) => void;
  hasFocusedThread?: boolean;
  /** term.* WS adapter for terminal-kind tabs (popped-out PTYs). */
  termWs?: TerminalWsApi | null;
};

function renderTab(
  tab: TabSpec,
  graphData: GraphData | null,
  graphError: string | null,
  termWs: TerminalWsApi | null,
) {
  const entry = lookupTabKind(tab.kind);
  if (entry) {
    const Comp = entry.component;
    return (
      <Comp tab={tab} graphData={graphData} graphError={graphError} termWs={termWs} />
    );
  }
  return <PlaceholderTab tab={tab} comingInStep={undefined} />;
}


// Helper message dropped into the rail when the user clicks the
// trailing "New…" tab affordance. Walks them through the three ways
// to add a new tab kind. Lives here (next to its trigger) rather than
// in some constants module so adding more guidance later is one edit.
const NEW_TAB_TIP = [
  "Want a new kind of tab? Three ways:",
  "",
  "  · Clone an existing one — e.g. \"clone the Plot tab as a Dashboard tab\"",
  "    and I'll copy the widget under a new tab kind for you to tweak.",
  "  · Describe a new one — e.g. \"new tab kind: timeline view of git",
  "    history per file\". I'll scaffold the React component, the daemon",
  "    routes if it needs persistence, and the verb registration.",
  "  · Install an extension pack — \"install pack github:user/bio-pack\"",
  "    pulls a bundle of skills + tab kinds + agent presets at once",
  "    (see the pack loader, step S in plan.md).",
  "",
  "Tab kinds register themselves at startup via the verbs registry —",
  "once the new kind exists, you can pin it in `.workbench/mode.json`.",
].join("\n");

// System tabs are cross-workspace surfaces that belong to the right of
// the strip, past every other tab. The Agents dashboard used to live
// here; it moved into the bottom DashboardPanel's expanded state, so
// `agents`-kind tabs (still present in older mode.json files) are
// filtered out of the strip entirely.
function isSystemTab(t: TabSpec): boolean {
  return t.source === "system";
}

export default function TabStrip({
  tabs, activeId, onSelect, graphData, graphError,
  onToggleScope, hasFocusedThread, termWs,
}: Props) {
  const active = tabs.find((t) => t.id === activeId) ?? tabs[0];
  // Force a re-render when the registry changes — pack tabs may
  // arrive after first render. The state value itself is unused;
  // we just want React to retick.
  const [, setTick] = useState(0);
  useEffect(() => onRegistryChange(() => setTick((t) => t + 1)), []);

  // If activeId points at a tab that no longer exists (mode/workspace
  // swap removed it), we render tabs[0] but App still thinks the old id
  // is active — keyboard tab-cycling and any activeTab-keyed logic then
  // disagree with what's on screen. Sync the fallback back to App.
  useEffect(() => {
    if (activeId !== null && !tabs.some((t) => t.id === activeId) && tabs[0]) {
      onSelect(tabs[0].id);
    }
  }, [activeId, tabs, onSelect]);

  // Partition: ordinary tabs (core/pack/user) keep their array order and
  // source-based dividers; system tabs are hoisted to a trailing group
  // after a separator, just before "+ New…" — regardless of where they
  // sit in mode.json.
  const shown = tabs.filter((t) => t.kind !== "agents");
  const normalTabs = shown.filter((t) => !isSystemTab(t));
  const systemTabs = shown.filter(isSystemTab);

  const renderTabButton = (t: TabSpec, cur: string) => (
    <button
      role="tab"
      aria-selected={t.id === active?.id}
      data-active={t.id === active?.id}
      data-tab-kind={t.kind}
      data-tour-tab-kind={t.kind}
      className={"sy-tab" + (t.thread ? " sy-tab--scoped" : "")}
      onClick={() => onSelect(t.id)}
      title={
        t.pack
          ? `${t.kind} tab · pack ${t.pack}`
          : cur === "system"
            ? `${t.kind} · spans all workspaces`
            : t.thread
              ? `${t.kind} tab · scoped to the focused thread`
              : `${t.kind} tab${cur !== "core" ? ` · ${cur}` : ""}`
      }
    >
      {t.title}
      {cur === "user" && onToggleScope && (t.thread || hasFocusedThread) && (
        <span
          className={"sy-tab-scope" + (t.thread ? " sy-tab-scope--on" : "")}
          role="button"
          tabIndex={0}
          aria-label={t.thread
            ? `${t.kind} tab is thread-scoped — activate to make workspace-wide`
            : `Scope the ${t.kind} tab to the focused thread`}
          aria-pressed={!!t.thread}
          title={t.thread
            ? "Thread-scoped — click to make workspace-wide"
            : "Scope this tab to the focused thread"}
          onClick={(ev) => {
            ev.stopPropagation();
            onToggleScope(t);
          }}
          onKeyDown={(ev) => {
            // Nested inside the tab <button>, so it can't itself be a
            // <button>; make it keyboard-operable as a role=button span.
            if (ev.key === "Enter" || ev.key === " ") {
              ev.preventDefault();
              ev.stopPropagation();
              onToggleScope(t);
            }
          }}
        >
          ◈
        </span>
      )}
    </button>
  );

  return (
    <>
      <nav className="sy-tabstrip" role="tablist">
        <span className="sy-tabstrip-label">TABS</span>
        {normalTabs.map((t, i) => {
          const prev = i > 0 ? (normalTabs[i - 1]!.source ?? "core") : null;
          const cur = t.source ?? "core";
          const showDivider = prev !== null && prev !== cur;
          return (
            <span key={t.id} style={{ display: "contents" }}>
              {showDivider && (
                <span
                  className="sy-tab-divider"
                  aria-hidden="true"
                  title={`${cur} tabs`}
                />
              )}
              {renderTabButton(t, cur)}
            </span>
          );
        })}
        {systemTabs.length > 0 && (
          <>
            <span
              className="sy-tab-divider sy-tab-divider--system"
              aria-hidden="true"
              title="cross-workspace"
            />
            {systemTabs.map((t) => (
              <span key={t.id} style={{ display: "contents" }}>
                {renderTabButton(t, "system")}
              </span>
            ))}
          </>
        )}
        <button
          type="button"
          className="sy-tab sy-tab-new"
          data-tour="new-tab"
          onClick={() => {
            window.dispatchEvent(new CustomEvent("sy:rail-system-tip", {
              detail: { text: NEW_TAB_TIP, focus: true },
            }));
          }}
          title="Drop a how-to in the rail and focus the input"
        >
          + New…
        </button>
      </nav>
      <div
        className={
          "sy-tab-content" + (active && isBareKind(active.kind) ? " sy-tab-content--bare" : "")
        }
        role="tabpanel"
      >
        {active ? (
          <TabErrorBoundary key={active.id} label={active.kind}>
            <Suspense fallback={<div className="sy-placeholder"><p>Loading…</p></div>}>
              {renderTab(active, graphData, graphError, termWs ?? null)}
            </Suspense>
          </TabErrorBoundary>
        ) : (
          <PlaceholderTab tab={null} comingInStep={undefined} />
        )}
      </div>
    </>
  );
}
