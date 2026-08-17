/**
 * DuckDB-WASM bootstrap. Selects the right bundle for this browser
 * (mvp / eh — exception-handling), spins up its Web Worker, and
 * returns an `AsyncDuckDBConnection`.
 *
 * Bundles are imported via Vite's `?url` so they're served from our
 * own origin — no third-party CDN, no MotherDuck phone-home, no
 * external network calls at any point.
 */

import * as duckdb from "@duckdb/duckdb-wasm";

import duckdb_mvp from "@duckdb/duckdb-wasm/dist/duckdb-mvp.wasm?url";
import mvp_worker from "@duckdb/duckdb-wasm/dist/duckdb-browser-mvp.worker.js?url";
import duckdb_eh from "@duckdb/duckdb-wasm/dist/duckdb-eh.wasm?url";
import eh_worker from "@duckdb/duckdb-wasm/dist/duckdb-browser-eh.worker.js?url";

const BUNDLES: duckdb.DuckDBBundles = {
  mvp: { mainModule: duckdb_mvp, mainWorker: mvp_worker },
  eh: { mainModule: duckdb_eh, mainWorker: eh_worker },
};

export type DBHandle = {
  db: duckdb.AsyncDuckDB;
  conn: duckdb.AsyncDuckDBConnection;
};

let _pending: Promise<DBHandle> | null = null;

export function getDB(): Promise<DBHandle> {
  if (!_pending) _pending = bootstrap();
  return _pending;
}

/** Stable DuckDB-WASM virtual-FS name for a workspace-relative path. */
export function vfsNameForPath(path: string): string {
  const cleaned = path.replace(/[^a-zA-Z0-9._-]+/g, "_").replace(/^_+|_+$/g, "");
  return `ws_${cleaned || "file"}`;
}

/**
 * Fetch a workspace file through the daemon and register it in
 * DuckDB-WASM's virtual FS. Relative `/api/fs/raw?path=…` strings
 * are treated as local files by `read_csv_auto` (the Sheet/Table
 * "no files match the pattern" error); a registered buffer is the
 * path that actually works in the browser.
 */
export async function registerWorkspaceFile(
  db: duckdb.AsyncDuckDB,
  path: string,
): Promise<string> {
  const name = vfsNameForPath(path);
  const resp = await fetch(`/api/fs/raw?path=${encodeURIComponent(path)}`);
  if (!resp.ok) throw new Error(`fetch failed: HTTP ${resp.status}`);
  const buf = new Uint8Array(await resp.arrayBuffer());
  try { await db.dropFile(name); } catch { /* first register */ }
  await db.registerFileBuffer(name, buf);
  return name;
}

const DATA_FILE_RE = /\.(csv|tsv|parquet|pq|json|jsonl|ndjson)$/i;

/** Turn a quoted SQL path into a workspace-relative path, or null. */
export function workspaceRelFromSqlPath(
  raw: string,
  workspaceRoot?: string | null,
): string | null {
  const s = raw.trim();
  if (!s) return null;
  const api = s.match(/\/api\/fs\/raw\?path=([^&]+)/i);
  if (api?.[1]) {
    try { return decodeURIComponent(api[1]); } catch { return api[1]; }
  }
  if (/^https?:\/\//i.test(s)) return null;
  if (s.startsWith("ws_")) return null;
  if (!DATA_FILE_RE.test(s)) return null;
  const ws = (workspaceRoot || "").replace(/\/+$/, "");
  if (ws && (s === ws || s.startsWith(ws + "/"))) {
    return s.slice(ws.length).replace(/^\/+/, "");
  }
  if (s.startsWith("/")) return null; // absolute, outside workspace
  return s.replace(/^\.\//, "");
}

/** Rewrite workspace file paths in SQL onto registered WASM vfs names.
 *  Covers `/api/fs/raw?path=…`, relative `data/foo.csv`, and absolute
 *  paths under the workspace — DuckDB-WASM cannot see the host FS. */
export async function rewriteRawPathsInSql(
  db: duckdb.AsyncDuckDB,
  sql: string,
  workspaceRoot?: string | null,
): Promise<string> {
  const quoted = /['"]([^'"]+)['"]/g;
  const found = new Map<string, string>(); // original substring → vfs
  let m: RegExpExecArray | null;
  while ((m = quoted.exec(sql)) !== null) {
    const raw = m[1] ?? "";
    const rel = workspaceRelFromSqlPath(raw, workspaceRoot);
    if (!rel || found.has(raw)) continue;
    found.set(raw, await registerWorkspaceFile(db, rel));
  }
  let out = sql;
  for (const [raw, vfs] of found) {
    out = out.split(raw).join(vfs);
  }
  return out;
}

async function bootstrap(): Promise<DBHandle> {
  const bundle = await duckdb.selectBundle(BUNDLES);
  const worker = new Worker(bundle.mainWorker!);
  const logger = new duckdb.ConsoleLogger(duckdb.LogLevel.WARNING);
  const db = new duckdb.AsyncDuckDB(logger, worker);
  await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
  const conn = await db.connect();
  return { db, conn };
}
