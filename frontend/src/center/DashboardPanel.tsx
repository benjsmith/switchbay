import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { registerCombo } from "../keys";
import AgentDashboardTab, { RunTranscript } from "../widgets/agents/AgentDashboardTab";

/**
 * Foundation C: the 3-level agents panel in the bottom slot freed by
 * the old docked terminal (Foundation B).
 *
 *   · collapsed — one strip: running count + per-workspace chips.
 *   · open     — live run rows (grouped: fan-out workers indent under
 *                their parent), each with a "working toward" line
 *                (STEP name → activity tail → input excerpt), jump ↗
 *                and kill ✕. Drag-resize; height persisted.
 *   · expanded — the panel takes over the whole centre column and
 *                renders the FULL dashboard (running + tools / rules /
 *                providers). This replaced the old top-strip Agents
 *                tab — the agents surface lives only here now.
 *
 * Double-clicking the "Agents" title cycles collapsed → open →
 * expanded → collapsed; single click toggles collapsed ↔ open.
 * Cmd+J toggles too, per the charter keybinding plan.
 *
 * Data comes from App's existing 2 s /api/runs/active poll (passed
 * down), so the panel adds no extra polling. PTY runs with status
 * `idle` (a shell at its prompt / a TUI waiting for input) are shown
 * but never counted as running.
 */

export type ActiveRun = {
  run_id: string;
  provider: string;
  model?: string;
  input_excerpt?: string;
  status?: string;
  started_at?: number;
  thread_id?: string;
  workspace?: string;
  workspace_name?: string;
  activity?: string;
  step?: string;
  parent_run_id?: string;
  worker_index?: number;
  is_background?: boolean;
};

type Props = {
  runs: ActiveRun[];
  /** Focused workspace path — rows from other workspaces get a chip. */
  workspace: string;
  onJump: (run: ActiveRun) => void;
  /** Lets CenterColumn hide the tab area while the panel fills it. */
  onExpandedChange?: (expanded: boolean) => void;
};

type PanelState = "collapsed" | "open" | "expanded";

const STORAGE_KEY = "sy:dash-panel";
const DEFAULT_HEIGHT = 220;
const MIN_HEIGHT = 100;
const MAX_HEIGHT = 560;

const LIVE_STATUSES = ["running", "planning", "merging"];

function readPersisted(): { state: PanelState; heightPx: number } {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { state: "collapsed", heightPx: DEFAULT_HEIGHT };
    const p = JSON.parse(raw) as { state?: string; open?: boolean; heightPx?: number };
    // Migrate the pre-3-state shape ({open: boolean}).
    const state: PanelState =
      p.state === "open" || p.state === "expanded" || p.state === "collapsed"
        ? p.state
        : p.open === true ? "open" : "collapsed";
    return {
      state,
      heightPx: typeof p.heightPx === "number"
        ? Math.max(MIN_HEIGHT, Math.min(MAX_HEIGHT, p.heightPx))
        : DEFAULT_HEIGHT,
    };
  } catch {
    return { state: "collapsed", heightPx: DEFAULT_HEIGHT };
  }
}

function elapsed(startedAt?: number): string {
  if (!startedAt) return "";
  const s = Math.max(0, Date.now() / 1000 - startedAt);
  if (s < 60) return `${Math.floor(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m${Math.floor(s % 60).toString().padStart(2, "0")}`;
  return `${Math.floor(s / 3600)}h${Math.floor((s % 3600) / 60)}m`;
}

/** The one-liner under each run: prefer the AG-UI step name, then the
 *  live activity tail, then the dispatch excerpt. Idle shells say so. */
function workingToward(r: ActiveRun): string {
  if (r.status === "idle") {
    return `${r.input_excerpt || "shell"} — waiting for input`;
  }
  return r.step || r.activity || r.input_excerpt || "";
}

const LIVE_STATUSES_SET = new Set(LIVE_STATUSES);
const DASH_RECENT_TTL_S = 15 * 60;
const DASH_RECENT_MAX = 8;

type DashRow = ActiveRun & { finished?: boolean; finished_at?: number };

export default function DashboardPanel({ runs, workspace, onJump, onExpandedChange }: Props) {
  const initial = useMemo(readPersisted, []);
  const [state, setState] = useState<PanelState>(initial.state);
  const [heightPx, setHeightPx] = useState(initial.heightPx);
  // Rows the user opened for an inline transcript (same insight the
  // full view gives, without leaving the panel). Keyed by run_id;
  // retired runs fall out of `runs` and their entries just go stale.
  const [openRows, setOpenRows] = useState<Set<string>>(() => new Set());
  const userCollapsed = useRef<Set<string>>(new Set());
  const prevRunsRef = useRef<Map<string, ActiveRun>>(new Map());
  const [recentFinished, setRecentFinished] = useState<DashRow[]>([]);

  const toggleRow = useCallback((runId: string) => {
    setOpenRows((cur) => {
      const next = new Set(cur);
      if (next.has(runId)) {
        next.delete(runId);
        userCollapsed.current.add(runId);
      } else {
        next.add(runId);
        userCollapsed.current.delete(runId);
      }
      return next;
    });
  }, []);

  // Detect finished runs + C1 auto-expand solo live agent.
  useEffect(() => {
    const nextMap = new Map(runs.map((r) => [r.run_id, r]));
    const departed: DashRow[] = [];
    for (const [id, prev] of prevRunsRef.current) {
      if (!nextMap.has(id) && prev.provider !== "pty") {
        departed.push({
          ...prev,
          finished: true,
          finished_at: Date.now() / 1000,
          status: "done",
        });
      }
    }
    prevRunsRef.current = nextMap;
    if (departed.length > 0) {
      setRecentFinished((cur) => {
        const now = Date.now() / 1000;
        return [
          ...departed,
          ...cur.filter((c) => !departed.some((d) => d.run_id === c.run_id)),
        ]
          .filter((c) => now - (c.finished_at ?? c.started_at ?? 0) < DASH_RECENT_TTL_S)
          .slice(0, DASH_RECENT_MAX);
      });
    } else {
      setRecentFinished((cur) => {
        const now = Date.now() / 1000;
        const next = cur.filter(
          (c) => now - (c.finished_at ?? c.started_at ?? 0) < DASH_RECENT_TTL_S,
        );
        return next.length === cur.length ? cur : next;
      });
    }

    const liveAgents = runs.filter(
      (r) =>
        (!r.status || LIVE_STATUSES_SET.has(r.status))
        && r.provider !== "pty"
        && !r.parent_run_id,
    );
    if (liveAgents.length === 1) {
      const id = liveAgents[0]!.run_id;
      if (!userCollapsed.current.has(id)) {
        setOpenRows((cur) => {
          if (cur.has(id)) return cur;
          const next = new Set(cur);
          next.add(id);
          return next;
        });
      }
    }
  }, [runs]);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ state, heightPx }));
    } catch { /* quota; ignore */ }
  }, [state, heightPx]);

  useEffect(() => {
    onExpandedChange?.(state === "expanded");
  }, [state, onExpandedChange]);

  // ⌘J toggle (freed by the terminal panel's removal), via the
  // central registry. The old Ctrl-` alias was removed 2026-07-05
  // (D17) — the charter keybinding rule now holds with zero
  // punctuation exceptions.
  const toggle = useCallback(() => {
    setState((s) => (s === "collapsed" ? "open" : "collapsed"));
  }, []);
  useEffect(() => registerCombo({
    key: "j",
    description: "Toggle the agents panel",
    handler: toggle,
  }), [toggle]);

  // External openers (top-bar tasks button, rail ↗ jumps, upload
  // ingest) ask for a specific panel state — usually "expanded",
  // the surface the old Agents tab provided.
  useEffect(() => {
    const onOpen = (ev: Event) => {
      const want = (ev as CustomEvent<{ state?: PanelState }>).detail?.state;
      setState(want === "collapsed" || want === "open" ? want : "expanded");
    };
    window.addEventListener("sy:agents-panel", onOpen);
    return () => window.removeEventListener("sy:agents-panel", onOpen);
  }, []);

  // Title interaction: single click toggles collapsed ↔ open;
  // double-click cycles collapsed → open → expanded → collapsed.
  // The single-click action is deferred one beat so a double-click
  // doesn't fire it first.
  const clickTimer = useRef<number | null>(null);
  useEffect(() => () => {
    if (clickTimer.current !== null) window.clearTimeout(clickTimer.current);
  }, []);
  const onTitleClick = useCallback(() => {
    if (clickTimer.current !== null) return;
    clickTimer.current = window.setTimeout(() => {
      clickTimer.current = null;
      toggle();
    }, 220);
  }, [toggle]);
  const onTitleDoubleClick = useCallback(() => {
    if (clickTimer.current !== null) {
      window.clearTimeout(clickTimer.current);
      clickTimer.current = null;
    }
    setState((s) =>
      s === "collapsed" ? "open" : s === "open" ? "expanded" : "collapsed");
  }, []);

  // Drag-resize on the panel's top edge. Setter-only state (functional
  // updates read the previous value) — no render depends on it.
  const [, setDrag] = useState<{ startY: number; startH: number } | null>(null);
  const onHandleDown = useCallback((ev: React.PointerEvent<HTMLDivElement>) => {
    setDrag({ startY: ev.clientY, startH: heightPx });
    (ev.target as HTMLDivElement).setPointerCapture(ev.pointerId);
  }, [heightPx]);
  const onHandleMove = useCallback((ev: React.PointerEvent<HTMLDivElement>) => {
    setDrag((s) => {
      if (!s) return s;
      setHeightPx(Math.max(MIN_HEIGHT, Math.min(MAX_HEIGHT, s.startH + (s.startY - ev.clientY))));
      return s;
    });
  }, []);
  const onHandleUp = useCallback((ev: React.PointerEvent<HTMLDivElement>) => {
    setDrag(null);
    try { (ev.target as HTMLDivElement).releasePointerCapture(ev.pointerId); }
    catch { /* already released */ }
  }, []);

  // Per-workspace running counts for the glance chips. Workers count
  // toward their workspace like any run; idle shells don't count.
  const byWs = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of runs) {
      if (r.status && !LIVE_STATUSES.includes(r.status)) continue;
      const name = r.workspace_name || "?";
      m.set(name, (m.get(name) ?? 0) + 1);
    }
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [runs]);
  const liveCount = byWs.reduce((n, [, c]) => n + c, 0);

  // Ordered rows: parents first, their workers directly beneath.
  const rows = useMemo(() => {
    const parents = runs.filter((r) => !r.parent_run_id);
    const workers = runs.filter((r) => r.parent_run_id);
    const out: ActiveRun[] = [];
    for (const p of parents) {
      out.push(p);
      out.push(...workers.filter((w) => w.parent_run_id === p.run_id));
    }
    // Orphan workers (parent already retired) still show, at the end.
    out.push(...workers.filter((w) => !parents.some((p) => p.run_id === w.parent_run_id)));
    return out;
  }, [runs]);

  const chips = (
    <span className="sy-dash-chips">
      {byWs.slice(0, 4).map(([name, n]) => (
        <span key={name} className="sy-dash-chip">{name}·{n}</span>
      ))}
    </span>
  );

  const titleButton = (glyph: string) => (
    <button
      type="button"
      className="sy-dash-toggle"
      onClick={onTitleClick}
      onDoubleClick={onTitleDoubleClick}
      title="Click: open/collapse · double-click: cycle collapsed → open → expanded (Cmd-J toggles)"
    >
      {glyph} Agents
      {liveCount > 0 && <span className="sy-dash-dot" />}
      {liveCount > 0 && <span className="sy-dash-count">{liveCount} running</span>}
    </button>
  );

  if (state === "collapsed") {
    return (
      <div className="sy-dash sy-dash--collapsed">
        {titleButton("▸")}
        {chips}
      </div>
    );
  }

  if (state === "expanded") {
    return (
      <div className="sy-dash sy-dash--expanded">
        <div className="sy-dash-header">
          {titleButton("▾")}
          {chips}
          <span style={{ flex: 1 }} />
          <button
            type="button"
            className="sy-dash-expand"
            onClick={() => setState("open")}
            title="Restore to the bottom panel"
          >
            ⤡ panel
          </button>
          <button
            type="button"
            className="sy-dash-expand"
            onClick={() => setState("collapsed")}
            title="Collapse the agents panel"
          >
            ▾ collapse
          </button>
        </div>
        <div className="sy-dash-full">
          <AgentDashboardTab />
        </div>
      </div>
    );
  }

  return (
    <>
      <div
        className="sy-dash-resize"
        role="separator"
        aria-orientation="horizontal"
        onPointerDown={onHandleDown}
        onPointerMove={onHandleMove}
        onPointerUp={onHandleUp}
        title="Drag to resize the agents panel"
      />
      <div className="sy-dash sy-dash--open" style={{ height: `${heightPx}px` }}>
        <div className="sy-dash-header">
          {titleButton("▾")}
          {chips}
          <span style={{ flex: 1 }} />
          <button
            type="button"
            className="sy-dash-expand"
            onClick={() => setState("expanded")}
            title="Expand to the full Agents dashboard"
          >
            ⤢ full view
          </button>
        </div>
        <div className="sy-dash-rows">
          {rows.length === 0 && recentFinished.length === 0 && (
            <div className="sy-dash-empty">no runs — everything is quiet</div>
          )}
          {([...rows, ...recentFinished] as DashRow[]).map((r) => {
            const foreign = !!r.workspace && r.workspace !== workspace;
            const idle = r.status === "idle";
            const done = !!r.finished || r.status === "done";
            const live = !done && (!r.status || LIVE_STATUSES.includes(r.status));
            const opened = openRows.has(r.run_id);
            const activity = (r.activity || "").trim();
            const activityLong = activity.length > 120;
            return (
              <div key={(done ? "done-" : "") + r.run_id}>
                <div
                  className={
                    "sy-dash-row sy-dash-row--clickable" +
                    (r.parent_run_id ? " sy-dash-row--worker" : "") +
                    (idle ? " sy-dash-row--idle" : live ? "" : " sy-dash-row--done")
                  }
                  onClick={() => toggleRow(r.run_id)}
                  title={opened
                    ? "Collapse this run's transcript"
                    : "Click for this run's live transcript"}
                >
                  <span className={"sy-dash-status" + (live ? " live" : idle ? " idle" : "")} />
                  <span className="sy-dash-glyph">
                    {r.provider === "pty" ? ">_" : opened ? "▾" : "▸"}
                  </span>
                  {foreign && (
                    <span className="sy-dash-chip sy-dash-chip--ws" title={r.workspace}>
                      ↗ {r.workspace_name}
                    </span>
                  )}
                  <span className="sy-dash-excerpt" title={r.input_excerpt}>
                    {done ? `(done) ${r.input_excerpt || r.run_id}` : workingToward(r)}
                  </span>
                  <span className="sy-dash-meta">
                    {r.provider} · {idle ? "idle" : done ? "done" : elapsed(r.started_at)}
                  </span>
                  {r.thread_id && (
                    <button
                      type="button"
                      className="sy-dash-btn"
                      title={foreign
                        ? "Jump to this run's thread (switches workspace)"
                        : "Jump to this run's thread"}
                      onClick={(ev) => { ev.stopPropagation(); onJump(r); }}
                    >
                      ↗
                    </button>
                  )}
                  {(live || idle) && (
                    <button
                      type="button"
                      className="sy-dash-btn sy-dash-btn--kill"
                      title={idle ? "Close this shell" : "Cancel this run"}
                      onClick={(ev) => {
                        ev.stopPropagation();
                        void fetch(`/api/runs/${encodeURIComponent(r.run_id)}/cancel`, {
                          method: "POST",
                        }).catch(() => { /* transient */ });
                      }}
                    >
                      ✕
                    </button>
                  )}
                </div>
                {activity && (
                  <button
                    type="button"
                    className={
                      "sy-dash-activity"
                      + (opened ? " sy-dash-activity--open" : "")
                      + (activityLong && !opened ? " sy-dash-activity--clamped" : "")
                    }
                    onClick={(ev) => {
                      ev.stopPropagation();
                      toggleRow(r.run_id);
                    }}
                    title={
                      opened
                        ? "Collapse transcript"
                        : "Click to inspect full activity + transcript"
                    }
                  >
                    <span className="sy-dash-activity-body">{activity}</span>
                    {activityLong && !opened && (
                      <span className="sy-dash-activity-more">Show full ▾</span>
                    )}
                  </button>
                )}
                {opened && (
                  <div className="sy-dash-row-tx">
                    <RunTranscript
                      runId={r.run_id}
                      live={live}
                      isPty={r.provider === "pty"}
                    />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}
