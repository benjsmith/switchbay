/**
 * Pre-seed the DuckDB-WASM instance with two virtual tables built
 * from data the daemon already serves:
 *
 *   files (path TEXT, size BIGINT, mtime TIMESTAMP, ext TEXT)
 *     ← /api/fs/inventory
 *   pages (id TEXT, path TEXT, type TEXT, title TEXT, degree INT)
 *     ← /api/graph/data (.nodes)
 *
 * The user can query these immediately and JOIN them with anything
 * they read via read_csv_auto / read_parquet using /api/fs/raw URLs.
 *
 * Stats objects are also returned so the tab can show summary cards
 * without re-running the queries client-side.
 */

import type * as duckdb from "@duckdb/duckdb-wasm";

export type FileRow = { path: string; size: number; mtime: number; ext: string };
export type PageRow = {
  id: string;
  path: string;
  type: string;
  title: string;
  degree: number;
};

/** File extensions we treat as tabular data sources — these show up
 *  in the Data card and DuckDB-WASM can probe them via read_csv_auto
 *  / read_parquet / read_json_auto / ATTACH. */
export const DATA_EXTS = new Set([
  "csv", "tsv",
  "parquet", "pq",
  "json", "jsonl", "ndjson",
  "db", "sqlite", "duckdb",
]);

export function dataKind(ext: string): "csv" | "parquet" | "json" | "sqlite" | "duckdb" | null {
  if (ext === "csv" || ext === "tsv") return "csv";
  if (ext === "parquet" || ext === "pq") return "parquet";
  if (ext === "json" || ext === "jsonl" || ext === "ndjson") return "json";
  if (ext === "db" || ext === "sqlite") return "sqlite";
  if (ext === "duckdb") return "duckdb";
  return null;
}

export type WorkspaceStats = {
  fileCount: number;
  totalBytes: number;
  byExt: Array<{ ext: string; count: number; bytes: number }>;
  byType: Array<{ type: string; count: number }>;
  recent: FileRow[];   // 10 most recently modified
  pageCount: number;
  /** Tabular data sources sorted by size (descending). */
  data: FileRow[];
};

export async function seed(
  db: duckdb.AsyncDuckDB,
  conn: duckdb.AsyncDuckDBConnection,
): Promise<WorkspaceStats> {
  const [filesRes, graphRes] = await Promise.all([
    fetch("/api/fs/inventory").then((r) => r.json()) as Promise<{ files: FileRow[] }>,
    fetch("/api/graph/data").then((r) => r.ok ? r.json() : { nodes: [] }) as Promise<{ nodes: PageRow[] }>,
  ]);

  const files = filesRes.files ?? [];
  const pages = graphRes.nodes ?? [];

  // Register both as virtual JSON files inside DuckDB-WASM and CREATE
  // TABLE … AS SELECT * FROM the JSON. Cast mtime → TIMESTAMP so the
  // user can ORDER BY / use date functions.
  await db.registerFileText("files.json", JSON.stringify(files));
  await db.registerFileText("pages.json", JSON.stringify(pages));

  await conn.query(`DROP TABLE IF EXISTS files;`);
  await conn.query(`
    CREATE TABLE files AS
    SELECT
      path,
      CAST(size AS BIGINT) AS size,
      to_timestamp(mtime) AS mtime,
      ext
    FROM read_json_auto('files.json');
  `);

  await conn.query(`DROP TABLE IF EXISTS pages;`);
  await conn.query(`
    CREATE TABLE pages AS
    SELECT
      id, path, type, title,
      CAST(degree AS INTEGER) AS degree
    FROM read_json_auto('pages.json');
  `);

  // Aggregate stats client-side (cheap; same data we just registered).
  const byExtMap = new Map<string, { count: number; bytes: number }>();
  let totalBytes = 0;
  for (const f of files) {
    totalBytes += f.size;
    const k = f.ext || "(no ext)";
    const cur = byExtMap.get(k) ?? { count: 0, bytes: 0 };
    cur.count += 1;
    cur.bytes += f.size;
    byExtMap.set(k, cur);
  }
  const byExt = [...byExtMap.entries()]
    .map(([ext, v]) => ({ ext, ...v }))
    .sort((a, b) => b.count - a.count);

  const byTypeMap = new Map<string, number>();
  for (const p of pages) byTypeMap.set(p.type, (byTypeMap.get(p.type) ?? 0) + 1);
  const byType = [...byTypeMap.entries()]
    .map(([type, count]) => ({ type, count }))
    .sort((a, b) => b.count - a.count);

  const recent = [...files].sort((a, b) => b.mtime - a.mtime).slice(0, 10);
  const data = files
    .filter((f) => DATA_EXTS.has(f.ext))
    .sort((a, b) => b.size - a.size);

  return {
    fileCount: files.length,
    totalBytes,
    byExt,
    byType,
    recent,
    pageCount: pages.length,
    data,
  };
}
