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

async function bootstrap(): Promise<DBHandle> {
  const bundle = await duckdb.selectBundle(BUNDLES);
  const worker = new Worker(bundle.mainWorker!);
  const logger = new duckdb.ConsoleLogger(duckdb.LogLevel.WARNING);
  const db = new duckdb.AsyncDuckDB(logger, worker);
  await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
  const conn = await db.connect();
  return { db, conn };
}
