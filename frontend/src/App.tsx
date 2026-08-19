import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Shell from "./layout/Shell";
import TopBar from "./layout/TopBar";
import SettingsModal from "./layout/SettingsModal";
import StoppedOverlay from "./layout/StoppedOverlay";
import HelpModal from "./layout/HelpModal";
import FirstRunWizard from "./layout/FirstRunWizard";
import CommandPalette from "./layout/CommandPalette";
import Sidebar from "./sidebar/Sidebar";
import CenterColumn from "./center/CenterColumn";
import { TabsProvider } from "./center/TabsContext";
import { registerBuiltinTabs } from "./center/builtinTabs";
import { loadPackTabs } from "./center/packTabs";

// Register built-in tab kinds with the tab registry once at module
// load — runs before <App /> first renders so TabStrip's lookup
// returns hits on the initial paint. Pack-loaded tab kinds layer on
// top via loadPackTabs() (an effect below).
registerBuiltinTabs();
import Rail, { type RailEntry } from "./rail/Rail";
import ZenShell from "./zen/ZenShell";
import { readUiMode, type UiMode } from "./layout/ModeToggle";
import type { ZenArtifact } from "./zen/ZenSurfaceHost";
import { ZEN_SYNTHETIC, isZenSynthetic } from "./zen/surfaces";
import type { TerminalWsApi } from "./rail/PtyThreadSurface";
import type { ActiveRun } from "./center/DashboardPanel";
import { installKeyRegistry, registerChord, registerCombo } from "./keys";
import { RailSocket, type Mode, type Selection, type ServerMessage, type TabSpec, type Workspaces } from "./ws";
import { SelectionProvider } from "./selection/SelectionContext";
import "./widgets/graph/load";    // window.Sidebar/Subgraph/Modal/Graph + ce-graph.css
import type { GraphData } from "./widgets/graph/types";
import { primeAnalysis } from "./widgets/sketch/deckRuns";
import Walkthrough, { maybeAutoStartWalkthrough } from "./walkthrough/Walkthrough";
import {
  stashFormula, stashSheetSelect, stashSheetValues, stashSql, stashSketchShow, stashPlotShow,
} from "./lib/pendingUiCommands";
import { notifyHtmlDeckOpen } from "./widgets/htmldeck/htmlDeckOpen";
import { notifyReportDocOpen } from "./widgets/library/reportDocOpen";
import { notifyReportOpen } from "./widgets/report/reportOpen";

const EMPTY_MODE: Mode = { name: "—", tabs: [] };
const EMPTY_WORKSPACES: Workspaces = { paths: [], active: null };

// localStorage key for the last workspace snapshot. Used to paint
// the dropdown immediately on page reload while the WS connection +
// /api/workspaces round-trip is still warming up — the real fetch
// overwrites once it arrives. Without this the dropdown sat at "—"
// for 5-10 seconds after every reload because the chrome was
// gated on the daemon answering.
const WORKSPACE_CACHE_KEY = "sy.workspaces.snapshot";

function readCachedWorkspaces(): { workspace: string; workspaces: Workspaces } {
  try {
    const raw = localStorage.getItem(WORKSPACE_CACHE_KEY);
    if (!raw) return { workspace: "", workspaces: EMPTY_WORKSPACES };
    const parsed = JSON.parse(raw) as {
      workspace?: string; workspaces?: Workspaces;
    };
    return {
      workspace: typeof parsed.workspace === "string" ? parsed.workspace : "",
      workspaces:
        parsed.workspaces
        && Array.isArray(parsed.workspaces.paths)
          ? parsed.workspaces : EMPTY_WORKSPACES,
    };
  } catch {
    return { workspace: "", workspaces: EMPTY_WORKSPACES };
  }
}

function writeCachedWorkspaces(workspace: string, workspaces: Workspaces): void {
  try {
    localStorage.setItem(
      WORKSPACE_CACHE_KEY,
      JSON.stringify({ workspace, workspaces }),
    );
  } catch {
    // Quota / disabled storage — nothing to do; cache is best-effort.
  }
}

export default function App() {
  // RailSocket lives entirely inside the WS effect below — see the long
  // comment there for why useMemo would leak a second connection in
  // React StrictMode dev mode.
  const socketRef = useRef<RailSocket | null>(null);
  // Seed from localStorage so the dropdown paints the active
  // workspace immediately on reload. Real values overwrite when
  // /api/workspaces resolves below.
  const cachedInit = useMemo(() => readCachedWorkspaces(), []);
  const [workspace, setWorkspace] = useState(cachedInit.workspace);
  const [mode, setMode] = useState<Mode>(EMPTY_MODE);
  const [workspacesState, setWorkspacesState] = useState<Workspaces>(cachedInit.workspaces);
  // Persist every workspace state transition so the next reload's
  // dropdown is hot from the first paint.
  useEffect(() => {
    writeCachedWorkspaces(workspace, workspacesState);
  }, [workspace, workspacesState]);
  const [activeTab, setActiveTab] = useState<string | null>(null);
  const [entries, setEntries] = useState<RailEntry[]>([]);
  // Permission cards NOT owned by the focused thread — external CLI
  // sessions (bench runs, scripts) and background threads. Rendered in
  // the rail's pinned "outside this thread" strip, never the
  // transcript, so parallel sessions can't bleed into the open
  // conversation.
  const [otherPerms, setOtherPerms] = useState<
    Extract<RailEntry, { source: "permission" }>[]
  >([]);
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [graphError, setGraphError] = useState<string | null>(null);
  // Bumped by the Graph tab's Retry affordance to re-run the fetch effect.
  const [graphReloadTick, setGraphReloadTick] = useState(0);
  const [selection, setSelectionLocal] = useState<Selection | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  // Non-null once the daemon is stopping (user Quit / `/quit`), which
  // switches the whole app to a "stopped" overlay and halts reconnects.
  const [stopped, setStopped] = useState<{ reason?: string } | null>(null);
  const [helpOpen, setHelpOpen] = useState(false);
  const [walkthroughOpen, setWalkthroughOpen] = useState(false);
  const walkthroughAutoTriedRef = useRef(false);
  // False until we know the first-install tour is neither pending nor
  // running. Other first-run surfaces (the FirstRunWizard modal) wait
  // on this so they don't land on top of the tour's coach-marks.
  const [walkthroughSettled, setWalkthroughSettled] = useState(false);
  // ── UI mode: Power (3-column) ↔ Zen (graph + surface + floating
  // chat). Sibling shells in the same tree — all state here survives
  // the toggle. ModeToggle announces flips via `sy:ui-mode`.
  const [uiMode, setUiMode] = useState<UiMode>(readUiMode);
  const uiModeRef = useRef(uiMode);
  useEffect(() => { uiModeRef.current = uiMode; }, [uiMode]);
  useEffect(() => {
    const onMode = (ev: Event) => {
      const m = (ev as CustomEvent<{ mode?: UiMode }>).detail?.mode;
      if (m === "power" || m === "zen") setUiMode(m);
    };
    window.addEventListener("sy:ui-mode", onMode);
    return () => window.removeEventListener("sy:ui-mode", onMode);
  }, []);
  // Zen right-pane surface: a tab id or "agents" (null = first tab).
  const [zenSurface, setZenSurface] = useState<string | null>(null);
  // Zen pending-artifact marker: set when an agent produces/updates a
  // surface; NEVER auto-switches the pane (charter ruling) — cleared
  // by any of the three one-click jump paths (badge / palette /
  // response-half arrow) or by the user reaching the surface anyway.
  const [zenArtifact, setZenArtifact] = useState<ZenArtifact | null>(null);
  const zenArtifactRef = useRef<ZenArtifact | null>(null);
  useEffect(() => { zenArtifactRef.current = zenArtifact; }, [zenArtifact]);
  const [oldestEventId, setOldestEventId] = useState<number | null>(null);
  const [hasMoreHistory, setHasMoreHistory] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  // Currently-executing run ids (polled), so the rail can mark run
  // blocks live vs done and drive the focus-switcher.
  const [activeRunIds, setActiveRunIds] = useState<Set<string>>(() => new Set());
  // Full run records from the same poll — feeds the bottom
  // DashboardPanel (Foundation C). Ref mirror so callbacks (switch-
  // away toast) can read the latest without re-subscribing.
  const [activeRuns, setActiveRuns] = useState<ActiveRun[]>([]);
  const activeRunsRef = useRef<ActiveRun[]>([]);
  // Bumped whenever the daemon broadcasts `files_changed` (page save,
  // file delete, fileops dup, an agent's Write/Edit, external edit).
  // Sidebar uses it to refetch /api/tree, App uses it to re-fetch
  // /api/graph/data so the pages list stays in sync.
  const [filesVersion, setFilesVersion] = useState(0);
  // Live entries get ids past 1e9 so they can never collide with the
  // event_ids assigned to hydrated rows from /api/rail/events.
  const idRef = useRef(1_000_000_000);
  const graphDataRef = useRef<GraphData | null>(null);
  // Focused workspace, mirrored into a ref so the once-mounted rail
  // socket handler can filter agent events by workspace without being
  // re-subscribed on every switch. The rail is strictly per-workspace:
  // live agent events for a run in ANOTHER workspace are dropped here
  // (the cross-workspace Agent Dashboard surfaces them instead).
  const focusedWsRef = useRef("");
  // run_ids dropped as belonging to another workspace — so their later
  // tool_use / tool_result / error frames (which don't carry workspace)
  // are also kept out of the rail.
  const foreignRunsRef = useRef<Set<string>>(new Set());
  // Focused thread (Workspace → Thread → Run → Turn). The rail shows
  // exactly one thread; runs of other threads in the SAME workspace
  // stream to their own transcript only (dashboard's business).
  // Mirrored into a ref for the once-mounted socket handler.
  const [focusedThread, setFocusedThread] = useState<string | null>(null);
  const focusedThreadRef = useRef<string | null>(null);
  // The focused thread's kind decides the rail surface: transcript +
  // composer ('structured-agent') vs xterm ('interactive-pty').
  const [focusedThreadKind, setFocusedThreadKind] = useState<string | null>(null);
  const focusedThreadKindRef = useRef<string | null>(null);
  // runId → {threadId, workspace, provider}, learned from RUN_STARTED.
  // Later frames carry only runId, so per-frame thread routing (and
  // the background-completion toasts' jump target) resolve through
  // this. Runs from before this page loaded are unknown → treated as
  // not-focused (dropped), which is the safe default.
  const runMetaRef = useRef<Map<string, {
    threadId: string; workspace?: string; provider?: string;
  }>>(new Map());
  // Transient bottom-right toasts: background runs finishing, and
  // "runs continue in background" on switch-away.
  type Toast = {
    id: number;
    text: string;
    err?: boolean;
    jump?: { workspace?: string; threadId: string; kind?: string };
    /** "Open" button that switches to this workspace (merge done). */
    switchTo?: string;
  };
  const [toasts, setToasts] = useState<Toast[]>([]);
  const pushToast = useCallback((t: Omit<Toast, "id">, ttlMs = 8000) => {
    const id = ++idRef.current;
    setToasts((cur) => [...cur.slice(-3), { ...t, id }]);
    window.setTimeout(() => {
      setToasts((cur) => cur.filter((x) => x.id !== id));
    }, ttlMs);
  }, []);
  useEffect(() => {
    graphDataRef.current = graphData;
  }, [graphData]);

  // Global toast bridge: any component can raise a toast via the
  // `sy:toast` event (see lib/toast.ts) so a user-initiated action that
  // fails deep in the tree surfaces instead of dying silently.
  useEffect(() => {
    const onToast = (ev: Event) => {
      const d = (ev as CustomEvent<{ text?: string; err?: boolean }>).detail;
      if (d?.text) pushToast({ text: d.text, err: d.err });
    };
    window.addEventListener("sy:toast", onToast);
    return () => window.removeEventListener("sy:toast", onToast);
  }, [pushToast]);

  const selectionClosedAt = useRef(0);
  /** Local update + push to daemon. Stable across renders. */
  const setSelection = useCallback((s: Selection | null) => {
    if (s == null) selectionClosedAt.current = Date.now();
    setSelectionLocal(s);
    socketRef.current?.send({ type: "selection_set", selection: s });
  }, []);

  // User-requested stop (Settings → Quit). Show the overlay + halt the
  // socket optimistically, THEN ask the daemon to exit — so the window
  // reads as "stopped" the instant you confirm, even before the daemon
  // dies (and doesn't reconnect-loop once it does). The daemon also
  // broadcasts daemon.shutdown to any *other* open window.
  const requestQuit = useCallback(async () => {
    setStopped({ reason: "user" });
    socketRef.current?.close();
    try {
      await fetch("/api/quit", { method: "POST" });
    } catch {
      // The daemon may die before the response lands — that's success.
    }
  }, []);

  // User-requested restart (Settings → Restart = `make restart`). Unlike
  // Quit we DON'T show the stopped overlay or close the socket: the
  // service manager brings a fresh daemon back on its own, and the
  // existing boot_id watcher (devReload.ts) auto-reloads the PWA. We
  // only surface a toast — and the daemon's refusal, if it isn't the
  // managed service (a dev daemon).
  const requestRestart = useCallback(async () => {
    try {
      const r = await fetch("/api/restart", { method: "POST" });
      if (r.ok) {
        pushToast({ text: "Restarting Switch Bay… it'll reconnect automatically." });
        return;
      }
      const body = (await r.json().catch(() => null)) as { error?: string } | null;
      pushToast({ text: body?.error || "Couldn't restart Switch Bay.", err: true }, 12000);
    } catch {
      // A dropped connection here usually means the restart already took
      // the daemon down — treat as success; devReload reloads on return.
      pushToast({ text: "Restarting Switch Bay… it'll reconnect automatically." });
    }
  }, [pushToast]);

  // Settings → Update: check GitHub, apply older Switch Bay / CE /
  // curiosity-merge releases, then the same restart path as above so
  // the boot_id watcher reloads the PWA.
  const requestUpdate = useCallback(async () => {
    pushToast({ text: "Checking GitHub for updates…" });
    try {
      const r = await fetch("/api/update", { method: "POST" });
      const body = (await r.json().catch(() => null)) as {
        ok?: boolean;
        error?: string;
        summary?: string;
        updated?: boolean;
        restarted?: boolean;
        restart_error?: string;
      } | null;
      const summary = (body?.summary || body?.error || "").trim();
      if (!r.ok && !summary) {
        pushToast({ text: body?.error || "Couldn't check for updates.", err: true }, 12000);
        return;
      }
      if (body?.restarted) {
        pushToast({
          text: (summary || "Update finished.") + " Restarting… it'll reconnect automatically.",
        });
        return;
      }
      if (body?.restart_error) {
        pushToast({
          text: (summary || "Updates applied.") + " " + body.restart_error,
          err: true,
        }, 14000);
        return;
      }
      pushToast(
        { text: summary || (body?.ok ? "Already up to date." : "Update failed."), err: !body?.ok },
        body?.ok ? 8000 : 12000,
      );
    } catch {
      // Connection dropped mid-restart — same success path as Restart.
      pushToast({ text: "Restarting Switch Bay… it'll reconnect automatically." });
    }
  }, [pushToast]);

  // RailSocket lifecycle: created INSIDE the effect (not via useMemo)
  // so React 18 StrictMode's deliberate double-mount can clean up the
  // first instance via the cleanup, instead of leaving two persistent
  // WS connections that each receive the daemon's hello and produce a
  // duplicated "connected · …" entry in the rail.
  // Pack-supplied tab kinds: load once on boot. Independent of the
  // WS lifecycle since the registry is module-scoped — a stale pack
  // import wouldn't be cleaned up by re-mounting App, so we only
  // run the loader once even under StrictMode's double-mount.
  useEffect(() => { void loadPackTabs(); }, []);

  // Central keybinding registry (charter rule): one listener owns all
  // shortcuts. Installed once; components register their own bindings.
  useEffect(() => installKeyRegistry(), []);
  // ⌘K → W: open the workspace switcher (it listens for the event).
  useEffect(() => registerChord({
    key: "w",
    description: "Switch workspace",
    handler: () => window.dispatchEvent(new CustomEvent("sy:open-workspace-switcher")),
  }), []);
  // Tab scoping (control surface v1): thread-scoped tabs render only
  // while their thread is focused. Filtered client-side so a thread
  // switch shows/hides them instantly, no round-trip. `agents`-kind
  // tabs are excluded everywhere (strip, ⌘K→G, ⌘1..9) — the agents
  // surface is the bottom DashboardPanel now, not a tab.
  const visibleTabs = useMemo(
    () => mode.tabs.filter(
      (t) => t.kind !== "agents" && (!t.thread || t.thread === focusedThread),
    ),
    [mode, focusedThread],
  );
  // If the active tab just went out of scope (thread switch), fall
  // back to the first visible one.
  useEffect(() => {
    if (activeTab && !visibleTabs.some((t) => t.id === activeTab)) {
      setActiveTab(visibleTabs[0]?.id ?? null);
    }
  }, [visibleTabs, activeTab]);

  // Zen right-pane surfaces: everything except the graph (always on
  // the left) and terminal tabs (Zen's pty lives in the chat box /
  // promoted pane — a terminal surface here would double-attach the
  // session and the two xterms would fight over winsize).
  const zenTabs = useMemo(
    () => visibleTabs.filter((t) => t.kind !== "graph" && t.kind !== "terminal"),
    [visibleTabs],
  );
  // Drop a stale surface id (workspace switch replaced the tab set).
  // Synthetic surfaces (Agents, Browser) aren't tabs and always survive.
  useEffect(() => {
    if (zenSurface && !isZenSynthetic(zenSurface)
        && !zenTabs.some((t) => t.id === zenSurface)) {
      setZenSurface(null);
    }
  }, [zenTabs, zenSurface]);

  /** Dropdown pick: reaching the pending artifact's surface by hand
   *  also clears the pulse. */
  const setZenSurfaceChecked = useCallback((s: string) => {
    setZenSurface(s);
    setZenArtifact((cur) => {
      if (!cur || isZenSynthetic(s)) return cur;
      const t = mode.tabs.find((x) => x.id === s);
      return t && t.kind === cur.kind ? null : cur;
    });
  }, [mode]);

  /** One-click jump to the newest artifact — shared by the pulse
   *  badge, the ⌘K palette entry, and the response-half arrow. The
   *  daemon's artifact event carries a ready-to-apply selection, so
   *  the jump lands on the exact plot/deck/page, not just the tab. */
  const jumpToArtifact = useCallback(() => {
    const cur = zenArtifactRef.current;
    if (!cur) return;
    if (cur.selection) setSelection(cur.selection);
    const t = mode.tabs.find((x) => x.kind === cur.kind);
    if (t) setZenSurface(t.id);
    setZenArtifact(null);
  }, [mode, setSelection]);

  // ⌘K → G: cycle to the next tab. ⌘1..9: tab by position. Both walk
  // the VISIBLE set so scoped-out tabs don't swallow a keystroke.
  // In Zen the same keys walk the right-pane surfaces instead
  // (Agents joins the ⌘K→G cycle as the last stop).
  useEffect(() => {
    const disposers = [
      registerChord({
        key: "g",
        description: "Next tab",
        handler: () => {
          if (uiModeRef.current === "zen") {
            const order = [
              ...zenTabs.map((t) => t.id),
              ...ZEN_SYNTHETIC.map((s) => s.id),
            ];
            if (order.length === 0) return;
            setZenSurface((cur) => {
              const i = order.indexOf(cur ?? zenTabs[0]?.id ?? order[0]!);
              return order[(i + 1) % order.length]!;
            });
            return;
          }
          setActiveTab((cur) => {
            if (visibleTabs.length === 0) return cur;
            const i = visibleTabs.findIndex((t) => t.id === cur);
            return visibleTabs[(i + 1) % visibleTabs.length]!.id;
          });
        },
      }),
      ...Array.from({ length: 9 }, (_, n) => registerCombo({
        key: String(n + 1),
        description: `Tab ${n + 1}`,
        handler: () => {
          if (uiModeRef.current === "zen") {
            const t = zenTabs[n];
            if (t) setZenSurface(t.id);
            return;
          }
          const t = visibleTabs[n];
          if (t) setActiveTab(t.id);
        },
      })),
    ];
    return () => { for (const d of disposers) d(); };
  }, [visibleTabs, zenTabs]);

  // ── Terminal pop-out (pty thread ↔ center tab) ────────────────
  // The tab for the FOCUSED thread, when it's popped out. Drives the
  // rail's "lives in a tab" placeholder — never render two xterms
  // against one session (they'd fight over winsize).
  const poppedTerminalTab = useMemo(() => {
    if (!focusedThread) return null;
    const t = mode.tabs.find(
      (x) =>
        x.kind === "terminal"
        && String(
          (x.payload as { thread_id?: unknown } | undefined)?.thread_id ?? "",
        ) === focusedThread,
    );
    return t ? { id: t.id, title: t.title } : null;
  }, [mode, focusedThread]);

  /** ⇱ from the rail pty surface: create (idempotently) the thread's
   *  terminal tab and switch to it. The tab is merged into mode
   *  optimistically — waiting for the hello broadcast would let the
   *  active-tab fallback effect bounce off the not-yet-known id. */
  const onPopOutTerminal = useCallback(async (threadId: string) => {
    try {
      const r = await fetch("/api/tabs/terminal", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_id: threadId }),
      });
      if (!r.ok) return;
      const b = (await r.json()) as { tab?: TabSpec };
      const tab = b.tab;
      if (!tab?.id) return;
      setMode((cur) =>
        cur.tabs.some((t) => t.id === tab.id)
          ? cur
          : { ...cur, tabs: [...cur.tabs, tab] },
      );
      setActiveTab(tab.id);
    } catch { /* daemon down */ }
  }, []);

  /** ⇲ from the rail placeholder: drop the tab; the pty surface
   *  reclaims the rail on the next render. */
  const onPopInTerminalTab = useCallback(async (tabId: string) => {
    try {
      await fetch("/api/tabs/terminal/remove", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tab_id: tabId }),
      });
      setMode((cur) => ({ ...cur, tabs: cur.tabs.filter((t) => t.id !== tabId) }));
    } catch { /* daemon down */ }
  }, []);

  /** Scope-toggle from the tab strip: user tabs flip between
   *  workspace-wide and scoped-to-the-focused-thread. The hello
   *  broadcast carries the updated mode back to every client. */
  const onToggleTabScope = useCallback(async (tab: TabSpec) => {
    const target = tab.thread ? null : focusedThreadRef.current;
    if (!tab.thread && !target) return; // nothing to scope to yet
    try {
      await fetch("/api/tabs/scope", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tab_id: tab.id, thread_id: target }),
      });
    } catch { /* daemon down */ }
  }, []);

  // Issue 5 — paint chrome immediately on (re)load. WS hello can lag
  // by seconds when claude_code probes auth or another provider does
  // an opening handshake; we don't need to gate the workspace name,
  // mode/tab strip, or workspace-switcher on it. Fire HTTP fetches
  // for the cheap state in parallel right after mount; the WS hello
  // arrives later and reconciles (workspace is set-once-equal so no
  // re-render churn). Independent of WS lifecycle so we can mount
  // before the socket connects.
  useEffect(() => {
    let cancelled = false;
    const headers = { "Content-Type": "application/json" };
    void Promise.allSettled([
      fetch("/api/workspaces", { headers })
        .then((r) => r.ok ? r.json() : null)
        .then((b) => {
          if (cancelled || !b) return;
          setWorkspacesState(b as Workspaces);
          if (b.active) setWorkspace((cur) => cur || String(b.active));
        })
        .catch(() => { /* WS hello will fill it */ }),
      fetch("/api/mode", { headers })
        .then((r) => r.ok ? r.json() : null)
        .then((b) => {
          if (cancelled || !b) return;
          // /api/mode shape may differ from Mode — check before setting.
          if (b.tabs && Array.isArray(b.tabs)) {
            setMode(b as Mode);
            setActiveTab((cur) => cur ?? b.tabs[0]?.id ?? null);
          }
        })
        .catch(() => { /* WS hello will fill it */ }),
    ]);
    return () => { cancelled = true; };
  }, []);

  // Flipped true once the RailSocket is constructed. The
  // termWsApi adapter below reads this so its listener-attachment
  // useMemo recomputes after the socket is actually live. Without
  // this, `socketRef.current` is null on first render and any
  // listener attached then attaches against null and is silently
  // dropped.
  const [socketReady, setSocketReady] = useState(false);

  // WS adapter for the rail's PtyThreadSurface — exposes `send` +
  // `onMessage` filtered to `term.*` frames. Lives at App-level
  // because it wraps the singleton socketRef.
  const termWsApi = useMemo<TerminalWsApi | null>(() => {
    if (!socketReady) return null;
    return {
      send: (msg: Record<string, unknown>) => {
        const s = socketRef.current;
        if (!s) return;
        (s as unknown as { send: (m: Record<string, unknown>) => void }).send(msg);
      },
      onMessage: (handler: (msg: Record<string, unknown>) => void) => {
        const s = socketRef.current;
        if (!s) return () => { /* noop */ };
        return s.on((m) => {
          const type = String((m as { type?: unknown }).type ?? "");
          if (type.startsWith("term.")) handler(m as Record<string, unknown>);
        });
      },
    };
  }, [socketReady]);

  useEffect(() => {
    const s = new RailSocket();
    socketRef.current = s;
    setSocketReady(true);
    const off = s.on((msg: ServerMessage) => {
      if (msg.type === "hello") {
        // Just set the workspace; the [workspace] reset effect below
        // clears graph state on a change. (Calling setGraphData inside
        // this updater is a side-effect-in-reducer anti-pattern that
        // React doesn't run reliably — it left the prior workspace's
        // pages in the sidebar after a switch.)
        // Thread ref BEFORE setWorkspace: the workspace hydrate effect
        // reads focusedThreadRef synchronously when it fires. Kind is
        // resolved there too (from /api/threads) — reset it only when
        // the focused thread actually changed (reconnect keeps it).
        if ((msg.thread_id ?? null) !== focusedThreadRef.current) {
          focusedThreadKindRef.current = null;
          setFocusedThreadKind(null);
        }
        focusedThreadRef.current = msg.thread_id ?? null;
        setFocusedThread(msg.thread_id ?? null);
        setWorkspace(msg.workspace);
        focusedWsRef.current = msg.workspace;
        setMode(msg.mode);
        setWorkspacesState(msg.workspaces);
        setActiveTab((cur) => cur ?? msg.mode.tabs[0]?.id ?? null);
        setSelectionLocal(msg.selection);   // restore persisted selection
        setEntries((prev) => {
          // Belt-and-braces: don't append another "connected …" line if
          // the previous entry was already an identical one (covers
          // sequential reconnects after a daemon restart).
          const text = `connected · ${msg.workspace} · mode: ${msg.mode.name} · ${msg.mode.tabs.length} tabs`;
          const last = prev[prev.length - 1];
          if (last && last.source === "system" && last.text === text) return prev;
          return [...prev, { id: ++idRef.current, source: "system", text }];
        });
        // First-install product tour (once per machine; /walkthrough re-runs).
        // If nothing will auto-start, release the first-run gate now;
        // otherwise the tour's own onClose releases it.
        if (!walkthroughAutoTriedRef.current) {
          walkthroughAutoTriedRef.current = true;
          void maybeAutoStartWalkthrough(() => setWalkthroughOpen(true))
            .then((scheduled) => { if (!scheduled) setWalkthroughSettled(true); });
        }
      } else if (msg.type === "notice") {
        setEntries((e) => [
          ...e,
          { id: ++idRef.current, source: "notice", text: msg.text, kind: msg.kind },
        ]);
      } else if (msg.type === "selection_state") {
        // Echo of our own broadcast OR change from another connected client.
        // Ignore a stale page echo just after the user closed the modal —
        // that race reopened Atlas docs.
        const incoming = msg.selection as { kind?: string } | null;
        if (
          incoming?.kind === "page"
          && Date.now() - selectionClosedAt.current < 1200
        ) {
          return;
        }
        setSelectionLocal(msg.selection);
      } else if (msg.type === "thread_focused") {
        // Another client (or our own POST, echoed; or a `!cmd` that
        // spawned a shell thread) moved the daemon's focus. Our own
        // switches set the ref before POSTing, so the echo no-ops
        // here; a genuinely foreign switch re-hydrates.
        if (msg.thread_id !== focusedThreadRef.current) {
          focusedThreadRef.current = msg.thread_id;
          setFocusedThread(msg.thread_id);
          focusedThreadKindRef.current = msg.kind ?? "structured-agent";
          setFocusedThreadKind(msg.kind ?? "structured-agent");
          hydrateThreadRef.current(msg.thread_id);
        }
      } else if (msg.type === "RUN_STARTED") {
        // Learn the run's thread FIRST — later frames carry only runId,
        // and a mid-run switch to this thread needs the mapping even if
        // the run isn't focused right now.
        runMetaRef.current.set(msg.runId, {
          threadId: msg.threadId,
          workspace: msg.workspace,
          provider: msg.provider,
        });
        if (runMetaRef.current.size > 512) {
          const oldest = runMetaRef.current.keys().next().value;
          if (oldest !== undefined) runMetaRef.current.delete(oldest);
        }
        // Rail is per-workspace: drop runs that belong to another
        // workspace. With no entry created here, their later message/
        // tool events (matched by runId) find no row and are ignored.
        if (msg.workspace && msg.workspace !== focusedWsRef.current) {
          foreignRunsRef.current.add(msg.runId);
          return;
        }
        if (focusedThreadRef.current === null) {
          // Our own dispatch on a fresh rail lazily created this
          // thread server-side — adopt it. No re-hydrate: we're
          // already live on an empty transcript. Chat runs only ever
          // start on structured-agent threads.
          focusedThreadRef.current = msg.threadId;
          setFocusedThread(msg.threadId);
          focusedThreadKindRef.current = "structured-agent";
          setFocusedThreadKind("structured-agent");
        } else if (msg.threadId !== focusedThreadRef.current) {
          // Same workspace, different thread — streams to its own
          // transcript only (the dashboard's business, not the rail's).
          return;
        }
        setEntries((prev) => [
          ...prev,
          {
            id: ++idRef.current,
            source: "assistant",
            run_id: msg.runId,
            message_id: null,
            text: "",
            done: false,
            meta: `${msg.provider} · ${msg.model}`,
          },
        ]);
      } else if (msg.type === "TEXT_MESSAGE_START") {
        if (foreignRunsRef.current.has(msg.runId)) return;
        if (runMetaRef.current.get(msg.runId)?.threadId !== focusedThreadRef.current) return;
        setEntries((prev) => {
          // First message of a run claims the empty placeholder bubble
          // RUN_STARTED created; later segments (prose after a tool
          // call) get their own bubble — mirrors how the persisted
          // event log splits assistant prose at tool boundaries.
          for (let i = prev.length - 1; i >= 0; i--) {
            const e = prev[i]!;
            if (e.source === "assistant" && e.run_id === msg.runId) {
              if (!e.done && !e.message_id && e.text === "") {
                const updated = { ...e, message_id: msg.messageId };
                return [...prev.slice(0, i), updated, ...prev.slice(i + 1)];
              }
              break;
            }
          }
          return [
            ...prev,
            {
              id: ++idRef.current,
              source: "assistant",
              run_id: msg.runId,
              message_id: msg.messageId,
              text: "",
              done: false,
            },
          ];
        });
      } else if (msg.type === "TEXT_MESSAGE_CONTENT") {
        setEntries((prev) => {
          // Find the assistant entry for this messageId (almost always
          // the last one). Foreign runs never opened a message, so
          // their deltas fall through harmlessly.
          for (let i = prev.length - 1; i >= 0; i--) {
            const e = prev[i]!;
            if (e.source === "assistant" && e.message_id === msg.messageId) {
              // Streamed deltas sometimes arrive with no whitespace
              // between a sentence-ending punctuation and the next
              // capitalized word ("parallel.Now let me…"). Insert a
              // single space at that specific boundary.
              const sep =
                e.text.length > 0 &&
                /[.!?]$/.test(e.text) &&
                /^[A-Z]/.test(msg.delta)
                  ? " "
                  : "";
              const updated = { ...e, text: e.text + sep + msg.delta };
              return [...prev.slice(0, i), updated, ...prev.slice(i + 1)];
            }
          }
          // Mid-stream join: the user switched onto this run's thread
          // AFTER its TEXT_MESSAGE_START went by (or hydration wiped
          // the live bubble). Open a bubble lazily so the rest of the
          // segment lands instead of vanishing.
          if (
            !foreignRunsRef.current.has(msg.runId) &&
            runMetaRef.current.get(msg.runId)?.threadId === focusedThreadRef.current
          ) {
            return [
              ...prev,
              {
                id: ++idRef.current,
                source: "assistant",
                run_id: msg.runId,
                message_id: msg.messageId,
                text: msg.delta,
                done: false,
              },
            ];
          }
          return prev;
        });
      } else if (msg.type === "TEXT_MESSAGE_END") {
        // Segment closed (tool call incoming, or end of stream) —
        // stop this bubble's streaming cursor. The run-level wrap-up
        // (token meta, error notices) arrives with RUN_FINISHED/ERROR.
        setEntries((prev) =>
          prev.map((e) =>
            e.source === "assistant" && e.message_id === msg.messageId
              ? { ...e, done: true }
              : e,
          ),
        );
      } else if (msg.type === "reasoning") {
        // Chain-of-thought for a segment → a collapsible entry. Same
        // foreign/other-thread guard as streamed text so background
        // runs don't leak into the focused rail.
        if (
          !foreignRunsRef.current.has(msg.runId) &&
          runMetaRef.current.get(msg.runId)?.threadId === focusedThreadRef.current
        ) {
          setEntries((prev) => [
            ...prev,
            { id: ++idRef.current, source: "reasoning", text: msg.text, run_id: msg.runId },
          ]);
        }
      } else if (msg.type === "RUN_FINISHED") {
        const meta = runMetaRef.current.get(msg.runId);
        const wasForeign = foreignRunsRef.current.delete(msg.runId);
        const otherThread = meta?.threadId !== focusedThreadRef.current;
        if (wasForeign || otherThread) {
          // A background run (other workspace or other thread)
          // completed — surface a toast with a jump-back. Shell
          // exits are routine; don't toast those.
          if (meta && meta.provider !== "pty") {
            pushToast({
              text: "background run finished",
              jump: { workspace: meta.workspace, threadId: meta.threadId },
            });
          }
          return;
        }
        setEntries((prev) => {
          for (let i = prev.length - 1; i >= 0; i--) {
            const e = prev[i]!;
            if (e.source === "assistant" && e.run_id === msg.runId) {
              const meta = msg.output_tokens
                ? `${e.meta ?? ""} · ${msg.output_tokens} tok`
                : e.meta;
              const updated = { ...e, done: true, meta };
              return [...prev.slice(0, i), updated, ...prev.slice(i + 1)];
            }
          }
          return prev;
        });
      } else if (msg.type === "RUN_ERROR") {
        const meta = runMetaRef.current.get(msg.runId);
        const wasForeign = foreignRunsRef.current.delete(msg.runId);
        if (wasForeign || meta?.threadId !== focusedThreadRef.current) {
          // Background failure — worth a louder toast than success.
          if (meta && meta.provider !== "pty" && msg.code !== "cancelled") {
            pushToast({
              text: `background run failed (${msg.code})`,
              err: true,
              jump: { workspace: meta.workspace, threadId: meta.threadId },
            });
          }
          return;
        }
        setEntries((prev) => {
          // Mark the in-flight assistant entries as done; append the error.
          const next = prev.map((e) =>
            e.source === "assistant" && e.run_id === msg.runId
              ? { ...e, done: true }
              : e,
          );
          return [
            ...next,
            {
              id: ++idRef.current,
              source: "notice",
              text: `agent error (${msg.code}): ${msg.message}`,
              kind: null,
            },
          ];
        });
      } else if (msg.type === "TOOL_CALL_START") {
        if (foreignRunsRef.current.has(msg.runId)) return;
        if (runMetaRef.current.get(msg.runId)?.threadId !== focusedThreadRef.current) return;
        setEntries((prev) => [
          ...prev,
          {
            id: ++idRef.current,
            source: "tool",
            run_id: msg.runId,
            tool_id: msg.toolCallId,
            name: msg.toolCallName,
            input: {},
          },
        ]);
      } else if (msg.type === "TOOL_CALL_ARGS") {
        setEntries((prev) => {
          // The daemon delivers the complete input as one JSON frame;
          // parse it into the tool entry. (A streaming-args provider
          // would need delta accumulation here — none exists today.)
          for (let i = prev.length - 1; i >= 0; i--) {
            const e = prev[i]!;
            if (e.source === "tool" && e.tool_id === msg.toolCallId) {
              let input = e.input;
              try {
                input = JSON.parse(msg.delta) as Record<string, unknown>;
              } catch {
                // partial frame — keep what we have
              }
              const updated = { ...e, input };
              return [...prev.slice(0, i), updated, ...prev.slice(i + 1)];
            }
          }
          return prev;
        });
      } else if (msg.type === "TOOL_CALL_RESULT") {
        setEntries((prev) => {
          // Patch the matching tool entry in place with its result.
          for (let i = prev.length - 1; i >= 0; i--) {
            const e = prev[i]!;
            if (e.source === "tool" && e.tool_id === msg.toolCallId) {
              const updated = { ...e, result: { ok: msg.ok, summary: msg.content } };
              return [...prev.slice(0, i), updated, ...prev.slice(i + 1)];
            }
          }
          return prev;
        });
      } else if (msg.type === "files_changed") {
        setFilesVersion((v) => v + 1);
      } else if (msg.type === "artifact") {
        // Pend a pulse badge (Zen) AND switch to the surface the
        // agent just wrote — sheet/plot requests used to finish
        // silently while the user was still on Table.
        if (uiModeRef.current === "zen") {
          setZenArtifact({
            kind: msg.kind,
            label: msg.label,
            selection: msg.selection ?? null,
          });
        }
        if (msg.selection) setSelection(msg.selection);
        switchToKindRef.current?.(msg.kind);
      } else if (msg.type === "workspace.merged" || msg.type === "workspace.split") {
        // D2/D4 completion ruling: toast with an Open button, never
        // an auto-switch. Long TTL — the build ran for minutes and
        // the user may only glance back now.
        const m = msg as unknown as { name?: string; path?: string };
        const verb = msg.type === "workspace.merged" ? "merge" : "split";
        pushToast({
          text: `${verb} done — "${m.name ?? "workspace"}" is ready`,
          switchTo: m.path,
        }, 30000);
      } else if (msg.type === "split.proposal") {
        // Agent-driven split gesture: land the user on the graph's
        // split review surface with the proposal pre-highlighted.
        const pages = (msg as unknown as { pages?: string[] }).pages ?? [];
        if (pages.length > 0) {
          switchToKindRef.current("graph");
          window.setTimeout(() => {
            window.dispatchEvent(new CustomEvent("sy:split-proposal", {
              detail: { pages },
            }));
          }, 200);
          pushToast({
            text: `split proposal: ${pages.length} pages highlighted on the graph — review & confirm there`,
          }, 15000);
        }
      } else if (msg.type === "rail_cleared") {
        // /clear-rail-history wiped the workspace's rail DB — every
        // thread is gone. Drop the transcript + paging state AND the
        // focused thread (the next turn creates a fresh one).
        setEntries([]);
        setOldestEventId(null);
        setHasMoreHistory(false);
        focusedThreadRef.current = null;
        setFocusedThread(null);
        focusedThreadKindRef.current = null;
        setFocusedThreadKind(null);
      } else if (msg.type === "daemon.shutdown") {
        // Another window (or /quit here) stopped the daemon. Show the
        // stopped overlay and stop reconnecting into a dead socket.
        setStopped({ reason: msg.reason });
        socketRef.current?.close();
      } else if (msg.type === "decision.review") {
        // Heartbeat drafted a charter amendment — drop the review
        // card into the rail. Dedupe by id: the same proposal can
        // arrive via broadcast AND the pending-refetch on reload.
        setEntries((prev) =>
          prev.some((e) => e.source === "decision" && e.dec_id === msg.id)
            ? prev
            : [
              ...prev,
              {
                id: ++idRef.current,
                source: "decision",
                dec_id: msg.id,
                text: msg.text,
                project: msg.project,
                charter_path: msg.charter_path,
                proposal: msg.proposal,
                state: "pending",
              },
            ],
        );
      } else if (msg.type === "decision.review_resolved") {
        setEntries((prev) =>
          prev.map((e) =>
            e.source === "decision" && e.dec_id === msg.id
              ? { ...e, state: msg.decision === "accept" ? "accepted" : "dismissed" }
              : e,
          ),
        );
      } else if (msg.type === "page_proposal_review") {
        // A local-model page proposal the reviewer flagged borderline —
        // an accept/reject card in the rail. Dedupe by id.
        setEntries((prev) =>
          prev.some((e) => e.source === "proposal" && e.prop_id === msg.id)
            ? prev
            : [
              ...prev,
              {
                id: ++idRef.current,
                source: "proposal",
                prop_id: msg.id,
                op: msg.op,
                kind: msg.kind,
                title: msg.title,
                path: msg.path,
                body: msg.body,
                review: msg.review,
                state: "pending",
              },
            ],
        );
      } else if (msg.type === "page_proposal_resolved") {
        setEntries((prev) =>
          prev.map((e) =>
            e.source === "proposal" && e.prop_id === msg.id
              ? { ...e, state: msg.decision === "accept" ? "accepted" : "dismissed" }
              : e,
          ),
        );
      } else if (msg.type === "provider_retry_offer") {
        // A run failed on a transient/capacity/billing error; offer a
        // one-click retry on another keyed provider (#12). Dedupe by id.
        setEntries((prev) =>
          prev.some((e) => e.source === "provider_retry" && e.retry_id === msg.id)
            ? prev
            : [
              ...prev,
              {
                id: ++idRef.current,
                source: "provider_retry",
                retry_id: msg.id,
                failed_label: msg.failed_label,
                code: msg.code,
                message: msg.message,
                alternatives: msg.alternatives,
                state: "pending",
              },
            ],
        );
      } else if (msg.type === "micro_edit.feedback") {
        const m = msg as {
          id?: string;
          rung_used?: string;
          provider?: string;
          model?: string;
          original_text?: string;
        };
        const fid = String(m.id ?? "");
        if (fid) {
          setEntries((prev) => {
            if (prev.some(
              (e) => e.source === "micro_edit_feedback" && e.feedback_id === fid,
            )) {
              return prev;
            }
            return [
              ...prev,
              {
                id: ++idRef.current,
                source: "micro_edit_feedback",
                feedback_id: fid,
                rung_used: String(m.rung_used ?? "trivial"),
                provider: String(m.provider ?? ""),
                model: String(m.model ?? ""),
                original_text: String(m.original_text ?? ""),
                state: "pending",
              },
            ];
          });
        }
      } else if (msg.type === "local_models.check_prompt") {
        const message = String(
          (msg as { message?: string }).message
          ?? "Check for newer local models?",
        );
        setEntries((prev) => {
          if (prev.some((e) => e.source === "local_models_check" && e.state === "pending")) {
            return prev;
          }
          return [
            ...prev,
            {
              id: ++idRef.current,
              source: "local_models_check",
              message,
              state: "pending",
            },
          ];
        });
      } else if (msg.type === "local_models.discovery") {
        const discovery = (msg as { discovery?: Record<string, unknown> }).discovery
          ?? {};
        setEntries((prev) => [
          ...prev,
          {
            id: ++idRef.current,
            source: "local_models_discovery",
            discovery: discovery as Extract<
              import("./rail/Rail").RailEntry,
              { source: "local_models_discovery" }
            >["discovery"],
            state: "pending",
          },
        ]);
      } else if (msg.type === "provider_retry_resolved") {
        setEntries((prev) =>
          prev.map((e) =>
            e.source === "provider_retry" && e.retry_id === msg.id
              ? { ...e, state: msg.provider ? "retried" : "dismissed", chosen: msg.provider }
              : e,
          ),
        );
      } else if (msg.type === "permission_request") {
        // Agent's PreToolUse hook (claude-code) is asking the user to
        // approve a tool call that isn't on the static allowlist.
        // Cards owned by the FOCUSED thread drop inline into the
        // transcript; everything else — external CLI sessions (bench
        // runs, scripts) and background threads — goes to the pinned
        // strip so parallel sessions can't bleed into the open
        // conversation as if they were part of it.
        const perm = {
          id: ++idRef.current,
          source: "permission" as const,
          req_id: msg.req_id,
          provider: msg.provider,
          tool: msg.tool,
          tool_input: msg.tool_input,
          pattern: msg.pattern,
          run_id: msg.run_id,
          origin: msg.origin ?? null,
          origin_path: msg.origin_path ?? null,
          state: "pending" as const,
        };
        if (msg.thread_id && msg.thread_id === focusedThreadRef.current) {
          setEntries((prev) => [...prev, perm]);
        } else {
          setOtherPerms((prev) => [...prev, perm]);
        }
      } else if (msg.type === "permission_resolved") {
        // "skip" = a muted source's card was cleared — drop it silently
        // (no approved/denied flash; the user didn't judge it).
        if (msg.decision === "skip") {
          setOtherPerms((prev) => prev.filter((e) => e.req_id !== msg.req_id));
          setEntries((prev) =>
            prev.filter((e) => !(e.source === "permission" && e.req_id === msg.req_id)),
          );
        } else {
          // Flip the matching dialog to its settled state and let it
          // linger one render tick before pruning, so the user can
          // see the verdict acknowledged in place. Strip cards prune
          // themselves after a beat — they have no transcript to
          // linger in.
          const settled =
            msg.decision === "approve" ? ("approved" as const) : ("denied" as const);
          setEntries((prev) =>
            prev.map((e) =>
              e.source === "permission" && e.req_id === msg.req_id
                ? { ...e, state: settled }
                : e,
            ),
          );
          setOtherPerms((prev) =>
            prev.map((e) => (e.req_id === msg.req_id ? { ...e, state: settled } : e)),
          );
          window.setTimeout(() => {
            setOtherPerms((prev) => prev.filter((e) => e.req_id !== msg.req_id));
          }, 2500);
        }
      } else if (msg.type === "sql.run") {
        // `!sql` — stash so cold Table tab drains on mount (only the
        // active tab is rendered).
        const m = msg as { query?: unknown; command_id?: unknown };
        const query = String(m.query ?? "");
        const commandId =
          m.command_id != null && String(m.command_id) ? String(m.command_id) : undefined;
        if (query) {
          const detail = { query, command_id: commandId };
          stashSql(detail);
          switchToKindRef.current?.("duckdb");
          window.setTimeout(() => {
            window.dispatchEvent(new CustomEvent("sy:sql-run", {
              detail,
            }));
          }, 0);
        }
      } else if (msg.type === "formula.run") {
        // `!fn` / sheet_set_formula — stash for cold Sheet tab.
        const m = msg as {
          formula?: unknown;
          cell?: unknown;
          writes?: unknown;
          command_id?: unknown;
        };
        const writes = Array.isArray(m.writes) ? m.writes : null;
        const formula = String(m.formula ?? "");
        const cell = m.cell != null ? String(m.cell) : undefined;
        const commandId =
          m.command_id != null && String(m.command_id) ? String(m.command_id) : undefined;
        if (writes?.length || formula) {
          const detail = writes?.length
            ? {
                writes: writes as { cell: string; formula: string }[],
                command_id: commandId,
              }
            : { formula, cell, command_id: commandId };
          stashFormula(detail);
          switchToKindRef.current?.("univer");
          window.setTimeout(() => {
            window.dispatchEvent(new CustomEvent("sy:formula-run", {
              detail,
            }));
          }, 50);
        }
      } else if (msg.type === "sheet.values") {
        const m = msg as {
          values?: unknown;
          origin?: unknown;
          command_id?: unknown;
        };
        const values = Array.isArray(m.values) ? m.values : [];
        const origin = String(m.origin ?? "agent");
        const commandId =
          m.command_id != null && String(m.command_id) ? String(m.command_id) : undefined;
        if (values.length) {
          const detail = {
            values: values as (string | number | boolean | null)[][],
            origin,
            command_id: commandId,
          };
          stashSheetValues(detail);
          switchToKindRef.current?.("univer");
          window.setTimeout(() => {
            window.dispatchEvent(new CustomEvent("sy:sheet-values", {
              detail,
            }));
          }, 50);
        }
      } else if (msg.type === "sheet.select") {
        const range = String((msg as { range?: unknown }).range ?? "");
        if (range) {
          stashSheetSelect(range);
          switchToKindRef.current?.("univer");
          window.setTimeout(() => {
            window.dispatchEvent(new CustomEvent("sy:sheet-select", {
              detail: { range },
            }));
          }, 50);
        }
      } else if (msg.type === "plot.show") {
        const m = msg as { id?: unknown; name?: unknown; command_id?: unknown };
        const id = String(m.id ?? "");
        const name = String(m.name ?? id);
        const commandId =
          m.command_id != null && String(m.command_id) ? String(m.command_id) : undefined;
        if (id) {
          const detail = { id, name, command_id: commandId };
          stashPlotShow(detail);
          setSelection({ kind: "plot", id, name });
          switchToKindRef.current?.("vega");
          window.setTimeout(() => {
            window.dispatchEvent(new CustomEvent("sy:plot-show", {
              detail,
            }));
          }, 50);
        }
      } else if (msg.type === "sketch.show") {
        const m = msg as {
          sketch_id?: unknown;
          slide_index?: unknown;
          name?: unknown;
          command_id?: unknown;
        };
        const sketchId = m.sketch_id != null ? String(m.sketch_id) : "";
        const slideIndex = typeof m.slide_index === "number" ? m.slide_index : null;
        const name = m.name != null ? String(m.name) : sketchId;
        const commandId =
          m.command_id != null && String(m.command_id) ? String(m.command_id) : undefined;
        stashSketchShow({
          sketch_id: sketchId || null,
          slide_index: slideIndex,
          name,
          command_id: commandId,
        });
        if (sketchId) {
          setSelection({ kind: "sketch", id: sketchId, name: name || sketchId });
        }
        switchToKindRef.current?.("sketch");
        window.setTimeout(() => {
          window.dispatchEvent(new CustomEvent("sy:sketch-show", {
            detail: {
              sketch_id: sketchId || null,
              slide_index: slideIndex,
              name,
              command_id: commandId,
            },
          }));
        }, 50);
      } else if (msg.type === "thread.titled") {
        // The background auto-titler named a thread — nudge the
        // ThreadBar so the label updates without a manual refresh.
        window.dispatchEvent(new CustomEvent("sy:thread-titled", {
          detail: { thread_id: msg.thread_id, title: msg.title },
        }));
      } else if (msg.type === "thread.project_changed") {
        // /project verb or the picker chip (possibly in another tab)
        // rebound a thread — refresh the ThreadBar chip + rows.
        window.dispatchEvent(new CustomEvent("sy:threads-changed"));
      } else if (msg.type === "thread.archived" || msg.type === "threads.purged") {
        // Removed threads: refresh the switcher; if the focused
        // thread went away without a follow-up thread_focused (last
        // thread archived), clear the rail rather than show a ghost.
        window.dispatchEvent(new CustomEvent("sy:threads-changed"));
        const gone = msg.type === "thread.archived"
          ? [msg.thread_id]
          : msg.thread_ids;
        if (focusedThreadRef.current && gone.includes(focusedThreadRef.current)) {
          onResetRef.current?.();
        }
      } else if (msg.type === "open_report") {
        // A capable model built a rich HTML report — hand the id to the
        // Report tab (it loads regardless) and focus the tab. The tab was
        // just added to mode.tabs by the preceding hello, but React state
        // may not have settled this tick, so retry the focus briefly
        // until switch-by-kind finds it.
        notifyReportOpen(String(msg.report_id || ""), String(msg.title || "Report"));
        const focus = (tries: number) => {
          if (switchToKindRef.current?.("report")) return;
          if (tries > 0) window.setTimeout(() => focus(tries - 1), 60);
        };
        focus(10);
      } else if (msg.type === "open_intro") {
        // /intro (or the first-install seed) added the Intro tab — focus
        // it. Like open_report, the tab arrived via the preceding hello,
        // so retry the switch briefly until React settles it in.
        const focus = (tries: number) => {
          if (switchToKindRef.current?.("intro")) return;
          if (tries > 0) window.setTimeout(() => focus(tries - 1), 60);
        };
        focus(10);
      } else if (msg.type === "open_html_deck") {
        const m = msg as { slug?: string; title?: string };
        if (m.slug) {
          // Stash + event so the lazy HtmlDeckTab still picks up the
          // show if it mounts after this message (first package click).
          notifyHtmlDeckOpen(m.slug, m.title || m.slug);
          const focus = (tries: number) => {
            if (switchToKindRef.current?.("html-deck")) return;
            if (tries > 0) window.setTimeout(() => focus(tries - 1), 60);
          };
          focus(10);
        }
      } else if (msg.type === "open_report_doc") {
        const m = msg as { slug?: string; title?: string };
        if (m.slug) {
          notifyReportDocOpen(m.slug, m.title || m.slug);
          const focus = (tries: number) => {
            if (switchToKindRef.current?.("report-doc")) return;
            if (tries > 0) window.setTimeout(() => focus(tries - 1), 60);
          };
          focus(10);
        }
      } else if (msg.type === "open_worksheet") {
        // SheetTab listens for sy:open-worksheet and applies snapshot.
        const m = msg as { slug?: string; title?: string; snapshot?: unknown };
        window.dispatchEvent(new CustomEvent("sy:open-worksheet", {
          detail: m,
        }));
        const focus = (tries: number) => {
          if (switchToKindRef.current?.("univer")) return;
          if (tries > 0) window.setTimeout(() => focus(tries - 1), 60);
        };
        focus(10);
      } else if (msg.type === "open_thrusters") {
        // Settings easter egg armed the Hopper tab — focus it.
        const focus = (tries: number) => {
          if (switchToKindRef.current?.("thrusters")) return;
          if (tries > 0) window.setTimeout(() => focus(tries - 1), 60);
        };
        focus(10);
      } else if (msg.type === "open_walkthrough") {
        setWalkthroughOpen(true);
      } else if (msg.type === "nav") {
        // /verb dispatched from the daemon: switch to the right tab,
        // apply selection if provided, and breadcrumb on the rail.
        const ok = switchToKindRef.current?.(msg.tab_kind);
        if (msg.payload?.selection !== undefined) {
          // null is meaningful — clear selection. Skip undefined to
          // avoid clobbering when the verb chose not to set selection.
          setSelection(msg.payload.selection ?? null);
        }
        setEntries((e) => [
          ...e,
          {
            id: ++idRef.current,
            source: "system",
            text: ok
              ? `→ ${msg.label}  ·  ${msg.tab_kind}`
              : `→ ${msg.label}  ·  no '${msg.tab_kind}' tab in this mode`,
          },
        ]);
      }
    });
    return () => {
      off();
      s.close();
      socketRef.current = null;
      setSocketReady(false);
    };
  }, []);

  // Per-workspace GraphData cache. Switching back to a workspace
  // we've already loaded paints the graph instantly from the cache;
  // a background refresh kicks in to pick up agent / external edits.
  // Invalidated on files_changed for the currently-active workspace
  // only (handled via filesVersion + the active-key check below).
  const graphCacheRef = useRef<Map<string, GraphData>>(new Map());
  const lastFilesVersionRef = useRef<number>(0);

  // The WorkspaceSwitcher hover-prefetch dispatches
  // `sy:graph-prefetched` with the foreign workspace's GraphData;
  // seed the cache here so a subsequent click paints instantly
  // (no fetch round-trip, no JSON parse).
  useEffect(() => {
    const onPrefetched = (ev: Event) => {
      const detail = (ev as CustomEvent<{ workspace: string; data: GraphData }>).detail;
      if (!detail?.workspace || !detail?.data) return;
      graphCacheRef.current.set(detail.workspace, detail.data);
    };
    window.addEventListener("sy:graph-prefetched", onPrefetched);
    return () => window.removeEventListener("sy:graph-prefetched", onPrefetched);
  }, []);

  // Reset graph state whenever the active workspace changes, so the
  // sidebar/graph never show the previous workspace's pages while the
  // new one's fetch is in flight (or fails because it has no wiki). The
  // fetch effect below then repaints from cache or the network.
  useEffect(() => {
    setGraphData(null);
    setGraphError(null);
  }, [workspace]);

  // Graph tab's "Retry" affordance (timeout / build failure) → re-run
  // the fetch effect below.
  useEffect(() => {
    const onReload = () => {
      setGraphError(null);
      setGraphReloadTick((t) => t + 1);
    };
    window.addEventListener("sy:graph-reload", onReload);
    return () => window.removeEventListener("sy:graph-reload", onReload);
  }, []);

  // Rehydrate borderline page proposals on load / workspace switch:
  // proposal review cards are disk-backed (survive a daemon restart),
  // but a browser reload wipes the in-memory rail entries. Re-fetch the
  // open ones so an Accept/Reject decision isn't lost to a refresh.
  useEffect(() => {
    if (!workspace) return;
    let cancelled = false;
    void (async () => {
      try {
        const r = await fetch("/api/proposals/pending");
        if (!r.ok || cancelled) return;
        const body = (await r.json()) as { proposals?: Array<{
          id: string; op: string; kind: string; title: string;
          path: string; body: string;
          review: { verdict?: string; confidence?: number; issues?: string[]; one_line?: string } | null;
        }> };
        const pending = body.proposals ?? [];
        if (pending.length === 0 || cancelled) return;
        setEntries((prev) => {
          const have = new Set(
            prev.filter((e) => e.source === "proposal").map((e) => (e as { prop_id: string }).prop_id),
          );
          const add = pending
            .filter((p) => !have.has(p.id))
            .map((p) => ({
              id: ++idRef.current,
              source: "proposal" as const,
              prop_id: p.id,
              op: p.op,
              kind: p.kind,
              title: p.title,
              path: p.path,
              body: p.body,
              review: p.review,
              state: "pending" as const,
            }));
          return add.length ? [...prev, ...add] : prev;
        });
      } catch {
        /* best-effort rehydrate */
      }
    })();
    return () => { cancelled = true; };
  }, [workspace]);

  // Poll active runs so the rail can mark run-blocks live vs done +
  // drive the focus-switcher. Cheap in-memory read on the daemon.
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await fetch("/api/runs/active");
        if (!r.ok) return;
        const body = (await r.json()) as { runs?: ActiveRun[] };
        if (cancelled) return;
        const runs = body.runs ?? [];
        activeRunsRef.current = runs;
        setActiveRuns(runs);
        const ids = new Set<string>();
        for (const run of runs) if (run.run_id) ids.add(run.run_id);
        setActiveRunIds((prev) => {
          // Keep the same Set reference when unchanged (stable memo input).
          if (prev.size === ids.size && [...ids].every((x) => prev.has(x))) return prev;
          return ids;
        });
      } catch { /* transient — try again next tick */ }
    };
    void tick();
    const h = window.setInterval(() => void tick(), 2000);
    return () => { cancelled = true; window.clearInterval(h); };
  }, []);

  useEffect(() => {
    if (!workspace) return;
    let cancelled = false;

    const cache = graphCacheRef.current;
    const cached = cache.get(workspace);

    // If filesVersion bumped (file edit broadcast), the cache for the
    // *currently active* workspace is stale — drop it before the
    // hit/miss check so we don't paint stale data after a change.
    if (filesVersion !== lastFilesVersionRef.current) {
      cache.delete(workspace);
      lastFilesVersionRef.current = filesVersion;
    }

    const fresh = cache.get(workspace);
    if (fresh) {
      // Instant paint from cache; refresh in the background so an
      // agent's recent edits land within a beat.
      setGraphData(fresh);
    }

    // Request THIS workspace's graph explicitly (?workspace=<abs-path>)
    // rather than the daemon's "currently active" one. Two switches in
    // quick succession used to let the previous workspace's data land +
    // cache under the new workspace's key; pinning the request to the
    // path this effect is for makes the response deterministic, and the
    // `cancelled` guard drops a superseded in-flight fetch. A timeout
    // aborts a hung build so the tab can offer a retry instead of
    // spinning forever.
    const ctrl = new AbortController();
    const timer = window.setTimeout(() => ctrl.abort(), 30_000);
    fetch(`/api/graph/data?workspace=${encodeURIComponent(workspace)}`, { signal: ctrl.signal })
      .then(async (r) => {
        if (!r.ok) {
          const body = (await r.json().catch(() => ({}))) as { error?: string };
          throw new Error(body.error ?? `HTTP ${r.status}`);
        }
        return (await r.json()) as GraphData;
      })
      .then((d) => {
        if (cancelled) return;
        cache.set(workspace, d);
        setGraphData(d);
      })
      .catch((e: Error) => {
        if (cancelled || cached) return;
        setGraphError(
          e.name === "AbortError"
            ? "graph build timed out — retry"
            : e.message,
        );
        // The "no wiki / viewer.sh build failed" prompt is DERIVED from
        // graphError (see noWikiAction below) and pinned in the rail —
        // NOT pushed as an entry, which races with rail re-hydration
        // (a reconnect/restart re-hydrates and wipes the entry).
      })
      .finally(() => window.clearTimeout(timer));
    return () => {
      cancelled = true;
      ctrl.abort();
      window.clearTimeout(timer);
    };
  }, [workspace, filesVersion, graphReloadTick]);

  /** Rail wikilinks ([[target]] in assistant prose) → open the page
   *  in the Graph tab's doc modal. Resolution is fuzzy: exact node
   *  id, path stem, or title — model-authored links vary in shape. */
  useEffect(() => {
    const onOpenWiki = (ev: Event) => {
      const target = String(
        (ev as CustomEvent<{ target?: string }>).detail?.target ?? "",
      ).trim();
      const g = graphDataRef.current;
      if (!target || !g) return;
      const tl = target.split("#")[0].toLowerCase().replace(/\.md$/, "");
      const stem = tl.split("/").pop() ?? tl;
      const bareTitle = (t: string) => t.replace(/^\[[^\]]+\]\s+/, "").toLowerCase();
      const nodes = g.nodes ?? [];
      const hit =
        nodes.find((n) => n.id.toLowerCase() === tl)
        ?? nodes.find((n) => {
          const nid = n.id.toLowerCase();
          return nid === stem || nid.endsWith(`/${stem}`);
        })
        ?? nodes.find((n) => (n.title ?? "").toLowerCase() === tl)
        ?? nodes.find((n) => bareTitle(n.title ?? "") === tl || bareTitle(n.title ?? "") === stem);
      if (!hit) return;
      const page = g.pages[hit.id];
      setSelection({ kind: "page", id: hit.id, path: page?.path ?? hit.id });
      // Zen: docs open in the right-pane Editor (the graph doc modal
      // is suppressed there); Power keeps the modal-on-graph flow.
      switchToKindRef.current?.(
        uiModeRef.current === "zen" ? "markdown" : "graph",
      );
    };
    window.addEventListener("sy:open-wiki-page", onOpenWiki);
    return () => window.removeEventListener("sy:open-wiki-page", onOpenWiki);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** CE's sidebar + graph.js still write `#page=<id>` to window.location.hash
   *  when the user clicks. Translate that into a selection-layer dispatch. */
  useEffect(() => {
    const onHash = () => {
      const m = window.location.hash.match(/^#page=([^&]+)$/);
      if (m) {
        const id = decodeURIComponent(m[1]);
        const page = graphDataRef.current?.pages[id];
        if (page) {
          setSelection({ kind: "page", id, path: page.path });
          // Power: route to the Graph tab so the doc modal opens.
          // For deck/analysis pages the modal exposes a "↗ Sketch"
          // button to switch into deck-mode in the Sketch tab on
          // explicit user action — auto-jumping there from the
          // sidebar click was disorienting.
          // Zen: a graph node click opens the doc in the right-pane
          // Editor instead (artifacts-on-the-right applies to
          // navigation too; the doc modal stays Power-only).
          switchToKindRef.current?.(
            uiModeRef.current === "zen" ? "markdown" : "graph",
          );
        }
      }
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [setSelection]);

  /** Highlight the active row in the Browser sidebar regardless of which
   *  tab is active. Modal/graph effects live in GraphTab (they can only
   *  fire when that tab is mounted). */
  useEffect(() => {
    if (!graphData) return;
    if (!selection || selection.kind !== "page") return;
    try { window.Sidebar.setActive(selection.id); } catch { /* ignore */ }
  }, [selection, graphData]);

  /** One-shot tips to drop into the rail the first time the user opens
   *  certain tabs. Tips don't persist across sessions — they're soft
   *  affordances, not user-configurable settings. */
  const shownTipsRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (!activeTab) return;
    const kind = mode.tabs.find((t) => t.id === activeTab)?.kind;
    if (kind === "duckdb" && !shownTipsRef.current.has("duckdb-starters")) {
      shownTipsRef.current.add("duckdb-starters");
      setEntries((prev) => [
        ...prev,
        {
          id: ++idRef.current,
          source: "notice",
          kind: null,
          text: "tip · SQL starter pills in the Table tab are editable. Click ✎ Edit starters to manage them by hand, or just ask me — \"add a starter that shows pages with degree > 10\" — and I'll add the pill via my add_duckdb_starters tool. Saved per workspace under .workbench/state/duckdb-starters.json.",
        },
      ]);
    }
  }, [activeTab, mode]);

  /** Global notice channel for non-tab UI to inject helper text into
   *  the rail (e.g. the "New…" tab affordance in TabStrip). Also
   *  re-dispatches `sy:rail-focus` so the input takes focus right
   *  after the message lands. */
  useEffect(() => {
    const onSystemTip = (ev: Event) => {
      const detail = (ev as CustomEvent<{ text: string; focus?: boolean }>).detail;
      if (!detail || !detail.text) return;
      setEntries((prev) => [
        ...prev,
        { id: ++idRef.current, source: "notice", kind: null, text: detail.text },
      ]);
      if (detail.focus) {
        // Defer to next tick so the new entry is in the DOM before
        // the rail tries to scroll-to-bottom on focus.
        window.setTimeout(() => {
          window.dispatchEvent(new CustomEvent("sy:rail-focus"));
        }, 0);
      }
    };
    window.addEventListener("sy:rail-system-tip", onSystemTip);
    return () => window.removeEventListener("sy:rail-system-tip", onSystemTip);
  }, []);

  /** Bridge from the vanilla-JS graph modal's "→ Slides" button into
   *  the React selection + tab-switch surfaces. The modal POSTs to
   *  /api/analysis/from-doc itself and dispatches this event with
   *  the resulting analysis's path; we set selection to that path,
   *  switch the active tab to the sketcher, and close the modal so
   *  the user lands directly on the new deck.
   *  Same cross-boundary pattern as `sy:rail-system-tip`. */
  useEffect(() => {
    const onOpenAsDeck = (ev: Event) => {
      const detail = (ev as CustomEvent<{
        path: string; title: string; slug: string;
        analysis?: Record<string, unknown>;
      }>).detail;
      if (!detail || !detail.path) return;
      // Prime the Sketch tab's analysis cache so the deck badge
      // appears on the next render — no /api/analysis round-trip
      // needed. Falls back to the fetch path if the modal didn't
      // attach the record (older callers).
      if (detail.analysis && typeof detail.analysis === "object") {
        primeAnalysis({
          ...detail.analysis,
          path: detail.path,
        });
      }
      setSelection({ kind: "page", id: detail.path, path: detail.path });
      switchToKindRef.current?.("sketch");
      try { window.Modal?.close(); } catch { /* modal may not be mounted */ }
      // Nudge the wiki + file browsers to refresh so the new deck
      // appears in the sidebar's analyses section without the user
      // needing to manually rescan. The daemon also rebuilds + emits
      // files_changed, but the rebuild can lag a couple of seconds
      // — bump the local counter to refetch immediately.
      setFilesVersion((v) => v + 1);
    };
    window.addEventListener("sy:open-as-deck", onOpenAsDeck);
    return () => window.removeEventListener("sy:open-as-deck", onOpenAsDeck);
  }, [setSelection]);

  /** Cross-boundary bridge for the graph modal's per-table "↗ Sheet"
   *  buttons. The modal walks every <table> in the rendered body
   *  and dispatches this event with the parsed 2D values + an
   *  origin breadcrumb; we set the table-data selection + flip
   *  the active tab to Sheet. */
  useEffect(() => {
    const onOpenAsSheet = (ev: Event) => {
      const detail = (ev as CustomEvent<{ origin: string; values: (string | number | null)[][] }>).detail;
      if (!detail || !Array.isArray(detail.values)) return;
      setSelection({
        kind: "table-data",
        origin: detail.origin || "graph-modal",
        values: detail.values,
      });
      switchToKindRef.current?.("univer");
      // Don't call window.Modal.close() — its onClose callback
      // (registered in GraphTab.tsx) nulls selection back to null,
      // which clobbers the table-data we just set. The modal stays
      // open behind the now-active Sheet tab and the user can dismiss
      // it on next visit.
    };
    window.addEventListener("sy:open-as-sheet", onOpenAsSheet);
    return () => window.removeEventListener("sy:open-as-sheet", onOpenAsSheet);
  }, [setSelection]);

  /** Cross-boundary tab-switch hatch. Used by vanilla-JS callers
   *  (graph modal's ↗ Plot button etc.) that have an existing
   *  context and just need React to flip to a different tab kind
   *  without setting a selection. */
  useEffect(() => {
    const onSwitchTab = (ev: Event) => {
      const detail = (ev as CustomEvent<{ kind: string }>).detail;
      if (!detail || !detail.kind) return;
      switchToKindRef.current?.(detail.kind);
    };
    window.addEventListener("sy:switch-tab-kind", onSwitchTab);
    return () => window.removeEventListener("sy:switch-tab-kind", onSwitchTab);
  }, []);

  /** Same vanilla-JS → React bridge for the graph modal's populate
   *  hand-off. The modal kicks /api/analysis/populate on its own
   *  thread and dispatches `sy:register-deck-run` with the run_id;
   *  we feed it into the sketch tab's deckRuns store so the
   *  spinner badge shows next to the deck title. */
  useEffect(() => {
    const onRegister = (ev: Event) => {
      const detail = (ev as CustomEvent<{ analysis_path: string; run_id: string }>).detail;
      if (!detail?.analysis_path || !detail?.run_id) return;
      void import("./widgets/sketch/deckRuns").then(({ setDeckRun }) => {
        setDeckRun(detail.analysis_path, detail.run_id);
      });
    };
    window.addEventListener("sy:register-deck-run", onRegister);
    return () => window.removeEventListener("sy:register-deck-run", onRegister);
  }, []);

  /** Rail-row `↗` jump button → expand the agents panel + tell the
   *  dashboard which run to auto-expand. Two-step so the dashboard
   *  has time to mount before its expand handler fires. */
  useEffect(() => {
    const onJump = (ev: Event) => {
      const detail = (ev as CustomEvent<{ run_id: string }>).detail;
      if (!detail?.run_id) return;
      if (uiModeRef.current === "zen") {
        // No bottom panel in Zen — the Agents dashboard is a right-
        // pane surface. Give it a beat to mount before expanding.
        setZenSurface("agents");
        window.setTimeout(() => {
          window.dispatchEvent(new CustomEvent("sy:expand-run", {
            detail: { run_id: detail.run_id },
          }));
        }, 200);
        return;
      }
      window.dispatchEvent(new CustomEvent("sy:agents-panel", {
        detail: { state: "expanded" },
      }));
      window.setTimeout(() => {
        window.dispatchEvent(new CustomEvent("sy:expand-run", {
          detail: { run_id: detail.run_id },
        }));
      }, 0);
    };
    window.addEventListener("sy:open-agents-run", onJump);
    return () => window.removeEventListener("sy:open-agents-run", onJump);
  }, []);

  const onSubmit = (text: string, opts: { n: number }) => {
    setEntries((e) => [...e, { id: ++idRef.current, source: "user", text }]);
    const payload: { type: "user_input"; text: string; n?: number } = {
      type: "user_input", text,
    };
    // Only include `n` when fan-out is dialed in. Daemon treats
    // missing / 0 / 1 as ordinary single-agent chat — keep the wire
    // shape backwards-compatible for older clients.
    if (opts.n >= 2) payload.n = opts.n;
    socketRef.current?.send(payload);
  };

  /** Drop displayed rail entries to match the daemon-side reset.
   *  The on-disk rail log is untouched — older turns stay searchable
   *  via recall_rail. The next turn opens a FRESH thread, so the
   *  focused thread is cleared too (RUN_STARTED adopts the new one). */
  const onReset = useCallback(() => {
    setEntries([]);
    setOldestEventId(null);
    setHasMoreHistory(false);
    focusedThreadRef.current = null;
    setFocusedThread(null);
    focusedThreadKindRef.current = null;
    setFocusedThreadKind(null);
  }, []);
  // Stable handle for the once-mounted WS handler (thread.archived /
  // threads.purged may need to clear a now-gone focused thread).
  const onResetRef = useRef(onReset);
  useEffect(() => { onResetRef.current = onReset; }, [onReset]);

  // Monotonic hydration token: a slow response from a superseded
  // hydrate (rapid thread switching) must not clobber the newer one.
  const hydrateSeqRef = useRef(0);

  /** Re-offer undecided permission cards. They are in-memory
   *  server-side (they settle within the hook's long-poll), so thread
   *  switches and reloads would otherwise lose them: focused-thread
   *  cards re-land in the transcript, the rest refresh the pinned
   *  "outside this thread" strip. */
  const refreshPendingPerms = useCallback((tid: string | null, seq: number) => {
    void fetch("/api/permission/pending")
      .then((r) => (r.ok ? r.json() : null))
      .then((b: {
        pending: {
          req_id: string; provider: string; tool: string;
          tool_input: Record<string, unknown>; pattern: string;
          run_id: string | null; thread_id: string | null;
          origin: string | null; origin_path: string | null;
        }[];
      } | null) => {
        if (!b?.pending || seq !== hydrateSeqRef.current) return;
        const toEntry = (p: (typeof b.pending)[number]) => ({
          id: ++idRef.current,
          source: "permission" as const,
          req_id: p.req_id,
          provider: p.provider,
          tool: p.tool,
          tool_input: p.tool_input,
          pattern: p.pattern,
          run_id: p.run_id,
          origin: p.origin,
          origin_path: p.origin_path,
          state: "pending" as const,
        });
        const mine = tid ? b.pending.filter((p) => p.thread_id === tid) : [];
        const others = b.pending.filter((p) => !tid || p.thread_id !== tid);
        setOtherPerms(others.map(toEntry));
        if (mine.length) {
          setEntries((prev) => [
            ...prev,
            ...mine
              .filter((p) => !prev.some(
                (e) => e.source === "permission" && e.req_id === p.req_id,
              ))
              .map(toEntry),
          ]);
        }
      })
      .catch(() => { /* older daemon — nothing to re-offer */ });
  }, []);

  /** Load one thread's transcript into the rail (thread switch, other
   *  clients' thread_focused, workspace open). Imperative — live
   *  adoption of a just-created thread deliberately does NOT re-fetch,
   *  so the in-flight bubbles survive. */
  const hydrateThread = useCallback((tid: string | null) => {
    const seq = ++hydrateSeqRef.current;
    setEntries([]);
    setOldestEventId(null);
    if (!tid) {
      setHasMoreHistory(false);
      refreshPendingPerms(null, seq);
      return;
    }
    setHasMoreHistory(true);
    fetch(`/api/rail/events?limit=50&thread_id=${encodeURIComponent(tid)}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((body: { events: RailEvent[] }) => {
        if (seq !== hydrateSeqRef.current) return;
        setEntries(hydrateEvents(body.events));
        if (body.events.length > 0) {
          setOldestEventId(body.events[0]!.event_id);
          setHasMoreHistory(body.events.length >= 50);
        } else {
          setHasMoreHistory(false);
        }
        // Re-offer undecided permission cards for this thread + refresh
        // the out-of-thread strip.
        refreshPendingPerms(tid, seq);
        // Re-offer undecided charter-amendment cards (D9) — they are
        // workspace-level and disk-backed, so every hydration (thread
        // switch, reload, workspace open) appends the outstanding
        // ones after the transcript. Dedupe by dec_id.
        void fetch("/api/decisions/pending")
          .then((r) => (r.ok ? r.json() : null))
          .then((b: {
            decisions: {
              id: string; text: string; project: string | null;
              charter_path: string; proposal: string;
            }[];
          } | null) => {
            if (!b || seq !== hydrateSeqRef.current) return;
            if (!b.decisions?.length) return;
            setEntries((prev) => [
              ...prev,
              ...b.decisions
                .filter((d) => !prev.some(
                  (e) => e.source === "decision" && e.dec_id === d.id,
                ))
                .map((d) => ({
                  id: ++idRef.current,
                  source: "decision" as const,
                  dec_id: d.id,
                  text: d.text,
                  project: d.project,
                  charter_path: d.charter_path,
                  proposal: d.proposal,
                  state: "pending" as const,
                })),
            ]);
          })
          .catch(() => { /* older daemon — no cards to re-offer */ });
      })
      .catch((e: Error) => {
        if (seq !== hydrateSeqRef.current) return;
        setHasMoreHistory(false);
        setEntries([{
          id: ++idRef.current,
          source: "notice",
          kind: null,
          text: `Couldn't load thread history: ${e.message}. Live messages will still appear.`,
        }]);
      });
  }, [refreshPendingPerms]);
  // Ref for the once-mounted socket handler (thread_focused arrives
  // there); always points at the latest callback.
  const hydrateThreadRef = useRef(hydrateThread);
  useEffect(() => { hydrateThreadRef.current = hydrateThread; });

  /** Switcher click: move the rail (and the daemon's focus) to `tid`.
   *  Sessions are per-thread server-side, so the thread we leave stays
   *  continuable. */
  const onSwitchThread = useCallback((tid: string, kind: string) => {
    if (tid === focusedThreadRef.current) return;
    // Background-on-switch: if the thread we're leaving still has
    // live runs, say so (with a jump-back) instead of letting them
    // silently vanish from view.
    const leaving = focusedThreadRef.current;
    if (leaving) {
      const still = activeRunsRef.current.filter(
        (r) => r.thread_id === leaving && r.provider !== "pty" &&
          (!r.status || ["running", "planning", "merging"].includes(r.status)),
      );
      if (still.length > 0) {
        pushToast({
          text: `${still.length} run${still.length === 1 ? "" : "s"} continue in background`,
          jump: { threadId: leaving, kind: focusedThreadKindRef.current ?? undefined },
        });
      }
    }
    focusedThreadRef.current = tid;
    setFocusedThread(tid);
    focusedThreadKindRef.current = kind;
    setFocusedThreadKind(kind);
    hydrateThread(tid);
    void fetch("/api/threads/focus", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ thread_id: tid }),
    }).catch(() => { /* daemon down — reconnect hello resyncs */ });
  }, [hydrateThread]);

  /** "+ New thread" / "+ shell": fresh thread, focused on both sides.
   *  For `interactive-pty` the daemon just creates the row; the pty
   *  surface spawns the shell on its first `term.attach`. */
  const onNewThread = useCallback(async (
    kind: "structured-agent" | "interactive-pty" = "structured-agent",
  ) => {
    try {
      const r = await fetch("/api/threads/new", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind }),
      });
      if (!r.ok) return;
      const body = (await r.json()) as { thread_id: string; kind: string };
      focusedThreadRef.current = body.thread_id;
      setFocusedThread(body.thread_id);
      focusedThreadKindRef.current = body.kind;
      setFocusedThreadKind(body.kind);
      setEntries([]);
      setOldestEventId(null);
      setHasMoreHistory(false);
    } catch { /* daemon down */ }
  }, []);

  /** Jump to a thread that may live in another workspace (dashboard
   *  panel rows, background-run toasts). Same-workspace jumps go
   *  through the normal switcher; cross-workspace jumps activate the
   *  workspace first and then focus the thread — the resulting hello
   *  + thread_focused broadcasts drive the UI from there. */
  const jumpToThread = useCallback(async (
    wsPath: string | undefined, tid: string, kind?: string,
  ) => {
    if (wsPath && wsPath !== focusedWsRef.current) {
      try {
        const r = await fetch("/api/workspaces/switch", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: wsPath }),
        });
        if (!r.ok) return;
        await fetch("/api/threads/focus", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ thread_id: tid }),
        });
      } catch { /* daemon down */ }
      return;
    }
    onSwitchThread(tid, kind ?? "structured-agent");
  }, [onSwitchThread]);

  const onJumpToRun = useCallback((run: ActiveRun) => {
    if (!run.thread_id) return;
    void jumpToThread(
      run.workspace, run.thread_id,
      run.provider === "pty" ? "interactive-pty" : "structured-agent",
    );
  }, [jumpToThread]);

  /** Agent Dashboard workspace pill → jump to that run's workspace
   *  (+ its thread when known). The dashboard is a bare tab with no
   *  props, so it asks via a window event; App owns the switch. */
  useEffect(() => {
    const onJumpWs = (ev: Event) => {
      const d = (ev as CustomEvent<{
        workspace?: string; thread_id?: string | null; provider?: string;
      }>).detail;
      if (!d?.workspace) return;
      const kind = d.provider === "pty" ? "interactive-pty" : "structured-agent";
      if (d.thread_id) {
        void jumpToThread(d.workspace, d.thread_id, kind);
      } else if (d.workspace !== focusedWsRef.current) {
        // No thread to focus — just switch the workspace.
        void fetch("/api/workspaces/switch", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: d.workspace }),
        }).catch(() => { /* daemon down */ });
      }
    };
    window.addEventListener("sy:jump-workspace-run", onJumpWs);
    return () => window.removeEventListener("sy:jump-workspace-run", onJumpWs);
  }, [jumpToThread]);

  /** Fetch one page of older events and prepend them. */
  const onLoadOlder = useCallback(async () => {
    if (loadingOlder || !hasMoreHistory || oldestEventId === null) return;
    const tid = focusedThreadRef.current;
    if (!tid) return;
    setLoadingOlder(true);
    try {
      const r = await fetch(
        `/api/rail/events?before_id=${oldestEventId}&limit=50` +
        `&thread_id=${encodeURIComponent(tid)}`,
      );
      if (!r.ok) return;
      const body = (await r.json()) as { events: RailEvent[] };
      const older = hydrateEvents(body.events);
      if (older.length === 0) {
        setHasMoreHistory(false);
        return;
      }
      setEntries((prev) => [...older, ...prev]);
      setOldestEventId(body.events[0]!.event_id);
      // If we got fewer than the page size, we've reached the start.
      if (body.events.length < 50) setHasMoreHistory(false);
    } finally {
      setLoadingOlder(false);
    }
  }, [loadingOlder, hasMoreHistory, oldestEventId]);

  /** Hydrate the rail every time the workspace changes. The rail shows
   *  ONE thread: the daemon's focused thread when it has one (hello
   *  carried it into focusedThreadRef), else auto-focus the most
   *  recent thread so reopening the app continues where the user left
   *  off. A workspace with no threads yet gets an empty rail — the
   *  first turn creates one (RUN_STARTED adopts it). */
  useEffect(() => {
    if (!workspace) return;
    let cancelled = false;
    const helloTid = focusedThreadRef.current;
    if (helloTid) hydrateThread(helloTid); // paint fast; kind resolves below
    else {
      setEntries([]);
      setOldestEventId(null);
      setHasMoreHistory(false);
    }
    // Always resolve against /api/threads: it supplies the focused
    // thread's KIND (transcript vs xterm surface) and, when the
    // daemon has no focus yet, the most-recent thread to auto-focus
    // so reopening the app continues where the user left off.
    fetch("/api/threads")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((body: {
        threads: { thread_id: string; kind: string }[];
        focused: string | null;
      }) => {
        if (cancelled) return;
        const tid = helloTid ?? body.focused ?? body.threads[0]?.thread_id ?? null;
        if (!tid) return; // brand-new workspace — empty rail
        const row = body.threads.find((t) => t.thread_id === tid);
        focusedThreadKindRef.current = row?.kind ?? "structured-agent";
        setFocusedThreadKind(row?.kind ?? "structured-agent");
        if (tid !== focusedThreadRef.current) {
          focusedThreadRef.current = tid;
          setFocusedThread(tid);
          hydrateThread(tid);
          // Tell the daemon so dispatch continues this thread rather
          // than minting a fresh one. Fire-and-forget; idempotent.
          void fetch("/api/threads/focus", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ thread_id: tid }),
          }).catch(() => { /* reconnect hello resyncs */ });
        }
      })
      .catch((e: Error) => {
        // Don't leave a silently-blank rail — surface it as a notice so
        // the user knows history failed to load (daemon down / fetch
        // error) rather than assuming the workspace has no history.
        if (cancelled) return;
        setHasMoreHistory(false);
        setEntries([{
          id: ++idRef.current,
          source: "notice",
          kind: null,
          text: `Couldn't load thread history: ${e.message}. Live messages will still appear.`,
        }]);
      });
    return () => {
      cancelled = true;
    };
  }, [workspace, hydrateThread]);

  // ── Away-digest (D5): "while you were away" on return ──────────
  // Last-seen is tracked per workspace in localStorage (heartbeat
  // while visible, stamped on hide). Returning after >30 min fetches
  // the deterministic digest and drops it into the rail + a toast.
  useEffect(() => {
    if (!workspace) return;
    const KEY = `sy:last-seen:${workspace}`;
    const mark = () => {
      try { localStorage.setItem(KEY, String(Date.now() / 1000)); } catch { /* quota */ }
    };
    const check = async () => {
      let last = 0;
      try { last = parseFloat(localStorage.getItem(KEY) ?? "0") || 0; } catch { /* ignore */ }
      mark();
      if (!last) return;
      const away = Date.now() / 1000 - last;
      if (away < 30 * 60) return;
      try {
        const r = await fetch(`/api/digest?since=${last}`);
        if (!r.ok) return;
        const d = (await r.json()) as {
          total: number;
          by_kind: Record<string, number>;
          notable: { kind: string; summary: string }[];
          pending_reviews: number;
        };
        if (d.total === 0 && d.pending_reviews === 0) return;
        const hours = Math.round(away / 360) / 10;
        const kinds = Object.entries(d.by_kind)
          .sort((a, b) => b[1] - a[1])
          .slice(0, 5)
          .map(([k, n]) => `${n} ${k}`)
          .join(" · ");
        const lines = [
          `While you were away (~${hours}h): ${d.total} events — ${kinds}.`,
          ...d.notable.map((n) => `  · [${n.kind}] ${n.summary}`),
          ...(d.pending_reviews
            ? [`  · ${d.pending_reviews} charter amendment(s) awaiting review`]
            : []),
        ];
        setEntries((prev) => [...prev, {
          id: ++idRef.current,
          source: "notice",
          kind: null,
          text: lines.join("\n"),
        }]);
        pushToast({
          text: `while you were away: ${d.total} events — digest in the rail`,
        }, 15000);
      } catch { /* daemon down / older daemon */ }
    };
    void check();
    const onVis = () => {
      if (document.visibilityState === "visible") void check();
      else mark();
    };
    document.addEventListener("visibilitychange", onVis);
    const iv = window.setInterval(mark, 60_000);
    return () => {
      document.removeEventListener("visibilitychange", onVis);
      window.clearInterval(iv);
    };
  }, [workspace, pushToast]);

  const switchToKind = useCallback(
    (kind: string) => {
      // Zen: the graph is always visible (left pane); every other
      // kind lands on the right-pane surface host. Reaching a kind
      // clears a pending artifact of that kind — the user got there.
      if (uiModeRef.current === "zen") {
        if (kind === "graph") return true;
        const t = mode.tabs.find((x) => x.kind === kind);
        if (!t) return false;
        setZenSurface(t.id);
        setZenArtifact((cur) => (cur && cur.kind === kind ? null : cur));
        return true;
      }
      const t = mode.tabs.find((x) => x.kind === kind);
      if (!t) return false;
      setActiveTab(t.id);
      return true;
    },
    [mode],
  );

  // Stable handle for the WS callback (mounted once) to call the
  // latest switchToKind without re-binding the listener every time
  // mode changes.
  const switchToKindRef = useRef(switchToKind);
  useEffect(() => {
    switchToKindRef.current = switchToKind;
  }, [switchToKind]);

  const tabsValue = useMemo(
    () => ({ tabs: mode.tabs, activeId: activeTab, setActive: setActiveTab, switchToKind }),
    [mode, activeTab, switchToKind],
  );

  // ⌘K palette: wiki pages join the fuzzy list (D5 + Zen ruling —
  // page find/search is the palette's job). Power opens the graph
  // doc modal; Zen opens the right-pane Editor.
  const palettePages = useMemo(
    () => (graphData?.nodes ?? []).map((n) => ({
      id: n.id,
      title: n.title ?? n.id,
    })),
    [graphData],
  );
  const paletteOpenPage = useCallback((id: string) => {
    const page = graphDataRef.current?.pages[id];
    setSelection({ kind: "page", id, path: page?.path ?? id });
    switchToKindRef.current?.(
      uiModeRef.current === "zen" ? "markdown" : "graph",
    );
  }, [setSelection]);

  // Derived (not an entry, so reconnect/re-hydration can't wipe it):
  // when the active workspace has no built wiki/graph, pin a one-click
  // "set up the wiki + run the curator" action in the rail.
  const noWikiAction =
    graphError && /no wiki|viewer\.sh|build failed/i.test(graphError)
      ? {
          text: "No wiki is set up in this workspace yet.",
          label: "Set up wiki + run curator",
          // Server-side slash: the daemon runs CE's setup.sh (the rail
          // agent is sandboxed shell-less + setup.sh is interactive),
          // builds the viewer, then dispatches the curator to ingest
          // vault/. See _handle_setup_wiki.
          command: "/setup-wiki",
        }
      : null;

  return (
    <TabsProvider value={tabsValue}>
      <SelectionProvider value={{ selection, setSelection }}>
        {uiMode === "zen" ? (
          <ZenShell
            workspace={workspace}
            workspaces={workspacesState}
            graphData={graphData}
            graphError={graphError}
            filesVersion={filesVersion}
            tabs={zenTabs}
            surface={zenSurface}
            setSurface={setZenSurfaceChecked}
            artifact={zenArtifact}
            onJumpArtifact={jumpToArtifact}
            entries={entries}
            onSubmit={onSubmit}
            focusedThread={focusedThread}
            focusedThreadKind={focusedThreadKind}
            onSwitchThread={onSwitchThread}
            onNewThread={onNewThread}
            termWs={termWsApi}
            activeRunIds={activeRunIds}
            activeRuns={activeRuns}
            hasMoreHistory={hasMoreHistory}
            loadingOlder={loadingOlder}
            onLoadOlder={onLoadOlder}
            onOpenSettings={() => setSettingsOpen(true)}
            onOpenHelp={() => setHelpOpen(true)}
          />
        ) : (
        <Shell
          topbar={
            <TopBar
              workspaces={workspacesState}
              modeName={mode.name}
              onOpenSettings={() => setSettingsOpen(true)}
              onOpenHelp={() => setHelpOpen(true)}
            />
          }
          sidebar={
            // key by workspace so a switch fully remounts the BROWSER
            // (graph sidebar + FileBrowser) — no stale pages/tree from
            // the previous workspace, and a clean empty state when the
            // new workspace has no built wiki.
            <Sidebar
              key={workspace}
              data={graphData}
              error={graphError}
              filesVersion={filesVersion}
            />
          }
          center={
            // Same: remount the center tabs on workspace switch so the
            // Table re-seeds, the Graph re-fetches, etc. — nothing from
            // the previous workspace lingers.
            <CenterColumn
              key={workspace}
              tabs={visibleTabs}
              activeId={activeTab}
              onSelect={setActiveTab}
              graphData={graphData}
              graphError={graphError}
              activeRuns={activeRuns}
              workspace={workspace}
              onJumpToRun={onJumpToRun}
              onToggleTabScope={onToggleTabScope}
              hasFocusedThread={focusedThread !== null}
              termWs={termWsApi}
            />
          }
          rail={
            <Rail
              entries={entries}
              onSubmit={onSubmit}
              onReset={onReset}
              onLoadOlder={onLoadOlder}
              hasMoreHistory={hasMoreHistory}
              loadingOlder={loadingOlder}
              pinnedAction={noWikiAction}
              otherPerms={otherPerms}
              activeRunIds={activeRunIds}
              focusedThread={focusedThread}
              focusedThreadKind={focusedThreadKind}
              onSwitchThread={onSwitchThread}
              onNewThread={onNewThread}
              termWs={termWsApi}
              poppedOutTab={poppedTerminalTab}
              onPopOutTerminal={onPopOutTerminal}
              onPopInTerminalTab={onPopInTerminalTab}
              onJumpToTab={setActiveTab}
            />
          }
        />
        )}
        <SettingsModal
          open={settingsOpen}
          onClose={() => setSettingsOpen(false)}
          onQuit={requestQuit}
          onRestart={requestRestart}
          onUpdate={requestUpdate}
        />
        <HelpModal open={helpOpen} onClose={() => setHelpOpen(false)} />
        <Walkthrough
          open={walkthroughOpen}
          onClose={() => { setWalkthroughOpen(false); setWalkthroughSettled(true); }}
          ctx={{
            graphData,
            switchToKind: (kind) => switchToKindRef.current?.(kind) ?? false,
            setSelection,
            setSettingsOpen,
            setUiMode: (mode) => {
              try { localStorage.setItem("sy:ui-mode", mode); } catch { /* */ }
              setUiMode(mode);
              window.dispatchEvent(new CustomEvent("sy:ui-mode", { detail: { mode } }));
            },
            uiMode,
          }}
        />
        <FirstRunWizard
          workspace={workspace}
          graphError={graphError}
          ready={walkthroughSettled && !walkthroughOpen}
          onOpenSettings={() => setSettingsOpen(true)}
          onOpenHelp={() => setHelpOpen(true)}
        />
        <CommandPalette
          tabs={uiMode === "zen" ? zenTabs : visibleTabs}
          activeTab={uiMode === "zen" ? zenSurface : activeTab}
          setActiveTab={uiMode === "zen" ? setZenSurfaceChecked : setActiveTab}
          workspaces={workspacesState}
          onSwitchThread={onSwitchThread}
          pages={palettePages}
          onOpenPage={paletteOpenPage}
          extra={uiMode === "zen" && zenArtifact ? [{
            label: `Latest artifact — ${zenArtifact.label}`,
            hint: "open ↗",
            run: jumpToArtifact,
          }] : undefined}
        />
        {toasts.length > 0 && (
          <div className="sy-toasts">
            {toasts.map((t) => (
              <div key={t.id} className={"sy-toast" + (t.err ? " sy-toast--err" : "")}>
                <span className="sy-toast-text">{t.text}</span>
                {t.jump && (
                  <button
                    type="button"
                    className="sy-toast-jump"
                    onClick={() => {
                      const j = t.jump!;
                      setToasts((cur) => cur.filter((x) => x.id !== t.id));
                      void jumpToThread(j.workspace, j.threadId, j.kind);
                    }}
                  >
                    jump ↗
                  </button>
                )}
                {t.switchTo && (
                  <button
                    type="button"
                    className="sy-toast-jump"
                    onClick={() => {
                      const path = t.switchTo!;
                      setToasts((cur) => cur.filter((x) => x.id !== t.id));
                      void fetch("/api/workspaces/switch", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ path }),
                      });
                    }}
                  >
                    open ↗
                  </button>
                )}
                <button
                  type="button"
                  className="sy-toast-close"
                  onClick={() => setToasts((cur) => cur.filter((x) => x.id !== t.id))}
                  aria-label="Dismiss"
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}
        {stopped && <StoppedOverlay />}
      </SelectionProvider>
    </TabsProvider>
  );
}

// ── Rail hydration ────────────────────────────────────────────────

/** Mirrors `conversations.list_events` row shape from the daemon. */
type RailEvent = {
  event_id: number;
  thread_id: string;
  created_at: number;
  kind: string;
  source: string;
  actor: string | null;
  summary: string;
  payload: Record<string, unknown> | null;
  ref_id: string | null;
  run_id: string | null;
};

/** Convert event-log rows into the rail's display shapes. tool_use
 *  rows are paired with their tool_result siblings (matched by ref_id)
 *  so the resulting `tool` entries already carry the result and don't
 *  flash a cursor on hydration. Non-chat event kinds (file_edit_internal,
 *  curation, slash, sql, …) become compact system entries. */
function hydrateEvents(rows: RailEvent[]): RailEntry[] {
  // First pass: map each row to a base RailEntry, skipping tool_result
  // (we'll merge them into matching tool_use entries below).
  const out: RailEntry[] = [];
  const toolByRefId = new Map<string, Extract<RailEntry, { source: "tool" }>>();
  for (const r of rows) {
    if (r.kind === "tool_result") continue;
    const id = r.event_id;
    if (r.kind === "user") {
      out.push({ id, source: "user", text: r.summary });
    } else if (r.kind === "assistant") {
      out.push({
        id, source: "assistant",
        // Use the persisted run_id so reloaded history groups into run
        // lanes; fall back to a synthetic per-event id (rendered loose)
        // for older rows that predate run_id persistence.
        text: r.summary, run_id: r.run_id ?? `historic-${id}`, done: true,
      });
    } else if (r.kind === "tool_use") {
      const p = (r.payload ?? {}) as Record<string, unknown>;
      const entry: Extract<RailEntry, { source: "tool" }> = {
        id, source: "tool",
        run_id: r.run_id ?? `historic-${id}`,
        tool_id: String(p.id ?? r.ref_id ?? id),
        name: String(p.name ?? r.actor ?? "?"),
        input: (p.input as Record<string, unknown>) ?? {},
      };
      out.push(entry);
      if (r.ref_id) toolByRefId.set(r.ref_id, entry);
    } else if (r.kind === "notice") {
      out.push({ id, source: "notice", text: r.summary, kind: null });
    } else if (r.kind === "reasoning") {
      const p = (r.payload ?? {}) as Record<string, unknown>;
      out.push({
        id, source: "reasoning",
        text: String(p.text ?? r.summary),
        run_id: r.run_id ?? undefined,
      });
    } else {
      // workspace_switch / file_edit / curation / slash / sql / nav / …
      // — render as a compact system breadcrumb.
      out.push({
        id, source: "system",
        text: `${r.kind === "workspace_switch" ? "·" : `[${r.kind}]`} ${r.summary}`,
      });
    }
  }
  // Second pass: merge tool_result.summary into the matching tool entry.
  for (const r of rows) {
    if (r.kind !== "tool_result") continue;
    if (!r.ref_id) continue;
    const target = toolByRefId.get(r.ref_id);
    if (!target) continue;
    const ok =
      typeof r.payload === "object" && r.payload && "ok" in r.payload
        ? Boolean((r.payload as Record<string, unknown>).ok)
        : true;
    target.result = { ok, summary: r.summary };
  }
  return out;
}
