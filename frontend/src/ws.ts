// Mirrors src/switchbay/protocol.py + rail.py shapes.
// Keep in sync by hand for now.

export type TabSpec = {
  id: string;
  title: string;
  kind: string;
  /** Where this tab came from. Drives the tab-strip's grouped
   *  rendering (core | pack | user dividers). `undefined` is
   *  treated as `core` for backwards compatibility with older
   *  mode.json files. `system` tabs are special, cross-workspace
   *  surfaces (the Agents dashboard) — pinned to the right, after a
   *  separator past all other tabs and before "+ New…". */
  source?: "core" | "pack" | "user" | "system";
  /** Optional pack id when source === "pack" — surfaces a
   *  hover hint and lets the rail target the right manifest if
   *  the user wants to inspect / uninstall. */
  pack?: string;
  /** Optional payload for pack-supplied generic tab kinds.
   *  Pack-file-list uses `{extensions, action, endpoint, …}`
   *  to drive its render without needing custom code. */
  payload?: Record<string, unknown>;
  /** Thread scope (user tabs only): when set, the tab renders only
   *  while this thread is focused — it hides on switch and reappears
   *  with its thread. Absent = workspace-wide. */
  thread?: string;
};
export type Mode = { name: string; tabs: TabSpec[] };

// Selection layer (step C). Widen as more tab kinds land.
export type SelectionPage = { kind: "page"; id: string; path: string };
export type SelectionCsv = { kind: "csv"; path: string };
/** Inline table data (e.g. a markdown table parsed from the Editor)
 *  routed to the Sheet tab without going through disk. `origin` is a
 *  human-readable breadcrumb for the Sheet status badge. */
export type SelectionTableData = {
  kind: "table-data";
  origin: string;
  values: (string | number | null)[][];
};
/** Saved Vega-Lite plot routed to the Plot tab via `/plot <name>` or
 *  the slash autocomplete. The Plot tab uses `id` to fetch the spec
 *  via `/api/plot?id=<id>`. */
export type SelectionPlot = { kind: "plot"; id: string; name: string };
/** Saved Excalidraw / drawio sketch routed to the Sketch tab via
 *  `/sketch <name>` or the slash autocomplete. */
export type SelectionSketch = { kind: "sketch"; id: string; name: string };
/** An ordered set of PNG slides — viewed in the Sketch tab's deck
 *  mode. Used by the core .pptx fallback (LibreOffice → PDF → PNGs)
 *  so we don't need a dedicated PPTX tab. Pack-supplied tabs (e.g.
 *  Impress) will override this routing when installed. */
export type SelectionImageDeck = {
  kind: "image-deck";
  title: string;
  /** Path to the on-disk source (.pptx, .pdf, …). Echoed back so
   *  the deck header can show breadcrumbs + an "open externally"
   *  affordance. */
  source_path: string;
  slides: { src: string; name: string }[];
};
export type Selection =
  | SelectionPage
  | SelectionCsv
  | SelectionTableData
  | SelectionPlot
  | SelectionSketch
  | SelectionImageDeck;

export type Workspaces = {
  paths: string[];
  active: string | null;
  /** Archived workspace paths (with timestamps). Surfaced in the
   *  switcher's "Archived" section for restore. Optional so older
   *  daemon responses without this field still type-check. */
  archived?: { path: string; archived_at?: number }[];
};

export type Hello = {
  type: "hello";
  workspace: string;
  default_file: string | null;
  mode: Mode;
  selection: Selection | null;
  workspaces: Workspaces;
  /** The daemon's focused thread — hydrate the rail from it without a
   *  /api/threads round-trip. null on a fresh workspace. */
  thread_id?: string | null;
};

/** The daemon's focused thread changed (switcher click, + New thread,
 *  a `!cmd` spawning a shell thread). All clients move their rail to
 *  this thread in lock-step; `kind` picks the surface (transcript vs
 *  xterm) without a round-trip. */
export type ThreadFocused = {
  type: "thread_focused";
  thread_id: string;
  kind?: string;
};

export type ParsedKind = "chat" | "cmd" | "slash" | "excel" | "sql" | "python";

export type Notice = {
  type: "notice";
  text: string;
  kind: ParsedKind | null;
};

export type UserInput = {
  type: "user_input";
  text: string;
};

export type SelectionSet = {
  type: "selection_set";
  selection: Selection | null;
};

export type SelectionState = {
  type: "selection_state";
  selection: Selection | null;
};

// ── AG-UI agent-run lifecycle events ──────────────────────────────
// The run stream speaks the AG-UI schema's stable core (decided
// 2026-07-03). Spec fields are camelCase (runId/threadId/messageId/
// toolCallId/delta); Switch Bay extras (provider, model, workspace,
// token counts) ride alongside in snake_case. Every event carries
// runId — our WS is a shared broadcast channel, so handlers route by
// run rather than assuming a per-run stream.

export type RunStarted = {
  type: "RUN_STARTED";
  threadId: string;
  runId: string;
  provider: string;
  model: string;
  /** Workspace the run belongs to. The rail uses it to ignore live
   *  events for runs in another workspace (rail is per-workspace; the
   *  Agent Dashboard is the cross-workspace surface). */
  workspace?: string;
};

export type RunFinished = {
  type: "RUN_FINISHED";
  threadId: string;
  runId: string;
  input_tokens: number | null;
  output_tokens: number | null;
  stop_reason: string | null;
};

export type RunError = {
  type: "RUN_ERROR";
  runId: string;
  threadId?: string;
  code: string;
  message: string;
};

/** One assistant text segment. START mints the messageId, CONTENT
 *  streams deltas, END closes it (at a tool call or end of stream). */
export type TextMessageStart = {
  type: "TEXT_MESSAGE_START";
  runId: string;
  messageId: string;
  role: string;
};

export type TextMessageContent = {
  type: "TEXT_MESSAGE_CONTENT";
  runId: string;
  messageId: string;
  delta: string;
};

export type TextMessageEnd = {
  type: "TEXT_MESSAGE_END";
  runId: string;
  messageId: string;
};

export type ToolCallStart = {
  type: "TOOL_CALL_START";
  runId: string;
  toolCallId: string;
  toolCallName: string;
  parentMessageId?: string;
};

/** Tool-argument JSON. The daemon sends the complete input as one
 *  frame between START and END (our providers don't stream args). */
export type ToolCallArgs = {
  type: "TOOL_CALL_ARGS";
  runId: string;
  toolCallId: string;
  delta: string;
};

export type ToolCallEnd = {
  type: "TOOL_CALL_END";
  runId: string;
  toolCallId: string;
};

export type ToolCallResult = {
  type: "TOOL_CALL_RESULT";
  runId: string;
  toolCallId: string;
  messageId: string;
  content: string;
  role: "tool";
  /** Switch Bay extra — drives the rail's success/failure styling. */
  ok: boolean;
};

export type StepStarted = { type: "STEP_STARTED"; runId: string; stepName: string };
export type StepFinished = { type: "STEP_FINISHED"; runId: string; stepName: string };

export type NavPayload = {
  selection?: Selection | null;
  // Tab-specific extra hints (e.g. open_db: rel for the Table tab).
  // The receiving tab decides what to do with these.
  [key: string]: unknown;
};

export type Nav = {
  type: "nav";
  tab_kind: string;
  payload: NavPayload;
  label: string;
};

/** Hint that workspace files have shifted since the last fetch.
 *  Triggers the Browser file-tree re-fetch and a graph re-fetch. */
export type FilesChanged = { type: "files_changed" };

/** A capable model produced a rich HTML report (create_report). The
 *  Report tab should focus and load `/api/report/<report_id>`. */
export type OpenReport = {
  type: "open_report";
  report_id: string;
  title: string;
};

/** The Intro tab was added (via /intro or the first-install seed) —
 *  focus it. The tab itself loads `/api/intro`. */
export type OpenIntro = { type: "open_intro" };

/** Open a workspace HTML slideshow (slideshows/<slug>/) in the Slideshow tab. */
export type OpenHtmlDeck = {
  type: "open_html_deck";
  slug: string;
  title?: string;
};

/** Open a durable report package (reports/<slug>/). */
export type OpenReportDoc = {
  type: "open_report_doc";
  slug: string;
  title?: string;
};

/** Open a named worksheet into the Sheet tab. */
export type OpenWorksheet = {
  type: "open_worksheet";
  slug: string;
  title?: string;
  snapshot?: unknown;
};

/** Settings easter egg armed the Hopper tab — focus it. */
export type OpenThrusters = { type: "open_thrusters" };

/** `/walkthrough` (or first-install auto-start) — open the product tour. */
export type OpenWalkthrough = { type: "open_walkthrough" };

/** An AGENT produced/updated a user-facing artifact (plot, deck
 *  slide, wiki page). `kind` = the tab kind that renders it;
 *  `selection`, when present, is ready to apply so the jump lands on
 *  the exact artifact. Zen's pulse badge rides this (never
 *  auto-switch); Power ignores it today. */
export type ArtifactMsg = {
  type: "artifact";
  kind: string;
  label: string;
  selection?: Selection | null;
};

/** The model's private chain-of-thought for one assistant segment
 *  (e.g. Ornith's reasoning_content). Delivered whole when the segment
 *  closes; the rail shows it as a collapsible block. */
export type ReasoningMsg = {
  type: "reasoning";
  runId: string;
  messageId: string;
  text: string;
};

/** Rail history was wiped on disk (via /clear-rail-history). Drop
 *  the in-memory transcript so the user immediately sees the rail
 *  match the server state. */
export type RailCleared = { type: "rail_cleared" };

/** The daemon is about to exit on a user-requested stop (Settings →
 *  Quit, or `/quit`). Every open window shows a "stopped" overlay and
 *  stops reconnecting, instead of reconnect-looping into a dead socket. */
export type DaemonShutdown = { type: "daemon.shutdown"; reason?: string };

/** `!sql <query>` from the chat — server tells the frontend to
 *  switch to the Table tab and run the supplied SQL. The DuckDBTab
 *  listens via a `sy:sql-run` window event that App dispatches in
 *  response. */
export type SqlRun = {
  type: "sql.run";
  query: string;
  command_id?: string | null;
  workspace?: string | null;
};

/** `!fn <formula>` from the chat — or agent `sheet_set_formula`.
 *  Server tells the frontend to switch to the Sheet tab and write
 *  formula(s). Legacy single-formula form targets the active cell
 *  (optional `cell` A1 override). Batch form uses `writes`. */
export type FormulaRun = {
  type: "formula.run";
  formula?: string;
  cell?: string;
  writes?: { cell: string; formula: string }[];
  /** Agent wait_ack path — Sheet reports apply+durable via command-ack. */
  command_id?: string | null;
  workspace?: string | null;
};

/** Agent `sheet_select` — move the Sheet tab selection to an A1 range. */
export type SheetSelect = { type: "sheet.select"; range: string };

/** Agent `sheet_set_values` — write a 2D grid onto a new/import sheet. */
export type SheetValues = {
  type: "sheet.values";
  values: (string | number | boolean | null)[][];
  origin?: string;
  command_id?: string | null;
  workspace?: string | null;
};

/** Agent plot_show / plot_update — switch to Plot and highlight a card. */
export type PlotShow = {
  type: "plot.show";
  id: string;
  name?: string;
  command_id?: string | null;
  workspace?: string | null;
};

/** Agent sketch_show / author_slide nudge — switch to Sketch and show a slide. */
export type SketchShow = {
  type: "sketch.show";
  sketch_id?: string | null;
  slide_index?: number | null;
  name?: string | null;
  command_id?: string | null;
  workspace?: string | null;
};

/** Background auto-titler named a thread (first user turn, small
 *  model). The ThreadBar refreshes its list / focused label via a
 *  `sy:thread-titled` window event App dispatches in response. */
export type ThreadTitled = { type: "thread.titled"; thread_id: string; title: string };

/** A thread was archived (hidden from the switcher; events kept in
 *  the log) or hard-purged from Settings → History. Both nudge the
 *  ThreadBar via a `sy:threads-changed` window event. */
export type ThreadArchived = { type: "thread.archived"; thread_id: string };
export type ThreadsPurged = { type: "threads.purged"; thread_ids: string[] };

/** A background workspace merge finished (D2). App shows a toast
 *  with an Open button — never an auto-switch. */
export type WorkspaceMerged = {
  type: "workspace.merged";
  name: string;
  path: string;
};

/** A background workspace split finished (D4). Same toast contract. */
export type WorkspaceSplit = {
  type: "workspace.split";
  name: string;
  path: string;
};

/** The rail agent proposed a split set (propose_split tool). App
 *  switches to the Graph tab and seeds the split review surface —
 *  the user still edits, names, and confirms there. */
export type SplitProposal = {
  type: "split.proposal";
  pages: string[];
  reason?: string;
};

/** A thread's project binding changed (D8: /project verb or the
 *  ThreadBar picker chip). Nudges the ThreadBar via the same
 *  `sy:threads-changed` window event as archive/purge. */
export type ThreadProjectChanged = {
  type: "thread.project_changed";
  thread_id: string;
  project: string | null;
};

/** Heartbeat-drafted charter amendment awaiting review (D9). The
 *  card renders from this event alone (proposal included); clicks
 *  POST `/api/decisions/decide`. Re-offered after reload via
 *  GET /api/decisions/pending — disk-backed, unlike permissions. */
export type DecisionReview = {
  type: "decision.review";
  id: string;
  text: string;
  project: string | null;
  created: string;
  charter_path: string;
  proposal: string;
};

/** Companion — broadcast after accept/dismiss so all clients settle
 *  the card in lock-step. */
export type DecisionReviewResolved = {
  type: "decision.review_resolved";
  id: string;
  decision: "accept" | "dismiss";
};

/** A local-model page proposal whose reviewer verdict is borderline
 *  ("edit") — hand it to the user as an accept/reject rail card. */
export type PageProposalReview = {
  type: "page_proposal_review";
  id: string;
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
};

export type PageProposalResolved = {
  type: "page_proposal_resolved";
  id: string;
  decision: "accept" | "dismiss" | "reject";
};

/** A run died on a transient/capacity/billing provider error and other
 *  providers are keyed — offer a one-click retry on one of them. */
export type ProviderRetryOffer = {
  type: "provider_retry_offer";
  id: string;
  failed_provider: string;
  failed_label: string;
  code: string;
  message: string;
  alternatives: { id: string; label: string }[];
};

export type ProviderRetryResolved = {
  type: "provider_retry_resolved";
  id: string;
  provider: string | null;
};

/** Inline rail dialog ask — agent's PreToolUse hook wants to run a
 *  tool that isn't on the static allowlist. Frontend pops an
 *  Approve / Approve+remember / Deny strip; click POSTs
 *  `/api/permission/decide`. */
export type PermissionRequest = {
  type: "permission_request";
  req_id: string;
  provider: string;
  tool: string;
  tool_input: Record<string, unknown>;
  pattern: string;
  run_id: string | null;
  /** Rail thread that owns the requesting CLI session, or null when
   *  the session is not one of ours (bench runs, scripts, background
   *  agents). Non-focused-thread and external cards render in the
   *  out-of-thread approvals strip, never the transcript. */
  thread_id?: string | null;
  /** For external cards: where the request came from (home-compacted
   *  cwd of the CLI session). */
  origin?: string | null;
  /** For external cards: absolute cwd of the source, when known —
   *  enables "watch in shell". Null for old hooks that don't send cwd. */
  origin_path?: string | null;
};

/** Companion to PermissionRequest — broadcast after a verdict so
 *  every connected tab can drop the dialog from its rail. */
export type PermissionResolved = {
  type: "permission_resolved";
  req_id: string;
  /** "skip" = a muted source's card was cleared (no verdict shown). */
  decision: "approve" | "deny" | "skip";
};

/** First micro-edit calibration card after a fast-path run. */
export type MicroEditFeedback = {
  type: "micro_edit.feedback";
  id: string;
  rung_used: string;
  provider: string;
  model: string;
  thread_id?: string;
  original_text?: string;
};

/** ~6-week nudge: check for new local models. */
export type LocalModelsCheckPrompt = {
  type: "local_models.check_prompt";
  message: string;
  interval_days?: number;
};

/** Discovery finished — show add/remove dialog data. */
export type LocalModelsDiscovery = {
  type: "local_models.discovery";
  discovery: {
    ok?: boolean;
    suggestions?: Array<{
      id: string;
      label: string;
      summary?: string;
      backend?: string;
      action?: string;
      est_gb?: number;
    }>;
    removals?: Array<{
      id: string;
      label: string;
      summary?: string;
      backend?: string;
      action?: string;
    }>;
    note?: string;
  };
};

export type ServerMessage =
  | Hello
  | Notice
  | SelectionState
  | ThreadFocused
  | RunStarted
  | RunFinished
  | RunError
  | TextMessageStart
  | TextMessageContent
  | TextMessageEnd
  | ToolCallStart
  | ToolCallArgs
  | ToolCallEnd
  | ToolCallResult
  | StepStarted
  | StepFinished
  | Nav
  | FilesChanged
  | OpenReport
  | OpenIntro
  | OpenHtmlDeck
  | OpenReportDoc
  | OpenWorksheet
  | OpenThrusters
  | OpenWalkthrough
  | ArtifactMsg
  | ReasoningMsg
  | RailCleared
  | DaemonShutdown
  | SqlRun
  | FormulaRun
  | SheetSelect
  | SheetValues
  | PlotShow
  | SketchShow
  | MicroEditFeedback
  | LocalModelsCheckPrompt
  | LocalModelsDiscovery
  | ThreadTitled
  | ThreadArchived
  | ThreadsPurged
  | WorkspaceMerged
  | WorkspaceSplit
  | SplitProposal
  | ThreadProjectChanged
  | DecisionReview
  | DecisionReviewResolved
  | PageProposalReview
  | PageProposalResolved
  | ProviderRetryOffer
  | ProviderRetryResolved
  | PermissionRequest
  | PermissionResolved;
export type ClientMessage = UserInput | SelectionSet;
export type Listener = (msg: ServerMessage) => void;

export class RailSocket {
  private ws: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private url: string;
  private retry = 0;
  private closed = false;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  /** True once we've successfully opened at least once, so a later
   *  open is a *re*connection (daemon restart) rather than first boot. */
  private hasConnected = false;
  /** Messages attempted while the socket was down — flushed on the
   *  next open so a click during a reconnect window (daemon restart)
   *  isn't silently dropped. */
  private sendQueue: unknown[] = [];

  constructor(url = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`) {
    this.url = url;
    this.connect();
  }

  private connect() {
    if (this.closed) return;
    this.ws = new WebSocket(this.url);
    this.ws.onopen = () => {
      this.retry = 0;
      // Flush anything queued while we were disconnected.
      const queued = this.sendQueue;
      this.sendQueue = [];
      for (const m of queued) this.ws?.send(JSON.stringify(m));
      // On a *re*connection (the daemon restarted), the server has no
      // terminal sessions and the frontend's are stale. Tell listeners
      // so stateful panels resync. `term.reset` rides the existing
      // term.* filter so it reaches the PtyThreadSurface; other handlers
      // ignore it. (The daemon also re-sends `hello` on connect, which
      // resyncs workspace/mode/selection.)
      if (this.hasConnected) {
        for (const fn of this.listeners) fn({ type: "term.reset" } as unknown as ServerMessage);
      }
      this.hasConnected = true;
    };
    this.ws.onmessage = (ev) => {
      try {
        // Switch Bay surfaces (hello/nav/selection/permission/…) ride
        // the wire as AG-UI CUSTOM events `{type:"CUSTOM", name, value}`.
        // Unwrap here, once — every downstream handler keeps seeing the
        // inner message shape, so AG-UI spec drift can't reach them.
        const raw = JSON.parse(ev.data) as { type?: string; value?: unknown };
        const msg = (raw.type === "CUSTOM" ? raw.value : raw) as ServerMessage;
        for (const fn of this.listeners) fn(msg);
      } catch {
        // ignore malformed
      }
    };
    this.ws.onclose = () => {
      if (this.closed) return;
      const delay = Math.min(1000 * 2 ** this.retry++, 10_000);
      this.retryTimer = setTimeout(() => this.connect(), delay);
    };
    this.ws.onerror = () => this.ws?.close();
  }

  on(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => {
      this.listeners.delete(fn);
    };
  }

  /** Cap the reconnect buffer so a long outage + a click-happy user
   *  can't replay a huge burst of now-stale frames on reconnect. */
  private static readonly MAX_QUEUE = 50;

  send(msg: ClientMessage) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
      return;
    }
    // Socket is mid-reconnect (e.g. daemon restart). Buffer instead of
    // dropping so the "+ Open a shell" / selection click the user just
    // made actually lands once we reconnect.
    //
    // selection_set is last-writer-wins: only the final selection during
    // the outage matters, so collapse consecutive ones instead of
    // replaying every intermediate hover. user_input is NOT collapsible
    // (each is a distinct turn) — those queue in order.
    if (
      msg.type === "selection_set"
      && this.sendQueue.length > 0
      && (this.sendQueue[this.sendQueue.length - 1] as ClientMessage).type === "selection_set"
    ) {
      this.sendQueue[this.sendQueue.length - 1] = msg;
    } else {
      this.sendQueue.push(msg);
    }
    // Hard cap: drop the OLDEST frames past the limit (keep the most
    // recent intent) so an hour-long outage doesn't accumulate forever.
    if (this.sendQueue.length > RailSocket.MAX_QUEUE) {
      this.sendQueue.splice(0, this.sendQueue.length - RailSocket.MAX_QUEUE);
    }
  }

  /** Permanently close the socket. Subsequent reconnect attempts are
   *  suppressed. Use this in React effect cleanups so StrictMode's
   *  double-mount doesn't leak a second persistent WS. */
  close() {
    this.closed = true;
    if (this.retryTimer) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
    this.listeners.clear();
    this.ws?.close();
    this.ws = null;
  }
}
