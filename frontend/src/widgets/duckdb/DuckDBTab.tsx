import { useCallback, useEffect, useRef, useState } from "react";
import type * as duckdb from "@duckdb/duckdb-wasm";
import { getDB, registerWorkspaceFile, rewriteRawPathsInSql } from "./duckdb-init";
import { dataKind, seed, type WorkspaceStats } from "./seed";
import { useSelection } from "../../selection/SelectionContext";
import { useEscToClose } from "../../lib/useEscToClose";
import { useTabs } from "../../center/TabsContext";
import { ackUiCommand, takeSql } from "../../lib/pendingUiCommands";
import { jsonSafe, jsonSafeStringify } from "../../lib/jsonSafe";

type Starter = { label: string; sql: string };

type RunState =
  | { kind: "idle" }
  | { kind: "running" }
  | { kind: "ok"; cols: string[]; rows: unknown[][]; ms: number; truncated: boolean }
  | { kind: "error"; message: string };

const ROW_CAP = 500;

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

function fmtRel(epoch_s: number): string {
  const ms = Date.now() - epoch_s * 1000;
  const s = ms / 1000;
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

function typeColor(type: string): string {
  // Map matches CE's type palette in ce-graph.css.
  const m: Record<string, string> = {
    analysis: "var(--type-analysis)",
    concept: "var(--type-concept)",
    entity: "var(--type-entity)",
    evidence: "var(--type-evidence)",
    fact: "var(--type-fact)",
    figure: "var(--type-figure)",
    table: "var(--type-table)",
    source: "var(--type-source)",
    note: "var(--type-note)",
    todo: "var(--type-todo)",
    "todo-list": "var(--type-todo-list)",
    project: "var(--type-project)",
    unclassified: "var(--type-unclassified)",
  };
  return m[type] ?? "var(--type-default)";
}


/** Human-friendly plural label for each canonical type. Mirrors the
 *  Browser sidebar's TYPE_LABEL so the Table tab's PAGES bar reads
 *  the same as the BROWSER section. */
function typeLabel(type: string): string {
  const m: Record<string, string> = {
    project: "Projects",
    concept: "Concepts",
    entity: "Entities",
    evidence: "Evidence",
    fact: "Facts",
    analysis: "Analyses",
    figure: "Figures",
    table: "Tables",
    source: "Sources",
    note: "Notes",
    todo: "Todos",
    "todo-list": "Todos",
    unclassified: "Unclassified",
  };
  return m[type] ?? type.charAt(0).toUpperCase() + type.slice(1);
}

export default function DuckDBTab() {
  const [stats, setStats] = useState<WorkspaceStats | null>(null);
  const [boot, setBoot] = useState<"loading" | "ready" | string>("loading");
  const [starters, setStarters] = useState<Starter[]>([]);
  const [query, setQuery] = useState("");
  const [run, setRun] = useState<RunState>({ kind: "idle" });
  const [editorOpen, setEditorOpen] = useState(false);
  const [currentDb, setCurrentDb] = useState<string | null>(null);
  const connRef = useRef<duckdb.AsyncDuckDBConnection | null>(null);
  const dbRef = useRef<duckdb.AsyncDuckDB | null>(null);
  const workspaceRef = useRef<string | null>(null);
  const { setSelection } = useSelection();
  const { switchToKind, tabs } = useTabs();
  const hasSheetTab = tabs.some((t) => t.kind === "univer");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch("/api/duckdb/starters");
        const body = (await r.json()) as { starters: Starter[] };
        if (cancelled) return;
        setStarters(body.starters);
        if (body.starters.length > 0) setQuery((q) => q || body.starters[0]!.sql);
      } catch {
        /* leave empty; user can add via Edit starters */
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    void fetch("/api/health")
      .then((r) => (r.ok ? r.json() : null))
      .then((h: { workspace?: string } | null) => {
        if (h?.workspace) workspaceRef.current = h.workspace;
      })
      .catch(() => { /* rewrite still handles /api/fs/raw + relative */ });
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { db, conn } = await getDB();
        if (cancelled) return;
        connRef.current = conn;
        dbRef.current = db;
        const s = await seed(db, conn);
        if (cancelled) return;
        setStats(s);
        setBoot("ready");
      } catch (e) {
        if (!cancelled) setBoot((e as Error).message);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const saveStarters = async (next: Starter[]) => {
    const r = await fetch("/api/duckdb/starters", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ starters: next }),
    });
    if (r.ok) {
      const body = (await r.json()) as { starters: Starter[] };
      setStarters(body.starters);
    }
  };

  // Rail dispatches `sy:sql-run` when the user types `!sql <…>`
  // (or agent table_run_sql). Stash if WASM isn't ready; drain on boot.
  // Agent wait_ack carries command_id → ACK after run completes.
  const pendingRunRef = useRef(false);
  const pendingAckIdRef = useRef<string | null>(null);
  useEffect(() => {
    const onRun = (ev: Event) => {
      const detail = (ev as CustomEvent<{ query?: string; command_id?: string }>).detail;
      const q = (detail?.query ?? "").trim();
      if (!q) return;
      setQuery(q);
      pendingAckIdRef.current = detail?.command_id || null;
      pendingRunRef.current = true;
    };
    window.addEventListener("sy:sql-run", onRun);
    return () => window.removeEventListener("sy:sql-run", onRun);
  }, []);

  // Cold mount: App stashed the SQL before this tab existed.
  useEffect(() => {
    const stashed = takeSql();
    if (!stashed?.query) return;
    setQuery(stashed.query);
    pendingAckIdRef.current = stashed.command_id || null;
    pendingRunRef.current = true;
  }, []);

  const finishSqlAck = useCallback((
    ok: boolean,
    extra?: { error?: string; result?: unknown },
  ) => {
    const cid = pendingAckIdRef.current;
    pendingAckIdRef.current = null;
    if (!cid) return;
    void ackUiCommand({
      command_id: cid,
      ok,
      surface: "table",
      applied: ok,
      error: extra?.error,
      result: extra?.result,
    });
  }, []);

  const runQuery = useCallback(async () => {
    setRun({ kind: "running" });
    const t0 = performance.now();
    if (currentDb) {
      // Route to the daemon's stock sqlite3 (handles vec0 / fts5 /
      // R*Tree DBs DuckDB-WASM can't ATTACH).
      try {
        const r = await fetch("/api/db/query", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: currentDb, sql: query }),
        });
        const body = await r.json() as { columns?: string[]; rows?: unknown[][]; truncated?: boolean; error?: string };
        if (!r.ok) {
          const message = body.error ?? `HTTP ${r.status}`;
          setRun({ kind: "error", message });
          finishSqlAck(false, { error: message });
          return;
        }
        const cols = body.columns ?? [];
        const rows = body.rows ?? [];
        const ms = Math.round(performance.now() - t0);
        setRun({
          kind: "ok",
          cols,
          rows,
          ms,
          truncated: !!body.truncated,
        });
        finishSqlAck(true, {
          result: { cols, row_count: rows.length, ms, truncated: !!body.truncated },
        });
      } catch (e) {
        const message = (e as Error).message;
        setRun({ kind: "error", message });
        finishSqlAck(false, { error: message });
      }
      return;
    }
    const c = connRef.current;
    if (!c) {
      // WASM still booting — re-queue so the boot-ready effect runs it.
      pendingRunRef.current = true;
      setRun({ kind: "idle" });
      return;
    }
    try {
      let rewritten = query;
      try {
        const db = dbRef.current ?? (await getDB()).db;
        rewritten = await rewriteRawPathsInSql(db, query, workspaceRef.current);
      } catch (regErr) {
        const message = (regErr as Error).message;
        setRun({ kind: "error", message });
        finishSqlAck(false, { error: message });
        return;
      }
      const res = await c.query(rewritten);
      const cols = res.schema.fields.map((f) => f.name);
      const arr = res.toArray();
      const truncated = arr.length > ROW_CAP;
      const sliced = truncated ? arr.slice(0, ROW_CAP) : arr;
      const rows: unknown[][] = sliced.map((r) =>
        cols.map((c) => jsonSafe((r as Record<string, unknown>)[c])),
      );
      const ms = Math.round(performance.now() - t0);
      setRun({ kind: "ok", cols, rows, ms, truncated });
      finishSqlAck(true, {
        result: { cols, row_count: rows.length, ms, truncated },
      });
    } catch (e) {
      const message = (e as Error).message;
      setRun({ kind: "error", message });
      finishSqlAck(false, { error: message });
    }
  }, [query, currentDb, finishSqlAck]);

  // When `!sql` came in via the rail bridge, run the freshly-set
  // query on the next render. Also drain once DuckDB is ready.
  useEffect(() => {
    if (!pendingRunRef.current) return;
    if (boot !== "ready" && !currentDb) return;
    pendingRunRef.current = false;
    if (query.trim()) void runQuery();
  }, [query, runQuery, boot, currentDb]);

  // Publish SQL editor focus + last result preview for the rail agent
  // (table_context / table_run_sql).
  const lastFocusSerialRef = useRef("");
  useEffect(() => {
    if (boot !== "ready") return;
    const payload: Record<string, unknown> = {
      surface: "table",
      sql: query,
      query,
    };
    if (run.kind === "ok") {
      payload.result = {
        cols: run.cols,
        row_count: run.rows.length,
        truncated: run.truncated,
        ms: run.ms,
        // Compact preview — first 12 rows × 8 cols.
        preview: run.rows.slice(0, 12).map((r) =>
          (Array.isArray(r) ? r : []).slice(0, 8).map((c) => {
            if (c == null) return null;
            const safe = jsonSafe(c);
            const s = String(safe);
            return s.length > 80 ? s.slice(0, 79) + "…" : safe;
          }),
        ),
      };
    } else if (run.kind === "error") {
      payload.result = { error: run.message };
    }
    const serialised = jsonSafeStringify(payload);
    if (serialised === lastFocusSerialRef.current) return;
    lastFocusSerialRef.current = serialised;
    void fetch("/api/ui/focus", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: serialised,
    }).catch(() => { /* ignore */ });
  }, [boot, query, run]);

  return (
    <div className="sy-duckdb">
      {boot === "loading" && (
        <div className="sy-duckdb-banner">Loading DuckDB-WASM…</div>
      )}
      {boot !== "loading" && boot !== "ready" && (
        <div className="sy-duckdb-banner sy-duckdb-banner--err">
          DuckDB failed to initialise: {boot}
        </div>
      )}

      {stats && (
        <section className="sy-duckdb-stats">
          <StatCard title="Files" subtitle={`${stats.fileCount.toLocaleString()} files · ${fmtBytes(stats.totalBytes)}`}>
            <BarList
              items={stats.byExt.slice(0, 8).map((e) => ({
                label: `.${e.ext || "(none)"}`,
                value: e.count,
                hint: fmtBytes(e.bytes),
                color: "var(--accent)",
              }))}
            />
          </StatCard>

          <StatCard title="Pages" subtitle={`${stats.pageCount.toLocaleString()} wiki pages`}>
            {stats.byType.length === 0 ? (
              <div className="sy-duckdb-empty">no wiki pages</div>
            ) : (
              <BarList
                items={stats.byType.map((t) => ({
                  label: typeLabel(t.type),
                  value: t.count,
                  color: typeColor(t.type),
                }))}
              />
            )}
          </StatCard>

          <StatCard title="Recent" subtitle="last 10 modified">
            <ul className="sy-duckdb-recent">
              {stats.recent.map((f) => (
                <li key={f.path}>
                  <span className="sy-duckdb-recent-path" title={f.path}>{f.path}</span>
                  <span className="sy-duckdb-recent-time">{fmtRel(f.mtime)}</span>
                </li>
              ))}
            </ul>
          </StatCard>

          <StatCard
            title="Data"
            subtitle={
              stats.data.length === 0
                ? "no data files"
                : `${stats.data.length} file${stats.data.length === 1 ? "" : "s"} · csv / parquet / json / db`
            }
          >
            {stats.data.length === 0 ? (
              <div className="sy-duckdb-empty">
                Drop CSV / Parquet / JSON / SQLite files into the workspace and they'll
                show up here. Click one to prefill a starter query that reads it via
                <code> read_csv_auto / read_parquet / ATTACH</code>.
              </div>
            ) : (
              <DataList
                files={stats.data}
                conn={connRef.current}
                db={dbRef.current}
                onPick={setQuery}
                hasSheetTab={hasSheetTab}
                onOpenInSheet={(path) => {
                  setSelection({ kind: "csv", path });
                  switchToKind("univer");
                }}
                onSetCurrentDb={setCurrentDb}
              />
            )}
          </StatCard>
        </section>
      )}

      <section className="sy-duckdb-sql">
        <div className="sy-duckdb-sql-head">
          <span className="sy-duckdb-sql-title">SQL</span>
          {currentDb && (
            <span className="sy-duckdb-route" title={`Routing queries to /api/db/query against ${currentDb}`}>
              via daemon · {currentDb.split("/").pop()}
              <button
                type="button"
                className="sy-duckdb-route-clear"
                onClick={() => setCurrentDb(null)}
                title="Switch back to in-browser DuckDB-WASM"
              >
                ✕
              </button>
            </span>
          )}
          <span className="sy-duckdb-sql-spacer" />
          {starters.map((q) => (
            <button
              key={q.label}
              type="button"
              className="sy-duckdb-pill"
              onClick={() => setQuery(q.sql)}
              title={q.sql}
            >
              {q.label}
            </button>
          ))}
          <button
            type="button"
            className="sy-duckdb-pill sy-duckdb-pill--edit"
            onClick={() => setEditorOpen(true)}
            title="Add, edit, or remove starter pills (saved per workspace)"
          >
            ✎ Edit starters
          </button>
        </div>
        <textarea
          className="sy-duckdb-editor"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          spellCheck={false}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
              e.preventDefault();
              runQuery();
            }
          }}
        />
        <div className="sy-duckdb-sql-foot">
          <button
            type="button"
            className="sy-confirm-btn sy-confirm-btn--primary"
            onClick={runQuery}
            disabled={boot !== "ready" || run.kind === "running"}
          >
            {run.kind === "running" ? "Running…" : "Run (⌘↵)"}
          </button>
          {run.kind === "ok" && (
            <span className="sy-duckdb-stat">
              {run.rows.length}{run.truncated ? `+ (capped at ${ROW_CAP})` : ""} rows · {run.ms} ms
            </span>
          )}
          {run.kind === "ok" && run.rows.length > 0 && hasSheetTab && (
            <button
              type="button"
              className="sy-confirm-btn"
              onClick={() => {
                // Hand the query result off to the Sheet tab as a
                // `table-data` selection — same shape the Editor's
                // per-table `↗ Sheet` buttons use. Headers go in
                // row 0; cell values are coerced to numbers when
                // they look numeric so formulas still work.
                const header: (string | number | null)[] = run.cols.slice();
                const body: (string | number | null)[][] = run.rows.map((r) =>
                  r.map((v) => {
                    const safe = jsonSafe(v);
                    if (safe === null || safe === undefined) return null;
                    if (typeof safe === "number" || typeof safe === "boolean") return Number(safe);
                    const s = String(safe);
                    return /^-?\d+(?:\.\d+)?$/.test(s) ? Number(s) : s;
                  }),
                );
                setSelection({
                  kind: "table-data",
                  origin: "duckdb-query",
                  values: [header, ...body],
                });
                switchToKind("univer");
              }}
              title="Send the current query result to the Sheet tab"
            >
              ↗ Sheet
            </button>
          )}
          {run.kind === "error" && (
            <span className="sy-duckdb-stat sy-duckdb-stat--err">{run.message}</span>
          )}
        </div>
        <ResultsTable run={run} />
      </section>
      {editorOpen && (
        <StartersEditor
          initial={starters}
          onCancel={() => setEditorOpen(false)}
          onSave={async (next) => {
            await saveStarters(next);
            setEditorOpen(false);
          }}
        />
      )}
    </div>
  );
}

function StartersEditor({
  initial, onCancel, onSave,
}: { initial: Starter[]; onCancel: () => void; onSave: (next: Starter[]) => void }) {
  useEscToClose(onCancel);
  const [draft, setDraft] = useState<Starter[]>(initial);

  const update = (i: number, patch: Partial<Starter>) =>
    setDraft((cur) => cur.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  const remove = (i: number) =>
    setDraft((cur) => cur.filter((_, j) => j !== i));
  const move = (i: number, dir: -1 | 1) =>
    setDraft((cur) => {
      const j = i + dir;
      if (j < 0 || j >= cur.length) return cur;
      const next = cur.slice();
      [next[i], next[j]] = [next[j]!, next[i]!];
      return next;
    });
  const add = () =>
    setDraft((cur) => [...cur, { label: "new starter", sql: "SELECT 1;" }]);

  return (
    <div className="sy-confirm-backdrop" onClick={onCancel}>
      <div
        className="sy-confirm sy-starters-dialog"
        role="dialog"
        aria-labelledby="sy-starters-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div id="sy-starters-title" className="sy-confirm-title">Edit starter pills</div>
        <div className="sy-confirm-body sy-starters-body">
          <p>
            Each row is one pill. Saved per workspace to
            <code> .workbench/state/duckdb-starters.json</code>.
          </p>
          {draft.length === 0 && <p className="sy-duckdb-empty">No starters. Click "+ Add" to create one.</p>}
          {draft.map((s, i) => (
            <div key={i} className="sy-starters-row">
              <div className="sy-starters-row-controls">
                <button type="button" className="sy-starters-mini" onClick={() => move(i, -1)} title="Move up">↑</button>
                <button type="button" className="sy-starters-mini" onClick={() => move(i, +1)} title="Move down">↓</button>
                <button type="button" className="sy-starters-mini sy-starters-mini--danger" onClick={() => remove(i)} title="Delete">✕</button>
              </div>
              <input
                className="sy-starters-label"
                placeholder="Pill label"
                value={s.label}
                onChange={(e) => update(i, { label: e.target.value })}
              />
              <textarea
                className="sy-starters-sql"
                rows={4}
                placeholder="SELECT … FROM files;"
                value={s.sql}
                spellCheck={false}
                onChange={(e) => update(i, { sql: e.target.value })}
              />
            </div>
          ))}
          <button type="button" className="sy-starters-add" onClick={add}>+ Add starter</button>
        </div>
        <div className="sy-confirm-actions">
          <button type="button" className="sy-confirm-btn" onClick={onCancel}>Cancel</button>
          <button
            type="button"
            className="sy-confirm-btn sy-confirm-btn--primary"
            onClick={() => onSave(draft)}
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

function StatCard({
  title, subtitle, children,
}: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <div className="sy-duckdb-card">
      <div className="sy-duckdb-card-head">
        <span className="sy-duckdb-card-title">{title}</span>
        <span className="sy-duckdb-card-sub">{subtitle}</span>
      </div>
      <div className="sy-duckdb-card-body">{children}</div>
    </div>
  );
}

function BarList({
  items,
}: { items: Array<{ label: string; value: number; hint?: string; color: string }> }) {
  const max = items.reduce((m, i) => Math.max(m, i.value), 0) || 1;
  return (
    <ul className="sy-duckdb-bars">
      {items.map((i) => (
        <li key={i.label}>
          <span className="sy-duckdb-bar-label" title={i.label}>{i.label}</span>
          <span className="sy-duckdb-bar-track">
            <span
              className="sy-duckdb-bar-fill"
              style={{ width: `${(i.value / max) * 100}%`, background: i.color }}
            />
          </span>
          <span className="sy-duckdb-bar-value">{i.value.toLocaleString()}</span>
          {i.hint && <span className="sy-duckdb-bar-hint">{i.hint}</span>}
        </li>
      ))}
    </ul>
  );
}

function ResultsTable({ run }: { run: RunState }) {
  if (run.kind !== "ok") return null;
  if (run.rows.length === 0) {
    return <div className="sy-duckdb-empty" style={{ padding: 16 }}>0 rows</div>;
  }
  return (
    <div className="sy-duckdb-results">
      <table>
        <thead>
          <tr>{run.cols.map((c) => <th key={c}>{c}</th>)}</tr>
        </thead>
        <tbody>
          {run.rows.map((r, i) => (
            <tr key={i}>
              {r.map((v, j) => <td key={j}>{formatCell(v)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function formatCell(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (v instanceof Date) return v.toISOString().replace("T", " ").slice(0, 19);
  const safe = jsonSafe(v);
  if (typeof safe === "object") {
    try { return jsonSafeStringify(safe); } catch { return String(safe); }
  }
  return String(safe);
}

/** Render the Data card: each row shows a data file with its size and
 *  a lazily-probed row/table count. Clicking a row prefills the SQL
 *  editor with a query that reads that file via /api/fs/raw. */
type Probe = { kind: "rows"; n: number } | { kind: "tables"; n: number } | { kind: "err"; msg: string } | { kind: "loading" };

type DbIntrospect = {
  tables: Array<{ name: string; type: string; rows: number | null; note?: string }>;
  note: string | null;
};

function formatIntrospect(path: string, body: DbIntrospect): string {
  const lines: string[] = [];
  lines.push(`-- ${path} · ${body.tables.length} table${body.tables.length === 1 ? "" : "s"}`);
  lines.push(`-- (introspected by the daemon's stock sqlite3 — DuckDB-WASM's`);
  lines.push(`--  sqlite extension can't ATTACH this file because some virtual`);
  lines.push(`--  tables need extensions it doesn't load.)`);
  if (body.note) lines.push(`-- note: ${body.note}`);
  lines.push("--");
  for (const t of body.tables) {
    const rows = t.rows == null ? "?" : t.rows.toLocaleString();
    const noteSuffix = t.note ? `  -- ${t.note.slice(0, 60)}` : "";
    lines.push(`--   ${t.name.padEnd(36)}  ${rows.padStart(10)}${noteSuffix}`);
  }
  lines.push("--");
  lines.push(`-- Run a query — it executes via the daemon (sqlite3), not the`);
  lines.push(`-- in-browser DuckDB. Use plain SQLite SQL.`);
  const first = body.tables.find((t) => t.rows != null);
  if (first) {
    lines.push(`SELECT * FROM "${first.name}" LIMIT 100;`);
  } else {
    lines.push(`SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;`);
  }
  return lines.join("\n");
}

function DataList({
  files, conn, db, onPick, hasSheetTab, onOpenInSheet, onSetCurrentDb,
}: {
  files: Array<{ path: string; size: number; ext: string; mtime: number }>;
  conn: duckdb.AsyncDuckDBConnection | null;
  db: duckdb.AsyncDuckDB | null;
  onPick: (sql: string) => void;
  hasSheetTab: boolean;
  onOpenInSheet: (path: string) => void;
  onSetCurrentDb: (path: string | null) => void;
}) {
  const [probes, setProbes] = useState<Map<string, Probe>>(new Map());
  const [busy, setBusy] = useState<string | null>(null);
  const shown = files.slice(0, 8);
  const pathsKey = shown.map((f) => f.path).join("\0");
  const probedRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (!conn) return;
    let cancelled = false;
    (async () => {
      for (const f of shown) {
        if (cancelled) return;
        if (probedRef.current.has(f.path)) continue;
        probedRef.current.add(f.path);
        setProbes((cur) => {
          if (cur.get(f.path)?.kind === "rows" || cur.get(f.path)?.kind === "tables") {
            return cur;
          }
          const next = new Map(cur);
          next.set(f.path, { kind: "loading" });
          return next;
        });
        const probe = await runProbe(conn, db, f.path, f.ext);
        if (cancelled) return;
        setProbes((cur) => {
          const next = new Map(cur);
          next.set(f.path, probe);
          return next;
        });
      }
    })();
    return () => { cancelled = true; };
    // pathsKey captures shown paths; don't reset on parent re-render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathsKey, conn, db]);

  const onClick = async (path: string, ext: string) => {
    const k = dataKind(ext);
    if (k === "csv" || k === "parquet" || k === "json") {
      onSetCurrentDb(null);
      if (!db) {
        const sql = starterSqlFor(path, ext);
        if (sql) onPick(sql);
        return;
      }
      try {
        const vfs = await registerWorkspaceFile(db, path);
        const sql = starterSqlForVfs(vfs, ext);
        if (sql) onPick(sql);
      } catch (e) {
        onPick(`-- failed to load ${path}\n-- ${(e as Error).message}`);
      }
      return;
    }
    if (k === "sqlite") {
      // SQLite files often use extensions DuckDB-WASM can't load
      // (sqlite-vec, FTS5, R*Tree, …) which crashes the WASM ATTACH's
      // catalog scan. Ask the daemon's stock `sqlite3` to enumerate
      // and route subsequent queries through /api/db/query.
      setBusy(path);
      try {
        const r = await fetch(`/api/db/introspect?path=${encodeURIComponent(path)}`);
        if (!r.ok) {
          const body = await r.json().catch(() => ({}));
          onSetCurrentDb(null);
          onPick(`-- introspect failed for ${path}\n-- ${(body as { error?: string }).error ?? `HTTP ${r.status}`}`);
          return;
        }
        const body = await r.json() as DbIntrospect;
        onSetCurrentDb(path);
        onPick(formatIntrospect(path, body));
      } finally {
        setBusy(null);
      }
      return;
    }
    if (k === "duckdb" && conn && db) {
      setBusy(path);
      const r = await attachDbFile(db, conn, path, k);
      setBusy(null);
      if ("error" in r) {
        onSetCurrentDb(null);
        onPick(
          `-- ATTACH failed for ${path}\n-- ${r.error}\n--\n-- Workarounds:\n-- · open the file with the duckdb CLI: \`duckdb ${path}\`\n-- · convert it to a Parquet first and load that, or\n-- · ask the agent to ingest the file into the workspace.`,
        );
        return;
      }
      const tableList = r.tables.length
        ? r.tables.map((t) => `${r.schema}.${t}`).join(", ")
        : "(none)";
      onSetCurrentDb(null);
      const sample = r.tables[0]
        ? `SELECT * FROM ${r.schema}.${r.tables[0]} LIMIT 100;`
        : `SHOW ALL TABLES;`;
      onPick(
        `-- Attached ${path} as schema '${r.schema}' (${r.tables.length} table${r.tables.length === 1 ? "" : "s"}).\n-- Tables: ${tableList}\n${sample}`,
      );
    }
  };

  return (
    <ul className="sy-duckdb-data">
      {shown.map((f) => {
        const p = probes.get(f.path);
        const name = f.path.split("/").pop() ?? f.path;
        const isBusy = busy === f.path;
        const k = dataKind(f.ext);
        const sheetable = k === "csv" || k === "parquet" || k === "json";
        return (
          <li key={f.path} className="sy-duckdb-data-li">
            <button
              type="button"
              className="sy-duckdb-data-row"
              onClick={() => onClick(f.path, f.ext)}
              disabled={isBusy || !conn}
              title={f.path}
            >
              <span className="sy-duckdb-data-name">{name}</span>
              <span className="sy-duckdb-data-ext">.{f.ext}</span>
              <span className="sy-duckdb-data-size">{fmtBytes(f.size)}</span>
              <span className="sy-duckdb-data-rows">
                {isBusy ? "attaching…" : formatProbe(p)}
              </span>
            </button>
            {hasSheetTab && sheetable && (
              <button
                type="button"
                className="sy-duckdb-data-sheet"
                onClick={() => onOpenInSheet(f.path)}
                title="Open this file in the Sheet tab (Univer)"
              >
                ↗
              </button>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function schemaForFile(path: string): string {
  const base = (path.split("/").pop() ?? path).replace(/\.[^.]+$/, "");
  const cleaned = base.toLowerCase().replace(/[^a-z0-9_]+/g, "_").replace(/^_+|_+$/g, "");
  return cleaned || "attached";
}

/** Pull the file from the daemon, register it in DuckDB-WASM's virtual
 *  filesystem, and ATTACH it. Returns the schema name + table list on
 *  success. SQLite needs the `sqlite` extension which DuckDB-WASM
 *  loads via INSTALL/LOAD; .duckdb files attach natively. */
async function attachDbFile(
  db: duckdb.AsyncDuckDB,
  conn: duckdb.AsyncDuckDBConnection,
  path: string,
  kind: "sqlite" | "duckdb",
): Promise<{ schema: string; tables: string[] } | { error: string }> {
  const schema = schemaForFile(path);
  const fileName = `attached_${schema}.${kind}`;
  try {
    const resp = await fetch(`/api/fs/raw?path=${encodeURIComponent(path)}`);
    if (!resp.ok) return { error: `fetch failed: HTTP ${resp.status}` };
    const buf = new Uint8Array(await resp.arrayBuffer());
    // Re-register cleanly even if a previous click registered a stale buffer.
    try { await db.dropFile(fileName); } catch { /* not registered yet */ }
    await db.registerFileBuffer(fileName, buf);
    if (kind === "sqlite") {
      try {
        await conn.query(`INSTALL sqlite;`);
        await conn.query(`LOAD sqlite;`);
      } catch (e) {
        return { error: `sqlite extension unavailable in DuckDB-WASM: ${(e as Error).message.slice(0, 120)}` };
      }
      try { await conn.query(`DETACH ${schema};`); } catch { /* not attached */ }
      await conn.query(`ATTACH '${fileName}' AS ${schema} (TYPE sqlite);`);
    } else {
      try { await conn.query(`DETACH ${schema};`); } catch { /* not attached */ }
      await conn.query(`ATTACH '${fileName}' AS ${schema};`);
    }
    const escapedSchema = schema.replace(/'/g, "''");

    // Belt-and-braces: confirm the catalog actually appeared. ATTACH
    // can succeed at the SQL layer but produce an empty catalog if
    // the underlying sqlite file is unreadable or the extension is
    // half-loaded.
    let attached = false;
    try {
      const dbsRes = await conn.query(`SELECT database_name FROM duckdb_databases();`);
      const dbs = dbsRes
        .toArray()
        .map((r) => String((r as Record<string, unknown>).database_name));
      attached = dbs.includes(schema);
    } catch {
      attached = true;  // duckdb_databases() not available — assume ok
    }
    if (!attached) {
      return { error: `ATTACH ran but ${schema} is not in duckdb_databases(); the sqlite extension may not be fully working in this WASM build.` };
    }

    // Tables in a sqlite-attached catalog are nested as
    // <catalog>.main.<table>; the bare <catalog>.sqlite_master form
    // resolves to memory.main.sqlite_master and DuckDB rightly errors
    // out (it does helpfully suggest the fix). Try the right form
    // first, then fall back.
    const queries = kind === "sqlite"
      ? [
          `SELECT name FROM ${schema}.main.sqlite_master WHERE type='table' ORDER BY name;`,
          `SELECT name FROM (SHOW ALL TABLES) WHERE database = '${escapedSchema}' ORDER BY name;`,
          `SELECT table_name AS name FROM information_schema.tables WHERE table_catalog = '${escapedSchema}' ORDER BY name;`,
        ]
      : [
          `SELECT name FROM (SHOW ALL TABLES) WHERE database = '${escapedSchema}' ORDER BY name;`,
          `SELECT table_name AS name FROM information_schema.tables WHERE table_catalog = '${escapedSchema}' ORDER BY name;`,
        ];

    let tables: string[] = [];
    let lastError: string | null = null;
    for (const q of queries) {
      try {
        const r = await conn.query(q);
        const got = r
          .toArray()
          .map((row) => String((row as Record<string, unknown>).name));
        if (got.length > 0) {
          tables = got;
          break;
        }
      } catch (e) {
        lastError = (e as Error).message;
      }
    }
    if (tables.length === 0 && lastError) {
      return { error: `attached, but couldn't list tables: ${lastError.slice(0, 160)}` };
    }
    return { schema, tables };
  } catch (e) {
    return { error: (e as Error).message };
  }
}

function formatProbe(p: Probe | undefined): string {
  if (!p) return "—";
  if (p.kind === "loading") return "…";
  if (p.kind === "rows") return `${p.n.toLocaleString()} rows`;
  if (p.kind === "tables") return `${p.n} tables`;
  return "?";
}

function readFnForKind(kind: ReturnType<typeof dataKind>): string | null {
  if (kind === "csv") return "read_csv_auto";
  if (kind === "parquet") return "read_parquet";
  if (kind === "json") return "read_json_auto";
  return null;
}

function starterSqlFor(path: string, ext: string): string | null {
  const fn = readFnForKind(dataKind(ext));
  if (!fn) return null;
  const url = `/api/fs/raw?path=${encodeURIComponent(path)}`;
  return `SELECT * FROM ${fn}('${url}') LIMIT 100;`;
}

function starterSqlForVfs(vfs: string, ext: string): string | null {
  const fn = readFnForKind(dataKind(ext));
  if (!fn) return null;
  return `SELECT * FROM ${fn}('${vfs.replace(/'/g, "''")}') LIMIT 100;`;
}

async function runProbe(
  conn: duckdb.AsyncDuckDBConnection,
  db: duckdb.AsyncDuckDB | null,
  path: string,
  ext: string,
): Promise<Probe> {
  const kind = dataKind(ext);
  const fn = readFnForKind(kind);
  if (!fn) {
    // sqlite / duckdb files: schema discovery happens on click via
    // attachDbFile. Show a hint until the user opts in.
    return { kind: "err", msg: "click to attach" };
  }
  if (!db) return { kind: "err", msg: "db not ready" };
  try {
    const vfs = await registerWorkspaceFile(db, path);
    const sql = `SELECT COUNT(*)::BIGINT AS n FROM ${fn}('${vfs.replace(/'/g, "''")}')`;
    const res = await conn.query(sql);
    const arr = res.toArray();
    const v = arr[0] as Record<string, unknown> | undefined;
    const raw = v?.n;
    const n = typeof raw === "bigint" ? Number(raw) : Number(raw ?? 0);
    return { kind: "rows", n };
  } catch (e) {
    return { kind: "err", msg: (e as Error).message.slice(0, 60) };
  }
}
