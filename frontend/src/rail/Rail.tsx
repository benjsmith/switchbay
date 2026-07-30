import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, ReactElement, ReactNode } from "react";
import { marked } from "marked";
import { sanitizeHtml } from "../lib/sanitizeHtml";
import type { ParsedKind } from "../ws";
import ProviderPicker from "./ProviderPicker";
import PtyThreadSurface, { type TerminalWsApi } from "./PtyThreadSurface";
import VoiceButton from "./VoiceButton";
import ReasoningPicker from "./ReasoningPicker";
import { registerChord } from "../keys";

type VerbInfo = { name: string; aliases: string[]; description: string };

// Stable empty set so a missing activeRunIds prop doesn't churn memos.
const EMPTY_RUNS: Set<string> = new Set();

export type RailEntry =
  | { id: number; source: "system"; text: string }
  | { id: number; source: "user"; text: string }
  | { id: number; source: "notice"; text: string; kind: ParsedKind | null }
  | { id: number; source: "reasoning"; text: string; run_id?: string }
  | {
      id: number;
      source: "assistant";
      text: string;
      run_id: string;
      /** AG-UI messageId of the live-streaming segment this bubble is
       *  assembling (TEXT_MESSAGE_START/CONTENT/END). null before the
       *  first delta; absent on hydrated rows. */
      message_id?: string | null;
      done: boolean;
      meta?: string;
    }
  | {
      id: number;
      source: "tool";
      run_id: string;
      tool_id: string;
      name: string;
      input: Record<string, unknown>;
      result?: { ok: boolean; summary: string };
    }
  | {
      id: number;
      source: "permission";
      req_id: string;
      provider: string;
      tool: string;
      tool_input: Record<string, unknown>;
      pattern: string;
      run_id: string | null;
      /** Where an out-of-thread request came from (home-compacted cwd
       *  of an external CLI session, e.g. the bench). Unset for cards
       *  owned by a rail thread. */
      origin?: string | null;
      /** Absolute cwd of an external source — enables "watch in shell".
       *  Unset for old hooks / thread-owned cards. */
      origin_path?: string | null;
      /** "pending" while awaiting click, then "approved" | "denied"
       *  briefly so the row can render an acknowledged-state before
       *  the WS `permission_resolved` drops it. */
      state: "pending" | "approved" | "denied";
    }
  | {
      id: number;
      /** Charter-amendment review card (D9): the heartbeat drafted a
       *  promotion of a captured /decision into a charter page;
       *  accept writes the page, dismiss leaves the note. */
      source: "decision";
      dec_id: string;
      text: string;
      project: string | null;
      charter_path: string;
      proposal: string;
      state: "pending" | "accepted" | "dismissed";
    }
  | {
      id: number;
      source: "proposal";
      prop_id: string;
      op: string;
      kind: string;
      title: string;
      path: string;
      body: string;
      review: {
        verdict?: string;
        confidence?: number;
        issues?: string[];
        one_line?: string;
      } | null;
      state: "pending" | "accepted" | "dismissed";
    }
  | {
      id: number;
      /** A run failed on a transient/capacity/billing provider error;
       *  offer a one-click retry on another keyed provider (#12). */
      source: "provider_retry";
      retry_id: string;
      failed_label: string;
      code: string;
      message: string;
      alternatives: { id: string; label: string }[];
      state: "pending" | "retried" | "dismissed";
      chosen?: string | null;
    }
  | {
      id: number;
      /** First micro-edit calibration: keep fast rung or increase. */
      source: "micro_edit_feedback";
      feedback_id: string;
      rung_used: string;
      provider: string;
      model: string;
      original_text: string;
      state: "pending" | "kept" | "increased" | "dismissed";
    }
  | {
      id: number;
      source: "local_models_check";
      message: string;
      state: "pending" | "checking" | "dismissed";
    }
  | {
      id: number;
      source: "local_models_discovery";
      discovery: {
        suggestions?: Array<{
          id: string;
          label: string;
          summary?: string;
          backend?: string;
          est_gb?: number;
        }>;
        removals?: Array<{
          id: string;
          label: string;
          summary?: string;
          backend?: string;
        }>;
        note?: string;
      };
      state: "pending" | "done";
    };

type Props = {
  entries: RailEntry[];
  onSubmit: (text: string, opts: { n: number }) => void;
  onReset: () => void;
  onLoadOlder: () => void;
  hasMoreHistory: boolean;
  loadingOlder: boolean;
  // Pinned one-click action (e.g. "no wiki — set one up?"). Derived from
  // app state and rendered above the input, so reconnect/re-hydration of
  // the entries list never wipes it. null = nothing pinned.
  pinnedAction?: { text: string; label: string; command: string } | null;
  // Permission cards NOT owned by the focused thread: external CLI
  // sessions (bench runs, scripts) and background threads. Rendered in
  // a pinned strip above the transcript so they stay actionable
  // without impersonating the conversation.
  otherPerms?: Extract<RailEntry, { source: "permission" }>[];
  // Run ids currently executing (from /api/runs/active). Drives the
  // live-vs-done state of run blocks + the focus-switcher chips.
  activeRunIds?: Set<string>;
  // Focused thread (Workspace → Thread → Run → Turn) + switcher
  // callbacks. The ThreadBar renders the picker; App owns the state.
  focusedThread: string | null;
  // 'structured-agent' → transcript+composer; 'interactive-pty' →
  // xterm surface (PtyThreadSurface). null = no thread focused yet.
  focusedThreadKind: string | null;
  onSwitchThread: (threadId: string, kind: string) => void;
  onNewThread: (kind?: "structured-agent" | "interactive-pty") => void;
  // term.* adapter over the shared rail WS, for the pty surface.
  termWs: TerminalWsApi | null;
  // Terminal pop-out: when the focused pty thread has a center tab,
  // the rail renders a placeholder instead of a second xterm (two
  // surfaces on one session would fight over winsize).
  poppedOutTab?: { id: string; title: string } | null;
  onPopOutTerminal?: (threadId: string) => void;
  onPopInTerminalTab?: (tabId: string) => void;
  onJumpToTab?: (tabId: string) => void;
};

type ThreadInfo = {
  thread_id: string;
  title: string | null;
  kind: string;
  project: string | null;
  created_at: number;
  updated_at: number;
  chat_count: number;
  last_summary: string;
  running: number;
  pty_live?: boolean;
};

type ProjectInfo = { name: string; archived: boolean; synthetic: boolean };

function relTime(ts: number): string {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return "now";
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

/** Thread switcher strip under the rail head: shows the focused
 *  thread's title, opens a picker (click or leader chord ⌘/Ctrl+K
 *  then T — charter keybinding rule: letters only, no punctuation),
 *  and hosts "+ new". Fetches /api/threads lazily: on focus change
 *  (for the title) and on every open (fresh running counts). */
function ThreadBar({
  focusedThread, onSwitchThread, onNewThread,
}: {
  focusedThread: string | null;
  onSwitchThread: (threadId: string, kind: string) => void;
  onNewThread: (kind?: "structured-agent" | "interactive-pty") => void;
}) {
  const [open, setOpen] = useState(false);
  const [threads, setThreads] = useState<ThreadInfo[]>([]);
  // Project picker chip (D8). Registered CE projects only; the chip
  // hides entirely in single-topic workspaces (no registry) — those
  // capture at workspace level and never need a binding.
  const [projOpen, setProjOpen] = useState(false);
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const load = async () => {
    try {
      const r = await fetch("/api/threads");
      if (!r.ok) return;
      const body = (await r.json()) as { threads: ThreadInfo[] };
      setThreads(body.threads);
    } catch { /* daemon down — keep the stale list */ }
  };
  const loadProjects = async () => {
    try {
      const r = await fetch("/api/projects");
      if (!r.ok) return;
      const body = (await r.json()) as { projects: ProjectInfo[] };
      setProjects(body.projects.filter((p) => !p.archived && !p.synthetic));
    } catch { /* daemon down — keep the stale list */ }
  };
  useEffect(() => { void load(); }, [focusedThread]);
  useEffect(() => { if (open) void load(); }, [open]);
  // Chip visibility needs the registry once up-front; reopen refetches
  // so a freshly-created project appears without a reload.
  useEffect(() => { void loadProjects(); }, []);
  useEffect(() => { if (projOpen) void loadProjects(); }, [projOpen]);
  // Background auto-titler named a thread / a thread was archived or
  // purged → refresh so the focused label / picker rows track reality.
  useEffect(() => {
    const onChanged = () => { void load(); };
    window.addEventListener("sy:thread-titled", onChanged);
    window.addEventListener("sy:threads-changed", onChanged);
    return () => {
      window.removeEventListener("sy:thread-titled", onChanged);
      window.removeEventListener("sy:threads-changed", onChanged);
    };
  }, []);
  /** Archive = remove from the switcher; events stay in the log
   *  (recall_rail still finds them). The daemon kills an attached
   *  shell and refocuses if needed — broadcasts drive the UI. */
  const archive = async (tid: string) => {
    try {
      await fetch(`/api/threads/${encodeURIComponent(tid)}/archive`, { method: "POST" });
      void load();
    } catch { /* daemon down — row stays until the next refresh */ }
  };
  // ⌘K → T toggles the picker, via the central registry. Esc closes.
  useEffect(() => registerChord({
    key: "t",
    description: "Switch thread",
    handler: () => setOpen((o) => !o),
  }), []);
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") { setOpen(false); setProjOpen(false); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  // Click-outside closes the picker (and the project drop-up) — same
  // dismissal contract as the workspace switcher; clicking the chip
  // again still toggles.
  const barRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open && !projOpen) return;
    const onDoc = (ev: MouseEvent) => {
      if (barRef.current && !barRef.current.contains(ev.target as Node)) {
        setOpen(false);
        setProjOpen(false);
      }
    };
    window.addEventListener("mousedown", onDoc);
    return () => window.removeEventListener("mousedown", onDoc);
  }, [open, projOpen]);
  /** Bind/unbind the focused thread's project (D8). The daemon
   *  broadcasts thread.project_changed → sy:threads-changed → load(),
   *  but we also refetch directly so the chip updates even if the WS
   *  is momentarily down. */
  const setProjectBinding = async (project: string | null) => {
    setProjOpen(false);
    if (!focusedThread) return;
    try {
      await fetch(`/api/threads/${encodeURIComponent(focusedThread)}/project`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project }),
      });
      void load();
    } catch { /* daemon down — chip stays until the next refresh */ }
  };
  // Display fallback for untitled threads: pty threads are shells;
  // chat threads predating the auto-titler show their last summary
  // head rather than an anonymous "(untitled)".
  const displayTitle = (t: ThreadInfo): string =>
    t.title
    ?? (t.kind === "interactive-pty"
      ? "shell"
      : (t.last_summary?.trim() || "(untitled)"));
  const focused = threads.find((t) => t.thread_id === focusedThread);
  // A just-created thread can be focused before the list refetch
  // lands — show the same placeholder shape the server assigns.
  const label = focusedThread
    ? (focused ? displayTitle(focused) : "New thread…")
    : "new thread";
  const liveTotal = threads.reduce((n, t) => n + t.running, 0);
  return (
    <div className="sy-thread-bar" ref={barRef}>
      <button
        type="button"
        className="sy-thread-btn"
        title="Switch thread (⌘K then T)"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="sy-thread-glyph">◈</span>
        <span className="sy-thread-label">{label}</span>
        {liveTotal > 0 && <span className="sy-thread-dot" title={`${liveTotal} running`} />}
        <span className="sy-thread-caret">▾</span>
      </button>
      <button
        type="button"
        className="sy-thread-new"
        title="Start a new chat thread"
        onClick={() => { setOpen(false); onNewThread(); }}
      >
        +
      </button>
      <button
        type="button"
        className="sy-thread-new sy-thread-new--shell"
        data-tour="terminal"
        title="Start a new shell thread (interactive terminal)"
        onClick={() => { setOpen(false); onNewThread("interactive-pty"); }}
      >
        {">_"}
      </button>
      {focusedThread && (projects.length > 0 || focused?.project) && (
        <div className="sy-thread-proj-wrap">
          <button
            type="button"
            className={"sy-thread-proj" + (focused?.project ? " bound" : "")}
            title={focused?.project
              ? `Project: ${focused.project} — /note /todo /decision here inherit it (click to change)`
              : "Bind this thread to a project — captures inherit it (/project)"}
            onClick={() => { setOpen(false); setProjOpen((o) => !o); }}
          >
            #{focused?.project ?? ""}
            <span className="sy-thread-caret">▾</span>
          </button>
          {projOpen && (
            <div className="sy-thread-menu sy-thread-proj-menu" role="menu">
              <button
                type="button"
                className={"sy-thread-row" + (focused?.project ? "" : " focused")}
                onClick={() => void setProjectBinding(null)}
              >
                <span className="sy-thread-row-title">(no project)</span>
              </button>
              {projects.map((p) => (
                <button
                  key={p.name}
                  type="button"
                  className={
                    "sy-thread-row" +
                    (focused?.project === p.name ? " focused" : "")
                  }
                  onClick={() => void setProjectBinding(p.name)}
                >
                  <span className="sy-thread-row-title">#{p.name}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
      {open && (
        <div className="sy-thread-menu" role="listbox">
          {threads.length === 0 && (
            <div className="sy-thread-empty">no threads yet — say something</div>
          )}
          {threads.map((t) => (
            <button
              key={t.thread_id}
              type="button"
              className={
                "sy-thread-row" +
                (t.thread_id === focusedThread ? " focused" : "")
              }
              onClick={() => { setOpen(false); onSwitchThread(t.thread_id, t.kind); }}
            >
              <span className="sy-thread-row-kind">
                {t.kind === "interactive-pty" ? ">_" : "◈"}
              </span>
              <span className="sy-thread-row-title">
                {displayTitle(t)}
              </span>
              {t.project && (
                <span className="sy-thread-row-proj">#{t.project}</span>
              )}
              {(t.running > 0 || t.pty_live) && <span className="sy-thread-dot" />}
              <span className="sy-thread-row-meta">
                {t.kind === "interactive-pty"
                  ? relTime(t.updated_at)
                  : `${t.chat_count} · ${relTime(t.updated_at)}`}
              </span>
              {(t.running === 0 || t.kind === "interactive-pty") && (
                // PTY threads keep the ✕ even while "running" — a
                // fresh shell reads as running until the dormancy
                // detector flips it (~8s), which used to hide the
                // kill until the second open. Archiving a pty thread
                // explicitly kills its shell (see the title).
                <span
                  className="sy-thread-row-del"
                  role="button"
                  tabIndex={-1}
                  title="Remove from the switcher (history stays in the log — purge from Settings if you really want it gone)"
                  onClick={(ev) => {
                    ev.stopPropagation();
                    void archive(t.thread_id);
                  }}
                >
                  ✕
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Rail({
  entries, onSubmit, onReset,
  onLoadOlder, hasMoreHistory, loadingOlder,
  pinnedAction, otherPerms, activeRunIds,
  focusedThread, focusedThreadKind, onSwitchThread, onNewThread,
  termWs, poppedOutTab, onPopOutTerminal, onPopInTerminalTab, onJumpToTab,
}: Props) {
  const [input, setInput] = useState("");
  // Run-lane focus: when set, that run's blocks highlight and others
  // dim. expandedBlocks tracks which collapsed (done) run segments the
  // user has manually opened (keyed by the block's first item id).
  const [focusedRun, setFocusedRun] = useState<string | null>(null);
  const [expandedRuns, setExpandedRuns] = useState<Set<string>>(() => new Set());
  // The LATEST run block stays open by default when it finishes (the
  // answer the user is reading must not snap shut under them); this
  // tracks explicit collapses of that default-open block.
  const [collapsedRuns, setCollapsedRuns] = useState<Set<string>>(() => new Set());
  const liveSet = activeRunIds ?? EMPTY_RUNS;
  // Live runs present in the current timeline, in first-appearance order.
  const liveRuns = useMemo(() => {
    const seen: string[] = [];
    for (const e of entries) {
      const rid = "run_id" in e ? (e as { run_id: string | null }).run_id : null;
      if (rid && liveSet.has(rid) && !seen.includes(rid)) seen.push(rid);
    }
    return seen;
  }, [entries, liveSet]);
  // Run-lane focus cycling: leader ⌘K then N (next) / P (previous),
  // per the charter keybinding rule — the old Ctrl+]/[ punctuation
  // bindings were the last grandfathered exception (D17, 2026-07-05).
  // Esc still clears focus.
  const cycleLane = useCallback((step: 1 | -1) => {
    if (liveRuns.length === 0) return;
    setFocusedRun((cur) => {
      const i = cur ? liveRuns.indexOf(cur) : -1;
      const next = (i + step + liveRuns.length) % liveRuns.length;
      return liveRuns[next] ?? null;
    });
  }, [liveRuns]);
  useEffect(() => registerChord({
    key: "n",
    description: "Focus next run lane",
    handler: () => cycleLane(1),
  }), [cycleLane]);
  useEffect(() => registerChord({
    key: "p",
    description: "Focus previous run lane",
    handler: () => cycleLane(-1),
  }), [cycleLane]);
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape" && focusedRun) setFocusedRun(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [focusedRun]);
  // Drop focus when its run finishes / leaves the timeline.
  useEffect(() => {
    if (focusedRun && !liveRuns.includes(focusedRun)) setFocusedRun(null);
  }, [liveRuns, focusedRun]);
  // Tiny status banner shown next to the action buttons after a
  // file upload (cleared after a few seconds). The actual
  // attachment reference lands prepended in the input itself —
  // user can edit / remove it before sending.
  const [attachStatus, setAttachStatus] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // User-global custom action buttons. Persists across workspaces
  // via ~/.config/switchbay/action-buttons.json. List fetched on
  // mount; mutations re-fetch.
  const [customButtons, setCustomButtons] = useState<
    { id: string; label: string; command: string }[]
  >([]);
  const [addingButton, setAddingButton] = useState<
    { label: string; command: string } | null
  >(null);
  const reloadButtons = async () => {
    try {
      const r = await fetch("/api/action-buttons");
      if (!r.ok) return;
      const body = (await r.json()) as { buttons: typeof customButtons };
      setCustomButtons(body.buttons);
    } catch { /* leave empty */ }
  };
  useEffect(() => { void reloadButtons(); }, []);
  const submitNewButton = async () => {
    if (!addingButton) return;
    const r = await fetch("/api/action-buttons", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(addingButton),
    });
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      window.alert(`add failed: ${body.error ?? r.status}`);
      return;
    }
    const body = (await r.json()) as { buttons: typeof customButtons };
    setCustomButtons(body.buttons);
    setAddingButton(null);
  };
  const removeCustomButton = async (id: string) => {
    if (!window.confirm("Remove this button?")) return;
    await fetch(`/api/action-buttons?id=${encodeURIComponent(id)}`, { method: "DELETE" });
    await reloadButtons();
  };
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const lastLenRef = useRef(0);
  const lastFirstIdRef = useRef<number | null>(null);
  // "Stuck to bottom": true while the user is at/near the bottom. Updated
  // on every scroll, so we can follow new + streaming content without
  // yanking the view when they've scrolled up to read. Measuring this at
  // scroll time (not after a new entry renders) is what makes it reliable
  // — a tall new entry no longer pushes us out of the threshold.
  const stickRef = useRef(true);

  // Slash-autocomplete state. Refetched when the focused thread
  // changes (which covers workspace switches too) so user-defined
  // commands from `.workbench/commands/` show up without a reload.
  const [verbs, setVerbs] = useState<VerbInfo[] | null>(null);
  const [acIndex, setAcIndex] = useState(0);
  useEffect(() => {
    fetch("/api/verbs")
      .then((r) => r.json())
      .then((b: { verbs: VerbInfo[] }) => setVerbs(b.verbs))
      .catch(() => setVerbs([]));
  }, [focusedThread]);

  // Input router (control surface): high-confidence shell detection
  // with an interpretation chip. When the daemon says the input looks
  // like a command, Enter runs it in a NEW shell thread (the `!`
  // path) and Tab flips the interpretation back to chat.
  const [shellHint, setShellHint] = useState(false);
  const [chatForced, setChatForced] = useState(false);
  const shellHintRef = useRef(false);
  const chatForcedRef = useRef(false);
  useEffect(() => { shellHintRef.current = shellHint; }, [shellHint]);
  useEffect(() => { chatForcedRef.current = chatForced; }, [chatForced]);
  useEffect(() => {
    const t = input.trim();
    setChatForced(false);
    if (!t || t.startsWith("/") || t.startsWith("!") || t.includes("\n")) {
      setShellHint(false);
      return;
    }
    const h = window.setTimeout(() => {
      fetch(`/api/shell/detect?text=${encodeURIComponent(t)}`)
        .then((r) => (r.ok ? r.json() : { shell: false }))
        .then((b: { shell?: boolean }) => setShellHint(b.shell === true))
        .catch(() => setShellHint(false));
    }, 200);
    return () => window.clearTimeout(h);
  }, [input]);

  // Global focus-the-rail signal. TabStrip's "New…" affordance fires
  // this when the user clicks the trailing `+` so the cursor lands in
  // the input right as the helper notice lands in the transcript.
  useEffect(() => {
    const onFocus = () => inputRef.current?.focus();
    window.addEventListener("sy:rail-focus", onFocus);
    return () => window.removeEventListener("sy:rail-focus", onFocus);
  }, []);

  // Prefill the chat input. Sketch tab's "Request edits…" action
  // uses this to drop the user into a ready-to-send prompt that
  // points the model at the deck's analysis page + slide files.
  useEffect(() => {
    const onSetInput = (ev: Event) => {
      const detail = (ev as CustomEvent<{ text: string; focus?: boolean }>).detail;
      if (!detail || typeof detail.text !== "string") return;
      setInput(detail.text);
      if (detail.focus !== false) {
        window.setTimeout(() => {
          inputRef.current?.focus();
          // Place cursor at end so the user can append without
          // arrow-keying through the prefilled text.
          const el = inputRef.current;
          if (el) {
            const n = el.value.length;
            el.setSelectionRange(n, n);
          }
        }, 0);
      }
    };
    window.addEventListener("sy:rail-set-input", onSetInput);
    return () => window.removeEventListener("sy:rail-set-input", onSetInput);
  }, []);

  // Match against the current input: open the menu when the user is
  // typing a slash command (cursor on the first line, line starts with
  // `/`, no space yet — we're still naming the verb).
  const acMatches = useMemo<VerbInfo[]>(() => {
    if (!verbs || verbs.length === 0) return [];
    if (!input.startsWith("/")) return [];
    const head = input.split("\n", 1)[0]!;
    if (head.includes(" ")) return [];      // already in args
    const prefix = head.slice(1).toLowerCase();
    // Show every verb when the user has just typed `/`. Filter by
    // prefix once they start typing the name. Match name OR any alias
    // so "/sh" surfaces /show (alias of /view).
    const filtered = verbs.filter((v) => {
      if (!prefix) return true;
      if (v.name.toLowerCase().startsWith(prefix)) return true;
      return v.aliases.some((a) => a.toLowerCase().startsWith(prefix));
    });
    return filtered.slice(0, 8);
  }, [input, verbs]);
  const acOpen = acMatches.length > 0;
  // Reset the highlighted row whenever the suggestion set changes.
  useEffect(() => {
    setAcIndex(0);
  }, [acMatches.length, input]);

  const acceptSuggestion = (v: VerbInfo) => {
    setInput(`/${v.name} `);
    // Keep focus in the textarea so the user can keep typing the args.
    requestAnimationFrame(() => inputRef.current?.focus());
  };

  useEffect(() => {
    // Follow the bottom on new AND streaming content when the user is
    // stuck to the bottom; leave their position alone when they've
    // scrolled up to read. `stickRef` is maintained by the scroll
    // listener below. (Runs on any entries change — including in-place
    // streaming text updates, not just length growth.)
    const el = scrollRef.current;
    if (!el) return;
    const prepended = entries.length > lastLenRef.current
      && entries[0] !== undefined
      && lastFirstIdRef.current !== null
      && entries[0].id < lastFirstIdRef.current;
    lastLenRef.current = entries.length;
    lastFirstIdRef.current = entries[0]?.id ?? null;
    // Don't jump when older history is prepended above the view.
    if (prepended) return;
    if (stickRef.current) el.scrollTo(0, el.scrollHeight);
  }, [entries]);

  // Keep pinned to the bottom while content *grows after* an entries
  // change — markdown/tool blocks lay out a frame or two later, and on
  // first hydration that left the stream parked mid-way. A ResizeObserver
  // over the stream's children re-pins to the bottom on any height
  // change while the user is stuck there. Re-attached as entries change.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      if (stickRef.current) el.scrollTop = el.scrollHeight;
    });
    for (const child of Array.from(el.children)) ro.observe(child);
    return () => ro.disconnect();
  }, [entries]);

  // Auto-fire `onLoadOlder` when the user scrolls past the top — same
  // idea as Slack / iMessage / Discord. Guarded against re-firing
  // while a request is in flight and when there's no older history.
  // 48 px threshold gives the user a small overscroll cushion before
  // we yank a new page in.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => {
      // Track stick-to-bottom for the follow effect above.
      stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
      if (!hasMoreHistory || loadingOlder) return;
      if (el.scrollTop < 48) onLoadOlder();
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [hasMoreHistory, loadingOlder, onLoadOlder]);

  // Preserve visual position when older entries land. Without this,
  // the prepend pushes everything down by N pixels and the user
  // (whose scrollTop didn't change) appears to "jump back" — i.e.
  // the entry they were reading suddenly slides off-screen below.
  // We capture scrollHeight before each entries-change and restore
  // scrollTop by the delta on the next paint when prepending is
  // active (loadingOlder→false transition).
  const prevScrollHeightRef = useRef(0);
  const prevLoadingRef = useRef(false);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (prevLoadingRef.current && !loadingOlder) {
      const delta = el.scrollHeight - prevScrollHeightRef.current;
      if (delta > 0) el.scrollTop = el.scrollTop + delta;
    }
    prevLoadingRef.current = loadingOlder;
    prevScrollHeightRef.current = el.scrollHeight;
  }, [entries, loadingOlder]);

  // External "Add to chat" bridge — the Browser pane's right-click
  // menu dispatches `sy:attach-path` with the workspace-relative
  // path of the chosen file. The file is already in-workspace, so
  // we skip the upload round-trip and just prepend `[attached: …]`
  // to whatever the user has already typed, matching the rail's
  // own attach-button behaviour.
  useEffect(() => {
    const onAttach = (ev: Event) => {
      const detail = (ev as CustomEvent<{ path: string }>).detail;
      if (!detail?.path) return;
      const prefix = `[attached: ${detail.path}]\n`;
      setInput((cur) => (cur.startsWith(prefix) ? cur : prefix + cur));
      setAttachStatus(`attached · ${detail.path}`);
      window.setTimeout(() => setAttachStatus(null), 2500);
    };
    window.addEventListener("sy:attach-path", onAttach);
    return () => window.removeEventListener("sy:attach-path", onAttach);
  }, []);

  const submit = () => {
    const text = input.trim();
    if (!text) return;
    // Router: detected-shell input goes through the `!` path (new
    // shell thread) unless the user Tab-flipped it back to chat.
    const asShell =
      shellHintRef.current && !chatForcedRef.current &&
      !text.startsWith("!") && !text.startsWith("/");
    onSubmit(asShell ? `!${text}` : text, { n: 0 });
    setInput("");
    setShellHint(false);
    setChatForced(false);
  };

  return (
    <>
      <div className="sy-rail-head">
        <span>RAIL</span>
        <span style={{ flex: 1 }} />
        <ProviderPicker />
        <button
          type="button"
          className="sy-rail-reset"
          title="Drop the current conversation context (next turn starts fresh, displayed entries also clear)"
          onClick={async () => {
            await fetch("/api/llm/reset", { method: "POST" });
            onReset();
          }}
        >
          ↺ reset
        </button>
      </div>
      <ThreadBar
        focusedThread={focusedThread}
        onSwitchThread={onSwitchThread}
        onNewThread={onNewThread}
      />
      {focusedThreadKind === "interactive-pty" && focusedThread ? (
        // A shell thread's surface IS the terminal — no transcript, no
        // composer (type in the xterm). Keyed by thread so switching
        // remounts + re-attaches cleanly. When the thread is popped
        // out to a center tab, that tab owns the xterm; the rail
        // shows a hand-off placeholder instead.
        poppedOutTab ? (
          <div className="sy-rail-pty-popped">
            <p>
              This terminal lives in the <b>{poppedOutTab.title}</b> tab.
            </p>
            <div className="sy-rail-pty-popped-btns">
              <button
                type="button"
                className="sy-rail-pty-btn"
                onClick={() => onJumpToTab?.(poppedOutTab.id)}
              >
                go to tab ↗
              </button>
              <button
                type="button"
                className="sy-rail-pty-btn"
                onClick={() => onPopInTerminalTab?.(poppedOutTab.id)}
                title="Close the tab and use this terminal here again"
              >
                ⇲ return to sidebar
              </button>
            </div>
          </div>
        ) : (
          <PtyThreadSurface
            key={focusedThread}
            threadId={focusedThread}
            ws={termWs}
            onPopOut={
              onPopOutTerminal
                ? () => onPopOutTerminal(focusedThread)
                : undefined
            }
          />
        )
      ) : (
        <>
      {(otherPerms?.length ?? 0) > 0 && (
        <div className="sy-rail-other-approvals">
          <div
            className="sy-rail-other-approvals-head"
            title="Approvals from CLI sessions outside this thread — external agents (bench runs, scripts) or background threads"
          >
            approvals outside this thread
          </div>
          {groupOtherApprovals(otherPerms!).map((grp) => (
            <div key={grp.key} className="sy-rail-approval-group">
              {grp.origin && (
                <ExternalSourceBar
                  origin={grp.origin}
                  originPath={grp.originPath}
                  count={grp.cards.length}
                />
              )}
              {grp.cards.map((e) => (
                <PermissionRow key={e.id} entry={e} />
              ))}
            </div>
          ))}
        </div>
      )}
      <div ref={scrollRef} className="sy-rail-stream">
        <div className="sy-rail-load-older-strip">
          <button
            type="button"
            className="sy-rail-load-older"
            onClick={onLoadOlder}
            disabled={loadingOlder || !hasMoreHistory}
            aria-busy={loadingOlder}
            title={
              hasMoreHistory
                ? "Fetch the next page of older rail events from this workspace"
                : "No older rail history in this workspace"
            }
          >
            {loadingOlder
              ? "loading older…"
              : hasMoreHistory
              ? "↑ load older"
              : "↑ no older history"}
          </button>
        </div>
        {entries.length === 0 && !hasMoreHistory && (
          <div className="sy-rail-entry" style={{ color: "var(--text-faint)", fontStyle: "italic" }}>
            type a message to begin · / for slash commands
          </div>
        )}
        {(() => {
        const renderItem = (item: RenderItem): ReactElement => {
          if (item.kind === "fold") {
            // Top-3 unique tool names, deduped, so the fold reads like
            // "Read, Glob, ToolSearch …" instead of repeating Read 7×.
            const uniq = Array.from(new Set(item.names));
            return (
              <div key={`fold-${item.startId}`} className="sy-rail-entry sy-rail-fold">
                <span className="sy-rail-prefix" data-kind="tool">⚙</span>
                <span className="sy-rail-running-dot" title="In flight" />
                <span className="sy-rail-fold-text">
                  {item.count} tool call{item.count === 1 ? "" : "s"} running
                </span>
                <span className="sy-rail-fold-names">
                  {uniq.slice(0, 3).join(", ")}{uniq.length > 3 ? "…" : ""}
                </span>
                <span className="sy-spacer" />
                <button
                  type="button"
                  className="sy-rail-jump"
                  title="Open this run in the Agent Dashboard"
                  onClick={() => openInAgents(item.run_id)}
                  aria-label="Jump to Agent Dashboard"
                >↗</button>
              </div>
            );
          }
          const e = item.entry;
          if (e.source === "decision") {
            return <DecisionRow key={e.id} entry={e} />;
          }
          if (e.source === "proposal") {
            return <ProposalRow key={e.id} entry={e} />;
          }
          if (e.source === "provider_retry") {
            return <ProviderRetryRow key={e.id} entry={e} />;
          }
          if (e.source === "micro_edit_feedback") {
            return <MicroEditFeedbackRow key={e.id} entry={e} />;
          }
          if (e.source === "local_models_check") {
            return <LocalModelsCheckRow key={e.id} entry={e} />;
          }
          if (e.source === "local_models_discovery") {
            return <LocalModelsDiscoveryRow key={e.id} entry={e} />;
          }
          if (e.source === "permission") {
            return <PermissionRow key={e.id} entry={e} />;
          }
          if (e.source === "reasoning") {
            return <ReasoningRow key={e.id} text={e.text} />;
          }
          if (e.source === "tool") {
            const isInternal =
              !!e.result?.summary?.startsWith("(handled internally");
            return (
              <details
                key={e.id}
                className={
                  "sy-rail-entry sy-rail-tool" +
                  (isInternal ? " sy-rail-tool--internal" : "")
                }
              >
                <summary className="sy-rail-tool-summary">
                  <span className="sy-rail-prefix" data-kind="tool">⚙</span>
                  {!e.result && (
                    <span className="sy-rail-running-dot" title="In flight" />
                  )}
                  <span className="sy-rail-tool-name">{e.name}</span>
                  <span className="sy-rail-tool-input">{summariseInput(e.input)}</span>
                  {e.result ? (
                    <span
                      className={
                        "sy-rail-tool-result" +
                        (e.result.ok ? "" : " sy-rail-tool-result--err")
                      }
                    >
                      → {e.result.summary}
                    </span>
                  ) : (
                    <span className="sy-rail-tool-result sy-rail-tool-result--running">
                      → running…
                    </span>
                  )}
                  {e.name === "Bash" && extractBashCommand(e.input) && (
                    <button
                      type="button"
                      className="sy-rail-jump sy-rail-jump--terminal"
                      title="Re-run this command in the terminal panel — interactive, you can answer prompts here"
                      onClick={(ev) => {
                        ev.preventDefault();
                        const cmd = extractBashCommand(e.input);
                        if (!cmd) return;
                        // `!<cmd>` from chat already spawns a fresh
                        // PTY tab in the panel and auto-focuses it.
                        // Reusing that path so the agent's Bash and
                        // the user's !cmd land in identical shells.
                        onSubmit(`!${cmd}`, { n: 0 });
                      }}
                      aria-label="Re-run in terminal"
                    >↗ term</button>
                  )}
                  {!e.result && (
                    <button
                      type="button"
                      className="sy-rail-jump"
                      title="Open this run in the Agent Dashboard"
                      onClick={(ev) => { ev.preventDefault(); openInAgents(e.run_id); }}
                      aria-label="Jump to Agent Dashboard"
                    >↗</button>
                  )}
                </summary>
                <div className="sy-rail-tool-detail">
                  {isInternal && (
                    <p className="sy-rail-tool-help">
                      The provider's CLI handled this tool inline (Bash, Read,
                      Edit, Write, Grep, ToolSearch, …). The daemon sees the
                      call but not a structured result — the next assistant
                      message picks up after the tool ran.
                    </p>
                  )}
                  <div className="sy-rail-tool-section">input</div>
                  <pre className="sy-rail-tool-json">{prettyJson(e.input)}</pre>
                  {e.result && (
                    <>
                      <div className="sy-rail-tool-section">result</div>
                      <pre className="sy-rail-tool-json">{prettyJson(e.result)}</pre>
                    </>
                  )}
                </div>
              </details>
            );
          }
          // User rows that started with `!` (shell command) or
          // one of the typed shell-prefixes get a small kind chip
          // next to the `›` so they read as command invocations
          // in the scrollback, not chat messages. Mirrors what the
          // backend rail.parse() does — kept client-side because
          // we don't carry the parsed kind back through the
          // hydration / live-input round-trip.
          const userKind = e.source === "user"
            ? detectUserKind(e.text)
            : null;
          return (
            <div key={e.id} className="sy-rail-entry">
              <span className="sy-rail-prefix" data-kind={e.source}>{prefixFor(e.source)}</span>
              {e.source === "notice" && e.kind && (
                <span className="sy-kind-chip" data-kind={e.kind}>{e.kind}</span>
              )}
              {userKind && (
                <span className="sy-kind-chip" data-kind={userKind}>{userKind}</span>
              )}
              {e.source === "assistant" ? (
                <span className="sy-rail-text sy-rail-md" data-kind="assistant">
                  <span
                    className="sy-mdview"
                    /* Render assistant prose with marked. Streaming
                     * partial markdown is fine — marked handles
                     * incomplete blocks gracefully and the cursor
                     * pin sits below the rendered HTML. [[wikilinks]]
                     * become clickable → doc modal in the Graph tab. */
                    dangerouslySetInnerHTML={{ __html: mdWithWikilinks(e.text) }}
                    onClick={(ev) => {
                      const a = (ev.target as HTMLElement).closest?.("a.sy-wikilink");
                      if (!a) return;
                      ev.preventDefault();
                      window.dispatchEvent(new CustomEvent("sy:open-wiki-page", {
                        detail: { target: a.getAttribute("data-wiki") },
                      }));
                    }}
                  />
                  {!e.done && <span className="sy-rail-cursor">▋</span>}
                </span>
              ) : (
                <span className="sy-rail-text" data-kind={e.source}>
                  {e.text}
                </span>
              )}
              {e.source === "assistant" && e.done && e.meta && (
                <span className="sy-rail-meta">{e.meta}</span>
              )}
            </div>
          );
        };
        // Group the flat item stream into per-run blocks (loose items —
        // user/system/notice — pass through untouched), then render
        // each block fenced + colour-coded with collapse + focus. The
        // LAST block defaults open — a just-finished answer must not
        // collapse under the reader.
        const nodes = groupRunBlocks(buildRenderItems(entries));
        const lastBlockRun = [...nodes].reverse().find(
          (n): n is Extract<TimelineNode, { kind: "block" }> => n.kind === "block",
        )?.runId ?? null;
        return nodes.flatMap((node) => {
          if (node.kind === "loose") return [renderItem(node.item)];
          const live = liveSet.has(node.runId);
          // Only fence a run that's live or actually did tool work.
          // A finished run with no tool calls (a brief reply, a slash
          // echo, a refusal) renders inline — no phantom "0 tools" block
          // fragmenting the real lanes.
          if (!live && blockToolCount(node.items) === 0) {
            return node.items.map(renderItem);
          }
          const shown = node.runId === lastBlockRun
            ? !collapsedRuns.has(node.runId)
            : expandedRuns.has(node.runId);
          return [(
            <RunBlock
              key={`block-${node.firstId}`}
              node={node}
              live={live}
              dimmed={focusedRun != null && focusedRun !== node.runId}
              focused={focusedRun === node.runId}
              expanded={shown}
              onToggleExpand={() => {
                if (live) return;
                if (shown) {
                  setExpandedRuns((s) => { const n = new Set(s); n.delete(node.runId); return n; });
                  setCollapsedRuns((s) => new Set(s).add(node.runId));
                } else {
                  setCollapsedRuns((s) => { const n = new Set(s); n.delete(node.runId); return n; });
                  setExpandedRuns((s) => new Set(s).add(node.runId));
                }
              }}
              onFocus={() => setFocusedRun((f) => (f === node.runId ? null : node.runId))}
              openInAgents={openInAgents}
              renderItem={renderItem}
            />
          )];
        });
        })()}
      </div>
      {liveRuns.length >= 2 && (
        <div className="sy-rail-lanes" role="tablist" aria-label="Running agents — focus a lane">
          <span className="sy-rail-lanes-hint" title="⌘K then N / P to cycle · Esc to clear">
            {liveRuns.length} running
          </span>
          {liveRuns.map((rid) => (
            <button
              key={rid}
              type="button"
              className={"sy-rail-lane-chip" + (focusedRun === rid ? " sy-rail-lane-chip--on" : "")}
              style={{ "--run-hue": String(runHue(rid)) } as CSSProperties}
              onClick={() => setFocusedRun((f) => (f === rid ? null : rid))}
              title={rid}
            >
              {shortRun(rid)}
            </button>
          ))}
          {focusedRun && (
            <button type="button" className="sy-rail-lane-clear" onClick={() => setFocusedRun(null)} title="Clear focus (Esc)">
              ✕
            </button>
          )}
        </div>
      )}
      {pinnedAction && (
        <div className="sy-rail-nowiki">
          <span className="sy-rail-text" data-kind="notice">{pinnedAction.text}</span>
          <button
            type="button"
            className="sy-rail-nowiki-btn"
            onClick={() => onSubmit(pinnedAction.command, { n: 0 })}
          >
            {pinnedAction.label}
          </button>
        </div>
      )}
      <div className="sy-rail-actions">
        <button
          type="button"
          className="sy-rail-action-btn sy-rail-attach-btn"
          title="Attach a file to the next message"
          onClick={() => fileInputRef.current?.click()}
          aria-label="Attach file"
        >
          {/* Folder + plus glyph: makes "what does this button do"
            * obvious next to text-labelled action buttons. The bare
            * `+` was getting confused with the trailing
            * "register-a-new-button" `+` to its right. */}
          <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
            <path d="M2 5.5 V12.5 a1 1 0 0 0 1 1 H13 a1 1 0 0 0 1-1 V6 a1 1 0 0 0 -1 -1 H8 L6.5 3.5 H3 a1 1 0 0 0 -1 1 Z"/>
            <line x1="8" y1="8" x2="8" y2="11"/>
            <line x1="6.5" y1="9.5" x2="9.5" y2="9.5"/>
          </svg>
        </button>
        <input
          type="file"
          ref={fileInputRef}
          style={{ display: "none" }}
          onChange={async (ev) => {
            const f = ev.target.files?.[0];
            ev.target.value = "";  // allow re-picking the same file
            if (!f) return;
            await uploadFile(f, setInput, setAttachStatus);
          }}
        />
        <button
          type="button"
          className="sy-rail-action-btn"
          data-tour="curate"
          title="Run the curiosity-engine curator (sweep mode) on this workspace. Use /curate <mode> for a specific pass."
          onClick={() => onSubmit("/curate", { n: 0 })}
        >
          curate
        </button>
        <button
          type="button"
          className="sy-rail-action-btn"
          title="Rebuild the wiki viewer (data.json + static bundle). Use after curation or page edits."
          onClick={() => onSubmit("/viewer", { n: 0 })}
        >
          rebuild viewer
        </button>
        <button
          type="button"
          className="sy-rail-action-btn"
          title="Cold re-index: drop Switch Bay's caches + rebuild viewer fresh. Use when the BROWSER sidebar shows stale folders / pages."
          onClick={() => onSubmit("/rescan", { n: 0 })}
        >
          rescan
        </button>
        {customButtons.map((b) => (
          <span key={b.id} className="sy-rail-custom-wrap">
            <button
              type="button"
              className="sy-rail-action-btn"
              title={b.command}
              onClick={() => onSubmit(b.command, { n: 0 })}
            >
              {b.label}
            </button>
            <button
              type="button"
              className="sy-rail-custom-rm"
              title="Remove this custom button"
              aria-label="Remove custom button"
              onClick={() => void removeCustomButton(b.id)}
            >
              ×
            </button>
          </span>
        ))}
        <button
          type="button"
          className="sy-rail-action-btn sy-rail-action-add"
          title="Register a custom button — shortcut to a slash command or a canned chat message. Persists across workspaces."
          onClick={() => setAddingButton({ label: "", command: "" })}
          aria-label="Register a custom button"
        >
          +
        </button>
        {attachStatus && (
          <span className="sy-rail-attach-status">{attachStatus}</span>
        )}
      </div>
      {addingButton && (
        <div
          className="sy-confirm-backdrop"
          onClick={() => setAddingButton(null)}
        >
          <div
            className="sy-confirm sy-rail-add-button-dialog"
            role="dialog"
            aria-labelledby="sy-rail-add-button-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div id="sy-rail-add-button-title" className="sy-confirm-title">
              Register a custom button
            </div>
            <div className="sy-confirm-body">
              <p>
                Buttons live next to <em>curate</em> / <em>rebuild
                viewer</em> / <em>rescan</em>. Persists across workspaces
                in <code>~/.config/switchbay/action-buttons.json</code>.
              </p>
              <label className="sy-rail-add-button-row">
                <span>Label</span>
                <input
                  type="text"
                  className="sy-ws-input"
                  autoFocus
                  value={addingButton.label}
                  onChange={(e) => setAddingButton({ ...addingButton, label: e.target.value })}
                  placeholder="e.g. ingest"
                />
              </label>
              <label className="sy-rail-add-button-row">
                <span>Command</span>
                <input
                  type="text"
                  className="sy-ws-input"
                  value={addingButton.command}
                  onChange={(e) => setAddingButton({ ...addingButton, command: e.target.value })}
                  placeholder="/ingest  or  any chat prompt"
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && addingButton.label.trim() && addingButton.command.trim()) {
                      e.preventDefault();
                      void submitNewButton();
                    }
                  }}
                />
              </label>
            </div>
            <div className="sy-confirm-actions">
              <button
                type="button"
                className="sy-confirm-btn"
                onClick={() => setAddingButton(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="sy-confirm-btn sy-confirm-btn--primary"
                disabled={!addingButton.label.trim() || !addingButton.command.trim()}
                onClick={() => void submitNewButton()}
              >
                Add
              </button>
            </div>
          </div>
        </div>
      )}
      <div className="sy-rail-input-wrap" data-tour="chat">
        {acOpen && (
          <div className="sy-rail-ac" role="listbox" aria-label="slash commands">
            {acMatches.map((v, i) => (
              <button
                key={v.name}
                type="button"
                role="option"
                aria-selected={i === acIndex}
                className={"sy-rail-ac-item" + (i === acIndex ? " sy-rail-ac-item--sel" : "")}
                onMouseDown={(ev) => {
                  // mousedown not click — click would race with the
                  // textarea's blur and lose focus before the insert.
                  ev.preventDefault();
                  acceptSuggestion(v);
                }}
                onMouseEnter={() => setAcIndex(i)}
              >
                <span className="sy-rail-ac-name">/{v.name}</span>
                {v.aliases.length > 0 && (
                  <span className="sy-rail-ac-aliases">
                    aka {v.aliases.map((a) => `/${a}`).join(", ")}
                  </span>
                )}
                <span className="sy-rail-ac-desc">{v.description}</span>
              </button>
            ))}
          </div>
        )}
        {shellHint && (
          <div className="sy-rail-interp">
            {chatForced ? (
              <>⏎ send as <b>chat</b> · Tab: run in a shell thread</>
            ) : (
              <>⏎ run in a <b>shell thread</b> · Tab: send as chat</>
            )}
          </div>
        )}
        <textarea
          ref={inputRef}
          className="sy-rail-input"
          rows={3}
          value={input}
          onChange={(ev) => setInput(ev.target.value)}
          onKeyDown={(ev) => {
            if (acOpen) {
              if (ev.key === "ArrowDown") {
                ev.preventDefault();
                setAcIndex((i) => Math.min(i + 1, acMatches.length - 1));
                return;
              }
              if (ev.key === "ArrowUp") {
                ev.preventDefault();
                setAcIndex((i) => Math.max(i - 1, 0));
                return;
              }
              if (ev.key === "Tab" || (ev.key === "Enter" && !ev.shiftKey && acMatches[acIndex])) {
                ev.preventDefault();
                acceptSuggestion(acMatches[acIndex]!);
                return;
              }
              if (ev.key === "Escape") {
                ev.preventDefault();
                setInput("");
                return;
              }
            }
            if (ev.key === "Tab" && shellHint) {
              // Interpretation chip: Tab toggles shell ↔ chat for
              // this input (autocomplete's Tab-accept won when open).
              ev.preventDefault();
              setChatForced((v) => !v);
              return;
            }
            if (ev.key === "Enter" && !ev.shiftKey) {
              ev.preventDefault();
              submit();
            }
          }}
          placeholder="chat, or use a prefix… (try /view)"
        />
        <ReasoningPicker />
        <VoiceButton
          onText={(text) =>
            setInput((cur) => (cur.trim() ? `${cur.replace(/\s+$/, "")} ${text}` : text))
          }
        />
        <div
          className="sy-rail-hint"
          title="Prefixes are optional for shell commands — typed commands are auto-detected (the chip above the box; Tab flips chat ↔ shell)."
        >
          <code>/</code> commands · <code>!</code> shell thread · <code>!py</code> python thread · <code>!sql</code> → Table · <code>!fn</code> → Sheet
        </div>
      </div>
        </>
      )}
    </>
  );
}

/** Switch to the Agents tab and auto-expand the given run. Two
 *  cooperating events: `sy:open-agents-run` carries the run_id;
 *  App.tsx flips the active tab; AgentDashboardTab subscribes to
 *  `sy:expand-run` (re-emitted by App.tsx after the tab switch
 *  takes effect) and pops that run open. Single yellow `↗` per
 *  running tool / fold in the rail invokes this. */
function openInAgents(runId: string): void {
  if (!runId) return;
  window.dispatchEvent(new CustomEvent("sy:open-agents-run", {
    detail: { run_id: runId },
  }));
}


export async function uploadFile(
  file: File,
  setInput: (updater: (cur: string) => string) => void,
  setStatus: (s: string | null) => void,
) {
  setStatus(`uploading ${file.name}…`);
  try {
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch("/api/chat/upload", { method: "POST", body: fd });
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      setStatus(`upload failed: ${body.error ?? r.status}`);
      return;
    }
    const body = (await r.json()) as { path: string; size: number };
    // Prepend the attachment reference to whatever the user has
    // already typed. The agent sees `[attached: <path>]` and reads
    // the file via its native file-reading tool (claude_code's
    // Read, codex's bash cat, etc.). User can edit before sending.
    setInput((cur) => {
      const prefix = `[attached: ${body.path}]\n`;
      return cur.startsWith(prefix) ? cur : prefix + cur;
    });
    const sizeKb = Math.max(1, Math.round(body.size / 1024));
    setStatus(`attached · ${sizeKb} KB`);
    window.setTimeout(() => setStatus(null), 2500);
  } catch (e) {
    setStatus(`upload failed: ${(e as Error).message}`);
  }
}


// ── Inline permission dialog row ─────────────────────────────────────


/** Charter-amendment review card (D9). Mirrors PermissionRow's
 *  shape/styling; the proposal is behind a <details> fold so the
 *  card stays scannable mid-conversation. Accept is the ONLY path
 *  that writes the charter page. Exported: Zen's chat box renders
 *  the same card inline in its response half. */
export function DecisionRow(props: {
  entry: Extract<RailEntry, { source: "decision" }>;
}) {
  const { entry } = props;
  const [busy, setBusy] = useState(false);

  const decide = async (decision: "accept" | "dismiss") => {
    if (busy || entry.state !== "pending") return;
    setBusy(true);
    try {
      await fetch("/api/decisions/decide", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: entry.dec_id, decision }),
      });
      // Settled state arrives via the decision.review_resolved
      // broadcast, same as permission cards.
    } finally {
      setBusy(false);
    }
  };

  const settled = entry.state !== "pending";
  return (
    <div
      className={
        "sy-rail-entry sy-rail-permission"
        + (entry.state === "accepted" ? " sy-rail-permission--approved" : "")
        + (entry.state === "dismissed" ? " sy-rail-permission--denied" : "")
      }
    >
      <span className="sy-rail-prefix" data-kind="permission">§</span>
      <div className="sy-rail-permission-body">
        <div className="sy-rail-permission-head">
          <span className="sy-rail-permission-tool">
            Charter amendment{entry.project ? <> for <code>{entry.project}</code></> : null}
            {" → "}<code>{entry.charter_path}</code>
          </span>
        </div>
        <div className="sy-rail-decision-text">“{entry.text}”</div>
        <details className="sy-rail-decision-proposal">
          <summary>proposed page ({entry.proposal.length} chars)</summary>
          <pre>{entry.proposal}</pre>
        </details>
        {!settled && (
          <div className="sy-rail-permission-actions">
            <button
              type="button"
              className="sy-rail-permission-btn sy-rail-permission-btn--approve"
              disabled={busy}
              onClick={() => void decide("accept")}
              title="Write the proposed page — the charter is amended in place"
            >
              Accept — amend charter
            </button>
            <button
              type="button"
              className="sy-rail-permission-btn sy-rail-permission-btn--deny"
              disabled={busy}
              onClick={() => void decide("dismiss")}
              title="Don't amend — the captured decision note stays in wiki/notes/decisions.md"
            >
              Dismiss
            </button>
          </div>
        )}
        {settled && (
          <span className="sy-rail-permission-resolved">
            {entry.state === "accepted" ? "✓ charter amended" : "✗ dismissed (note kept)"}
          </span>
        )}
      </div>
    </div>
  );
}


export function ProposalRow(props: {
  entry: Extract<RailEntry, { source: "proposal" }>;
}) {
  const { entry } = props;
  const [busy, setBusy] = useState(false);
  const settled = entry.state !== "pending";
  const verdict = (entry.review?.verdict || "review").toLowerCase();
  const issues = entry.review?.issues || [];

  const decide = async (decision: "accept" | "dismiss") => {
    if (busy || settled) return;
    setBusy(true);
    try {
      await fetch("/api/proposals/decide", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: entry.prop_id, decision }),
      });
      // Settled state arrives via page_proposal_resolved.
    } finally {
      setBusy(false);
    }
  };

  const view = () => {
    // Pop the proposed page + reviewer annotations into a Report tab.
    void fetch(`/api/proposals/${encodeURIComponent(entry.prop_id)}/preview`, {
      method: "POST",
    });
  };

  return (
    <div
      className={
        "sy-rail-entry sy-rail-permission"
        + (entry.state === "accepted" ? " sy-rail-permission--approved" : "")
        + (entry.state === "dismissed" ? " sy-rail-permission--denied" : "")
      }
    >
      <span className="sy-rail-prefix" data-kind="permission">✎</span>
      <div className="sy-rail-permission-body">
        <div className="sy-rail-permission-head">
          <span className="sy-rail-permission-tool">
            Proposed {entry.kind} page — <code>{entry.title}</code>
          </span>
          <span className={"sy-kind-chip sy-proposal-verdict sy-proposal-verdict--" + verdict}>
            {verdict}
          </span>
        </div>
        {entry.review?.one_line && (
          <div className="sy-rail-decision-text">{entry.review.one_line}</div>
        )}
        {issues.length > 0 && (
          <details className="sy-rail-decision-proposal">
            <summary>reviewer's objections ({issues.length})</summary>
            <ul className="sy-proposal-issues">
              {issues.map((it, i) => <li key={i}>{it}</li>)}
            </ul>
          </details>
        )}
        {!settled && (
          <div className="sy-rail-permission-actions">
            <button
              type="button"
              className="sy-rail-permission-btn sy-rail-permission-btn--approve"
              disabled={busy}
              onClick={() => void decide("accept")}
              title="File this page into the wiki"
            >
              Accept — file page
            </button>
            <button
              type="button"
              className="sy-rail-permission-btn sy-rail-permission-btn--deny"
              disabled={busy}
              onClick={() => void decide("dismiss")}
              title="Discard this proposal — nothing is written"
            >
              Reject
            </button>
            <button
              type="button"
              className="sy-rail-permission-btn"
              onClick={view}
              title="Open the proposed page + annotations in a Report tab"
            >
              ↗ View
            </button>
          </div>
        )}
        {settled && (
          <span className="sy-rail-permission-resolved">
            {entry.state === "accepted" ? "✓ filed" : "✗ rejected"}
          </span>
        )}
      </div>
    </div>
  );
}

export function LocalModelsCheckRow(props: {
  entry: Extract<RailEntry, { source: "local_models_check" }>;
}) {
  const { entry } = props;
  const [busy, setBusy] = useState(false);
  const [state, setState] = useState(entry.state);
  if (state !== "pending" && state !== "checking") {
    return (
      <div className="sy-rail-entry sy-rail-permission sy-rail-permission--denied">
        <span className="sy-rail-prefix" data-kind="permission">🖥</span>
        <span className="sy-rail-permission-resolved">local model check dismissed</span>
      </div>
    );
  }
  const act = async (action: "check" | "dismiss") => {
    if (busy) return;
    setBusy(true);
    try {
      await fetch("/api/local-models/prompt", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      setState(action === "check" ? "checking" : "dismissed");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="sy-rail-entry sy-rail-permission">
      <span className="sy-rail-prefix" data-kind="permission">🖥</span>
      <div className="sy-rail-permission-body">
        <div className="sy-rail-permission-head">
          <span className="sy-rail-permission-tool">Local models refresh</span>
        </div>
        <div className="sy-rail-decision-text">{entry.message}</div>
        {state === "checking" ? (
          <span className="sy-rail-permission-resolved">Searching HF / catalog…</span>
        ) : (
          <div className="sy-rail-permission-actions">
            <button
              type="button"
              className="sy-rail-permission-btn sy-rail-permission-btn--approve"
              disabled={busy}
              onClick={() => void act("check")}
            >
              Check for updates
            </button>
            <button
              type="button"
              className="sy-rail-permission-btn sy-rail-permission-btn--deny"
              disabled={busy}
              onClick={() => void act("dismiss")}
            >
              Not now
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export function LocalModelsDiscoveryRow(props: {
  entry: Extract<RailEntry, { source: "local_models_discovery" }>;
}) {
  const { entry } = props;
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(entry.state === "done");
  const [add, setAdd] = useState<Record<string, boolean>>({});
  const [remove, setRemove] = useState<Record<string, boolean>>({});
  const sugg = entry.discovery.suggestions ?? [];
  const rems = entry.discovery.removals ?? [];

  const apply = async () => {
    if (busy || done) return;
    setBusy(true);
    try {
      for (const [id, on] of Object.entries(add)) {
        if (!on) continue;
        await fetch("/api/localllm/install", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ candidate_id: id }),
        });
      }
      for (const [id, on] of Object.entries(remove)) {
        if (!on) continue;
        await fetch("/api/local-models/remove", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id }),
        });
      }
      setDone(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={"sy-rail-entry sy-rail-permission" + (done ? " sy-rail-permission--approved" : "")}>
      <span className="sy-rail-prefix" data-kind="permission">🖥</span>
      <div className="sy-rail-permission-body">
        <div className="sy-rail-permission-head">
          <span className="sy-rail-permission-tool">Local model options</span>
        </div>
        {entry.discovery.note && (
          <div className="sy-rail-decision-text" style={{ fontSize: 11, opacity: 0.8 }}>
            {entry.discovery.note}
          </div>
        )}
        {sugg.length > 0 && (
          <div className="sy-rail-local-list">
            <div className="sy-rail-local-list-h">Add</div>
            {sugg.map((s) => (
              <label key={s.id} className="sy-rail-local-row">
                <input
                  type="checkbox"
                  checked={!!add[s.id]}
                  disabled={done || busy}
                  onChange={(e) => setAdd((p) => ({ ...p, [s.id]: e.target.checked }))}
                />
                <span>
                  <strong>{s.label}</strong>
                  {s.est_gb != null && <em> ~{s.est_gb} GB</em>}
                  <br />
                  <span className="sy-rail-local-sum">{s.summary || s.backend}</span>
                </span>
              </label>
            ))}
          </div>
        )}
        {rems.length > 0 && (
          <div className="sy-rail-local-list">
            <div className="sy-rail-local-list-h">Remove (free disk)</div>
            {rems.map((s) => (
              <label key={s.id} className="sy-rail-local-row">
                <input
                  type="checkbox"
                  checked={!!remove[s.id]}
                  disabled={done || busy}
                  onChange={(e) => setRemove((p) => ({ ...p, [s.id]: e.target.checked }))}
                />
                <span>
                  <strong>{s.label}</strong>
                  <br />
                  <span className="sy-rail-local-sum">{s.summary}</span>
                </span>
              </label>
            ))}
          </div>
        )}
        {sugg.length === 0 && rems.length === 0 && (
          <div className="sy-rail-decision-text">No new catalog fits; installed list empty.</div>
        )}
        {!done && (
          <div className="sy-rail-permission-actions">
            <button
              type="button"
              className="sy-rail-permission-btn sy-rail-permission-btn--approve"
              disabled={busy}
              onClick={() => void apply()}
            >
              Apply selection
            </button>
          </div>
        )}
        {done && <span className="sy-rail-permission-resolved">✓ applied (installs may continue in background)</span>}
      </div>
    </div>
  );
}

export function MicroEditFeedbackRow(props: {
  entry: Extract<RailEntry, { source: "micro_edit_feedback" }>;
}) {
  const { entry } = props;
  const [busy, setBusy] = useState(false);
  const [scope, setScope] = useState<"thread" | "workspace" | "global">("workspace");
  const [localState, setLocalState] = useState(entry.state);
  const settled = localState !== "pending";

  const decide = async (action: "keep" | "increase" | "dismiss") => {
    if (busy || settled) return;
    setBusy(true);
    try {
      const r = await fetch("/api/micro-edits/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: entry.feedback_id,
          action,
          scope,
        }),
      });
      if (r.ok) {
        setLocalState(
          action === "keep" ? "kept"
            : action === "increase" ? "increased"
              : "dismissed",
        );
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className={
        "sy-rail-entry sy-rail-permission"
        + (settled && entry.state !== "dismissed" ? " sy-rail-permission--approved" : "")
        + (entry.state === "dismissed" ? " sy-rail-permission--denied" : "")
      }
    >
      <span className="sy-rail-prefix" data-kind="permission">⚡</span>
      <div className="sy-rail-permission-body">
        <div className="sy-rail-permission-head">
          <span className="sy-rail-permission-tool">
            Micro-edit used <code>{entry.rung_used}</code>
            {" · "}
            {entry.provider} / {entry.model}
          </span>
        </div>
        <div className="sy-rail-decision-text">
          Keep the fast path for small Sheet / Sketch / Table / Plot edits,
          or increase intelligence? Scope applies to future micro-edits
          (Increase also redoes this request).
        </div>
        {!settled && (
          <>
            <label className="sy-rail-micro-scope">
              Scope{" "}
              <select
                value={scope}
                onChange={(e) => setScope(e.target.value as typeof scope)}
                disabled={busy}
              >
                <option value="workspace">Workspace (default)</option>
                <option value="thread">This thread</option>
                <option value="global">Globally</option>
              </select>
            </label>
            <div className="sy-rail-permission-actions">
              <button
                type="button"
                className="sy-rail-permission-btn sy-rail-permission-btn--approve"
                disabled={busy}
                onClick={() => void decide("keep")}
                title="Keep using this rung for micro-edits"
              >
                Keep
              </button>
              <button
                type="button"
                className="sy-rail-permission-btn"
                disabled={busy}
                onClick={() => void decide("increase")}
                title="Bump micro-edit rung and redo this request"
              >
                Increase &amp; redo
              </button>
              <button
                type="button"
                className="sy-rail-permission-btn sy-rail-permission-btn--deny"
                disabled={busy}
                onClick={() => void decide("dismiss")}
                title="Dismiss without changing preference"
              >
                Dismiss
              </button>
            </div>
            <div className="sy-rail-decision-text" style={{ opacity: 0.75, fontSize: "11px" }}>
              Change later: Settings → Model ladder, or{" "}
              <code>/micro-edits</code> (trivial · normal · hard).
            </div>
          </>
        )}
        {settled && (
          <span className="sy-rail-permission-resolved">
            {entry.state === "kept" && "✓ keep fast path"}
            {entry.state === "increased" && "↑ increased — redoing"}
            {entry.state === "dismissed" && "dismissed"}
          </span>
        )}
      </div>
    </div>
  );
}

export function ProviderRetryRow(props: {
  entry: Extract<RailEntry, { source: "provider_retry" }>;
}) {
  const { entry } = props;
  const [busy, setBusy] = useState(false);
  const settled = entry.state !== "pending";

  const decide = async (provider?: string) => {
    if (busy || settled) return;
    setBusy(true);
    try {
      await fetch("/api/provider-retry/decide", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: entry.retry_id, provider: provider ?? "" }),
      });
      // Settled state arrives via provider_retry_resolved.
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className={
        "sy-rail-entry sy-rail-permission"
        + (entry.state === "retried" ? " sy-rail-permission--approved" : "")
        + (entry.state === "dismissed" ? " sy-rail-permission--denied" : "")
      }
    >
      <span className="sy-rail-prefix" data-kind="permission">↻</span>
      <div className="sy-rail-permission-body">
        <div className="sy-rail-permission-head">
          <span className="sy-rail-permission-tool">
            <code>{entry.failed_label}</code> failed ({entry.code})
          </span>
        </div>
        <div className="sy-rail-decision-text">
          {entry.message.slice(0, 200)}
          {entry.alternatives.length > 0 && " — retry on another provider?"}
        </div>
        {!settled && (
          <div className="sy-rail-permission-actions">
            {entry.alternatives.map((alt) => (
              <button
                key={alt.id}
                type="button"
                className="sy-rail-permission-btn sy-rail-permission-btn--approve"
                disabled={busy}
                onClick={() => void decide(alt.id)}
                title={`Re-run this turn on ${alt.label}`}
              >
                Retry on {alt.label}
              </button>
            ))}
            <button
              type="button"
              className="sy-rail-permission-btn sy-rail-permission-btn--deny"
              disabled={busy}
              onClick={() => void decide()}
              title="Dismiss — leave the run failed"
            >
              Dismiss
            </button>
          </div>
        )}
        {settled && (
          <span className="sy-rail-permission-resolved">
            {entry.state === "retried"
              ? `↻ retried${entry.chosen ? ` on ${entry.chosen}` : ""}`
              : "✗ dismissed"}
          </span>
        )}
      </div>
    </div>
  );
}

type PermEntry = Extract<RailEntry, { source: "permission" }>;
type ApprovalGroup = {
  key: string;
  /** Home-compacted source label; null for background-thread cards
   *  (which belong to another Switch Bay thread, not an outside CLI). */
  origin: string | null;
  originPath: string | null;
  cards: PermEntry[];
};

/** Group out-of-thread approval cards by their source. External CLI
 *  sessions (bench, scripts) share an `origin` and get a source bar
 *  with watch/mute controls; background-thread cards (no origin) fall
 *  into one trailing group rendered plainly. Order is first-seen. */
function groupOtherApprovals(entries: PermEntry[]): ApprovalGroup[] {
  const groups: ApprovalGroup[] = [];
  const byKey = new Map<string, ApprovalGroup>();
  for (const e of entries) {
    // Sentinel for "no origin" (background-thread cards). Written
    // as an escape rather than a literal NUL byte: the raw byte
    // made this whole file read as BINARY, so grep/ripgrep
    // silently skipped it and searches came back empty. Same
    // runtime value, plain text on disk.
    const key = e.origin ?? "\u0000internal";
    let g = byKey.get(key);
    if (!g) {
      g = {
        key,
        origin: e.origin ?? null,
        originPath: e.origin_path ?? null,
        cards: [],
      };
      byKey.set(key, g);
      groups.push(g);
    }
    if (!g.originPath && e.origin_path) g.originPath = e.origin_path;
    g.cards.push(e);
  }
  return groups;
}

/** Header for an external source's approvals: names it as outside
 *  Switch Bay and offers "watch in shell" (open a terminal in its
 *  dir) + "mute" (stop its requests coming through the rail). */
function ExternalSourceBar(props: {
  origin: string; originPath: string | null; count: number;
}) {
  const { origin, originPath, count } = props;
  const [busy, setBusy] = useState(false);
  const watch = async () => {
    if (busy || !originPath) return;
    setBusy(true);
    try {
      await fetch("/api/permission/watch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ origin_path: originPath }),
      });
    } finally { setBusy(false); }
  };
  const mute = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await fetch("/api/permission/mute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ origin, muted: true }),
      });
    } finally { setBusy(false); }
  };
  return (
    <div className="sy-rail-approval-source">
      <span
        className="sy-rail-approval-source-label"
        title={`Outside Switch Bay — ${originPath ?? origin} (${count} pending)`}
      >
        outside Switch Bay · <code>{origin}</code>
      </span>
      <span className="sy-rail-approval-source-actions">
        {originPath && (
          <button
            type="button"
            className="sy-rail-approval-source-btn"
            disabled={busy}
            onClick={() => void watch()}
            title="Open a shell in this source's folder to watch it"
          >
            watch in shell
          </button>
        )}
        <button
          type="button"
          className="sy-rail-approval-source-btn"
          disabled={busy}
          onClick={() => void mute()}
          title="Stop this source's approvals from coming through the rail (until daemon restart)"
        >
          mute
        </button>
      </span>
    </div>
  );
}

export function PermissionRow(props: {
  entry: Extract<RailEntry, { source: "permission" }>;
}) {
  const { entry } = props;
  const [busy, setBusy] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  const decide = async (
    decision: "approve" | "deny",
    opts: { remember?: boolean; session?: boolean; pattern?: string } = {},
  ) => {
    if (busy || entry.state !== "pending") return;
    setBusy(true);
    setMenuOpen(false);
    try {
      await fetch("/api/permission/decide", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ req_id: entry.req_id, decision, ...opts }),
      });
    } finally {
      setBusy(false);
    }
  };
  // Tool-level wildcard, e.g. Read(*) — matches every call of this tool.
  const toolPattern = `${entry.tool}(*)`;

  const settled = entry.state !== "pending";
  return (
    <div
      className={
        "sy-rail-entry sy-rail-permission"
        + (entry.state === "approved" ? " sy-rail-permission--approved" : "")
        + (entry.state === "denied" ? " sy-rail-permission--denied" : "")
      }
    >
      <span className="sy-rail-prefix" data-kind="permission">🔒</span>
      <div className="sy-rail-permission-body">
        <div className="sy-rail-permission-head">
          <span className="sy-rail-permission-tool">
            {entry.provider} wants to run <code>{entry.tool}</code>
          </span>
        </div>
        <ToolInputView input={entry.tool_input} />
        {!settled && (
          <div className="sy-rail-permission-actions">
            <button
              type="button"
              className="sy-rail-permission-btn sy-rail-permission-btn--approve"
              disabled={busy}
              onClick={() => void decide("approve")}
              title="Allow this one tool call"
            >
              Approve once
            </button>
            <span className="sy-rail-permission-split">
              <button
                type="button"
                className="sy-rail-permission-btn sy-rail-permission-btn--approve-remember"
                disabled={busy}
                onClick={() => void decide("approve", { remember: true })}
                title={`Allow + remember this exact command (${entry.pattern}) in this workspace`}
              >
                Allow this command
              </button>
              <button
                type="button"
                className="sy-rail-permission-btn sy-rail-permission-caret"
                disabled={busy}
                aria-label="More allow options"
                title="More allow options"
                onClick={() => setMenuOpen((o) => !o)}
              >
                ▾
              </button>
              {menuOpen && (
                <div className="sy-rail-permission-menu" role="menu">
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => void decide("approve", { remember: true })}
                  >
                    Allow this command <span className="sy-help-dim">(remember · {entry.pattern})</span>
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => void decide("approve", { session: true, pattern: toolPattern })}
                  >
                    Allow all <code>{entry.tool}</code> this session <span className="sy-help-dim">({toolPattern})</span>
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => void decide("approve", { remember: true, pattern: toolPattern })}
                  >
                    Allow all <code>{entry.tool}</code> in this workspace <span className="sy-help-dim">(remember · {toolPattern})</span>
                  </button>
                </div>
              )}
            </span>
            <button
              type="button"
              className="sy-rail-permission-btn sy-rail-permission-btn--deny"
              disabled={busy}
              onClick={() => void decide("deny")}
              title="Refuse — the agent will see a denial"
            >
              Deny
            </button>
          </div>
        )}
        {settled && (
          <span className="sy-rail-permission-resolved">
            {entry.state === "approved" ? "✓ approved" : "✗ denied"}
          </span>
        )}
      </div>
    </div>
  );
}


/** Human-readable tool input for the permission card — no JSON
 *  syntax, no information loss. Shell-style tools show their command
 *  as code (commands ARE code); every other argument renders as a
 *  labelled row with the value in plain text. Nested values fall
 *  back to compact JSON only when there's genuinely structure. */
function ToolInputView({ input }: { input: Record<string, unknown> }) {
  const fmtValue = (v: unknown): string => {
    if (typeof v === "string") return v;
    if (v === null || v === undefined) return "—";
    if (typeof v === "number" || typeof v === "boolean") return String(v);
    try {
      return JSON.stringify(v);
    } catch {
      return String(v);
    }
  };
  const command = typeof input.command === "string" ? input.command : null;
  const rest = Object.entries(input).filter(
    ([k, v]) => !(k === "command" && command !== null) && v !== undefined,
  );
  if (command === null && rest.length === 0) {
    return <div className="sy-perm-fields sy-perm-fields--empty">no arguments</div>;
  }
  return (
    <>
      {command !== null && (
        <pre className="sy-rail-permission-input">{command}</pre>
      )}
      {rest.length > 0 && (
        <div className="sy-perm-fields">
          {rest.map(([k, v]) => (
            <div key={k} className="sy-perm-field">
              <span className="sy-perm-key">{k}</span>
              <span className="sy-perm-val">{fmtValue(v)}</span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}


function prefixFor(source: RailEntry["source"]): string {
  if (source === "user") return "›";
  if (source === "system") return "·";
  if (source === "assistant") return "‹";
  if (source === "tool") return "⚙";
  if (source === "reasoning") return "💭";
  return "»";
}

/** Collapsible chain-of-thought block. Collapsed by default (a peek of
 *  the first line in the summary); expand to inspect the full
 *  reasoning. Shared by the Power rail and Zen's response half. */
export function ReasoningRow({ text }: { text: string }) {
  const peek = text.replace(/\s+/g, " ").trim().slice(0, 88);
  return (
    <details className="sy-rail-entry sy-rail-reasoning">
      <summary className="sy-rail-reasoning-summary">
        <span className="sy-rail-prefix" data-kind="reasoning">💭</span>
        <span className="sy-rail-reasoning-label">reasoning</span>
        <span className="sy-rail-reasoning-peek">{peek}</span>
      </summary>
      <div className="sy-rail-reasoning-body">{text}</div>
    </details>
  );
}


/**
 * Match the backend rail.parse() prefix detection so user rows
 * render with the right kind chip (`cmd` / `excel` / `sql` /
 * `python`). Bare `!` is `cmd`; `/foo` is the slash kind handled
 * elsewhere. Returns null when the prompt is plain chat.
 */
/**
 * Pull the actual command string out of a Bash tool_use's input.
 * claude-code's Bash tool ships `{command, description?, timeout?}`
 * — we surface a "re-run in terminal" button only when the command
 * field is present so we don't dispatch an empty `!`.
 */
function extractBashCommand(input: unknown): string | null {
  if (!input || typeof input !== "object") return null;
  const cmd = (input as { command?: unknown }).command;
  if (typeof cmd !== "string") return null;
  const trimmed = cmd.trim();
  return trimmed ? trimmed : null;
}


export function detectUserKind(text: string): string | null {
  const t = text.trimStart();
  if (t.startsWith("/")) return "slash";
  if (/^!(?:fn|exc)\b/i.test(t)) return "formula";
  if (/^!sql\b/i.test(t)) return "sql";
  if (/^!py\b/i.test(t)) return "python";
  if (t.startsWith("!")) return "cmd";
  return null;
}

export function prettyJson(value: unknown): string {
  try {
    const s = JSON.stringify(value, null, 2);
    // Cap exotic blobs so the panel stays readable. The full payload
    // is in the rail log on disk and recallable via recall_rail.
    return s.length > 4000 ? s.slice(0, 4000) + "\n…(truncated)" : s;
  } catch {
    return String(value);
  }
}

export function summariseInput(input: Record<string, unknown>): string {
  const keys = Object.keys(input);
  if (keys.length === 0) return "()";
  // Compact: show key counts for arrays / objects, primitives inline.
  const parts = keys.slice(0, 3).map((k) => {
    const v = input[k];
    if (Array.isArray(v)) return `${k}[${v.length}]`;
    if (v && typeof v === "object") return `${k}{…}`;
    const s = String(v);
    return `${k}=${s.length > 30 ? s.slice(0, 30) + "…" : s}`;
  });
  const rest = keys.length > 3 ? ` +${keys.length - 3}` : "";
  return `(${parts.join(", ")}${rest})`;
}

type RenderItem =
  | { kind: "entry"; entry: RailEntry }
  | { kind: "fold"; startId: number; count: number; names: string[]; run_id: string };

/** When a turn fires 4+ in-flight tool calls in a row, fold the
 *  whole run into one calm summary line (no individual flashing
 *  cursors). 3 or fewer renders inline as before. As tools resolve
 *  their results arrive and the run shrinks; once ≤3 the fold goes
 *  away naturally and the resolved entries show with their results. */
function buildRenderItems(entries: RailEntry[]): RenderItem[] {
  const PEND_THRESHOLD = 3;
  const out: RenderItem[] = [];
  const isPendingTool = (e: RailEntry): boolean =>
    e.source === "tool" && !e.result;
  let i = 0;
  while (i < entries.length) {
    const e = entries[i]!;
    if (isPendingTool(e)) {
      let j = i;
      while (j < entries.length && isPendingTool(entries[j]!)) j++;
      const len = j - i;
      if (len > PEND_THRESHOLD) {
        const hidden = entries.slice(i, j);
        const first = hidden[0] as Extract<RailEntry, { source: "tool" }>;
        out.push({
          kind: "fold",
          startId: hidden[0]!.id,
          count: hidden.length,
          names: hidden.map((x) => (x as Extract<RailEntry, { source: "tool" }>).name),
          run_id: first.run_id,
        });
      } else {
        for (let k = i; k < j; k++) out.push({ kind: "entry", entry: entries[k]! });
      }
      i = j;
    } else {
      out.push({ kind: "entry", entry: e });
      i++;
    }
  }
  return out;
}

// ── Run lanes ──────────────────────────────────────────────────────
// Parallel agents interleave in the rail. Group contiguous same-run
// items into fenced, colour-coded "run blocks" so each stream is
// followable; completed blocks collapse, live ones stay open, and a
// focus switcher dims the others.

type TimelineNode =
  | { kind: "loose"; item: RenderItem }
  | { kind: "block"; runId: string; firstId: number; items: RenderItem[] };

function itemRunId(item: RenderItem): string | null {
  let rid: string | null = null;
  if (item.kind === "fold") rid = item.run_id;
  else {
    const e = item.entry;
    if (e.source === "assistant" || e.source === "tool") rid = e.run_id;
    else if (e.source === "permission") rid = e.run_id;
  }
  // Synthetic per-event ids from rail hydration don't represent a real
  // run grouping — treat them as loose (flat) so reloaded history isn't
  // split into one block per event. Real run ids (live dispatches) fence
  // into lanes. (Cross-reload historical grouping needs the backend to
  // persist run_id per event — a follow-up.)
  if (rid == null || rid.startsWith("historic-")) return null;
  return rid;
}

function firstItemId(item: RenderItem): number {
  return item.kind === "fold" ? item.startId : item.entry.id;
}

/** Stable hue (0-359) from a run id, for the lane colour. */
function runHue(id: string): number {
  let h = 0;
  for (let k = 0; k < id.length; k++) h = (h * 31 + id.charCodeAt(k)) >>> 0;
  return h % 360;
}

function shortRun(id: string): string {
  return id.replace(/^run-/, "").slice(0, 8);
}

/** Assistant markdown with [[wikilinks]] turned into clickable
 *  anchors (data-wiki carries the raw target; click is delegated to
 *  a window event App resolves against the graph). Runs BEFORE
 *  marked so the anchor survives as inline HTML. */
export function mdWithWikilinks(text: string): string {
  const esc = (s: string) => s
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const pre = text.replace(
    /\[\[([^\]|]+?)(?:\|([^\]]+?))?\]\]/g,
    (_m, target: string, alias?: string) =>
      `<a href="#" class="sy-wikilink" data-wiki="${esc(target.trim())}">`
      + `${esc((alias ?? target).trim())}</a>`,
  );
  return sanitizeHtml(marked.parse(pre) as string);
}


function groupRunBlocks(items: RenderItem[]): TimelineNode[] {
  const out: TimelineNode[] = [];
  let i = 0;
  while (i < items.length) {
    const rid = itemRunId(items[i]!);
    if (rid == null) {
      out.push({ kind: "loose", item: items[i]! });
      i++;
      continue;
    }
    const group: RenderItem[] = [];
    let j = i;
    while (j < items.length && itemRunId(items[j]!) === rid) {
      group.push(items[j]!);
      j++;
    }
    out.push({ kind: "block", runId: rid, firstId: firstItemId(group[0]!), items: group });
    i = j;
  }
  return out;
}

function blockToolCount(items: RenderItem[]): number {
  let n = 0;
  for (const it of items) {
    if (it.kind === "fold") n += it.count;
    else if (it.entry.source === "tool") n += 1;
  }
  return n;
}

function blockLabel(items: RenderItem[]): string {
  for (const it of items) {
    if (it.kind === "entry" && it.entry.source === "assistant" && it.entry.text.trim()) {
      return it.entry.text.trim().replace(/\s+/g, " ").slice(0, 64);
    }
  }
  for (const it of items) {
    if (it.kind === "entry" && it.entry.source === "tool") return it.entry.name;
    if (it.kind === "fold") return it.names[0] ?? "tools";
  }
  return "";
}

function RunBlock(props: {
  node: Extract<TimelineNode, { kind: "block" }>;
  live: boolean;
  dimmed: boolean;
  focused: boolean;
  expanded: boolean;
  onToggleExpand: () => void;
  onFocus: () => void;
  openInAgents: (runId: string) => void;
  renderItem: (item: RenderItem) => ReactNode;
}) {
  const { node, live, dimmed, focused, expanded, onToggleExpand, onFocus, openInAgents, renderItem } = props;
  const show = live || expanded;
  const tools = blockToolCount(node.items);
  const label = blockLabel(node.items);
  return (
    <div
      className={
        "sy-rail-block"
        + (dimmed ? " sy-rail-block--dim" : "")
        + (focused ? " sy-rail-block--focus" : "")
        + (live ? " sy-rail-block--live" : "")
      }
      style={{ "--run-hue": String(runHue(node.runId)) } as CSSProperties}
    >
      <div
        className={"sy-rail-block-head" + (live ? "" : " sy-rail-block-head--toggle")}
        /* The WHOLE header row toggles — the chevron alone was too
         * small a target and nobody guessed it. Buttons inside stop
         * propagation so focus/jump don't also toggle. */
        onClick={() => { if (!live) onToggleExpand(); }}
        title={live ? undefined : show ? "Collapse this run" : "Expand this run"}
      >
        <button
          type="button"
          className="sy-rail-block-toggle"
          onClick={(ev) => { ev.stopPropagation(); onToggleExpand(); }}
          disabled={live}
          title={live ? "Running — stays open" : show ? "Collapse this run segment" : "Expand this run segment"}
        >
          {live ? "●" : show ? "▾" : "▸"}
        </button>
        <span className="sy-rail-block-id" title={node.runId}>{shortRun(node.runId)}</span>
        {label && <span className="sy-rail-block-label">{label}</span>}
        <span className="sy-spacer" />
        <span className="sy-rail-block-status" title={live ? "running" : "done"} aria-label={live ? "running" : "done"}>
          {live ? (
            // line-drawn timer/clock, inherits the run colour
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M9 2h6" />
              <circle cx="12" cy="13" r="8" />
              <path d="M12 13V9" />
            </svg>
          ) : (
            // line-drawn check
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M20 6 9 17l-5-5" />
            </svg>
          )}
        </span>
        <span className="sy-rail-block-tools">{tools} tool{tools === 1 ? "" : "s"}</span>
        <button
          type="button"
          className="sy-rail-block-focusbtn"
          onClick={(ev) => { ev.stopPropagation(); onFocus(); }}
          title="Focus this run — dim the others"
        >
          {focused ? "focused" : "focus"}
        </button>
        <button
          type="button"
          className="sy-rail-jump"
          onClick={(ev) => { ev.stopPropagation(); openInAgents(node.runId); }}
          title="Open this run in the Agent Dashboard"
          aria-label="Open in Agent Dashboard"
        >↗</button>
      </div>
      {show && <div className="sy-rail-block-body">{node.items.map(renderItem)}</div>}
    </div>
  );
}
