import { useCallback, useEffect, useRef, useState } from "react";
import { ReasoningRow } from "../../rail/Rail";
import SkillsPanel from "./SkillsPanel";

/**
 * Agent Dashboard — primary purpose: live monitoring of running
 * agents in this workspace. Foreground + background runs in one
 * view; per-run status, last-activity, tool-call count, and a kill
 * button. Polls `/api/runs/active` every couple of seconds; the
 * registry is in process memory on the daemon so the read is cheap.
 *
 * Each running row is expandable — click the row, the activity
 * strip, or the caret to inline a live per-step transcript. A
 * solo live run auto-expands. Finished runs linger briefly under
 * "Recently finished" so you can re-inspect without hunting the
 * rail. Reasoning events render as collapsible 💭 blocks (same
 * pattern as the rail).
 */

const RUNS_POLL_MS = 2000;
/** How long a completed run stays inspectable after leaving /active. */
const RECENT_FINISHED_TTL_S = 15 * 60;
const RECENT_FINISHED_MAX = 10;
const LIVE_RUN_STATUSES = new Set(["running", "planning", "merging"]);

type Tool = {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
};

type Rule = {
  id: string;
  trigger: string;
  action: string;
};

type PaletteRow = {
  name: string;
  aliases: string[];
  description: string;
  source: string;
  kind: string;
  scope?: string;
  default_tools: string[];
  tools: string[];
  overridden: boolean;
  tokens: number;
  clipped: string[];
  fits: boolean;
};

type PaletteCatalogItem = { name: string; description: string };

type PalettesPayload = {
  rung: { id: string; label: string; prompt_budget: number };
  commands: PaletteRow[];
  catalog: PaletteCatalogItem[];
};

type Provider = {
  id: string;
  label: string;
  category: string;
  default_model: string;
  chosen_model?: string | null;
  has_key?: boolean;
  models_fresh?: boolean;
};

type Run = {
  run_id: string;
  provider: string;
  model: string;
  input_excerpt: string;
  started_at: number;
  last_chunk_at: number;
  tool_count: number;
  status: string;
  /** Human-readable description of what the run is doing right
   *  now — trailing edge of the latest assistant text, or a
   *  "⚙ ToolName(...)" snapshot when a tool's mid-execution.
   *  Stays visible while long-running subprocesses (claude_code's
   *  Bash, viewer.sh build, etc.) are running so the dashboard
   *  doesn't look stalled. */
  activity?: string;
  current_tool?: string;
  /** Absolute path + folder name of the workspace this run belongs
   *  to. The dashboard is cross-workspace, so it labels/groups runs
   *  by workspace and resolves each transcript against the run's own
   *  workspace DB. */
  workspace?: string;
  workspace_name?: string;
  /** Thread that owns this run (rail thread id, or the pty thread for
   *  shell runs). Lets the workspace pill jump straight to the run's
   *  thread in its own workspace. */
  thread_id?: string | null;
  /** Set after the user clicks "background" — pure UX hint that
   *  this run is acknowledged-long-running. Asyncio task continues
   *  regardless. */
  is_background?: boolean;
  /** For fan-out workers: id of the parent run that planned + spawned
   *  them. Used by the dashboard to collapse the worker rows under
   *  the parent so 10 concurrent workers don't dominate the list. */
  parent_run_id?: string | null;
  /** Optional 1-based index within the parent's worker set, lifted
   *  out of the worker's `run-XXX-w<N>` id when present. Used to
   *  sort + display "w1 / w2 / …" under the parent. */
  worker_index?: number | null;
  /** Set on a fan-out parent record so the dashboard can render the
   *  "fan-out · N=4 · 3 of 4 running" badge even before child rows
   *  arrive. Absent on regular single-agent runs. */
  fanout_n?: number | null;
  workers_total?: number | null;
  workers_running?: number | null;
  /** Set in fanout.py's finally block — flips workers from "running"
   *  to "done" so the lingered row reads as completed. */
  finished_at?: number | null;
};

// The currently-focused workspace, read from the snapshot App.tsx
// persists on every workspace transition. The dashboard is
// cross-workspace, so it uses this only to flag runs that live in
// ANOTHER workspace ("steerable from here") — never to filter them out.
function readFocusedWorkspace(): string {
  try {
    const raw = window.localStorage.getItem("sy.workspaces.snapshot");
    if (!raw) return "";
    const parsed = JSON.parse(raw) as { workspace?: string };
    return typeof parsed.workspace === "string" ? parsed.workspace : "";
  } catch { return ""; }
}

function isLiveRun(r: Run): boolean {
  return !r.status || LIVE_RUN_STATUSES.has(r.status);
}

/** Solo top-level live agent run → auto-expand for inspectability. */
function soloAutoExpandId(runs: Run[]): string | null {
  const tops = runs.filter(
    (r) => isLiveRun(r) && r.provider !== "pty" && !r.parent_run_id,
  );
  return tops.length === 1 ? tops[0]!.run_id : null;
}

export default function AgentDashboardTab() {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [recentFinished, setRecentFinished] = useState<Run[]>([]);
  const prevRunsRef = useRef<Map<string, Run>>(new Map());
  const [focusedWs, setFocusedWs] = useState<string>(readFocusedWorkspace);
  const [tools, setTools] = useState<Tool[] | null>(null);
  const [rules, setRules] = useState<Rule[] | null>(null);
  const [palettes, setPalettes] = useState<PalettesPayload | null>(null);
  const [providers, setProviders] = useState<Provider[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Running-runs poll loop. We keep this separate from the static
  // panels' reloadAll so it ticks fast (every 2s) without re-fetching
  // the slower-moving panels. Errors are non-fatal — a transient 500
  // shouldn't blank the panel.
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await fetch("/api/runs/active");
        if (!r.ok) return;
        const body = (await r.json()) as { runs: Run[] };
        if (!cancelled) {
          const list = body.runs ?? [];
          // Detect runs that left the active registry → "Recently finished".
          const nextMap = new Map(list.map((x) => [x.run_id, x]));
          const departed: Run[] = [];
          for (const [id, prev] of prevRunsRef.current) {
            if (!nextMap.has(id) && prev.provider !== "pty") {
              departed.push({
                ...prev,
                status: "done",
                finished_at: Date.now() / 1000,
              });
            }
          }
          prevRunsRef.current = nextMap;
          if (departed.length > 0) {
            setRecentFinished((cur) => {
              const now = Date.now() / 1000;
              const merged = [
                ...departed,
                ...cur.filter((c) => !departed.some((d) => d.run_id === c.run_id)),
              ];
              return merged
                .filter((c) => now - (c.finished_at ?? c.last_chunk_at) < RECENT_FINISHED_TTL_S)
                .slice(0, RECENT_FINISHED_MAX);
            });
          } else {
            // Age out stale entries even when nothing departed.
            setRecentFinished((cur) => {
              const now = Date.now() / 1000;
              const next = cur.filter(
                (c) => now - (c.finished_at ?? c.last_chunk_at) < RECENT_FINISHED_TTL_S,
              );
              return next.length === cur.length ? cur : next;
            });
          }
          setRuns(list);
          // Cheap to re-read each tick; keeps the "other workspace"
          // flag correct right after a switch without extra wiring.
          setFocusedWs(readFocusedWorkspace());
        }
      } catch { /* swallow — try again next tick */ }
    };
    void tick();
    const id = window.setInterval(() => { void tick(); }, RUNS_POLL_MS);
    return () => { cancelled = true; window.clearInterval(id); };
  }, []);

  const reloadAll = useCallback(async () => {
    setError(null);
    try {
      const [t, r, pal, p] = await Promise.all([
        fetch("/api/tools").then((r) => r.json()),
        fetch("/api/agent_rules").then((r) => r.json()),
        fetch("/api/command_palettes").then((r) => r.json()),
        fetch("/api/llm/providers").then((r) => r.json()),
      ]);
      setTools(t.tools as Tool[]);
      setRules(r.rules as Rule[]);
      setPalettes(Array.isArray(pal?.commands) ? pal as PalettesPayload : null);
      setProviders(p.providers as Provider[]);
    } catch (e) { setError((e as Error).message); }
  }, []);

  useEffect(() => { void reloadAll(); }, [reloadAll]);

  const onCancelRun = useCallback(async (runId: string) => {
    if (!window.confirm(`Cancel run ${runId}?`)) return;
    await fetch(`/api/runs/${encodeURIComponent(runId)}/cancel`, {
      method: "POST",
    });
    // The poll loop will pick up the deregistration on its own.
  }, []);

  const onBackgroundRun = useCallback(async (runId: string) => {
    await fetch(`/api/runs/${encodeURIComponent(runId)}/background`, {
      method: "POST",
    });
    // Poll will pick up the is_background=true flag.
  }, []);

  // Rail's `↗` jump button asks us to auto-expand a specific run.
  // Held in state so RunRow can read it and decide whether to
  // start expanded; cleared after one consumption so a manual
  // collapse afterwards isn't undone on the next poll tick.
  const [pendingExpand, setPendingExpand] = useState<string | null>(null);
  useEffect(() => {
    const onExpand = (ev: Event) => {
      const detail = (ev as CustomEvent<{ run_id: string }>).detail;
      if (detail?.run_id) setPendingExpand(detail.run_id);
    };
    window.addEventListener("sy:expand-run", onExpand);
    return () => window.removeEventListener("sy:expand-run", onExpand);
  }, []);

  const onDeleteRule = useCallback(async (id: string) => {
    if (!window.confirm("Delete this rule?")) return;
    // No dedicated DELETE endpoint today — use the existing tool-call
    // path which the rail uses for everything else. POST /api/tool with
    // name=delete_rule wouldn't work (tools are MCP-bridged, not HTTP);
    // instead, hit the agent_rules module via a small POST endpoint.
    // For MVP: re-derive the list from the action since we already
    // have the underlying file API via `register_rule` etc. Until that
    // route lands, surface the path so the user can delete by hand.
    await fetch(`/api/agent_rules?id=${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
    await reloadAll();
  }, [reloadAll]);

  return (
    <div className="sy-agents">
      <div className="sy-agents-header">
        <h2>Agent Dashboard</h2>
        <button
          type="button"
          className="sy-vega-toolbar-btn"
          onClick={() => void reloadAll()}
          title="Refresh all panels"
        >
          Refresh
        </button>
      </div>
      {error && (
        <div className="sy-vega-banner sy-vega-banner--err">{error}</div>
      )}

      <Section
        title="Running"
        // Dormant shells (status "idle" — a pty at its prompt / a TUI
        // waiting for input) stay listed but don't count as running.
        count={runs?.filter((r) => isLiveRun(r)).length}
        primary
        subtitle="live · refreshes every 2s · click activity or ▸ for transcript"
      >
        {runs === null ? <Loading /> : runs.length === 0 ? (
          <Empty>
            No active runs. Type something in the rail to kick one off,
            or watch this panel while a long-running agent works.
          </Empty>
        ) : (
          <ul className="sy-agents-list">
            {groupRuns(runs).map((g) => (
              <RunGroup
                key={g.parent.run_id}
                parent={g.parent}
                workers={g.workers}
                onCancel={onCancelRun}
                onBackground={onBackgroundRun}
                forceOpenId={pendingExpand}
                onForceOpenAck={() => setPendingExpand(null)}
                autoExpandId={soloAutoExpandId(runs)}
                focusedWs={focusedWs}
              />
            ))}
          </ul>
        )}
      </Section>

      {recentFinished.length > 0 && (
        <Section
          title="Recently finished"
          count={recentFinished.length}
          subtitle="kept ~15 min for inspection"
        >
          <ul className="sy-agents-list">
            {recentFinished.map((r) => (
              <RunRow
                key={`done-${r.run_id}`}
                run={r}
                onCancel={() => { /* already done */ }}
                onBackground={() => { /* n/a */ }}
                focusedWs={focusedWs}
                finished
              />
            ))}
          </ul>
        </Section>
      )}

      <Section title="Tools" count={tools?.length}>
        {tools === null ? <Loading /> : tools.length === 0 ? (
          <Empty>No tools registered.</Empty>
        ) : (
          <ul className="sy-agents-list">
            {tools.map((t) => (
              <li key={t.name} className="sy-agents-row">
                <code className="sy-agents-name">{t.name}</code>
                <span className="sy-agents-desc">{t.description}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Rules" count={rules?.length}>
        {rules === null ? <Loading /> : rules.length === 0 ? (
          <Empty>
            No rules saved yet. Type <code>when I say X, do Y</code> in the
            rail or use <code>/rule "X" /view Y</code> to add one.
          </Empty>
        ) : (
          <ul className="sy-agents-list">
            {rules.map((r) => (
              <li key={r.id} className="sy-agents-row">
                <span className="sy-agents-rule">
                  <em>“{r.trigger}”</em>
                  <span className="sy-agents-arrow">→</span>
                  <code>{r.action}</code>
                </span>
                <button
                  type="button"
                  className="sy-agents-row-btn"
                  onClick={() => void onDeleteRule(r.id)}
                  title="Delete this rule"
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section
        title="Command palettes"
        count={palettes?.commands.length}
        subtitle={
          palettes
            ? `${palettes.rung.label} · ${palettes.rung.prompt_budget} tok budget`
            : "local model desks"
        }
      >
        {palettes === null ? <Loading /> : palettes.commands.length === 0 ? (
          <Empty>
            No command palettes yet. Shipped slashes like <code>/curate</code>{" "}
            and <code>/create-deck</code> get a tight tool desk automatically.
          </Empty>
        ) : (
          <PaletteList
            payload={palettes}
            onChange={(next) => setPalettes(next)}
          />
        )}
      </Section>

      <Section title="Providers" count={providers?.length}>
        {providers === null ? <Loading /> : providers.length === 0 ? (
          <Empty>No providers configured.</Empty>
        ) : (
          <ul className="sy-agents-list">
            {providers.map((p) => (
              <li key={p.id} className="sy-agents-row">
                <span className="sy-agents-provider">
                  <strong>{p.label}</strong>
                  <span className="sy-agents-cat">{p.category}</span>
                </span>
                <span className="sy-agents-meta">
                  model: <code>{p.chosen_model || p.default_model}</code>
                </span>
                <span
                  className={
                    "sy-agents-status " +
                    (p.has_key ? "sy-agents-status--ok" : "sy-agents-status--off")
                  }
                  title={p.has_key ? "Authenticated" : "No key / not authenticated"}
                >
                  {p.has_key ? "ready" : "not configured"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Skills" subtitle="author + iterate your own">
        <SkillsPanel />
      </Section>
    </div>
  );
}


function toolGroup(name: string): string {
  if (
    name.startsWith("ce_") ||
    name.startsWith("wiki") ||
    name.startsWith("propose_") ||
    name === "search_wiki" ||
    name === "read_wiki_page" ||
    name === "list_wiki_pages"
  ) {
    return "Wiki / CE";
  }
  if (
    name.includes("slide") ||
    name.includes("analysis") ||
    name.startsWith("sketch")
  ) {
    return "Deck / sketch";
  }
  if (name.startsWith("plot") || name === "save_plot") return "Plot";
  if (
    name.startsWith("sheet") ||
    name.startsWith("table") ||
    name.includes("duckdb")
  ) {
    return "Sheet / table";
  }
  return "Other";
}


function PaletteList({
  payload,
  onChange,
}: {
  payload: PalettesPayload;
  onChange: (next: PalettesPayload) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);

  const apply = useCallback(async (res: Response) => {
    if (!res.ok) return;
    const body = (await res.json()) as PalettesPayload;
    onChange(body);
  }, [onChange]);

  const save = useCallback(async (name: string, tools: string[]) => {
    const res = await fetch("/api/command_palettes", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command: name, tools }),
    });
    await apply(res);
  }, [apply]);

  const reset = useCallback(async (name: string) => {
    const res = await fetch(
      `/api/command_palettes?command=${encodeURIComponent(name)}`,
      { method: "DELETE" },
    );
    await apply(res);
  }, [apply]);

  return (
    <ul className="sy-agents-list">
      {payload.commands.map((row) => (
        <PaletteEditor
          key={row.name}
          row={row}
          catalog={payload.catalog}
          open={open === row.name}
          onToggle={() => setOpen((cur) => (cur === row.name ? null : row.name))}
          onSave={save}
          onReset={reset}
        />
      ))}
    </ul>
  );
}


function PaletteEditor({
  row,
  catalog,
  open,
  onToggle,
  onSave,
  onReset,
}: {
  row: PaletteRow;
  catalog: PaletteCatalogItem[];
  open: boolean;
  onToggle: () => void;
  onSave: (name: string, tools: string[]) => Promise<void>;
  onReset: (name: string) => Promise<void>;
}) {
  const [draft, setDraft] = useState<string[]>(row.tools);
  const [pick, setPick] = useState("");
  useEffect(() => { setDraft(row.tools); }, [row.tools]);

  const available = catalog.filter((t) => !draft.includes(t.name));
  const groups = new Map<string, PaletteCatalogItem[]>();
  for (const t of available) {
    const g = toolGroup(t.name);
    const list = groups.get(g) ?? [];
    list.push(t);
    groups.set(g, list);
  }
  const dirty =
    draft.length !== row.tools.length ||
    draft.some((n, i) => n !== row.tools[i]);

  return (
    <li className={"sy-agents-palette" + (open ? " sy-agents-palette--open" : "")}>
      <div className="sy-agents-row sy-agents-palette-head">
        <button
          type="button"
          className="sy-agents-palette-toggle"
          onClick={onToggle}
          aria-expanded={open}
        >
          <code className="sy-agents-name">/{row.name}</code>
          {row.aliases.length > 0 && (
            <span className="sy-agents-cat">
              {row.aliases.map((a) => `/${a}`).join(" ")}
            </span>
          )}
          <span className="sy-agents-desc">{row.description}</span>
        </button>
        <span className="sy-agents-meta">
          {row.tools.length} tools · ~{row.tokens} tok
          {row.overridden ? " · override" : ` · ${row.source}`}
          {row.clipped.length > 0 ? ` · clipped ${row.clipped.length}` : ""}
        </span>
      </div>
      {open && (
        <div className="sy-agents-palette-edit">
          <div className="sy-agents-chips">
            {draft.map((name) => (
              <span key={name} className="sy-agents-chip">
                {name}
                <button
                  type="button"
                  className="sy-agents-chip-x"
                  onClick={() => setDraft((cur) => cur.filter((n) => n !== name))}
                  title={`Remove ${name}`}
                >
                  ×
                </button>
              </span>
            ))}
            {draft.length === 0 && (
              <span className="sy-agents-desc">No tools — run will use the default chat desk.</span>
            )}
          </div>
          <div className="sy-agents-palette-add">
            <select
              value={pick}
              onChange={(e) => setPick(e.target.value)}
              aria-label={`Add a tool to /${row.name}`}
            >
              <option value="">Add a tool…</option>
              {[...groups.entries()].map(([group, items]) => (
                <optgroup key={group} label={group}>
                  {items.map((t) => (
                    <option key={t.name} value={t.name} title={t.description}>
                      {t.name}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
            <button
              type="button"
              className="sy-vega-toolbar-btn"
              disabled={!pick}
              onClick={() => {
                if (!pick) return;
                setDraft((cur) => (cur.includes(pick) ? cur : [...cur, pick]));
                setPick("");
              }}
            >
              Add
            </button>
            <button
              type="button"
              className="sy-vega-toolbar-btn"
              disabled={!dirty}
              onClick={() => void onSave(row.name, draft)}
            >
              Save
            </button>
            {row.overridden && (
              <button
                type="button"
                className="sy-vega-toolbar-btn"
                onClick={() => void onReset(row.name)}
              >
                Reset
              </button>
            )}
          </div>
        </div>
      )}
    </li>
  );
}


function Section(props: {
  title: string;
  count?: number;
  children: React.ReactNode;
  primary?: boolean;
  subtitle?: string;
}) {
  return (
    <section
      className={"sy-agents-section" + (props.primary ? " sy-agents-section--primary" : "")}
    >
      <h3>
        {props.title}
        {typeof props.count === "number" && (
          <span className="sy-agents-count">{props.count}</span>
        )}
        {props.subtitle && (
          <span className="sy-agents-subtitle">{props.subtitle}</span>
        )}
      </h3>
      {props.children}
    </section>
  );
}


type RunEvent = {
  event_id: number;
  created_at: number;
  kind: string;
  source: string;
  actor: string | null;
  summary: string;
  payload: unknown;
  ref_id: string | null;
};

const TRANSCRIPT_POLL_MS = 2000;
const TRANSCRIPT_LIMIT = 200;


type RunGroup = { parent: Run; workers: Run[] };


/**
 * Re-shape the flat runs list into parent + worker groups so the
 * dashboard collapses fan-out children under their planner. Runs
 * without a `parent_run_id` are their own one-row groups. Workers
 * whose parent isn't in the active list get promoted to standalone
 * (rare — the parent finished but the worker didn't).
 */
function groupRuns(runs: Run[]): RunGroup[] {
  const byId = new Map(runs.map((r) => [r.run_id, r]));
  const workersByParent = new Map<string, Run[]>();
  const tops: Run[] = [];
  for (const r of runs) {
    const parentId = r.parent_run_id;
    if (parentId && byId.has(parentId)) {
      const arr = workersByParent.get(parentId) ?? [];
      arr.push(r);
      workersByParent.set(parentId, arr);
    } else {
      tops.push(r);
    }
  }
  return tops.map((parent) => ({
    parent,
    workers: (workersByParent.get(parent.run_id) ?? []).slice().sort(
      (a, b) => (a.worker_index ?? 0) - (b.worker_index ?? 0),
    ),
  }));
}


function RunGroup(props: {
  parent: Run;
  workers: Run[];
  onCancel: (id: string) => void;
  onBackground: (id: string) => void;
  forceOpenId?: string | null;
  onForceOpenAck?: () => void;
  /** When this matches parent (or a worker), auto-expand that row
   *  unless the user has manually collapsed it this session. */
  autoExpandId?: string | null;
  /** Currently-focused workspace path — rows in another workspace get
   *  a "↗ <name>" chip so the cross-workspace nature is visible. */
  focusedWs?: string;
}) {
  const {
    parent, workers, onCancel, onBackground,
    forceOpenId, onForceOpenAck, autoExpandId, focusedWs,
  } = props;
  const isFanout = typeof parent.fanout_n === "number" && parent.fanout_n > 1;
  const hasWorkers = workers.length > 0;
  // Default expanded for fan-out parents so the user can see what
  // each worker is doing — that's the whole point of dialling N up.
  // Single-agent runs that somehow grew a child row stay collapsed.
  const [showWorkers, setShowWorkers] = useState(isFanout);

  return (
    <li className="sy-agents-rungroup">
      <RunRow
        run={parent}
        onCancel={onCancel}
        onBackground={onBackground}
        forceOpen={forceOpenId === parent.run_id}
        onForceOpenAck={onForceOpenAck}
        autoExpand={autoExpandId === parent.run_id}
        focusedWs={focusedWs}
        workerCount={
          // For fan-out parents, surface the *declared* worker count
          // (workers_total) so the chip is informative even before
          // children register or after they retire — not just the
          // live `workers.length`.
          isFanout
            ? (parent.workers_total ?? workers.length)
            : (hasWorkers ? workers.length : undefined)
        }
        workersRunning={isFanout ? (parent.workers_running ?? 0) : undefined}
        workersExpanded={isFanout || hasWorkers ? showWorkers : undefined}
        onToggleWorkers={
          isFanout || hasWorkers ? () => setShowWorkers((v) => !v) : undefined
        }
      />
      {hasWorkers && showWorkers && (
        <ul className="sy-agents-list sy-agents-list--workers">
          {workers.map((w) => (
            <RunRow
              key={w.run_id}
              run={w}
              onCancel={onCancel}
              onBackground={onBackground}
              forceOpen={forceOpenId === w.run_id}
              onForceOpenAck={onForceOpenAck}
              autoExpand={autoExpandId === w.run_id}
              focusedWs={focusedWs}
              indented
            />
          ))}
        </ul>
      )}
    </li>
  );
}


function RunRow(props: {
  run: Run;
  onCancel: (id: string) => void;
  onBackground: (id: string) => void;
  forceOpen?: boolean;
  onForceOpenAck?: () => void;
  /** Solo live run — expand unless user collapsed this id. */
  autoExpand?: boolean;
  /** When set, paint a chevron on the row that toggles a child
   *  list of fan-out workers in the parent RunGroup. */
  workerCount?: number;
  /** Number of workers currently mid-run (vs lingered as done). When
   *  defined and < workerCount, the chip reads "3 of 4 running". */
  workersRunning?: number;
  workersExpanded?: boolean;
  onToggleWorkers?: () => void;
  /** Visually indent + de-emphasise — used by RunGroup to render
   *  workers nested beneath their parent row. */
  indented?: boolean;
  /** Currently-focused workspace — used to flag a run that lives in a
   *  different workspace (the cross-workspace case). */
  focusedWs?: string;
  /** Row from "Recently finished" — no kill/bg, transcript not live. */
  finished?: boolean;
}) {
  const {
    run, onCancel, onBackground, forceOpen, onForceOpenAck, autoExpand,
    workerCount, workersRunning, workersExpanded, onToggleWorkers, indented,
    focusedWs, finished,
  } = props;
  // Cross-workspace flag: this run belongs to a workspace other than the
  // one currently focused. We never hide it (the dashboard is global) —
  // we just label it so the user knows where its work is landing.
  const otherWs = !!run.workspace && !!focusedWs && run.workspace !== focusedWs;
  const [expanded, setExpanded] = useState(false);
  // Once the user manually collapses, don't re-auto-expand on poll.
  const userCollapsedRef = useRef(false);

  const setExpandedUser = useCallback((next: boolean | ((v: boolean) => boolean)) => {
    setExpanded((cur) => {
      const v = typeof next === "function" ? next(cur) : next;
      if (!v) userCollapsedRef.current = true;
      if (v) userCollapsedRef.current = false;
      return v;
    });
  }, []);

  // Honour the rail's `↗` jump request: if the parent says to
  // open this row, set expanded=true once and then clear the
  // signal so a subsequent manual collapse stays collapsed.
  useEffect(() => {
    if (forceOpen) {
      userCollapsedRef.current = false;
      setExpanded(true);
      onForceOpenAck?.();
    }
  }, [forceOpen, onForceOpenAck]);

  // C1: solo live run auto-expands for inspection.
  useEffect(() => {
    if (autoExpand && !userCollapsedRef.current) {
      setExpanded(true);
    }
  }, [autoExpand, run.run_id]);

  const elapsed = humanElapsed(Date.now() / 1000 - run.started_at);
  const stale = !finished && Date.now() / 1000 - run.last_chunk_at > 8;
  const activity = run.activity?.trim() || "";
  const activityLong = activity.length > 160 || activity.includes("\n");

  return (
    <li
      className={
        "sy-agents-run-wrap"
        + (run.is_background ? " sy-agents-run-wrap--bg" : "")
        + (indented ? " sy-agents-run-wrap--worker" : "")
        + (finished ? " sy-agents-run-wrap--finished" : "")
      }
    >
      <div
        className="sy-agents-row sy-agents-run"
        role="button"
        tabIndex={0}
        onClick={() => setExpandedUser((v) => !v)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setExpandedUser((v) => !v);
          }
        }}
        title={expanded ? "Collapse transcript" : "Expand transcript"}
        aria-expanded={expanded}
      >
        <span
          className="sy-agents-run-caret"
          data-expanded={expanded}
          aria-hidden="true"
        >▸</span>
        <span
          className="sy-agents-run-dot"
          data-stale={stale}
          data-finished={finished ? "true" : undefined}
          title={finished ? "finished" : stale ? "no recent activity" : "active"}
        />
        <code className="sy-agents-name">{run.run_id}</code>
        <span className="sy-agents-run-meta">
          <code>{run.provider}</code>
          <span className="sy-agents-arrow">·</span>
          <code>{run.model}</code>
          <span className="sy-agents-arrow">·</span>
          <span title="elapsed">{elapsed}</span>
          <span className="sy-agents-arrow">·</span>
          <span title="tools called this run">{run.tool_count} tool{run.tool_count === 1 ? "" : "s"}</span>
          {finished && (
            <>
              <span className="sy-agents-arrow">·</span>
              <span className="sy-agents-run-done-tag">done</span>
            </>
          )}
          {run.workspace_name && (
            <>
              <span className="sy-agents-arrow">·</span>
              <button
                type="button"
                className={"sy-agents-run-ws" + (otherWs ? " sy-agents-run-ws--other" : "")}
                title={
                  otherWs
                    ? `Jump to this run in workspace ${run.workspace}`
                    : run.thread_id
                    ? `Open this run's thread (workspace ${run.workspace})`
                    : `workspace ${run.workspace}`
                }
                onClick={(e) => {
                  e.stopPropagation();
                  // Jump to the run's own workspace + thread. App owns
                  // the workspace-switch machinery (`/api/workspaces/
                  // switch` + thread focus); the dashboard is a bare
                  // tab with no props, so it asks via a window event.
                  window.dispatchEvent(new CustomEvent("sy:jump-workspace-run", {
                    detail: {
                      workspace: run.workspace,
                      thread_id: run.thread_id ?? null,
                      provider: run.provider,
                    },
                  }));
                }}
              >
                {otherWs ? "↗ " : ""}{run.workspace_name}
              </button>
            </>
          )}
        </span>
        <span className="sy-agents-run-input" title={run.input_excerpt}>
          “{run.input_excerpt}”
        </span>
        {typeof workerCount === "number" && workerCount > 0 && (
          <button
            type="button"
            className={
              "sy-agents-run-workerchip"
              + (typeof workersRunning === "number" && workersRunning > 0
                ? " sy-agents-run-workerchip--live"
                : "")
            }
            onClick={(e) => { e.stopPropagation(); onToggleWorkers?.(); }}
            title={
              workersExpanded
                ? "Hide fan-out workers"
                : `Show ${workerCount} fan-out worker${workerCount === 1 ? "" : "s"}`
            }
            aria-expanded={workersExpanded}
          >
            {workersExpanded ? "▾" : "▸"} fan-out{" "}
            {typeof workersRunning === "number"
              ? `· ${workersRunning} of ${workerCount} running`
              : `· ${workerCount}`}
          </button>
        )}
        <span className="sy-agents-run-actions">
          {!finished && !run.is_background && (
            <button
              type="button"
              className="sy-agents-row-btn sy-agents-bg"
              onClick={(e) => { e.stopPropagation(); onBackground(run.run_id); }}
              title="Push to background — keeps running if you close the tab; we'll surface results when ready."
            >
              bg
            </button>
          )}
          {!finished && run.is_background && (
            <span className="sy-agents-bg-tag" title="Backgrounded — will keep running across tab closes">
              bg
            </span>
          )}
          {!finished && (
            <button
              type="button"
              className="sy-agents-row-btn sy-agents-cancel"
              onClick={(e) => { e.stopPropagation(); onCancel(run.run_id); }}
              title="Cancel this run"
            >
              kill
            </button>
          )}
        </span>
      </div>
      {activity && (
        <button
          type="button"
          className={
            "sy-agents-run-activity"
            + (expanded ? " sy-agents-run-activity--open" : "")
            + (activityLong && !expanded ? " sy-agents-run-activity--clamped" : "")
          }
          onClick={(e) => {
            e.stopPropagation();
            setExpandedUser((v) => !v);
          }}
          title={
            expanded
              ? "Collapse transcript"
              : "Click to inspect full activity + transcript"
          }
        >
          <span className="sy-agents-run-activity-body">{activity}</span>
          {activityLong && !expanded && (
            <span className="sy-agents-run-activity-more">Show full activity ▾</span>
          )}
          {expanded && (
            <span className="sy-agents-run-activity-more">Hide transcript ▴</span>
          )}
        </button>
      )}
      {expanded && (
        <RunTranscript
          runId={run.run_id}
          live={!finished && isLiveRun(run)}
          isPty={run.provider === "pty"}
        />
      )}
    </li>
  );
}


/** Per-step transcript for one run. Polls /api/rail/events?run_id=
 *  while `live` is true (i.e. the run is still in the active list).
 *  When the run completes the parent unmounts this whole row, so we
 *  don't need to detect transition-to-done ourselves. Exported —
 *  the bottom DashboardPanel's expandable rows reuse it. */
export function RunTranscript(
  { runId, live, isPty = false }:
  { runId: string; live: boolean; isPty?: boolean },
) {
  const [events, setEvents] = useState<RunEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await fetch(
          `/api/rail/events?run_id=${encodeURIComponent(runId)}&limit=${TRANSCRIPT_LIMIT}`,
        );
        if (!r.ok) {
          if (!cancelled) setError(`HTTP ${r.status}`);
          return;
        }
        const body = (await r.json()) as { events: RunEvent[] };
        if (!cancelled) {
          setEvents(body.events);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      }
    };
    void tick();
    if (!live) return () => { cancelled = true; };
    const id = window.setInterval(() => { void tick(); }, TRANSCRIPT_POLL_MS);
    return () => { cancelled = true; window.clearInterval(id); };
  }, [runId, live]);

  if (events === null) {
    return <div className="sy-agents-transcript sy-agents-transcript--loading">Loading transcript…</div>;
  }
  if (error && events.length === 0) {
    return <div className="sy-agents-transcript sy-agents-transcript--err">{error}</div>;
  }
  if (events.length === 0) {
    // Shell (interactive-pty) runs stream their output to the rail's
    // xterm surface, not the rail event log — so this transcript is
    // always empty for them. Say where the output actually is instead
    // of "Waiting for the first chunk…" (which never arrives).
    return (
      <div className="sy-agents-transcript sy-agents-transcript--empty">
        {isPty
          ? "Shell output appears in the rail terminal, not here."
          : "Waiting for the first chunk…"}
      </div>
    );
  }
  return (
    <div className="sy-agents-transcript">
      {events.map((ev) => <TranscriptEvent key={ev.event_id} ev={ev} />)}
    </div>
  );
}


function reasoningText(ev: RunEvent): string {
  const p = ev.payload;
  if (p && typeof p === "object" && "text" in p) {
    const t = (p as { text?: unknown }).text;
    if (typeof t === "string" && t.trim()) return t;
  }
  return ev.summary || "";
}

function TranscriptEvent({ ev }: { ev: RunEvent }) {
  const cls = `sy-agents-tx sy-agents-tx--${ev.kind.replace(/_/g, "-")}`;
  if (ev.kind === "user") {
    return <div className={cls}><span className="sy-agents-tx-tag">user</span> {ev.summary}</div>;
  }
  if (ev.kind === "assistant") {
    return <div className={cls}><span className="sy-agents-tx-tag">assistant</span> {ev.summary}</div>;
  }
  if (ev.kind === "reasoning") {
    // Full chain-of-thought lives in payload.text (summary is truncated
    // for the rail index). Same collapsible pattern as the Power rail.
    const text = reasoningText(ev);
    if (!text.trim()) return null;
    return (
      <div className={cls + " sy-agents-tx--reasoning-wrap"}>
        <ReasoningRow text={text} />
      </div>
    );
  }
  if (ev.kind === "tool_use") {
    const name = (ev.actor || "").trim();
    const summary = (ev.summary || "").trim();
    // Grok used to emit nameless tool_call events; don't render empty TOOL ().
    if (!name && (!summary || summary === "()")) return null;
    return (
      <div className={cls}>
        <span className="sy-agents-tx-tag sy-agents-tx-tag--tool">tool</span>
        <code>{name || "tool"}</code>
        {summary && summary !== "()" && (
          <span className="sy-agents-tx-summary">{summary}</span>
        )}
      </div>
    );
  }
  if (ev.kind === "tool_result") {
    const ok = isOkResult(ev.payload);
    return (
      <div className={cls} data-ok={ok}>
        <span className="sy-agents-tx-tag sy-agents-tx-tag--result">{ok ? "✓" : "✗"}</span>
        <code>{ev.actor ?? "?"}</code>
        <span className="sy-agents-tx-summary">{ev.summary}</span>
      </div>
    );
  }
  return (
    <div className={cls}>
      <span className="sy-agents-tx-tag">{ev.kind}</span> {ev.summary}
    </div>
  );
}


function isOkResult(payload: unknown): boolean {
  if (payload && typeof payload === "object" && "ok" in payload) {
    return Boolean((payload as { ok: unknown }).ok);
  }
  return true;  // assume ok if shape doesn't carry an explicit flag
}


function humanElapsed(secs: number): string {
  if (secs < 1) return "<1s";
  if (secs < 60) return `${Math.round(secs)}s`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ${Math.round(secs % 60)}s`;
  return `${Math.floor(secs / 3600)}h ${Math.floor((secs % 3600) / 60)}m`;
}

function Loading() {
  return <div className="sy-agents-loading">Loading…</div>;
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="sy-agents-empty">{children}</div>;
}
